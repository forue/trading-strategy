package com.rotation.auth.repository;

import com.rotation.auth.entity.FeatureQuota;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface FeatureQuotaRepository extends JpaRepository<FeatureQuota, Long> {

    Optional<FeatureQuota> findByFeatureKeyAndRole(String featureKey, String role);
}
