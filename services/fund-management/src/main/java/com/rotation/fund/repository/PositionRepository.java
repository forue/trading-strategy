package com.rotation.fund.repository;

import com.rotation.fund.entity.Position;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
import java.util.Optional;

public interface PositionRepository extends JpaRepository<Position, Long> {
    List<Position> findByUserIdAndStatus(Long userId, String status);
    List<Position> findByUserIdAndStrategyTypeAndStatus(Long userId, String strategyType, String status);
    List<Position> findByStrategyTypeAndStatus(String strategyType, String status);

    /** 按用户+策略+板块定位单笔持仓：开仓查重 / 平仓定位（下推到 DB，避免内存过滤） */
    Optional<Position> findFirstByUserIdAndStrategyTypeAndStatusAndSectorCode(
            Long userId, String strategyType, String status, String sectorCode);
}
