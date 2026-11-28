package com.rotation.auth.repository;

import com.rotation.auth.entity.User;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.Optional;

public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByUsername(String username);
    boolean existsByUsername(String username);

    long countByRole(String role);

    /** 后台账号管理：关键字（用户名/邮箱）与角色筛选，两个条件都可留空 */
    @Query("""
            select u from User u
            where (:keyword = ''
                   or lower(u.username) like lower(concat('%', :keyword, '%'))
                   or lower(coalesce(u.email, '')) like lower(concat('%', :keyword, '%')))
              and (:role = '' or u.role = :role)
            """)
    Page<User> search(@Param("keyword") String keyword, @Param("role") String role, Pageable pageable);
}
