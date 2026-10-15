package com.rotation.fund.service;

import com.rotation.fund.entity.BankTransfer;
import com.rotation.fund.entity.Position;
import com.rotation.fund.entity.Trade;
import com.rotation.fund.repository.BankTransferRepository;
import com.rotation.fund.repository.PositionRepository;
import com.rotation.fund.repository.TradeRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class PositionServiceTest {

    @Mock PositionRepository positionRepository;
    @Mock BankTransferRepository bankTransferRepository;
    @Mock TradeRepository tradeRepository;
    @Mock EtfCodeValidator etfCodeValidator;

    @InjectMocks PositionService positionService;

    private BankTransfer deposit(String amount) {
        BankTransfer t = new BankTransfer();
        t.setDirection("DEPOSIT");
        t.setAmount(new BigDecimal(amount));
        return t;
    }

    @Test
    void openPosition_calculatesQuantityAndCosts() {
        when(bankTransferRepository.findByUserIdOrderByTransferDateDesc(1L))
                .thenReturn(List.of(deposit("1000000")));
        when(tradeRepository.findByUserIdOrderByTradedAtDesc(1L)).thenReturn(List.of());
        when(etfCodeValidator.validate(any(), any()))
                .thenReturn(EtfCodeValidator.ValidationResult.ok("512800"));
        when(positionRepository.findByUserIdAndStatus(1L, "OPEN")).thenReturn(List.of());
        when(positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                1L, "AGGRESSIVE", "OPEN", "SW801780")).thenReturn(Optional.empty());
        when(positionRepository.save(any(Position.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tradeRepository.save(any(Trade.class))).thenAnswer(inv -> inv.getArgument(0));

        Position pos = positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "512800",
                new BigDecimal("0.5"), new BigDecimal("10"));

        // 目标市值 50 万 / 价格 10 = 50000 份（已是 100 的整数倍）
        assertEquals(0, new BigDecimal("50000").compareTo(pos.getQuantity()));
        assertEquals("OPEN", pos.getStatus());
        assertEquals("512800", pos.getEtfCode());

        ArgumentCaptor<Trade> captor = ArgumentCaptor.forClass(Trade.class);
        verify(tradeRepository).save(captor.capture());
        Trade trade = captor.getValue();
        assertEquals(0, new BigDecimal("500000.00").compareTo(trade.getAmount()));
        assertEquals(0, new BigDecimal("150.0000").compareTo(trade.getCommission())); // 50万 * 0.0003
        assertEquals(0, new BigDecimal("500.0000").compareTo(trade.getSlippage()));   // 50万 * 0.001
        assertEquals("BUY", trade.getDirection());
    }

    @Test
    void openPosition_roundsDownToLotSize() {
        when(bankTransferRepository.findByUserIdOrderByTransferDateDesc(1L))
                .thenReturn(List.of(deposit("100000")));
        when(tradeRepository.findByUserIdOrderByTradedAtDesc(1L)).thenReturn(List.of());
        when(etfCodeValidator.validate(any(), any()))
                .thenReturn(EtfCodeValidator.ValidationResult.ok("512800"));
        when(positionRepository.findByUserIdAndStatus(1L, "OPEN")).thenReturn(List.of());
        when(positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                1L, "AGGRESSIVE", "OPEN", "SW801780")).thenReturn(Optional.empty());
        when(positionRepository.save(any(Position.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tradeRepository.save(any(Trade.class))).thenAnswer(inv -> inv.getArgument(0));

        // 目标市值 3 万 / 价格 7 = 4285.71 → 向下取整到 100 份 = 4200
        Position pos = positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "512800",
                new BigDecimal("0.3"), new BigDecimal("7"));

        assertEquals(0, new BigDecimal("4200").compareTo(pos.getQuantity()));
    }

    @Test
    void getCash_deductsCostsAndTotalAssetsReflectsProfit() {
        when(bankTransferRepository.findByUserIdOrderByTransferDateDesc(1L))
                .thenReturn(List.of(deposit("1000000")));
        Trade buy = new Trade();
        buy.setDirection("BUY");
        buy.setAmount(new BigDecimal("500000"));
        buy.setCommission(new BigDecimal("150"));
        buy.setSlippage(new BigDecimal("500"));
        when(tradeRepository.findByUserIdOrderByTradedAtDesc(1L)).thenReturn(List.of(buy));

        Position held = new Position();
        held.setQuantity(new BigDecimal("50000"));
        held.setAvgPrice(new BigDecimal("10"));
        held.setCurrentPrice(new BigDecimal("12")); // 上涨到 12 元
        when(positionRepository.findByUserIdAndStatus(1L, "OPEN")).thenReturn(List.of(held));

        // 现金 = 1000000 - 500000 - 150 - 500 = 499350（买入成本与费用真实扣减）
        assertEquals(0, new BigDecimal("499350").compareTo(positionService.getCash(1L)));
        // 市值 = 50000 * 12 = 600000
        assertEquals(0, new BigDecimal("600000").compareTo(positionService.getMarketValue(1L)));
        // 总资产 = 499350 + 600000 = 1099350，相对净入金 100 万体现盈利 99350
        assertEquals(0, new BigDecimal("1099350").compareTo(positionService.getTotalAssets(1L)));
    }

    @Test
    void openPosition_rejectsDuplicateOpenPosition() {
        when(etfCodeValidator.validate(any(), any()))
                .thenReturn(EtfCodeValidator.ValidationResult.ok("512800"));
        when(positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                1L, "AGGRESSIVE", "OPEN", "SW801780")).thenReturn(Optional.of(new Position()));

        assertThrows(IllegalArgumentException.class,
                () -> positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "512800",
                        new BigDecimal("0.5"), new BigDecimal("10")));
    }

    @Test
    void openPosition_rejectsInvalidRatio() {
        assertThrows(IllegalArgumentException.class,
                () -> positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "512800",
                        new BigDecimal("1.5"), new BigDecimal("10")));
    }

    @Test
    void openPosition_rejectsUnmappedEtfCode() {
        when(etfCodeValidator.validate(any(), any()))
                .thenReturn(EtfCodeValidator.ValidationResult.reject("标的合法但未纳入映射"));

        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "159999",
                        new BigDecimal("0.5"), new BigDecimal("10")));
        assertTrue(ex.getMessage().contains("未纳入映射"));
    }

    @Test
    void closePosition_marksClosedAndAppliesSellCosts() {
        Position open = new Position();
        open.setUserId(1L);
        open.setStrategyType("AGGRESSIVE");
        open.setSectorCode("SW801780");
        open.setSectorName("银行");
        open.setQuantity(new BigDecimal("100"));
        open.setAvgPrice(new BigDecimal("10"));
        open.setCurrentPrice(new BigDecimal("10"));
        open.setStatus("OPEN");
        when(positionRepository.findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
                1L, "AGGRESSIVE", "OPEN", "SW801780")).thenReturn(Optional.of(open));
        when(positionRepository.save(any(Position.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tradeRepository.save(any(Trade.class))).thenAnswer(inv -> inv.getArgument(0));

        Position closed = positionService.closePosition(1L, "AGGRESSIVE", "SW801780", new BigDecimal("12"));

        assertEquals("CLOSED", closed.getStatus());
        assertNotNull(closed.getClosedAt());

        ArgumentCaptor<Trade> captor = ArgumentCaptor.forClass(Trade.class);
        verify(tradeRepository).save(captor.capture());
        Trade trade = captor.getValue();
        assertEquals(0, new BigDecimal("1200.00").compareTo(trade.getAmount()));
        assertEquals(0, new BigDecimal("1.2000").compareTo(trade.getStampTax()));    // 1200 * 0.001
        assertEquals(0, new BigDecimal("5.0000").compareTo(trade.getCommission()));  // 不足最低 5 元
        assertEquals("SELL", trade.getDirection());
    }

    @Test
    void openPosition_rejectsNonPositivePrice() {
        assertThrows(IllegalArgumentException.class,
                () -> positionService.openPosition(1L, "AGGRESSIVE", "SW801780", "银行", "512800",
                        new BigDecimal("0.5"), BigDecimal.ZERO));
    }

    @Test
    void markToMarket_reportsCompleteWhenAllHoldingsCovered() {
        Position p = new Position();
        p.setEtfCode("512800");
        p.setCurrentPrice(new BigDecimal("1.0"));
        when(positionRepository.findByUserIdAndStatus(1L, "OPEN")).thenReturn(List.of(p));
        when(positionRepository.save(any(Position.class))).thenAnswer(inv -> inv.getArgument(0));

        Map<String, Object> result = positionService.markToMarket(1L,
                Map.of("512800", new BigDecimal("1.2")));

        assertEquals(1, ((Number) result.get("updated")).intValue());
        assertEquals(List.of(), result.get("missing_etf_codes"));
        assertTrue((Boolean) result.get("complete"));
    }

    @Test
    void markToMarket_reportsIncompleteWhenPriceMissing() {
        Position covered = new Position();
        covered.setEtfCode("512800");
        covered.setCurrentPrice(new BigDecimal("1.0"));
        Position uncovered = new Position();
        uncovered.setEtfCode("512720");
        when(positionRepository.findByUserIdAndStatus(1L, "OPEN"))
                .thenReturn(List.of(covered, uncovered));
        when(positionRepository.save(any(Position.class))).thenAnswer(inv -> inv.getArgument(0));

        // 仅提供 512800 的价格，512720 缺失 → 必须报 incomplete，供调度方中止重算
        Map<String, Object> result = positionService.markToMarket(1L,
                Map.of("512800", new BigDecimal("1.2")));

        assertEquals(2, ((Number) result.get("open_positions")).intValue());
        assertEquals(1, ((Number) result.get("updated")).intValue());
        assertEquals(List.of("512720"), result.get("missing_etf_codes"));
        assertFalse((Boolean) result.get("complete"));
    }
}
