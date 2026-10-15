package com.rotation.fund.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * ETF 代码校验：开仓前确认标的可被收盘盯市。
 *
 * <p>背景：未纳入映射的 ETF 无法采集收盘价 → 该持仓价格永不更新 →
 * 盯市完整性为 false → 净值重算被中止（账户净值停更）。因此必须在开仓前拦截。
 *
 * <p>校验层次：
 * <ol>
 *   <li>L1 格式：6 位数字（沪市 5 开头 / 深市 15 开头）</li>
 *   <li>L2 存在性：是否在映射全集内</li>
 *   <li>L3 可交易性：不在映射时进一步判断标的是否真实存在（区分错误代码与未纳入映射）</li>
 * </ol>
 *
 * <p>缺失代码时按板块自动填充默认标的；映射服务不可用时降级为仅格式校验并告警（保证可用性）。
 */
@Service
public class EtfCodeValidator {

    private static final Logger log = LoggerFactory.getLogger(EtfCodeValidator.class);

    /** 沪市 ETF 5 开头、深市 ETF 15 开头，均为 6 位数字 */
    private static final Pattern ETF_CODE_PATTERN = Pattern.compile("^(5\\d{5}|15\\d{4})$");
    private static final long CACHE_TTL_MS = Duration.ofMinutes(10).toMillis();

    private final EtfMappingClient mappingClient;
    private final boolean strictMapping;

    private volatile Map<String, Map<String, String>> cache;
    private volatile long cacheLoadedAt = 0;

    public EtfCodeValidator(EtfMappingClient mappingClient,
                            @Value("${fund.etf.strict-mapping:true}") boolean strictMapping) {
        this.mappingClient = mappingClient;
        this.strictMapping = strictMapping;
    }

    public record ValidationResult(boolean accepted, String etfCode, String reason, boolean autoFilled) {
        public static ValidationResult ok(String code) {
            return new ValidationResult(true, code, null, false);
        }

        public static ValidationResult filled(String code) {
            return new ValidationResult(true, code, null, true);
        }

        public static ValidationResult reject(String reason) {
            return new ValidationResult(false, null, reason, false);
        }
    }

    /**
     * 校验 ETF 代码。
     *
     * @param etfCode    传入的 ETF 代码，可为空（将尝试按板块自动填充）
     * @param sectorName 板块名，用于空值填充
     */
    public ValidationResult validate(String etfCode, String sectorName) {
        String code = etfCode == null ? null : etfCode.trim();

        if (code == null || code.isEmpty()) {
            String filled = defaultEtfOfSector(sectorName);
            if (filled != null) {
                log.info("ETF 代码为空，按板块自动填充: sector={} -> {}", sectorName, filled);
                return ValidationResult.filled(filled);
            }
            return ValidationResult.reject(
                    "缺少 ETF 代码，且板块「" + sectorName + "」在映射中无默认标的，请联系管理员添加映射");
        }

        if (!ETF_CODE_PATTERN.matcher(code).matches()) {
            return ValidationResult.reject(
                    "ETF 代码格式非法（应为 6 位数字：沪市 5 开头或深市 15 开头）: " + code);
        }

        Map<String, Map<String, String>> mapping = mapping();
        if (mapping == null) {
            // 映射服务不可用：降级放行（仅做格式校验），避免 data-collector 故障拖垮开仓
            log.warn("ETF 映射不可用，开仓降级为仅格式校验: code={} sector={}", code, sectorName);
            return ValidationResult.ok(code);
        }

        if (mapping.containsKey(code)) {
            return ValidationResult.ok(code);
        }

        boolean tradable = mappingClient.isTradable(code);
        if (tradable) {
            if (!strictMapping) {
                log.warn("ETF 未纳入映射，非严格模式放行（该持仓将无法收盘盯市）: code={}", code);
                return ValidationResult.ok(code);
            }
            return ValidationResult.reject("标的合法但未纳入映射，无法采集收盘价（会导致净值停更），"
                    + "请联系管理员添加映射: " + code);
        }
        return ValidationResult.reject("ETF 代码不存在或已不可交易: " + code);
    }

    /** 映射全集（带 10 分钟缓存）；null 表示拉取失败 */
    private Map<String, Map<String, String>> mapping() {
        Map<String, Map<String, String>> cached = cache;
        long now = System.currentTimeMillis();
        if (cached != null && now - cacheLoadedAt < CACHE_TTL_MS) {
            return cached;
        }
        Map<String, Map<String, String>> loaded = mappingClient.fetchMapping();
        if (loaded != null) {
            cache = loaded;
            cacheLoadedAt = now;
        }
        return loaded;
    }

    /** 按板块取映射中的默认（首选）ETF 代码 */
    private String defaultEtfOfSector(String sectorName) {
        Map<String, Map<String, String>> mapping = mapping();
        if (mapping == null || sectorName == null) {
            return null;
        }
        return mapping.entrySet().stream()
                .filter(e -> sectorName.equals(e.getValue().get("sector_name")))
                .map(Map.Entry::getKey)
                .findFirst()
                .orElse(null);
    }
}
