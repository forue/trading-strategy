package com.rotation.auth.controller;

import com.rotation.auth.entity.User;
import com.rotation.auth.service.AccessControlService;
import com.rotation.auth.support.RouteCatalog;
import com.rotation.auth.support.TokenGuard;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 当前登录用户可见的权限与功能配额。
 *
 * 前端路由守卫与侧栏过滤读 /permissions/me；
 * 策略服务在消耗型功能（如盘感训练）入口调用 /quota/consume。
 */
@RestController
@RequestMapping("/api/auth")
public class AccessController {

    private final TokenGuard tokenGuard;
    private final AccessControlService accessControlService;

    public AccessController(TokenGuard tokenGuard, AccessControlService accessControlService) {
        this.tokenGuard = tokenGuard;
        this.accessControlService = accessControlService;
    }

    @GetMapping("/permissions/me")
    public ResponseEntity<?> myPermissions(@RequestHeader(value = "Authorization", required = false) String authHeader) {
        User user = tokenGuard.requireUser(authHeader);

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("id", user.getId());
        data.put("username", user.getUsername());
        data.put("role", user.getRole());
        data.put("isAdmin", RouteCatalog.ROLE_ADMIN.equals(user.getRole()));
        data.put("allowedPaths", accessControlService.allowedPaths(user.getRole()));

        return ResponseEntity.ok(Map.of("code", 200, "data", data));
    }

    @GetMapping("/quota/me")
    public ResponseEntity<?> myQuota(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                     @RequestParam String feature) {
        User user = tokenGuard.requireUser(authHeader);
        return ResponseEntity.ok(Map.of("code", 200,
                "data", accessControlService.quotaState(feature, user.getRole(), user.getId())));
    }

    /**
     * 消耗一次配额。服务间调用：调用方把用户 Token 转发过来，
     * 计数按 Token 解析出的账号计，不信任请求参数里的用户名。
     */
    @PostMapping("/quota/consume")
    public ResponseEntity<?> consume(@RequestHeader(value = "Authorization", required = false) String authHeader,
                                     @RequestParam String feature) {
        User user = tokenGuard.requireUser(authHeader);
        return ResponseEntity.ok(Map.of("code", 200,
                "data", accessControlService.consumeQuota(feature, user.getRole(), user.getId())));
    }
}
