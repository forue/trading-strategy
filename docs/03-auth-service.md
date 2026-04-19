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

### 3.3 SecurityConfig

```
安全策略:
  - CSRF: 禁用（前后端分离，Token验证）
  - CORS: 允许所有来源（开发环境），生产环境限制域名
  - Session: STATELESS（无状态）
  - 放行路径: /api/auth/login, /api/auth/register, /health
  - 其他路径: 需认证
```

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
1. 提取Token
2. 将Token写入Redis黑名单: token:blacklist:{token} = "1"
3. 设置TTL为24小时（与JWT过期时间一致）
4. 后续请求携带此Token时，getUserInfo接口会检查黑名单
```

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
