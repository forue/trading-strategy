# 认证中心服务设计文档

> 版本: v1.0 | 更新日期: 2026-04-18

---

## 一、模块概述

认证中心负责用户身份验证、JWT Token签发与验证、Token黑名单管理，是系统的安全入口。

| 属性 | 值 |
|------|-----|
| 服务名 | backend-auth |
| 端口 | 8001 |
| 语言 | Java 17 |
| 框架 | Spring Boot 3.2 + Spring Security |
| 数据库 | PostgreSQL + Redis |

---

## 二、技术架构

```
┌─────────────────────────────────────────────┐
│              AuthController                  │
│  POST /api/auth/login                       │
│  POST /api/auth/register                    │
│  GET  /api/auth/user/info                   │
│  POST /api/auth/logout                      │
└───────────┬─────────────────────────────────┘
            │
    ┌───────▼────────┐
    │   JwtUtil      │ ← JWT签发/验证
    └───────┬────────┘
            │
    ┌───────▼──────────────────────┐
    │  UserRepository (JPA)        │ ← PostgreSQL
    │  StringRedisTemplate         │ ← Redis (Token黑名单)
    └──────────────────────────────┘
```

---

## 三、核心类设计

### 3.1 User实体

```java
@Entity
@Table(name = "users")
public class User {
    private Long id;           // 主键
    private String username;   // 用户名（唯一）
    private String password;   // BCrypt加密密码
    private String email;      // 邮箱
    private String phone;      // 手机号
    private String role;       // 角色: USER / ADMIN
    private String status;     // 状态: ACTIVE / DISABLED
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}
```

### 3.2 JwtUtil

```java
@Component
public class JwtUtil {
    // Token签发
    String generateToken(Long userId, String username, String role)
    
    // 从Token提取用户名
    String getUsernameFromToken(String token)
    
    // 从Token提取用户ID
    Long getUserIdFromToken(String token)
    
    // 验证Token有效性
    boolean validateToken(String token)
}
```

**Token载荷结构**:

```json
{
  "sub": "admin",           // 用户名
  "userId": 1,              // 用户ID
  "role": "USER",           // 角色
  "iat": 1713408000,        // 签发时间
  "exp": 1713494400         // 过期时间 (24h)
}
```

### 3.3 Python 服务的 Token 解析（按用户隔离配置）

strategy / signal-notification / ai-decision 三个 Python 服务需要知道"当前请求属于哪个用户"来读写按用户隔离的配置
（设置项、推送通道、AI 凭据与对话）。它们通过 `services/shared/auth.py` 本地验签同一个 JWT：

- 密钥来自环境变量 `JWT_SECRET`，与 auth 服务 `jwt.secret` 必须一致（docker-compose 已注入四个服务）
- 只接受 `alg=HS256`，用常量时间比较签名，并校验 `exp`；`payload.userId` 即用户 id，`role` 用于判定管理员
- 各服务 Redis db 不同（strategy/signal 为 db 1、ai 为 db 3、auth 为 db 0），Python 服务读不到 auth 的
  Token 黑名单，因此"退出登录后 token 立即失效"只在 auth 的 TokenGuard 侧成立；Python 侧拿它仅做
  配置归属判定，能访问的也只是该 token 持有者自己的数据

### 3.4 SecurityConfig

```
安全策略:
  - CSRF: 禁用（前后端分离，Token验证）
  - CORS: 允许所有来源（开发环境），生产环境限制域名
  - Session: STATELESS（无状态）
  - 放行路径: /api/auth/login, /api/auth/register, /health
  - 其他路径: 需认证
```

### 3.5 权限与配额模型

后台管理的三块能力由两张表 + 两份静态目录驱动：

| 组件 | 位置 | 说明 |
|------|------|------|
| `RouteCatalog` | `support/RouteCatalog.java` | 页面清单（路径 / 名称 / 分组 / 是否仅管理员），前端路由的单一来源 |
| `FeatureCatalog` | `support/FeatureCatalog.java` | 受配额控制的功能清单（当前：`stock_sense_training` 盘感训练，默认 USER 3 次/天、ADMIN 不限） |
| `RoutePermission` | `entity/RoutePermission.java` | `route_permissions(role, route_path, allowed)`，唯一键 (role, route_path) |
| `FeatureQuota` | `entity/FeatureQuota.java` | `feature_quotas(feature_key, role, daily_limit, enabled)`，`daily_limit=0` 表示不限次 |
| `TokenGuard` | `support/TokenGuard.java` | Token → 用户 → 管理员校验，**角色取自数据库**（降级后旧 Token 立即失效） |
| `AccessControlService` | `service/AccessControlService.java` | 目录默认值补齐、权限读写、配额读写与计数 |
| `ApiException(Handler)` | `support/` | 业务异常 → `{code, message}` + 对应 HTTP 状态码 |

