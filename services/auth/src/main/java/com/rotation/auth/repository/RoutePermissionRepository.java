package com.rotation.auth.repository;

import com.rotation.auth.entity.RoutePermission;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface RoutePermissionRepository extends JpaRepository<RoutePermission, Long> {

    List<RoutePermission> findByRole(String role);
}
