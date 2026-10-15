package com.rotation.fund.service;

import com.rotation.fund.entity.BankTransfer;
import com.rotation.fund.entity.Position;
import com.rotation.fund.entity.Trade;
import com.rotation.fund.repository.BankTransferRepository;
import com.rotation.fund.repository.PositionRepository;
import com.rotation.fund.repository.TradeRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.*;

/**
 * 持仓交易服务：开仓 / 平仓核心逻辑、交易成本计算与收盘盯市。
 *
 * <p>资金模型：现金由真实现金流推导，而非「净入金 − 持仓市值」。
 * 现金 = 净入金 − Σ(买入金额 + 手续费 + 滑点) + Σ(卖出金额 − 手续费 − 印花税 − 滑点)；
 * 总资产 = 现金 + 持仓市值（按 currentPrice 计），因此行情变动可真实反映为盈亏。
 */
@Service
@RequiredArgsConstructor
public class PositionService {

    // 交易成本参数（来自 docs/07 4.2）
    private static final BigDecimal COMMISSION_RATE = new BigDecimal("0.0003"); // 手续费 万三
    private static final BigDecimal STAMP_TAX_RATE = new BigDecimal("0.001");   // 印花税 千一（仅卖出）
    private static final BigDecimal SLIPPAGE_RATE = new BigDecimal("0.001");    // 滑点 千一
    private static final BigDecimal MIN_COMMISSION = new BigDecimal("5");        // 最低 5 元
    private static final BigDecimal LOT_SIZE = BigDecimal.valueOf(100);          // ETF 最小交易单位 100 份

    private final PositionRepository positionRepository;
    private final BankTransferRepository bankTransferRepository;
    private final TradeRepository tradeRepository;
    private final EtfCodeValidator etfCodeValidator;

    /** 净入金 = Σ入金 − Σ出金 */
    public BigDecimal getNetDeposit(Long userId) {
        List<BankTransfer> transfers = bankTransferRepository.findByUserIdOrderByTransferDateDesc(userId);
        BigDecimal net = BigDecimal.ZERO;
        for (BankTransfer t : transfers) {
            if ("DEPOSIT".equals(t.getDirection())) {
                net = net.add(nz(t.getAmount()));
            } else {
                net = net.subtract(nz(t.getAmount()));
            }
        }
        return net;
    }

    /** 当前持仓市值 = Σ(数量 × 当前价，当前价缺失时回退均价) */
    public BigDecimal getMarketValue(Long userId) {
        List<Position> open = positionRepository.findByUserIdAndStatus(userId, "OPEN");
        BigDecimal mv = BigDecimal.ZERO;
        for (Position p : open) {
            BigDecimal price = p.getCurrentPrice() != null ? p.getCurrentPrice() : p.getAvgPrice();
            if (price != null && p.getQuantity() != null) {
                mv = mv.add(price.multiply(p.getQuantity()));
            }
        }
        return mv;
    }

    /** 现金 = 净入金 − Σ买入支出 + Σ卖出回款（交易成本真实扣减，不为负） */
    public BigDecimal getCash(Long userId) {
        BigDecimal cash = getNetDeposit(userId);
        for (Trade t : tradeRepository.findByUserIdOrderByTradedAtDesc(userId)) {
            if ("BUY".equals(t.getDirection())) {
                cash = cash.subtract(nz(t.getAmount()))
                        .subtract(nz(t.getCommission()))
                        .subtract(nz(t.getSlippage()));
            } else {
                cash = cash.add(nz(t.getAmount()))
                        .subtract(nz(t.getCommission()))
                        .subtract(nz(t.getStampTax()))
                        .subtract(nz(t.getSlippage()));
            }
        }
        return cash.compareTo(BigDecimal.ZERO) < 0 ? BigDecimal.ZERO : cash;
    }

    /** 总资产 = 现金 + 持仓市值 */
    public BigDecimal getTotalAssets(Long userId) {
        return getCash(userId).add(getMarketValue(userId));
    }

    @Transactional
    public Position openPosition(Long userId, String strategyType, String sectorCode, String sectorName,
                                 String etfCode, BigDecimal positionRatio, BigDecimal currentPrice) {
        if (currentPrice == null || currentPrice.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("开仓当前价必须为正");
        }
        if (positionRatio == null || positionRatio.compareTo(BigDecimal.ZERO) <= 0
                || positionRatio.compareTo(BigDecimal.ONE) > 0) {
            throw new IllegalArgumentException("仓位比例必须在 (0, 1] 之间");
        }

        // 校验 ETF 代码（格式 → 映射 → 可交易性），缺失时按板块自动填充。
        // 未纳入映射的标的无法采集收盘价，会导致该持仓永不盯市并拖停净值重算，故默认拒绝。
        EtfCodeValidator.ValidationResult validated = etfCodeValidator.validate(etfCode, sectorName);
        if (!validated.accepted()) {
            throw new IllegalArgumentException(validated.reason());
        }

        if (positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                userId, strategyType, "OPEN", sectorCode).isPresent()) {
            throw new IllegalArgumentException("该板块已存在 OPEN 持仓，禁止重复开仓: " + sectorCode);
        }

