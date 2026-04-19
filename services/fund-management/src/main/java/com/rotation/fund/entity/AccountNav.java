package com.rotation.fund.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "account_nav", uniqueConstraints = {
    @UniqueConstraint(columnNames = {"user_id", "nav_date"})
})
public class AccountNav {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "nav_date", nullable = false)
    private LocalDate navDate;

    @Column(name = "total_assets", nullable = false, precision = 15, scale = 4)
    private BigDecimal totalAssets = BigDecimal.ZERO;

    @Column(nullable = false, precision = 15, scale = 4)
    private BigDecimal cash = BigDecimal.ZERO;

    @Column(name = "market_value", nullable = false, precision = 15, scale = 4)
    private BigDecimal marketValue = BigDecimal.ZERO;

    @Column(name = "daily_return", precision = 8, scale = 6)
    private BigDecimal dailyReturn;

    @Column(name = "cumulative_return", precision = 8, scale = 6)
    private BigDecimal cumulativeReturn;

    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @PrePersist
    protected void onCreate() {
        createdAt = LocalDateTime.now();
    }
}