约定：

- 缺行视为未授权；服务启动（`@PostConstruct`）按目录补默认值，新增页面/功能无需手工改库
- 管理员的后台管理三项强制开启，保存时不可撤销（避免把自己锁在门外）；普通角色的后台管理页强制关闭，提交里带上也会被忽略
- 非管理员角色读取权限时同样过滤后台管理页（库里被误标为 `allowed=true` 也不会外泄），保证 `/permissions/me`、侧栏、权限矩阵三处口径一致
- 任一角色至少保留一个可访问页面
- 当日用量只落 Redis：`quota:{featureKey}:{userId}:{yyyy-MM-dd}`，48h 过期；超限的尝试不累加计数
- 计数主体是 Token 解析出的账号，不信任请求参数里的用户名

---

## 四、接口设计

### 4.1 登录

```
POST /api/auth/login
Content-Type: application/json

请求:
{
  "username": "admin",
  "password": "123456"
}

成功响应 (200):
{
  "code": 200,
  "message": "登录成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9...",
    "user": {
      "id": 1,
      "username": "admin",
      "email": "admin@rotation.com",
      "role": "USER"
    }
  }
}

失败响应 (401):
{
  "code": 401,
  "message": "密码错误"
}
```

**登录流程**:

```
1. 接收 username + password
2. 查询数据库验证用户存在
3. BCrypt验证密码匹配
4. 检查账号状态为ACTIVE
5. JwtUtil.generateToken() 签发Token
6. 返回Token + 用户信息
```

### 4.2 注册

```
POST /api/auth/register
Content-Type: application/json

请求:
{
  "username": "newuser",
  "password": "123456",
  "email": "user@example.com"
}

成功响应 (200):
{
  "code": 200,
  "message": "注册成功",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9...",
    "user": { "id": 2, "username": "newuser", ... }
  }
}

失败响应 (400):
{
  "code": 400,
  "message": "用户名已存在"
}
```

**注册流程**:

```
1. 检查用户名唯一性
2. BCrypt加密密码
3. 保存User到PostgreSQL
4. 自动签发Token（注册即登录）
5. 返回Token + 用户信息
```

### 4.3 获取用户信息

```
GET /api/auth/user/info
Authorization: Bearer {token}

成功响应:
{
  "code": 200,
  "data": {
    "id": 1,
    "username": "admin",
    "email": "admin@rotation.com",
    "role": "USER"
  }
}

失败响应 (401):
  Token无效或已过期
```

### 4.4 退出登录

```
POST /api/auth/logout
Authorization: Bearer {token}

响应:
{
  "code": 200,
  "message": "退出成功"
}
```

**退出流程**:

```
1. 提取Token（从Authorization头）
2. 将Token写入Redis黑名单: token:blacklist:{token} = "1"
3. 设置TTL为24小时（与JWT过期时间一致）
4. 后续请求携带此Token时，getUserInfo接口会检查黑名单
```

### 4.5 健康检查

```
GET /api/auth/health

响应:
{
  "code": 200,
  "data": {
    "status": "healthy",
    "service": "auth",
    "timestamp": 1713408000000
  }
}
```

### 4.6 后台管理接口（仅 ADMIN）

