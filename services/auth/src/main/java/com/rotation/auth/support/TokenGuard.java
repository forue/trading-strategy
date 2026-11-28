package com.rotation.auth.support;

import com.rotation.auth.entity.User;
import com.rotation.auth.repository.UserRepository;
import com.rotation.auth.util.JwtUtil;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 请求级身份校验：Token → 当前用户 → 管理员校验。
 *
 * 角色以数据库为准（不是 Token 里的 claim）：管理员被降级为 USER 后，
 * 手里的旧 Token 立刻失去后台接口权限。
 */
@Component
public class TokenGuard {

    private final JwtUtil jwtUtil;
    private final StringRedisTemplate redisTemplate;
    private final UserRepository userRepository;

    public TokenGuard(JwtUtil jwtUtil, StringRedisTemplate redisTemplate, UserRepository userRepository) {
        this.jwtUtil = jwtUtil;
        this.redisTemplate = redisTemplate;
        this.userRepository = userRepository;
    }

    public User requireUser(String authHeader) {
        if (authHeader == null || !authHeader.startsWith("Bearer ")) {
            throw new ApiException(401, "缺少认证信息");
        }
        String token = authHeader.substring(7);
        if (!jwtUtil.validateToken(token)) {
            throw new ApiException(401, "登录状态已失效，请重新登录");
        }
        if (Boolean.TRUE.equals(redisTemplate.hasKey("token:blacklist:" + token))) {
            throw new ApiException(401, "Token已失效");
        }
        User user = userRepository.findByUsername(jwtUtil.getUsernameFromToken(token))
                .orElseThrow(() -> new ApiException(401, "用户不存在"));
        if (!"ACTIVE".equals(user.getStatus())) {
            throw new ApiException(403, "账号已被禁用");
        }
        return user;
    }

    public User requireAdmin(String authHeader) {
        User user = requireUser(authHeader);
        if (!RouteCatalog.ROLE_ADMIN.equals(user.getRole())) {
            throw new ApiException(403, "需要管理员权限");
        }
        return user;
    }
}
