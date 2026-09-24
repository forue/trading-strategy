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

    /** 指定日期之前最近一条净值（昨日总资产），用于日收益率/今日盈亏 */
    Optional<AccountNav> findTopByUserIdAndNavDateBeforeOrderByNavDateDesc(Long userId, LocalDate date);

    /** 最早一条净值（累计收益率基准） */
    Optional<AccountNav> findFirstByUserIdOrderByNavDateAsc(Long userId);

    /** 最新一条净值 */
    Optional<AccountNav> findTopByUserIdOrderByNavDateDesc(Long userId);
}
