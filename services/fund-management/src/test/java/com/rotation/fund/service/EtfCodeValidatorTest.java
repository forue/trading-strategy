package com.rotation.fund.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EtfCodeValidatorTest {

    @Mock EtfMappingClient mappingClient;

    private EtfCodeValidator validator(boolean strict) {
        return new EtfCodeValidator(mappingClient, strict);
    }

    @Test
    void rejectsInvalidFormat() {
        var r = validator(true).validate("abcdef", "银行");
        assertFalse(r.accepted());
        assertTrue(r.reason().contains("格式非法"));
    }

    @Test
    void acceptsCodeInMapping() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of("512800", Map.of("sector_name", "银行")));
        var r = validator(true).validate("512800", "银行");
        assertTrue(r.accepted());
        assertEquals("512800", r.etfCode());
        assertFalse(r.autoFilled());
    }

    @Test
    void rejectsTradableButUnmappedCode() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of());
        when(mappingClient.isTradable("159999")).thenReturn(true);
        var r = validator(true).validate("159999", "银行");
        assertFalse(r.accepted());
        assertTrue(r.reason().contains("未纳入映射"));
    }

    @Test
    void rejectsNonexistentCode() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of());
        when(mappingClient.isTradable("159998")).thenReturn(false);
        var r = validator(true).validate("159998", "银行");
        assertFalse(r.accepted());
        assertTrue(r.reason().contains("不存在"));
    }

    @Test
    void autoFillsWhenCodeMissing() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of("512800", Map.of("sector_name", "银行")));
        var r = validator(true).validate(null, "银行");
        assertTrue(r.accepted());
        assertTrue(r.autoFilled());
        assertEquals("512800", r.etfCode());
    }

    @Test
    void rejectsWhenMissingAndSectorUnmapped() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of());
        var r = validator(true).validate(null, "未知板块");
        assertFalse(r.accepted());
        assertTrue(r.reason().contains("缺少 ETF 代码"));
    }

    @Test
    void degradesToFormatCheckWhenMappingUnavailable() {
        // data-collector 不可用时降级放行，避免故障拖垮开仓
        when(mappingClient.fetchMapping()).thenReturn(null);
        var r = validator(true).validate("512800", "银行");
        assertTrue(r.accepted());
    }

    @Test
    void nonStrictModeAllowsUnmappedCode() {
        when(mappingClient.fetchMapping()).thenReturn(Map.of());
        when(mappingClient.isTradable("159999")).thenReturn(true);
        var r = validator(false).validate("159999", "银行");
        assertTrue(r.accepted());
    }
}
