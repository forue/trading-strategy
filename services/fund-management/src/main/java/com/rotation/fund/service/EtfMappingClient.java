package com.rotation.fund.service;

import java.util.Map;

/**
 * ETF 映射查询客户端。
 *
 * <p>映射的唯一权威源在 data-collector（services/shared/sector_etf_map.py），
 * fund 不持有映射副本，只通过本接口查询，避免两边漂移。
 */
public interface EtfMappingClient {

    /**
     * 拉取映射全集。
     *
     * @return {etf_code: {etf_name, sector_name}}；**null 表示拉取失败**（与空 Map 区分）
     */
    Map<String, Map<String, String>> fetchMapping();

    /** 校验代码是否真实可交易（能取到最近交易日收盘价） */
    boolean isTradable(String etfCode);
}
