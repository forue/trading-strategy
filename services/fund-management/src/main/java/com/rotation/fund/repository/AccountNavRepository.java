package com.rotation.fund.repository;

import com.rotation.fund.entity.AccountNav;
import org.springframework.data.jpa.repository.JpaRepository;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

public interface AccountNavRepository extends JpaRepository<AccountNav, Long> {
    List<AccountNav> findByUserIdAndNavDateBetweenOrderByNavDateAsc(Long userId, LocalDate start, LocalDate end);
    Optional<AccountNav> findByUserIdAndNavDate(Long userId, LocalDate date);
    List<AccountNav> findByUserIdOrderByNavDateDesc(Long userId);
}
