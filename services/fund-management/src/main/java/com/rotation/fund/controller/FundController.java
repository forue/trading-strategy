package com.rotation.fund.controller;

import com.rotation.fund.entity.AccountNav;
import com.rotation.fund.entity.BankTransfer;
import com.rotation.fund.entity.Position;
import com.rotation.fund.repository.AccountNavRepository;
import com.rotation.fund.repository.BankTransferRepository;
import com.rotation.fund.repository.PositionRepository;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.stream.Collectors;

@RestController
@RequestMapping("/api/fund")
public class FundController {

    private final PositionRepository positionRepository;
    private final AccountNavRepository accountNavRepository;
    private final BankTransferRepository bankTransferRepository;

    public FundController(PositionRepository positionRepository,
                          AccountNavRepository accountNavRepository,
                          BankTransferRepository bankTransferRepository) {
        this.positionRepository = positionRepository;
        this.accountNavRepository = accountNavRepository;
        this.bankTransferRepository = bankTransferRepository;
    }

    @GetMapping("/summary")
    public ResponseEntity<?> getAccountSummary(
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        List<Position> openPositions = positionRepository.findByUserIdAndStatus(userId, "OPEN");
        BigDecimal totalMarketValue = openPositions.stream()
                .map(p -> p.getCurrentPrice() != null && p.getQuantity() != null
                        ? p.getCurrentPrice().multiply(p.getQuantity())
                        : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        List<BankTransfer> transfers = bankTransferRepository.findByUserIdOrderByTransferDateDesc(userId);
        BigDecimal netDeposit = BigDecimal.ZERO;
        for (BankTransfer t : transfers) {
            if ("DEPOSIT".equals(t.getDirection())) netDeposit = netDeposit.add(t.getAmount());
            else netDeposit = netDeposit.subtract(t.getAmount());
        }
        BigDecimal cash = netDeposit.subtract(totalMarketValue);
        if (cash.compareTo(BigDecimal.ZERO) < 0) cash = BigDecimal.ZERO;

        List<AccountNav> navList = accountNavRepository.findByUserIdOrderByNavDateDesc(userId);
        BigDecimal cumulativeReturn = BigDecimal.ZERO;
        BigDecimal todayPnl = BigDecimal.ZERO;
        if (!navList.isEmpty()) {
            AccountNav latest = navList.get(0);
            cumulativeReturn = latest.getCumulativeReturn() != null ? latest.getCumulativeReturn() : BigDecimal.ZERO;
            todayPnl = latest.getDailyReturn() != null
                    ? latest.getDailyReturn().multiply(totalMarketValue).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO;
        }

        Map<String, Object> summary = new HashMap<>();
        summary.put("total_assets", totalMarketValue.add(cash));
        summary.put("cash", cash);
        summary.put("market_value", totalMarketValue);
        summary.put("today_pnl", todayPnl);
        summary.put("cumulative_return", cumulativeReturn);
        summary.put("net_deposit", netDeposit);

        return ResponseEntity.ok(Map.of("code", 200, "data", summary));
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
            @RequestParam(defaultValue = "1") Integer strategyType,
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

    @GetMapping("/daily-pnl")
    public ResponseEntity<?> getDailyPnl(
            @RequestParam String month,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        LocalDate start = LocalDate.parse(month + "-01");
        LocalDate end = start.withDayOfMonth(start.lengthOfMonth());
        List<AccountNav> navList = accountNavRepository
                .findByUserIdAndNavDateBetweenOrderByNavDateAsc(userId, start, end);

        List<Map<String, Object>> result = navList.stream().map(nav -> {
            Map<String, Object> item = new HashMap<>();
            item.put("date", nav.getNavDate().toString());
            item.put("total_assets", nav.getTotalAssets());
            item.put("market_value", nav.getMarketValue());
            item.put("daily_return", nav.getDailyReturn() != null
                    ? nav.getDailyReturn().multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            item.put("cumulative_return", nav.getCumulativeReturn() != null
                    ? nav.getCumulativeReturn().multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            item.put("daily_pnl_amount", nav.getDailyReturn() != null && nav.getTotalAssets() != null
                    ? nav.getDailyReturn().multiply(nav.getTotalAssets()).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            return item;
        }).collect(Collectors.toList());

        return ResponseEntity.ok(Map.of("code", 200, "data", result));
    }

    @GetMapping("/profit-curve")
    public ResponseEntity<?> getProfitCurve(
            @RequestParam(defaultValue = "3") int months,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        LocalDate end = LocalDate.now();
        LocalDate start = end.minusMonths(months);
        List<AccountNav> navList = accountNavRepository
                .findByUserIdAndNavDateBetweenOrderByNavDateAsc(userId, start, end);

        if (navList.isEmpty()) {
            return ResponseEntity.ok(Map.of("code", 200, "data", Map.of(
                    "nav_curve", List.of(),
                    "monthly_returns", List.of(),
                    "stats", Map.of()
            )));
        }

        List<Map<String, Object>> navCurve = navList.stream().map(nav -> {
            Map<String, Object> item = new HashMap<>();
            item.put("nav_date", nav.getNavDate().toString());
            item.put("total_assets", nav.getTotalAssets());
            item.put("daily_return_pct", nav.getDailyReturn() != null
                    ? nav.getDailyReturn().multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            item.put("cumulative_return_pct", nav.getCumulativeReturn() != null
                    ? nav.getCumulativeReturn().multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            return item;
        }).collect(Collectors.toList());

        Map<String, List<AccountNav>> monthlyMap = new LinkedHashMap<>();
        for (AccountNav nav : navList) {
            String monthKey = nav.getNavDate().format(DateTimeFormatter.ofPattern("yyyy-MM"));
            monthlyMap.computeIfAbsent(monthKey, k -> new ArrayList<>()).add(nav);
        }
        List<Map<String, Object>> monthlyReturns = new ArrayList<>();
        for (Map.Entry<String, List<AccountNav>> entry : monthlyMap.entrySet()) {
            List<AccountNav> monthNavs = entry.getValue();
            BigDecimal startAsset = monthNavs.get(0).getTotalAssets();
            BigDecimal endAsset = monthNavs.get(monthNavs.size() - 1).getTotalAssets();
            BigDecimal monthReturn = startAsset.compareTo(BigDecimal.ZERO) > 0
                    ? endAsset.subtract(startAsset).divide(startAsset, 6, RoundingMode.HALF_UP)
                            .multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO;
            monthlyReturns.add(Map.of("month", entry.getKey(), "return_pct", monthReturn));
        }

        AccountNav firstNav = navList.get(0);
        AccountNav lastNav = navList.get(navList.size() - 1);
        BigDecimal totalReturn = lastNav.getCumulativeReturn() != null
                ? lastNav.getCumulativeReturn().multiply(BigDecimal.valueOf(100)).setScale(2, RoundingMode.HALF_UP)
                : BigDecimal.ZERO;

        Map<String, Object> stats = new HashMap<>();
        stats.put("total_return_pct", totalReturn);
        stats.put("max_drawdown_pct", BigDecimal.ZERO);
        stats.put("annual_return_pct", BigDecimal.ZERO);
        stats.put("sharpe_ratio", BigDecimal.ZERO);
        stats.put("start_date", firstNav.getNavDate().toString());
        stats.put("end_date", lastNav.getNavDate().toString());

        BigDecimal peak = BigDecimal.ZERO;
        BigDecimal maxDrawdown = BigDecimal.ZERO;
        for (AccountNav nav : navList) {
            if (nav.getTotalAssets().compareTo(peak) > 0) peak = nav.getTotalAssets();
            BigDecimal dd = peak.subtract(nav.getTotalAssets()).multiply(BigDecimal.valueOf(100))
                    .divide(peak, 2, RoundingMode.HALF_UP);
            if (dd.compareTo(maxDrawdown) > 0) maxDrawdown = dd;
        }
        stats.put("max_drawdown_pct", maxDrawdown);

        return ResponseEntity.ok(Map.of("code", 200, "data", Map.of(
                "nav_curve", navCurve,
                "monthly_returns", monthlyReturns,
                "stats", stats
        )));
    }

    @GetMapping("/attribution")
    public ResponseEntity<?> getReturnAttribution(
            @RequestParam(defaultValue = "") String strategyType,
            @RequestParam String startDate,
            @RequestParam String endDate,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        List<Position> positions = positionRepository.findByUserIdAndStatus(userId, "CLOSED");
        List<Map<String, Object>> attribution = new ArrayList<>();
        if (positions.isEmpty()) {
            return ResponseEntity.ok(Map.of("code", 200, "data", attribution, "message", "无持仓数据"));
        }

        Map<String, Double> sectorProfit = new HashMap<>();
        double totalProfit = 0.0;
        for (Position position : positions) {
            String sectorName = position.getSectorName();
            double profit = 0.0;
            if (position.getAvgPrice() != null && position.getCurrentPrice() != null && position.getQuantity() != null) {
                profit = position.getCurrentPrice().subtract(position.getAvgPrice())
                        .multiply(position.getQuantity()).doubleValue();
            }
            sectorProfit.put(sectorName, sectorProfit.getOrDefault(sectorName, 0.0) + profit);
            totalProfit += profit;
        }

        for (Map.Entry<String, Double> entry : sectorProfit.entrySet()) {
            double profit = entry.getValue();
            double percentage = totalProfit != 0 ? (profit / totalProfit * 100) : 0;
            attribution.add(Map.of(
                    "sector_name", entry.getKey(),
                    "contribution", BigDecimal.valueOf(profit).setScale(2, RoundingMode.HALF_UP),
                    "percentage", BigDecimal.valueOf(percentage).setScale(2, RoundingMode.HALF_UP)
            ));
        }
        attribution.sort((a, b) -> Double.compare(
                ((Number) b.get("contribution")).doubleValue(),
                ((Number) a.get("contribution")).doubleValue()
        ));

        return ResponseEntity.ok(Map.of("code", 200, "data", attribution));
    }

    @PostMapping("/transfer")
    public ResponseEntity<?> createTransfer(@RequestBody Map<String, Object> body,
                                             @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        BankTransfer transfer = new BankTransfer();
        transfer.setUserId(userId);
        transfer.setTransferDate(LocalDate.parse((String) body.get("transfer_date")));
        transfer.setDirection((String) body.get("direction"));
        transfer.setAmount(new BigDecimal(body.get("amount").toString()));
        transfer.setRemark((String) body.getOrDefault("remark", ""));
        bankTransferRepository.save(transfer);

        return ResponseEntity.ok(Map.of("code", 200, "message", "转账记录已创建", "data", transfer));
    }

    @GetMapping("/transfers")
    public ResponseEntity<?> getTransfers(
            @RequestParam(required = false) String startDate,
            @RequestParam(required = false) String endDate,
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        List<BankTransfer> transfers;
        if (startDate != null && endDate != null) {
            transfers = bankTransferRepository.findByUserIdAndTransferDateBetweenOrderByTransferDateDesc(
                    userId, LocalDate.parse(startDate), LocalDate.parse(endDate));
        } else {
            transfers = bankTransferRepository.findByUserIdOrderByTransferDateDesc(userId);
        }
        return ResponseEntity.ok(Map.of("code", 200, "data", transfers));
    }

    @DeleteMapping("/transfer/{id}")
    public ResponseEntity<?> deleteTransfer(@PathVariable Long id,
                                             @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        bankTransferRepository.deleteById(id);
        return ResponseEntity.ok(Map.of("code", 200, "message", "转账记录已删除"));
    }

    @GetMapping("/health")
    public ResponseEntity<?> health() {
        return ResponseEntity.ok(Map.of("status", "healthy", "service", "fund-management"));
    }
}
