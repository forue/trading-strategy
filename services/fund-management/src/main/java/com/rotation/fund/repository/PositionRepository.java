package com.rotation.fund.repository;

import com.rotation.fund.entity.Position;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface PositionRepository extends JpaRepository<Position, Long> {
    List<Position> findByUserIdAndStatus(Long userId, String status);
    List<Position> findByUserIdAndStrategyTypeAndStatus(Long userId, String strategyType, String status);
    List<Position> findByStrategyTypeAndStatus(String strategyType, String status);
}
