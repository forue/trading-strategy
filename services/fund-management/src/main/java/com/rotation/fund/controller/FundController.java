package com.rotation.fund.controller;

import com.rotation.fund.entity.AccountNav;
import com.rotation.fund.entity.BankTransfer;
import com.rotation.fund.entity.Position;
import com.rotation.fund.repository.AccountNavRepository;
import com.rotation.fund.repository.BankTransferRepository;
import com.rotation.fund.repository.PositionRepository;
import com.rotation.fund.service.AccountNavService;
import com.rotation.fund.service.PositionService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
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
    private final PositionService positionService;
    private final AccountNavService accountNavService;

    @Value("${fund.internal.enabled:false}")
    private boolean internalEndpointsEnabled;

    public FundController(PositionRepository positionRepository,
                          AccountNavRepository accountNavRepository,
                          BankTransferRepository bankTransferRepository,
                          PositionService positionService,
                          AccountNavService accountNavService) {
        this.positionRepository = positionRepository;
        this.accountNavRepository = accountNavRepository;
        this.bankTransferRepository = bankTransferRepository;
        this.positionService = positionService;
        this.accountNavService = accountNavService;
    }

    @GetMapping("/summary")
    public ResponseEntity<?> getAccountSummary(
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        Map<String, Object> summary = accountNavService.getSummary(userId);
        return ResponseEntity.ok(Map.of("code", 200, "data", summary));
    }

    @PostMapping("/recalc-nav")
    public ResponseEntity<?> recalcNav(
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        AccountNav nav = accountNavService.recalcNav(userId, LocalDate.now());
        return ResponseEntity.ok(Map.of("code", 200, "message", "净值已重算", "data", nav));
    }

    /**
     * 收盘盯市：接收 {ETF代码: 收盘价} 映射，回写 OPEN 持仓最新价。
     * 由 scheduler 收盘任务调用（scheduler 用 AkShare 取 ETF 收盘价后推送），解决持仓价格永不更新的问题。
     */
    @PostMapping("/mark-to-market")
    public ResponseEntity<?> markToMarket(@RequestBody Map<String, Object> body,
                                          @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        Map<String, BigDecimal> prices = new HashMap<>();
        Object raw = body.get("prices");
        if (raw instanceof Map<?, ?> priceMap) {
            for (Map.Entry<?, ?> e : priceMap.entrySet()) {
                prices.put(String.valueOf(e.getKey()), new BigDecimal(String.valueOf(e.getValue())));
            }
        }
        Map<String, Object> result = accountNavService.markToMarket(userId, prices);
        boolean complete = Boolean.TRUE.equals(result.get("complete"));
        return ResponseEntity.ok(Map.of("code", 200,
                "message", complete ? "盯市完成" : "盯市未完成：部分持仓缺少收盘价",
                "data", result));
    }

    /** 当前持仓涉及的 ETF 代码，供调度方按需采集收盘价（按持仓需求驱动，避免采集无关标的） */
    @GetMapping("/etf-codes")
    public ResponseEntity<?> getHoldingEtfCodes(
            @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        List<String> codes = positionService.getOpenEtfCodes(userId);
        return ResponseEntity.ok(Map.of("code", 200, "data", codes));
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

        // 当日盈亏 = 当日总资产 − 上一净值日总资产（量纲为金额，不能用收益率×资产近似）
        BigDecimal prevTotal = accountNavRepository
                .findTopByUserIdAndNavDateBeforeOrderByNavDateDesc(userId, start)
                .map(AccountNav::getTotalAssets)
                .orElse(null);

        List<Map<String, Object>> result = new ArrayList<>();
        for (AccountNav nav : navList) {
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
            item.put("daily_pnl_amount", (prevTotal != null && nav.getTotalAssets() != null)
                    ? nav.getTotalAssets().subtract(prevTotal).setScale(2, RoundingMode.HALF_UP)
                    : BigDecimal.ZERO);
            if (nav.getTotalAssets() != null) {
                prevTotal = nav.getTotalAssets();
            }
            result.add(item);
        }

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

        // 峰值（peak）为 0 时必须跳过：空账户（未入金、无持仓）的净值记录 total_assets=0，
        // 直接用 peak 做除数会抛 ArithmeticException(/ by zero) 导致接口 500。
        BigDecimal peak = BigDecimal.ZERO;
        BigDecimal maxDrawdown = BigDecimal.ZERO;
        for (AccountNav nav : navList) {
            BigDecimal assets = nav.getTotalAssets() != null ? nav.getTotalAssets() : BigDecimal.ZERO;
            if (assets.compareTo(peak) > 0) {
                peak = assets;
            }
            if (peak.compareTo(BigDecimal.ZERO) <= 0) {
                continue;
            }
            BigDecimal dd = peak.subtract(assets).multiply(BigDecimal.valueOf(100))
                    .divide(peak, 2, RoundingMode.HALF_UP);
            if (dd.compareTo(maxDrawdown) > 0) {
                maxDrawdown = dd;
            }
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
        accountNavService.refreshSummaryCache(userId);

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
        accountNavService.refreshSummaryCache(userId);
        return ResponseEntity.ok(Map.of("code", 200, "message", "转账记录已删除"));
    }

    /**
     * 内部触发端点（仅供本地联调，不依赖 RabbitMQ 即可验证 Service 层）。
     * 默认关闭，需显式配置 fund.internal.enabled=true 才可用，避免无鉴权下单风险。
     */
    @PostMapping("/execute")
    public ResponseEntity<?> executeTrade(@RequestBody Map<String, Object> body,
                                         @RequestHeader(value = "X-User-Id", defaultValue = "1") Long userId) {
        if (!internalEndpointsEnabled) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN)
                    .body(Map.of("code", 403, "message", "内部端点未启用（需设置 fund.internal.enabled=true）"));
        }
        String strategyType = (String) body.get("strategyType");
        String sectorCode = (String) body.get("sectorCode");
        String sectorName = body.get("sectorName") != null ? (String) body.get("sectorName") : "";
        String etfCode = body.get("etfCode") != null ? (String) body.get("etfCode") : null;
        String direction = body.getOrDefault("direction", "BUY").toString();
        BigDecimal positionRatio = new BigDecimal(body.getOrDefault("positionRatio", "0").toString());
        BigDecimal currentPrice = body.get("currentPrice") != null
                ? new BigDecimal(body.get("currentPrice").toString()) : null;

        Position pos;
        if ("SELL".equals(direction)) {
            pos = positionService.closePosition(userId, strategyType, sectorCode, currentPrice);
        } else {
            pos = positionService.openPosition(userId, strategyType, sectorCode, sectorName, etfCode,
                    positionRatio, currentPrice);
        }
        accountNavService.recalcNav(userId, LocalDate.now());
        return ResponseEntity.ok(Map.of("code", 200, "message", "执行完成", "data", pos));
    }

    @GetMapping("/health")
    public ResponseEntity<?> health() {
        return ResponseEntity.ok(Map.of("status", "healthy", "service", "fund-management"));
    }
}
