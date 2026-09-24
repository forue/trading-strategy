package com.rotation.fund.service;

import com.fasterxml.jackson.core.JsonGenerator;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rotation.fund.entity.AccountNav;
import com.rotation.fund.repository.AccountNavRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDate;
import java.util.*;

/**
 * 账户净值服务：重算并落库每日净值（upsert）、收盘盯市，并维护 Redis 缓存 fund:summary:{user_id}。
 * 现金与总资产由 PositionService 提供（含交易成本的真实现金流）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AccountNavService {

    private static final BigDecimal ZERO = BigDecimal.ZERO;
    private static final BigDecimal ONE = BigDecimal.ONE;
    private static final String CACHE_PREFIX = "fund:summary:";
    private static final Duration CACHE_TTL = Duration.ofMinutes(5);

    private final PositionService positionService;
    private final AccountNavRepository accountNavRepository;
    private final StringRedisTemplate redisTemplate;
    // 金额以普通十进制输出，避免反序列化为 Double 造成精度/科学计数问题
    private final ObjectMapper objectMapper =
            new ObjectMapper().enable(JsonGenerator.Feature.WRITE_BIGDECIMAL_AS_PLAIN);

    /** 重算并落库指定日期的账户净值，并刷新概览缓存 */
    @Transactional
    public AccountNav recalcNav(Long userId, LocalDate date) {
        BigDecimal marketValue = positionService.getMarketValue(userId);
        BigDecimal cash = positionService.getCash(userId);
        BigDecimal totalAssets = cash.add(marketValue);

        BigDecimal prevTotal = getPreviousTotalAssets(userId, date);
        BigDecimal dailyReturn = ZERO;
        if (prevTotal != null && prevTotal.compareTo(ZERO) > 0) {
            dailyReturn = totalAssets.divide(prevTotal, 6, RoundingMode.HALF_UP).subtract(ONE);
        }

        BigDecimal initial = getInitialCapital(userId);
        BigDecimal cumulative = ZERO;
        if (initial.compareTo(ZERO) > 0) {
            cumulative = totalAssets.divide(initial, 6, RoundingMode.HALF_UP).subtract(ONE);
        }

        AccountNav nav = accountNavRepository.findByUserIdAndNavDate(userId, date)
                .orElse(new AccountNav());
        nav.setUserId(userId);
        nav.setNavDate(date);
        nav.setTotalAssets(totalAssets);
        nav.setCash(cash);
        nav.setMarketValue(marketValue);
        nav.setDailyReturn(dailyReturn);
        nav.setCumulativeReturn(cumulative);
        AccountNav saved = accountNavRepository.save(nav);

        refreshSummaryCache(userId);
        return saved;
    }

    /** 收盘盯市：回写 OPEN 持仓最新价后刷新缓存，返回覆盖完整性结果 */
    @Transactional
    public Map<String, Object> markToMarket(Long userId, Map<String, BigDecimal> priceMap) {
        Map<String, Object> result = positionService.markToMarket(userId, priceMap);
        Number updated = (Number) result.get("updated");
        if (updated != null && updated.intValue() > 0) {
            refreshSummaryCache(userId);
        }
        return result;
    }

    /** 计算账户概览；优先读 Redis 缓存，未命中则实时计算并回填 */
    public Map<String, Object> getSummary(Long userId) {
        String cached = safeGet(CACHE_PREFIX + userId);
        if (cached != null) {
            try {
                return objectMapper.readValue(cached, Map.class);
            } catch (JsonProcessingException e) {
                log.warn("净值概览缓存解析失败，降级实时计算: {}", e.getMessage());
            }
        }
        Map<String, Object> summary = computeSummary(userId);
        refreshSummaryCache(userId);
        return summary;
    }

    /** 实时计算账户概览（不含缓存） */
    public Map<String, Object> computeSummary(Long userId) {
        BigDecimal marketValue = positionService.getMarketValue(userId);
        BigDecimal cash = positionService.getCash(userId);
        BigDecimal totalAssets = cash.add(marketValue);

        // 今日盈亏 = 当前总资产 − 最近一个净值日的总资产（量纲为金额，而非收益率×市值）
        BigDecimal prevTotal = getPreviousTotalAssets(userId, LocalDate.now());
        BigDecimal todayPnl = prevTotal != null ? totalAssets.subtract(prevTotal) : ZERO;

        BigDecimal cumulativeReturn = accountNavRepository.findTopByUserIdOrderByNavDateDesc(userId)
                .map(AccountNav::getCumulativeReturn)
                .orElse(ZERO);

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("total_assets", totalAssets);
        summary.put("cash", cash);
        summary.put("market_value", marketValue);
        summary.put("today_pnl", todayPnl.setScale(2, RoundingMode.HALF_UP));
        summary.put("cumulative_return", cumulativeReturn);
        summary.put("net_deposit", positionService.getNetDeposit(userId));
        return summary;
    }

    /** 刷新概览缓存（转账、成交、盯市等资产变动后调用） */
    public void refreshSummaryCache(Long userId) {
        try {
            String json = objectMapper.writeValueAsString(computeSummary(userId));
            redisTemplate.opsForValue().set(CACHE_PREFIX + userId, json, CACHE_TTL);
        } catch (Exception e) {
            log.warn("净值概览缓存写入失败（已降级）: {}", e.getMessage());
        }
    }

    private String safeGet(String key) {
        try {
            return redisTemplate.opsForValue().get(key);
        } catch (Exception e) {
            log.warn("Redis 读取失败（已降级）: {}", e.getMessage());
            return null;
        }
    }

    /** 指定日期之前最近一个净值日的总资产（昨日总资产） */
    public BigDecimal getPreviousTotalAssets(Long userId, LocalDate date) {
        return accountNavRepository.findTopByUserIdAndNavDateBeforeOrderByNavDateDesc(userId, date)
                .map(AccountNav::getTotalAssets)
                .orElse(null);
    }

    /** 累计收益率基准：最早一个净值日的总资产，无净值记录时取净入金 */
    private BigDecimal getInitialCapital(Long userId) {
        return accountNavRepository.findFirstByUserIdOrderByNavDateAsc(userId)
                .map(AccountNav::getTotalAssets)
                .orElseGet(() -> positionService.getNetDeposit(userId));
    }
}
