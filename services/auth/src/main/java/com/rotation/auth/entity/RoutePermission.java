package com.rotation.auth.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 页面访问权限：角色 → 前端路由路径（是否可访问）。
 *
 * 一行为「某角色对某页面的授权」，页面清单由 RouteCatalog 维护，
 * 缺行视为未授权，因此新增页面后需要由 AccessControlService 补默认值。
 */
@Data
@Entity
@Table(name = "route_permissions",
        uniqueConstraints = @UniqueConstraint(name = "uk_route_permission", columnNames = {"role", "route_path"}))
public class RoutePermission {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 20)
    private String role;

    @Column(name = "route_path", nullable = false, length = 100)
    private String routePath;

    @Column(nullable = false)
    private Boolean allowed = Boolean.FALSE;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