        BigDecimal targetValue = getTotalAssets(userId).multiply(positionRatio);
        // 取整到 100 份（1 手），避免碎股
        BigDecimal quantity = targetValue.divide(currentPrice, 4, RoundingMode.DOWN)
                .divideToIntegralValue(LOT_SIZE).multiply(LOT_SIZE);
        if (quantity.compareTo(BigDecimal.ZERO) <= 0) {
            throw new IllegalArgumentException("目标市值过小，不足 1 手(100 份)");
        }
        BigDecimal buyAmount = quantity.multiply(currentPrice);
        BigDecimal commission = buyAmount.multiply(COMMISSION_RATE);
        if (commission.compareTo(MIN_COMMISSION) < 0) commission = MIN_COMMISSION;
        BigDecimal slippage = buyAmount.multiply(SLIPPAGE_RATE);

        Position pos = new Position();
        pos.setUserId(userId);
        pos.setStrategyType(strategyType);
        pos.setSectorCode(sectorCode);
        pos.setSectorName(sectorName);
        pos.setEtfCode(validated.etfCode());
        pos.setDirection("BUY");
        pos.setQuantity(quantity);
        pos.setAvgPrice(currentPrice);
        pos.setCurrentPrice(currentPrice);
        pos.setPositionRatio(positionRatio);
        pos.setStatus("OPEN");
        pos = positionRepository.save(pos);

        tradeRepository.save(buildTrade(userId, strategyType, sectorCode, sectorName, pos.getId(), "BUY",
                quantity, currentPrice, buyAmount, commission, BigDecimal.ZERO, slippage));

        return pos;
    }

    @Transactional
    public Position closePosition(Long userId, String strategyType, String sectorCode, BigDecimal currentPrice) {
        Position pos = positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                        userId, strategyType, "OPEN", sectorCode)
                .orElseThrow(() -> new IllegalArgumentException("未找到该板块的 OPEN 持仓: " + sectorCode));

        BigDecimal price = (currentPrice != null && currentPrice.compareTo(BigDecimal.ZERO) > 0)
                ? currentPrice
                : (pos.getCurrentPrice() != null ? pos.getCurrentPrice() : pos.getAvgPrice());
        BigDecimal sellAmount = pos.getQuantity().multiply(price);
        BigDecimal commission = sellAmount.multiply(COMMISSION_RATE);
        if (commission.compareTo(MIN_COMMISSION) < 0) commission = MIN_COMMISSION;
        BigDecimal stampTax = sellAmount.multiply(STAMP_TAX_RATE);
        BigDecimal slippage = sellAmount.multiply(SLIPPAGE_RATE);

        pos.setCurrentPrice(price);
        pos.setStatus("CLOSED");
        pos.setClosedAt(LocalDateTime.now());
        pos = positionRepository.save(pos);

        tradeRepository.save(buildTrade(userId, strategyType, sectorCode, pos.getSectorName(), pos.getId(), "SELL",
                pos.getQuantity(), price, sellAmount, commission, stampTax, slippage));

        return pos;
    }

    /**
     * 收盘盯市：按 ETF 代码回写 OPEN 持仓最新价，并返回价格覆盖完整性。
     *
     * <p>complete=false 表示存在持仓未取到收盘价（缺失代码见 missing_etf_codes），
     * 调用方必须据此中止后续净值重算，避免用陈旧价格写入错误净值。
     */
    @Transactional
    public Map<String, Object> markToMarket(Long userId, Map<String, BigDecimal> priceMap) {
        Map<String, BigDecimal> prices = priceMap != null ? priceMap : Map.of();
        List<Position> opens = positionRepository.findByUserIdAndStatus(userId, "OPEN");
        int updated = 0;
        List<String> missing = new ArrayList<>();
        for (Position p : opens) {
            BigDecimal price = p.getEtfCode() != null ? prices.get(p.getEtfCode()) : null;
            if (price != null && price.compareTo(BigDecimal.ZERO) > 0) {
                p.setCurrentPrice(price);
                positionRepository.save(p);
                updated++;
            } else {
                // 无 ETF 代码或价格缺失都记为不完整，供调度方明确感知
                missing.add(p.getEtfCode() != null ? p.getEtfCode() : "sector:" + p.getSectorCode());
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("open_positions", opens.size());
        result.put("updated", updated);
        result.put("missing_etf_codes", missing);
        result.put("complete", missing.isEmpty());
        return result;
    }

    /** OPEN 持仓涉及的 ETF 代码（供收盘盯市按需采集，避免采集无关标的） */
    public List<String> getOpenEtfCodes(Long userId) {
        List<String> codes = new ArrayList<>();
        for (Position p : positionRepository.findByUserIdAndStatus(userId, "OPEN")) {
            if (p.getEtfCode() != null && !p.getEtfCode().isBlank()) {
                codes.add(p.getEtfCode());
            }
        }
        return codes;
    }

    private Trade buildTrade(Long userId, String strategyType, String sectorCode, String sectorName,
                             Long positionId, String direction, BigDecimal quantity, BigDecimal price,
                             BigDecimal amount, BigDecimal commission, BigDecimal stampTax, BigDecimal slippage) {
        Trade trade = new Trade();
        trade.setUserId(userId);
        trade.setStrategyType(strategyType);
        trade.setSectorCode(sectorCode);
        trade.setSectorName(sectorName);
        trade.setPositionId(positionId);
        trade.setDirection(direction);
        trade.setQuantity(quantity);
        trade.setPrice(price);
        trade.setAmount(amount);
        trade.setCommission(commission);
        trade.setStampTax(stampTax);
        trade.setSlippage(slippage);
        trade.setSignalDate(LocalDateTime.now().toLocalDate());
        return trade;
    }

    private BigDecimal nz(BigDecimal v) {
        return v != null ? v : BigDecimal.ZERO;
    }
}
