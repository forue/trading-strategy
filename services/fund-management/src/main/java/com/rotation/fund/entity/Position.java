package com.rotation.fund.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "positions")
public class Position {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "strategy_type", nullable = false, length = 20)
    private String strategyType;

    @Column(name = "sector_code", nullable = false, length = 20)
    private String sectorCode;

    @Column(name = "sector_name", nullable = false, length = 50)
    private String sectorName;

    @Column(nullable = false, length = 10)
    private String direction = "BUY";

    @Column(nullable = false, precision = 15, scale = 4)
    private BigDecimal quantity = BigDecimal.ZERO;

    @Column(name = "avg_price", nullable = false, precision = 10, scale = 4)
    private BigDecimal avgPrice = BigDecimal.ZERO;

    @Column(name = "current_price", precision = 10, scale = 4)
    private BigDecimal currentPrice;

    @Column(name = "position_ratio", nullable = false, precision = 5, scale = 4)
    private BigDecimal positionRatio = BigDecimal.ZERO;

    @Column(name = "opened_at", updatable = false)
    private LocalDateTime openedAt;

    @Column(name = "closed_at")
    private LocalDateTime closedAt;

    @Column(nullable = false, length = 20)
    private String status = "OPEN";

    @PrePersist
    protected void onCreate() {
        openedAt = LocalDateTime.now();
    }
}
