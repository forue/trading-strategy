package com.rotation.fund.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;

/** 通过 data-collector 的 HTTP 端点查询 ETF 映射与可交易性 */
@Component
public class HttpEtfMappingClient implements EtfMappingClient {

    private static final Logger log = LoggerFactory.getLogger(HttpEtfMappingClient.class);

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();
    private final ObjectMapper mapper = new ObjectMapper();
    private final String baseUrl;

    public HttpEtfMappingClient(@Value("${app.data-collector.url:http://localhost:8003}") String baseUrl) {
        this.baseUrl = baseUrl;
    }

    @Override
    public Map<String, Map<String, String>> fetchMapping() {
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(baseUrl + "/sector-etf-map"))
                    .timeout(Duration.ofSeconds(10)).GET().build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                log.warn("获取 ETF 映射失败，HTTP {}", resp.statusCode());
                return null;
            }
            JsonNode data = mapper.readTree(resp.body()).path("data");
            Map<String, Map<String, String>> mapping = new HashMap<>();
            data.fields().forEachRemaining(e -> {
                Map<String, String> meta = new HashMap<>();
                meta.put("etf_name", e.getValue().path("etf_name").asText(""));
                meta.put("sector_name", e.getValue().path("sector_name").asText(""));
                mapping.put(e.getKey(), meta);
            });
            return mapping;
        } catch (Exception e) {
            log.warn("获取 ETF 映射失败（校验降级，仅做格式校验）: {}", e.getMessage());
            return null;
        }
    }

    @Override
    public boolean isTradable(String etfCode) {
        try {
            HttpRequest req = HttpRequest.newBuilder(
                            URI.create(baseUrl + "/etf-tradable?code=" + etfCode))
                    .timeout(Duration.ofSeconds(10)).GET().build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            if (resp.statusCode() != 200) {
                return false;
            }
            return mapper.readTree(resp.body()).path("data").path("tradable").asBoolean(false);
        } catch (Exception e) {
            log.warn("ETF 可交易性校验失败 {}: {}", etfCode, e.getMessage());
            return false;
        }
    }
}
