package com.rotation.fund.consumer;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rotation.fund.service.AccountNavService;
import com.rotation.fund.service.PositionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * 信号消费者：监听 strategy 发布的 signal.generated 事件，
 * 解析 BUY/SELL 信号并调用 PositionService 完成开/平仓，成交后重算当日净值。
 * 与 docs/07 第 6.1 节「信号消费（待实现）」对应。
 */
@Component
public class SignalConsumer {

    private static final Logger log = LoggerFactory.getLogger(SignalConsumer.class);
    private static final Long DEFAULT_USER_ID = 1L;

    private final PositionService positionService;
    private final AccountNavService accountNavService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public SignalConsumer(PositionService positionService, AccountNavService accountNavService) {
        this.positionService = positionService;
        this.accountNavService = accountNavService;
    }

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(value = "fund.signal.queue", durable = "true"),
            exchange = @Exchange(value = "rotation", type = "topic", durable = "true"),
            key = "signal.generated"))
    public void handleSignal(Message message) {
        String json = new String(message.getBody(), StandardCharsets.UTF_8);
        Map<String, Object> payload;
        try {
            payload = objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            log.error("信号消息解析失败: {}", e.getMessage());
            return;
        }

        String strategyType = (String) payload.get("strategy_type");
        Long userId = payload.get("user_id") != null
                ? Long.valueOf(payload.get("user_id").toString()) : DEFAULT_USER_ID;
        Object signalsObj = payload.get("signals");
        if (!(signalsObj instanceof List)) {
            log.warn("信号消息缺少 signals 列表，跳过");
            return;
        }
        List<Map<String, Object>> signals = (List<Map<String, Object>>) signalsObj;

        for (Map<String, Object> s : signals) {
            try {
                String direction = (String) s.get("direction");
                String sectorCode = (String) s.get("sector_code");
                String sectorName = s.get("sector_name") != null ? (String) s.get("sector_name") : "";
                String etfCode = s.get("etf_code") != null ? (String) s.get("etf_code") : null;
                BigDecimal positionRatio = s.get("position_ratio") != null
                        ? new BigDecimal(s.get("position_ratio").toString()) : BigDecimal.ZERO;
                BigDecimal currentPrice = s.get("current_price") != null
                        ? new BigDecimal(s.get("current_price").toString()) : null;

                if ("SELL".equals(direction)) {
                    positionService.closePosition(userId, strategyType, sectorCode, currentPrice);
                } else {
                    positionService.openPosition(userId, strategyType, sectorCode, sectorName, etfCode,
                            positionRatio, currentPrice);
                }
            } catch (Exception e) {
                log.error("处理单条信号失败(sector={}): {}", s.get("sector_code"), e.getMessage());
            }
        }

        try {
            accountNavService.recalcNav(userId, LocalDate.now());
        } catch (Exception e) {
            log.error("成交后净值重算失败: {}", e.getMessage());
        }
    }
}
