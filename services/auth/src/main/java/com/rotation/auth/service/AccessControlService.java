package com.rotation.auth.service;

import com.rotation.auth.entity.FeatureQuota;
import com.rotation.auth.entity.RoutePermission;
import com.rotation.auth.repository.FeatureQuotaRepository;
import com.rotation.auth.repository.RoutePermissionRepository;
import com.rotation.auth.support.ApiException;
import com.rotation.auth.support.FeatureCatalog;
import com.rotation.auth.support.RouteCatalog;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/**
 * 页面访问权限 + 高级功能配额。
 *
 * 权限配置落库（route_permissions / feature_quotas）；当日用量只落 Redis，
 * key = quota:{featureKey}:{userId}:{yyyy-MM-dd}，48h 后自然过期。
 */
@Service
public class AccessControlService {

    private static final Logger log = LoggerFactory.getLogger(AccessControlService.class);
    private static final int QUOTA_TTL_HOURS = 48;

    private final RoutePermissionRepository routeRepository;
    private final FeatureQuotaRepository quotaRepository;
    private final StringRedisTemplate redisTemplate;

    public AccessControlService(RoutePermissionRepository routeRepository,
                                FeatureQuotaRepository quotaRepository,
                                StringRedisTemplate redisTemplate) {
        this.routeRepository = routeRepository;
        this.quotaRepository = quotaRepository;
        this.redisTemplate = redisTemplate;
    }

    /** 启动时补齐目录新增项的默认值（老库不会自动补行） */
    @PostConstruct
    public void initDefaults() {
        try {
            List<RoutePermission> routeRows = new ArrayList<>();
            for (String role : RouteCatalog.ROLES) {
                Map<String, RoutePermission> existing = new LinkedHashMap<>();
                routeRepository.findByRole(role).forEach(r -> existing.put(r.getRoutePath(), r));
                for (RouteCatalog.RouteDef def : RouteCatalog.ROUTES) {
                    RoutePermission row = existing.get(def.path());
                    if (row == null) {
                        RoutePermission created = new RoutePermission();
                        created.setRole(role);
                        created.setRoutePath(def.path());
                        created.setAllowed(RouteCatalog.defaultAllowed(role, def.path()));
                        routeRows.add(created);
                        continue;
                    }
                    // 锁定路径（adminOnly）的既有行必须一起校正：老库里
                    // (USER, /monitor, allowed=true) 是既成事实，只补缺失行永远修不掉。
                    // 幂等：已是 false 的行不进列表，避免每次启动都写库；
                    // 非锁定路径完全不动，以免回滚管理员在页面权限页做的个性化授权。
                    if (def.adminOnly() && !RouteCatalog.ROLE_ADMIN.equals(role)
                            && Boolean.TRUE.equals(row.getAllowed())) {
                        row.setAllowed(Boolean.FALSE);
                        routeRows.add(row);
                        log.info("已收回角色 {} 对锁定页面 {} 的访问权", role, def.path());
                    }
                }
            }
            if (!routeRows.isEmpty()) {
                routeRepository.saveAll(routeRows);
                log.info("页面权限默认值已补齐/校正 {} 条", routeRows.size());
            }

            List<FeatureQuota> quotaRows = new ArrayList<>();
            for (FeatureCatalog.FeatureDef def : FeatureCatalog.FEATURES) {
                for (String role : RouteCatalog.ROLES) {
                    if (quotaRepository.findByFeatureKeyAndRole(def.key(), role).isEmpty()) {
                        FeatureQuota row = new FeatureQuota();
                        row.setFeatureKey(def.key());
                        row.setRole(role);
                        row.setDailyLimit(FeatureCatalog.defaultLimit(def, role));
                        row.setEnabled(true);
                        quotaRows.add(row);
                    }
                }
            }
            if (!quotaRows.isEmpty()) {
                quotaRepository.saveAll(quotaRows);
                log.info("功能配额默认值已补齐 {} 条", quotaRows.size());
            }
        } catch (Exception e) {
            // 数据库未就绪时不阻塞服务启动，下一次重启会重试
            log.warn("权限/配额默认值初始化失败: {}", e.getMessage());
        }
    }

