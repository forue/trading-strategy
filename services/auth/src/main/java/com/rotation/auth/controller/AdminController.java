package com.rotation.auth.controller;

import com.rotation.auth.entity.User;
import com.rotation.auth.repository.UserRepository;
import com.rotation.auth.service.AccessControlService;
import com.rotation.auth.support.ApiException;
import com.rotation.auth.support.RouteCatalog;
import com.rotation.auth.support.TokenGuard;
import lombok.Data;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 后台管理接口（仅 ADMIN）：账号管理、页面访问权限、高级功能配额。
 *
 * 每个方法先走 TokenGuard.requireAdmin —— 角色以数据库为准，
 * 因此 Token 里的旧 role 声明不会成为越权入口。
 */
@RestController
@RequestMapping("/api/auth/admin")
public class AdminController {

    private static final Logger log = LoggerFactory.getLogger(AdminController.class);

    /** 这些表用 users(id) 外键挂住账号：有数据就删不掉，只能改为禁用 */
    private static final String[] USER_FK_TABLES =
            {"positions", "trades", "account_nav", "bank_transfers", "strategy_configs", "user_strategies", "user_workshop_algorithms", "user_strategy_likes"};

    private final TokenGuard tokenGuard;
    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final AccessControlService accessControlService;
    private final JdbcTemplate jdbcTemplate;
    private final RestTemplate restTemplate = new RestTemplate();

    @Value("${internal.token:}")
    private String internalToken;

    public AdminController(TokenGuard tokenGuard, UserRepository userRepository,
                           PasswordEncoder passwordEncoder, AccessControlService accessControlService,
                           JdbcTemplate jdbcTemplate) {
        this.tokenGuard = tokenGuard;
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
        this.accessControlService = accessControlService;
        this.jdbcTemplate = jdbcTemplate;
    }

    // ───────────────────────── 账号管理 ─────────────────────────

    @GetMapping("/users")
    public ResponseEntity<?> listUsers(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                       @RequestParam(defaultValue = "") String keyword,
                                       @RequestParam(defaultValue = "") String role,
                                       @RequestParam(defaultValue = "1") int page,
                                       @RequestParam(defaultValue = "10") int size) {
        tokenGuard.requireAdmin(authHeader);

        int pageNo = Math.max(page, 1);
        int pageSize = Math.min(Math.max(size, 1), 100);
        Page<User> result = userRepository.search(
                keyword == null ? "" : keyword.trim(),
                role == null ? "" : role.trim(),
                PageRequest.of(pageNo - 1, pageSize, Sort.by(Sort.Direction.DESC, "id")));

        List<Map<String, Object>> items = new ArrayList<>();
        result.getContent().forEach(u -> items.add(toView(u)));

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("items", items);
        data.put("total", result.getTotalElements());
        data.put("page", pageNo);
        data.put("size", pageSize);
        return ok(data);
    }

    @PostMapping("/users")
    public ResponseEntity<?> createUser(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                        @RequestBody UserForm form) {
        tokenGuard.requireAdmin(authHeader);

        String username = trim(form.getUsername());
        if (username.isEmpty()) {
            throw new ApiException(400, "用户名不能为空");
        }
        checkPassword(form.getPassword());
        if (userRepository.existsByUsername(username)) {
            throw new ApiException(400, "用户名已存在");
        }

        User user = new User();
        user.setUsername(username);
        user.setPassword(passwordEncoder.encode(form.getPassword()));
        user.setEmail(trimToNull(form.getEmail()));
        user.setPhone(trimToNull(form.getPhone()));
        user.setRole(normalizeRole(form.getRole()));
        user.setStatus(normalizeStatus(form.getStatus()));
        userRepository.save(user);
        // 兜底：id 被再次分配时（库还原、序列回退）先清掉旧账号残留，
        // 否则新账号一登录就会看到别人的训练记录与信号。清理失败不影响建号。
        try {
            purgeAccountData(user.getId());
        } catch (Exception e) {
            log.warn("新建账号 {} 的残留数据清理失败：{}", user.getId(), e.getMessage());
        }
        return ok(toView(user));
    }

