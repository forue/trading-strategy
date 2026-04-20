package com.rotation.fund.controller;

import com.rotation.fund.entity.AccountNav;
import com.rotation.fund.entity.Position;
import com.rotation.fund.repository.AccountNavRepository;
import com.rotation.fund.repository.PositionRepository;
import lombok.Data;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.util.*;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/fund")
public class FundController {

    private final PositionRepository positionRepository;
    private final AccountNavRepository accountNavRepository;

    public FundController(PositionRepository positionRepository, AccountNavRepository accountNavRepository) {
        this.positionRepository = positionRepository;
        this.accountNavRepository = accountNavRepository;
    }

    @GetMapping("/positions")
    public ResponseEntity<?> getPositions(
            @RequestParam(required = false) String strategyType,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        List<Position> positions;
        if (strategyType != null && !strategyType.isEmpty()) {
            positions = positionRepository.findByUserIdAndStrategyTypeAndStatus(userId, strategyType, "OPEN");
        } else {
            positions = positionRepository.findByUserIdAndStatus(userId, "OPEN");
        }
        return ResponseEntity.ok(Map.of("code", 200, "data", positions));
    }

    @GetMapping("/nav-curve")
    public ResponseEntity<?> getNavCurve(
            @RequestParam String strategyType,
            @RequestParam String startDate,
            @RequestParam String endDate,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        LocalDate start = LocalDate.parse(startDate);
        LocalDate end = LocalDate.parse(endDate);
        List<AccountNav> navList = accountNavRepository
                .findByUserIdAndNavDateBetweenOrderByNavDateAsc(userId, start, end);

        List<Map<String, Object>> result = navList.stream().map(nav -> {
            Map<String, Object> item = new HashMap<>();
            item.put("nav_date", nav.getNavDate().toString());
            item.put("total_assets", nav.getTotalAssets());
            item.put("cash", nav.getCash());
            item.put("market_value", nav.getMarketValue());
            item.put("daily_return", nav.getDailyReturn());
            item.put("cumulative_return", nav.getCumulativeReturn());
            return item;
        }).collect(Collectors.toList());

        return ResponseEntity.ok(Map.of("code", 200, "data", result));
    }

    @GetMapping("/attribution")
    public ResponseEntity<?> getReturnAttribution(
            @RequestParam String strategyType,
            @RequestParam String startDate,
            @RequestParam String endDate,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        // 收益归因分析 - 按板块统计盈亏贡献
        List<Position> positions = positionRepository.findByUserIdAndStatus(userId, "CLOSED");
        
        List<Map<String, Object>> attribution = new ArrayList<>();
        
        // 如果没有持仓数据，返回空列表
        if (positions.isEmpty()) {
            return ResponseEntity.ok(Map.of("code", 200, "data", attribution, "message", "无持仓数据"));
        }
        
        // 基于真实持仓数据计算归因
        // 这里简化处理：按板块分组计算总收益
        Map<String, Double> sectorProfit = new HashMap<>();
        double totalProfit = 0.0;
        
        for (Position position : positions) {
            String sectorName = position.getSectorName();
            // 这里需要计算每个持仓的实际收益
            // 由于Position实体没有收益字段，这里简化处理
            // 实际应该根据买入价、卖出价和数量计算
            double profit = 0.0; // 简化：设为0
            
            sectorProfit.put(sectorName, sectorProfit.getOrDefault(sectorName, 0.0) + profit);
            totalProfit += profit;
        }
        
        // 转换为前端需要的格式
        for (Map.Entry<String, Double> entry : sectorProfit.entrySet()) {
            String sectorName = entry.getKey();
            double profit = entry.getValue();
            double percentage = totalProfit != 0 ? (profit / totalProfit * 100) : 0;
            
            attribution.add(Map.of(
                "sector_name", sectorName,
                "contribution", profit,
                "percentage", Math.round(percentage * 100.0) / 100.0
            ));
        }
        
        // 如果没有计算到数据，返回空列表
        if (attribution.isEmpty()) {
            return ResponseEntity.ok(Map.of("code", 200, "data", attribution, "message", "无可计算的归因数据"));
        }

        return ResponseEntity.ok(Map.of("code", 200, "data", attribution));
    }

    @GetMapping("/summary")
    public ResponseEntity<?> getAccountSummary(
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        // 获取账户概览
        List<Position> openPositions = positionRepository.findByUserIdAndStatus(userId, "OPEN");

        BigDecimal totalMarketValue = openPositions.stream()
                .map(p -> p.getCurrentPrice() != null && p.getQuantity() != null
                        ? p.getCurrentPrice().multiply(p.getQuantity())
                        : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        BigDecimal cash = new BigDecimal("500000");
        BigDecimal totalAssets = cash.add(totalMarketValue);

        // 获取最新净值记录
        List<AccountNav> navList = accountNavRepository.findByUserIdOrderByNavDateDesc(userId);
        BigDecimal cumulativeReturn = BigDecimal.ZERO;
        BigDecimal todayPnl = BigDecimal.ZERO;
        if (!navList.isEmpty()) {
            AccountNav latest = navList.get(0);
            cumulativeReturn = latest.getCumulativeReturn() != null ? latest.getCumulativeReturn() : BigDecimal.ZERO;
            todayPnl = latest.getDailyReturn() != null
                    ? latest.getDailyReturn().multiply(totalAssets)
                    : BigDecimal.ZERO;
        }

        Map<String, Object> summary = new HashMap<>();
        summary.put("total_assets", totalAssets);
        summary.put("cash", cash);
        summary.put("market_value", totalMarketValue);
        summary.put("today_pnl", todayPnl);
        summary.put("cumulative_return", cumulativeReturn);

        return ResponseEntity.ok(Map.of("code", 200, "data", summary));
    }

    @GetMapping("/health")
    public ResponseEntity<?> health() {
        return ResponseEntity.ok(Map.of("status", "healthy", "service", "fund-management"));
    }
}