    // ───────────────────────── 页面权限 ─────────────────────────

    public List<String> allowedPaths(String role) {
        List<RoutePermission> rows = routeRepository.findByRole(role);
        if (rows.isEmpty()) {
            return RouteCatalog.ROUTES.stream()
                    .filter(r -> RouteCatalog.defaultAllowed(role, r.path()))
                    .map(RouteCatalog.RouteDef::path)
                    .toList();
        }
        Set<String> allowed = new LinkedHashSet<>();
        rows.stream()
                .filter(r -> Boolean.TRUE.equals(r.getAllowed()))
                .forEach(r -> allowed.add(r.getRoutePath()));
        return RouteCatalog.ROUTES.stream()
                .map(RouteCatalog.RouteDef::path)
                // 后台管理页只对管理员开放，即使库中被误标为已授权也不外泄
                .filter(p -> RouteCatalog.ROLE_ADMIN.equals(role) || !RouteCatalog.isAdminOnly(p))
                .filter(allowed::contains)
                .toList();
    }

    public Map<String, Object> routeMatrix() {
        Map<String, List<String>> permissions = new LinkedHashMap<>();
        for (String role : RouteCatalog.ROLES) {
            permissions.put(role, allowedPaths(role));
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("routes", RouteCatalog.ROUTES);
        data.put("permissions", permissions);
        data.put("lockedPaths", RouteCatalog.ROUTES.stream()
                .filter(RouteCatalog.RouteDef::adminOnly)
                .map(RouteCatalog.RouteDef::path)
                .toList());
        return data;
    }

    @Transactional
    public void updateRoleRoutes(String role, List<String> allowedPaths) {
        if (!RouteCatalog.ROLES.contains(role)) {
            throw new ApiException(400, "未知角色: " + role);
        }
        Set<String> wanted = new LinkedHashSet<>(allowedPaths == null ? List.of() : allowedPaths);
        Map<String, RoutePermission> existing = new HashMap<>();
        routeRepository.findByRole(role).forEach(r -> existing.put(r.getRoutePath(), r));

        List<RoutePermission> rows = new ArrayList<>();
        for (RouteCatalog.RouteDef def : RouteCatalog.ROUTES) {
            RoutePermission row = existing.get(def.path());
            if (row == null) {
                row = new RoutePermission();
                row.setRole(role);
                row.setRoutePath(def.path());
            }
            if (def.adminOnly()) {
                // 后台管理页：对管理员强制保留（避免误操作把自己锁在门外），对其他角色强制关闭
                row.setAllowed(RouteCatalog.ROLE_ADMIN.equals(role));
            } else {
                row.setAllowed(wanted.contains(def.path()));
            }
            rows.add(row);
        }
        if (rows.stream().noneMatch(r -> Boolean.TRUE.equals(r.getAllowed()))) {
            // 全关会让该角色登录后无处可去（路由守卫会原地打转）
            throw new ApiException(400, "该角色至少需要保留一个可访问页面");
        }
        routeRepository.saveAll(rows);
    }

    // ───────────────────────── 功能配额 ─────────────────────────

    public List<Map<String, Object>> quotaList() {
        List<Map<String, Object>> out = new ArrayList<>();
        for (FeatureCatalog.FeatureDef def : FeatureCatalog.FEATURES) {
            Map<String, Object> feature = new LinkedHashMap<>();
            feature.put("key", def.key());
            feature.put("name", def.name());
            feature.put("description", def.description());

            List<Map<String, Object>> roles = new ArrayList<>();
            for (String role : RouteCatalog.ROLES) {
                FeatureQuota row = quotaRepository.findByFeatureKeyAndRole(def.key(), role).orElse(null);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("role", role);
                item.put("dailyLimit", row != null ? row.getDailyLimit() : FeatureCatalog.defaultLimit(def, role));
                item.put("enabled", row == null || Boolean.TRUE.equals(row.getEnabled()));
                roles.add(item);
            }
            feature.put("roles", roles);
            out.add(feature);
        }
        return out;
    }

    @Transactional
    public void updateQuota(String featureKey, String role, Integer dailyLimit, Boolean enabled) {
        FeatureCatalog.FeatureDef def = FeatureCatalog.find(featureKey);
        if (def == null) {
            throw new ApiException(400, "未知功能: " + featureKey);
        }
        if (!RouteCatalog.ROLES.contains(role)) {
            throw new ApiException(400, "未知角色: " + role);
        }
        int limit = dailyLimit == null ? 0 : dailyLimit;
        if (limit < 0 || limit > 9999) {
            throw new ApiException(400, "每日次数需在 0~9999 之间（0 表示不限次）");
        }
        FeatureQuota row = quotaRepository.findByFeatureKeyAndRole(featureKey, role)
                .orElseGet(() -> {
                    FeatureQuota created = new FeatureQuota();
                    created.setFeatureKey(featureKey);
                    created.setRole(role);
                    return created;
                });
        row.setDailyLimit(limit);
        row.setEnabled(enabled == null || enabled);
        quotaRepository.save(row);
    }

    /** 只读当前状态，不计数 */
    public Map<String, Object> quotaState(String featureKey, String role, Long userId) {
        FeatureCatalog.FeatureDef def = requireFeature(featureKey);
        boolean enabled = isEnabled(featureKey, role);
        int limit = limitOf(featureKey, def, role);
        long used = readUsed(featureKey, userId);
        return buildState(featureKey, def, enabled, limit, used);
    }

    /** 记一次使用；超限 / 未开放直接抛 403 / 429 */
    public Map<String, Object> consumeQuota(String featureKey, String role, Long userId) {
        FeatureCatalog.FeatureDef def = requireFeature(featureKey);
        if (!isEnabled(featureKey, role)) {
            throw new ApiException(403, def.name() + "未对当前角色开放");
        }
        int limit = limitOf(featureKey, def, role);

        String key = redisKey(featureKey, userId);
        Long used = redisTemplate.opsForValue().increment(key);
        long usedCount = used == null ? 1L : used;
        if (usedCount == 1L) {
            redisTemplate.expire(key, QUOTA_TTL_HOURS, TimeUnit.HOURS);
        }

        if (limit > 0 && usedCount > limit) {
            // 超限的尝试不计数：把计数回落成上限，避免反复点击把当日用量刷成天文数字
            redisTemplate.opsForValue().set(key, String.valueOf(limit), QUOTA_TTL_HOURS, TimeUnit.HOURS);
            throw new ApiException(429, "今日" + def.name() + "次数已达上限（" + limit + " 次/天）");
        }
        return buildState(featureKey, def, true, limit, usedCount);
    }

    private FeatureCatalog.FeatureDef requireFeature(String featureKey) {
        FeatureCatalog.FeatureDef def = FeatureCatalog.find(featureKey);
        if (def == null) {
            throw new ApiException(400, "未知功能: " + featureKey);
        }
        return def;
    }

    private boolean isEnabled(String featureKey, String role) {
        return quotaRepository.findByFeatureKeyAndRole(featureKey, role)
                .map(q -> Boolean.TRUE.equals(q.getEnabled()))
                .orElse(true);
    }

    private int limitOf(String featureKey, FeatureCatalog.FeatureDef def, String role) {
        return quotaRepository.findByFeatureKeyAndRole(featureKey, role)
                .map(FeatureQuota::getDailyLimit)
                .orElse(FeatureCatalog.defaultLimit(def, role));
    }

    private long readUsed(String featureKey, Long userId) {
        String raw = redisTemplate.opsForValue().get(redisKey(featureKey, userId));
        if (raw == null) {
            return 0L;
        }
        try {
            return Long.parseLong(raw);
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    private Map<String, Object> buildState(String featureKey, FeatureCatalog.FeatureDef def,
                                           boolean enabled, int limit, long used) {
        long effectiveUsed = limit > 0 ? Math.min(used, limit) : used;
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("featureKey", featureKey);
        data.put("featureName", def.name());
        data.put("enabled", enabled);
        data.put("dailyLimit", limit);
        data.put("used", effectiveUsed);
        data.put("remaining", limit > 0 ? Math.max(limit - effectiveUsed, 0) : -1);
        return data;
    }

    private String redisKey(String featureKey, Long userId) {
        return "quota:" + featureKey + ":" + userId + ":" + LocalDate.now();
    }
}
