package com.rotation.auth.support;

import lombok.Getter;

/**
 * 带 HTTP 状态码的业务异常，由 ApiExceptionHandler 统一转成 {code, message}。
 */
@Getter
public class ApiException extends RuntimeException {

    private final int status;

    public ApiException(int status, String message) {
        super(message);
        this.status = status;
    }
}
