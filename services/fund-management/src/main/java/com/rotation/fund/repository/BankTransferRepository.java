package com.rotation.fund.repository;

import com.rotation.fund.entity.BankTransfer;
import org.springframework.data.jpa.repository.JpaRepository;
import java.time.LocalDate;
import java.util.List;

public interface BankTransferRepository extends JpaRepository<BankTransfer, Long> {
    List<BankTransfer> findByUserIdAndTransferDateBetweenOrderByTransferDateDesc(Long userId, LocalDate start, LocalDate end);
    List<BankTransfer> findByUserIdOrderByTransferDateDesc(Long userId);
    List<BankTransfer> findByUserIdAndTransferDate(Long userId, LocalDate date);
}
