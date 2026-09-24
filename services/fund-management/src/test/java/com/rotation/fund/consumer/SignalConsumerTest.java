package com.rotation.fund.consumer;

import com.rotation.fund.service.AccountNavService;
import com.rotation.fund.service.PositionService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.amqp.core.Message;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class SignalConsumerTest {

    @Mock PositionService positionService;
    @Mock AccountNavService accountNavService;

    @Test
    void handleSignal_usesUserIdAndEtfCodeFromPayload() {
        SignalConsumer consumer = new SignalConsumer(positionService, accountNavService);
        String json = "{\"strategy_type\":\"AGGRESSIVE\",\"user_id\":7,\"signals\":["
                + "{\"direction\":\"BUY\",\"sector_code\":\"SW801780\",\"sector_name\":\"银行\","
                + "\"etf_code\":\"512800\",\"position_ratio\":0.5,\"current_price\":10}]}";

        consumer.handleSignal(new Message(json.getBytes(StandardCharsets.UTF_8)));

        // 用户取消息体中的 user_id（而非硬编码 1），ETF 代码一并传入用于后续盯市
        verify(positionService).openPosition(eq(7L), eq("AGGRESSIVE"), eq("SW801780"), eq("银行"),
                eq("512800"), eq(new BigDecimal("0.5")), eq(new BigDecimal("10")));
        verify(accountNavService).recalcNav(eq(7L), any(LocalDate.class));
    }
}