    @PutMapping("/users/{id}")
    public ResponseEntity<?> updateUser(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                        @PathVariable Long id,
                                        @RequestBody UserForm form) {
        User operator = tokenGuard.requireAdmin(authHeader);
        User target = userRepository.findById(id)
                .orElseThrow(() -> new ApiException(404, "账号不存在"));

        boolean self = target.getId().equals(operator.getId());

        if (form.getEmail() != null) {
            target.setEmail(trimToNull(form.getEmail()));
        }
        if (form.getPhone() != null) {
            target.setPhone(trimToNull(form.getPhone()));
        }
        if (form.getRole() != null) {
            String role = normalizeRole(form.getRole());
            if (self && !RouteCatalog.ROLE_ADMIN.equals(role)) {
                throw new ApiException(400, "不能取消当前登录账号的管理员角色");
            }
            if (RouteCatalog.ROLE_ADMIN.equals(target.getRole()) && !RouteCatalog.ROLE_ADMIN.equals(role)
                    && userRepository.countByRole(RouteCatalog.ROLE_ADMIN) <= 1) {
                throw new ApiException(400, "系统至少需要保留一名管理员");
            }
            target.setRole(role);
        }
        if (form.getStatus() != null) {
            String status = normalizeStatus(form.getStatus());
            if (self && !"ACTIVE".equals(status)) {
                throw new ApiException(400, "不能禁用当前登录账号");
            }
            target.setStatus(status);
        }
        if (form.getPassword() != null && !form.getPassword().isEmpty()) {
            checkPassword(form.getPassword());
            target.setPassword(passwordEncoder.encode(form.getPassword()));
        }

        userRepository.save(target);
        return ok(toView(target));
    }

    @DeleteMapping("/users/{id}")
    public ResponseEntity<?> deleteUser(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                        @PathVariable Long id) {
        User operator = tokenGuard.requireAdmin(authHeader);
        if (operator.getId().equals(id)) {
            throw new ApiException(400, "不能删除当前登录账号");
        }
        User target = userRepository.findById(id)
                .orElseThrow(() -> new ApiException(404, "账号不存在"));
        if (RouteCatalog.ROLE_ADMIN.equals(target.getRole())
                && userRepository.countByRole(RouteCatalog.ROLE_ADMIN) <= 1) {
            throw new ApiException(400, "系统至少需要保留一名管理员");
        }
        // 外键表里有数据时先拦下，避免"数据清了一半账号没删掉"
        ensureNoUserRows(id);
        // 删号必须先清个人数据：id 会被再次分配（库还原、序列回退），
        // 残留的 user:{id}: 键会让下一个账号继承训练记录与信号
        purgeAccountData(id);
        try {
            userRepository.delete(target);
        } catch (DataIntegrityViolationException e) {
            // 持仓/交易记录引用 users(id)，删不掉时引导改为禁用
            throw new ApiException(400, "该账号存在关联的持仓或交易记录，请改为禁用");
        }
        return ResponseEntity.ok(Map.of("code", 200, "message", "账号已删除"));
    }

    /** 外键表里还有该账号的数据时直接拒绝删除（与数据库约束保持同一口径） */
    private void ensureNoUserRows(Long userId) {
        for (String table : USER_FK_TABLES) {
            Integer count = jdbcTemplate.queryForObject(
                    "SELECT count(*) FROM " + table + " WHERE user_id = ?", Integer.class, userId);
            if (count != null && count > 0) {
                throw new ApiException(400, "该账号存在关联的持仓、交易或资金记录，请改为禁用");
            }
        }
    }

    /**
     * 通知策略与 AI 服务清空该账号的个人数据（Redis user:{id}: 键 + 信号表行）。
     *
     * 两个服务各自持有自己的存储（策略用 db1 + 信号表，AI 用 db3），删号时必须一起清；
     * 任一失败就抛出，让删号失败，避免留下会串给下一个账号的残留。
     */
    private void purgeAccountData(Long userId) {
        if (internalToken == null || internalToken.isBlank()) {
            log.warn("未配置 INTERNAL_TOKEN，跳过账号 {} 的个人数据清理（仅限本地调试）", userId);
            return;
        }
        purgeRemote("策略", "http://backend-strategy:8002/internal/users/" + userId + "/purge");
        purgeRemote("AI", "http://backend-ai-decision:8007/internal/users/" + userId + "/purge");
    }

