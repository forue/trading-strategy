package com.rotation.auth.support;

import java.util.List;

/**
 * 前端页面清单（与 frontend/src/router/index.ts 保持一致）。
 *
 * 后端用它做两件事：给权限表补默认值、给后台管理页渲染可授权页面列表。
 * 新增前端页面时必须同步登记，否则不会出现在权限管理页，且路由守卫会判为无权限。
 */
public final class RouteCatalog {

    /** 角色常量：与 users.role 取值一致 */
    public static final String ROLE_ADMIN = "ADMIN";
    public static final String ROLE_USER = "USER";
    public static final List<String> ROLES = List.of(ROLE_USER, ROLE_ADMIN);

    public record RouteDef(String path, String name, String group, boolean adminOnly) {
    }

    public static final List<RouteDef> ROUTES = List.of(
            new RouteDef("/", "仪表盘", "工作台", false),
            new RouteDef("/strategy", "策略管理", "策略与交易", false),
            new RouteDef("/strategy-workshop", "策略工坊", "策略与交易", false),
            new RouteDef("/signals", "交易信号", "策略与交易", false),
            new RouteDef("/fund", "资金管理", "策略与交易", false),
            new RouteDef("/review", "策略复盘", "复盘与分析", false),
            new RouteDef("/factor-analysis", "因子分析", "复盘与分析", false),
            new RouteDef("/factor-ranking", "板块因子排名", "复盘与分析", false),
            new RouteDef("/data-replay", "数据回放", "复盘与分析", false),
            new RouteDef("/stock-sense", "盘感训练", "复盘与分析", false),
            // 系统监控会暴露运行时内部信息（连接数/队列/缓存明细），只给管理员；
            // 锁定后普通用户既拿不到默认授权，也无法在「页面权限」页被单独放开
            new RouteDef("/monitor", "系统监控", "系统", true),
            new RouteDef("/settings", "系统设置", "系统", false),
            new RouteDef("/admin/users", "账号管理", "后台管理", true),
            new RouteDef("/admin/permissions", "页面权限", "后台管理", true),
            new RouteDef("/admin/features", "高级功能", "后台管理", true)
    );

    private RouteCatalog() {
    }

    public static boolean isKnownPath(String path) {
        return ROUTES.stream().anyMatch(r -> r.path().equals(path));
    }

    public static boolean isAdminOnly(String path) {
        return ROUTES.stream().anyMatch(r -> r.path().equals(path) && r.adminOnly());
    }

    /** 角色默认值：管理员全开，普通用户不含后台管理页 */
    public static boolean defaultAllowed(String role, String path) {
        return ROLE_ADMIN.equals(role) || !isAdminOnly(path);
    }
}
