package com.rotation.auth.entity;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 高级功能配额：角色在某功能上的每日次数上限。
 *
 * dailyLimit = 0 表示不限次；enabled = false 表示该角色完全不开放该功能。
 * 当日实际用量不入库，存 Redis（quota:{feature}:{userId}:{yyyy-MM-dd}）。
 */
@Data
@Entity
@Table(name = "feature_quotas",
        uniqueConstraints = @UniqueConstraint(name = "uk_feature_quota", columnNames = {"feature_key", "role"}))
public class FeatureQuota {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "feature_key", nullable = false, length = 64)
    private String featureKey;

    @Column(nullable = false, length = 20)
    private String role;

    @Column(name = "daily_limit", nullable = false)
    private Integer dailyLimit = 0;

    @Column(nullable = false)
    private Boolean enabled = Boolean.TRUE;

    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @PrePersist
    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}