所有接口先过 `TokenGuard.requireAdmin`：401 缺 Token/失效，403 非管理员或账号已禁用。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/admin/users?keyword=&role=&page=1&size=10` | 账号分页（关键字匹配用户名/邮箱），返回 `{items,total,page,size}` |
| POST | `/api/auth/admin/users` | 新建账号 `{username,password,email?,phone?,role,status}`，密码 ≥6 位 |
| PUT | `/api/auth/admin/users/{id}` | 局部更新：仅传需要改的字段；`password` 非空即重置密码 |
| DELETE | `/api/auth/admin/users/{id}` | 删除账号；有持仓/交易/资金记录时返回 400 提示改为禁用；删除前会清空该账号的个人数据（见下） |
| GET | `/api/auth/admin/route-permissions` | 返回 `{routes,permissions,lockedPaths}` |
| PUT | `/api/auth/admin/route-permissions` | 保存整份角色权限 `{role,allowedPaths}`，返回最新矩阵 |
| GET | `/api/auth/admin/feature-quotas` | 功能配额列表，按功能分组、每个角色一行 |
| PUT | `/api/auth/admin/feature-quotas` | 批量保存 `{items:[{featureKey,role,dailyLimit,enabled}]}` |

安全兜底：

- 不能取消/禁用/删除当前登录账号
- 系统至少保留一名管理员（降级或删除最后一个 ADMIN 返回 400）
- 锁定页面（`RouteCatalog` 中 `adminOnly=true` 的 `/monitor` 与 `/admin/*`）强制"仅管理员"：
  对管理员强制保留、对普通角色强制关闭，提交无效；启动时还会把老库里普通角色已放开的锁定页行校正为 `false`
- 角色可访问页面不能清空

**删号必须连带清理个人数据**：账号 id 会被再次分配（库还原、序列回退、同名重建），而个人数据挂在
Redis `user:{id}:` 与 `trade_signals` / `signal_outcomes` 上。若只删 `users` 行，下一个拿到同 id 的账号
会直接看到上一个人的盘感训练记录、信号缓存与市场状态（2026-11-22 实测：新建账号继承了 21 天前
同 id 账号的 11 条训练记录）。删除流程因此分三步，任一步失败都不删号：

1. `ensureNoUserRows` 先查 `positions / trades / account_nav / bank_transfers / strategy_configs`，
   有数据直接返回 400 提示改为禁用（与数据库外键同一口径，避免"数据清了一半账号没删掉"）。
2. `purgeAccountData` 带 `X-Internal-Token` 调 `POST /internal/users/{id}/purge`：
   strategy 清 db1 的 `user:{id}:*` 与两张信号表，ai-decision 清 db3 的 `user:{id}:*`。
3. 最后删 `users` 行。

新建账号时也会调一次同样的清理（幂等，失败只记 WARN 不阻断建号），把历史遗留的孤儿数据兜住。
未配置 `INTERNAL_TOKEN` 时跳过清理（仅限本地调试）。

### 4.7 我的权限与配额（所有登录用户）

```
GET /api/auth/permissions/me
Authorization: Bearer {token}

响应:
{
  "code": 200,
  "data": {
    "id": 2,
    "username": "alice",
    "role": "USER",
    "isAdmin": false,
    "allowedPaths": ["/", "/strategy", "/signals", "/fund", "/review",
                     "/factor-analysis", "/factor-ranking", "/data-replay",
                     "/stock-sense", "/settings"]
  }
}
```

```
GET  /api/auth/quota/me?feature=stock_sense_training        # 只读状态
POST /api/auth/quota/consume?feature=stock_sense_training   # 计一次使用

响应 (200):
{ "code": 200, "data": { "featureKey": "stock_sense_training", "featureName": "盘感训练",
                         "enabled": true, "dailyLimit": 3, "used": 1, "remaining": 2 } }

越权/超限:
403 { "code": 403, "message": "盘感训练未对当前角色开放" }
429 { "code": 429, "message": "今日盘感训练次数已达上限（3 次/天）" }
```

`/quota/consume` 由服务间调用：策略服务在 `/stock-sense/start` 入口把用户 Token 转发过来，
auth 校验 Token 后按账号计数并回传剩余次数，拒绝原因原样透传给前端。

---

## 五、Token安全机制

### 5.1 Token生命周期

```
签发 → 使用(每次请求携带) → 过期/主动登出(加入黑名单)
│         │                      │
│         │                      └─ Redis黑名单拦截
│         └─ Axios拦截器自动附加
└─ JWT有效期24h
```

### 5.2 Token验证链路

```
前端请求 (Authorization: Bearer xxx)
    │
    ▼ Nginx代理
    │
    ▼ Spring Security过滤器链
    │
    ▼ Controller方法
    │
    ├─ JwtUtil.validateToken(token)      → 验证签名和过期时间
    └─ Redis黑名单检查                    → 确认Token未被注销
```

### 5.3 密码安全

- 存储方式: BCrypt加密（自动加盐，每次密文不同）
- 传输安全: HTTPS（生产环境）
- 强度要求: 注册时前端校验≥6位（可扩展复杂度规则）

---

## 六、配置项

```yaml
# application.yml
server:
  port: 8001

spring:
  datasource:
    url: jdbc:postgresql://postgres:5432/rotation_db
    username: admin
    password: secret
  jpa:
    hibernate:
      ddl-auto: update        # 自动建表（生产改为validate）
  data:
    redis:
      host: redis
      port: 6379
      password: redis123

jwt:
  secret: ${JWT_SECRET}       # 从环境变量读取
  expiration: 86400000         # 24小时 (毫秒)
```

---

## 七、扩展设计

### 7.1 短期扩展

- **Refresh Token**: 双Token机制，AccessToken短期(2h) + RefreshToken长期(7d)
- **权限细粒度**: RBAC模型，增加Permission表和接口级权限控制
- **登录日志**: 记录登录IP/时间/设备，支持异常登录告警

### 7.2 长期扩展

- **OAuth2集成**: 支持微信/企业微信第三方登录
- **多因子认证**: SMS验证码 / TOTP
- **单点登录**: 多系统间共享认证状态