    private void purgeRemote(String service, String url) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Internal-Token", internalToken);
        try {
            restTemplate.postForEntity(url, new HttpEntity<>(headers), String.class);
        } catch (Exception e) {
            log.error("{}服务清理账号数据失败：{}", service, e.getMessage());
            throw new ApiException(500, service + "服务清理账号数据失败，账号未删除，请稍后重试");
        }
    }

    // ───────────────────────── 页面访问权限 ─────────────────────────

    @GetMapping("/route-permissions")
    public ResponseEntity<?> routePermissions(@RequestHeader(value = "Authorization", required = false) String authHeader) {
        tokenGuard.requireAdmin(authHeader);
        return ok(accessControlService.routeMatrix());
    }

    @PutMapping("/route-permissions")
    public ResponseEntity<?> saveRoutePermissions(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                                  @RequestBody RoutePermissionForm form) {
        tokenGuard.requireAdmin(authHeader);
        accessControlService.updateRoleRoutes(form.getRole(), form.getAllowedPaths());
        return ok(accessControlService.routeMatrix());
    }

    // ───────────────────────── 高级功能配额 ─────────────────────────

    @GetMapping("/feature-quotas")
    public ResponseEntity<?> featureQuotas(@RequestHeader(value = "Authorization", required = false) String authHeader) {
        tokenGuard.requireAdmin(authHeader);
        return ok(accessControlService.quotaList());
    }

    @PutMapping("/feature-quotas")
    public ResponseEntity<?> saveFeatureQuotas(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                               @RequestBody QuotaForm form) {
        tokenGuard.requireAdmin(authHeader);
        List<QuotaItem> items = form.getItems();
        if (items == null || items.isEmpty()) {
            throw new ApiException(400, "没有需要保存的配额");
        }
        for (QuotaItem item : items) {
            accessControlService.updateQuota(item.getFeatureKey(), item.getRole(),
                    item.getDailyLimit(), item.getEnabled());
        }
        return ok(accessControlService.quotaList());
    }

    // ───────────────────────── 内部工具 ─────────────────────────

    private ResponseEntity<?> ok(Object data) {
        return ResponseEntity.ok(Map.of("code", 200, "data", data));
    }

    private Map<String, Object> toView(User user) {
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("id", user.getId());
        view.put("username", user.getUsername());
        view.put("email", user.getEmail());
        view.put("phone", user.getPhone());
        view.put("role", user.getRole());
        view.put("status", user.getStatus());
        view.put("createdAt", user.getCreatedAt());
        return view;
    }

    private String trim(String value) {
        return value == null ? "" : value.trim();
    }

    /** 选填字段留空时入库为 NULL，避免出现空字符串脏数据 */
    private String trimToNull(String value) {
        String trimmed = trim(value);
        return trimmed.isEmpty() ? null : trimmed;
    }

    /** 密码规则与前端注册页一致：至少 6 位 */
    private void checkPassword(String password) {
        if (password == null || password.length() < 6) {
            throw new ApiException(400, "密码至少 6 位");
        }
    }

    private String normalizeRole(String role) {
        String value = trim(role).toUpperCase();
        if (value.isEmpty()) {
            return RouteCatalog.ROLE_USER;
        }
        if (!RouteCatalog.ROLES.contains(value)) {
            throw new ApiException(400, "未知角色: " + role);
        }
        return value;
    }

    private String normalizeStatus(String status) {
        String value = trim(status).toUpperCase();
        if (value.isEmpty()) {
            return "ACTIVE";
        }
        if (!"ACTIVE".equals(value) && !"DISABLED".equals(value)) {
            throw new ApiException(400, "未知状态: " + status);
        }
        return value;
    }

    @Data
    public static class UserForm {
        private String username;
        private String password;
        private String email;
        private String phone;
        private String role;
        private String status;
    }

    @Data
    public static class RoutePermissionForm {
        private String role;
        private List<String> allowedPaths;
    }

    @Data
    public static class QuotaForm {
        private List<QuotaItem> items;
    }

    @Data
    public static class QuotaItem {
        private String featureKey;
        private String role;
        private Integer dailyLimit;
        private Boolean enabled;
    }
}
