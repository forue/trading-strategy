package com.rotation.fund.entity;

import jakarta.persistence.*;
import lombok.Data;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@Entity
@Table(name = "trades")
public class Trade {

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

    /** 关联持仓，便于开/平仓配对与对账 */
    @Column(name = "position_id")
    private Long positionId;

    @Column(nullable = false, length = 10)
    private String direction;

    @Column(nullable = false, precision = 15, scale = 4)
    private BigDecimal quantity = BigDecimal.ZERO;

    @Column(nullable = false, precision = 10, scale = 4)
    private BigDecimal price = BigDecimal.ZERO;

    @Column(nullable = false, precision = 15, scale = 4)
    private BigDecimal amount = BigDecimal.ZERO;

    @Column(nullable = false, precision = 10, scale = 4)
    private BigDecimal commission = BigDecimal.ZERO;

    @Column(nullable = false, precision = 10, scale = 4)
    private BigDecimal stampTax = BigDecimal.ZERO;

    @Column(nullable = false, precision = 10, scale = 4)
    private BigDecimal slippage = BigDecimal.ZERO;

    @Column(name = "signal_date", nullable = false)
    private LocalDate signalDate;

    @Column(name = "traded_at", updatable = false)
    private LocalDateTime tradedAt;

    @PrePersist
    protected void onCreate() {
        tradedAt = LocalDateTime.now();
    }
}
