package com.rotation.fund.service;

import com.rotation.fund.entity.AccountNav;
import com.rotation.fund.repository.AccountNavRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AccountNavServiceTest {

    @Mock PositionService positionService;
    @Mock AccountNavRepository accountNavRepository;
    @Mock StringRedisTemplate redisTemplate;
    @Mock ValueOperations<String, String> valueOperations;

    @InjectMocks AccountNavService accountNavService;

    @Test
    void recalcNav_computesReturnsFromCashAndMarketValue() {
        LocalDate today = LocalDate.of(2026, 9, 25);
        when(positionService.getCash(1L)).thenReturn(new BigDecimal("499350"));
        when(positionService.getMarketValue(1L)).thenReturn(new BigDecimal("600000"));

        AccountNav yesterday = new AccountNav();
        yesterday.setTotalAssets(new BigDecimal("1000000"));
        when(accountNavRepository.findTopByUserIdAndNavDateBeforeOrderByNavDateDesc(eq(1L), any(LocalDate.class)))
                .thenReturn(Optional.of(yesterday));

        AccountNav first = new AccountNav();
        first.setTotalAssets(new BigDecimal("1000000"));
        when(accountNavRepository.findFirstByUserIdOrderByNavDateAsc(1L)).thenReturn(Optional.of(first));
        when(accountNavRepository.findByUserIdAndNavDate(1L, today)).thenReturn(Optional.empty());
        when(accountNavRepository.save(any(AccountNav.class))).thenAnswer(inv -> inv.getArgument(0));
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);

        AccountNav nav = accountNavService.recalcNav(1L, today);

        assertEquals(0, new BigDecimal("1099350").compareTo(nav.getTotalAssets()));
        assertEquals(0, new BigDecimal("499350").compareTo(nav.getCash()));
        // 日收益率 = 1099350 / 1000000 - 1 = 0.099350
        assertEquals(0, new BigDecimal("0.099350").compareTo(nav.getDailyReturn()));
        // 累计收益率以最早净值日为基准 = 0.099350
        assertEquals(0, new BigDecimal("0.099350").compareTo(nav.getCumulativeReturn()));
    }

    @Test
    void computeSummary_todayPnlIsAmountDifference() {
        when(positionService.getCash(1L)).thenReturn(new BigDecimal("499350"));
        when(positionService.getMarketValue(1L)).thenReturn(new BigDecimal("600000"));
        when(positionService.getNetDeposit(1L)).thenReturn(new BigDecimal("1000000"));

        AccountNav yesterday = new AccountNav();
        yesterday.setTotalAssets(new BigDecimal("1000000"));
        when(accountNavRepository.findTopByUserIdAndNavDateBeforeOrderByNavDateDesc(eq(1L), any(LocalDate.class)))
                .thenReturn(Optional.of(yesterday));
        when(accountNavRepository.findTopByUserIdOrderByNavDateDesc(1L)).thenReturn(Optional.empty());

        Map<String, Object> summary = accountNavService.computeSummary(1L);

        assertEquals(0, new BigDecimal("1099350").compareTo((BigDecimal) summary.get("total_assets")));
        // 今日盈亏 = 1099350 - 1000000 = 99350（金额量纲），而非「收益率 × 市值」
        assertEquals(0, new BigDecimal("99350.00").compareTo((BigDecimal) summary.get("today_pnl")));
    }
}
