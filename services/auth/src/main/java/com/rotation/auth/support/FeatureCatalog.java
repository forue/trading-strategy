package com.rotation.auth.support;

import java.util.List;

/**
 * 受配额控制的高级功能清单。
 *
 * featureKey 必须与调用方传入的一致（策略服务：stock_sense_training）。
 * userLimit / adminLimit 为默认每日次数，0 表示不限次。
 */
public final class FeatureCatalog {

    public record FeatureDef(String key, String name, String description, int userLimit, int adminLimit) {
    }

    public static final String STOCK_SENSE_TRAINING = "stock_sense_training";

    public static final List<FeatureDef> FEATURES = List.of(
            new FeatureDef(STOCK_SENSE_TRAINING, "盘感训练",
                    "随机标的 + 隐藏后市K线的训练入口，每触发一次「开始训练」计一次", 3, 0)
    );

    private FeatureCatalog() {
    }

    public static FeatureDef find(String key) {
        return FEATURES.stream().filter(f -> f.key().equals(key)).findFirst().orElse(null);
    }

    public static int defaultLimit(FeatureDef def, String role) {
        return RouteCatalog.ROLE_ADMIN.equals(role) ? def.adminLimit() : def.userLimit();
    }
}
