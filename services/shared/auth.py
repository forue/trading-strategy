"""共享库 - 解析 auth 服务签发的 JWT，得到当前登录用户

Python 服务不引入 PyJWT：token 是 HS256，用标准库验签即可，避免为多个服务
新增依赖与镜像体积。密钥与 auth 服务共用 JWT_SECRET 环境变量。

用途边界：仅用于判定"配置/数据归属于哪个用户"，不做敏感的后台管理鉴权
（后台管理仍由 auth 服务的 TokenGuard 负责）。auth 侧的退出登录靠 Redis 黑名单，
Python 服务各自连不同的 Redis db，读不到该黑名单，因此登出后 token 在有效期内
仍可本地验签——它能访问的也只是该 token 持有者自己的配置。
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

# 管理员账号固定 id（init-db.sql 初始化的 admin 为 1），后台任务取该账号的 AI 配置
ADMIN_USER_ID = 1

_jwt_secret = os.getenv("JWT_SECRET", "")


class AuthError(Exception):
    """token 缺失或无效"""


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "ADMIN"


def set_jwt_secret(secret: str) -> None:
    """由各服务在启动时用自身配置覆盖（.env / docker 环境变量）"""
    global _jwt_secret
    if secret:
        _jwt_secret = secret


def _b64decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_token(token: str) -> dict:
    """校验签名与过期时间，返回 payload"""
    if not _jwt_secret:
        raise AuthError("服务未配置 JWT_SECRET，无法校验登录状态")

    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("token 格式错误")
    header_b64, payload_b64, signature_b64 = parts

    try:
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
        signature = _b64decode(signature_b64)
    except (binascii.Error, ValueError, json.JSONDecodeError):
        raise AuthError("token 解析失败")

    # 只接受 auth 服务签发的 HS256，拒绝 alg=none 之类的伪造
    if header.get("alg") != "HS256":
        raise AuthError("不支持的签名算法")

    expected = hmac.new(
        _jwt_secret.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, signature):
        raise AuthError("token 签名无效")

    exp = payload.get("exp")
    if exp is not None:
        try:
            if float(exp) < time.time():
                raise AuthError("登录已过期")
        except (TypeError, ValueError):
            raise AuthError("token 过期时间非法")

    return payload


def get_current_user(authorization: Optional[str]) -> CurrentUser:
    """从 Authorization 请求头解析当前用户，缺失/无效时抛 AuthError"""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("未登录")
    payload = decode_token(authorization[7:].strip())
    try:
        user_id = int(payload["userId"])
    except (KeyError, TypeError, ValueError):
        raise AuthError("token 缺少用户标识")
    return CurrentUser(
        user_id=user_id,
        username=str(payload.get("sub") or ""),
        role=str(payload.get("role") or "USER"),
    )


def try_get_current_user(authorization: Optional[str]) -> Optional[CurrentUser]:
    """解析失败时返回 None（供可选登录场景使用）"""
    try:
        return get_current_user(authorization)
    except AuthError:
        return None


def user_scope(user_id: int) -> str:
    """按用户隔离的 Redis 键前缀"""
    return f"user:{user_id}"
