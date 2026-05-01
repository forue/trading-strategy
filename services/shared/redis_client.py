"""Redis 连接管理器 - 单例模式，复用连接"""
import json
import redis
from typing import Optional, Any
from loguru import logger


class RedisManager:
    """Redis 连接管理器（单例）"""
    
    _instance: Optional["RedisManager"] = None
    _client: Optional[redis.Redis] = None
    
    def __new__(cls) -> "RedisManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def connect(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str = "",
        db: int = 0,
        decode_responses: bool = True,
    ) -> None:
        """建立连接"""
        try:
            if self._client and self._client.ping():
                return
            
            self._client = redis.Redis(
                host=host,
                port=port,
                password=password,
                db=db,
                decode_responses=decode_responses,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            self._client.ping()
            logger.info("Redis 连接已建立")
        except Exception as e:
            logger.error(f"Redis 连接失败: {e}")
            self._client = None
    
    def close(self) -> None:
        """关闭连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
    
    @property
    def client(self) -> redis.Redis:
        """获取 Redis 客户端"""
        if self._client is None:
            raise RuntimeError("Redis 未连接，请先调用 connect()")
        return self._client
    
    def get(self, key: str) -> Optional[str]:
        """获取值"""
        try:
            return self.client.get(key)
        except Exception as e:
            logger.error(f"Redis GET 失败: {e}")
            return None
    
    def set(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """设置值"""
        try:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            self.client.set(key, value, ex=ex)
            return True
        except Exception as e:
            logger.error(f"Redis SET 失败: {e}")
            return False
    
    def setex(self, key: str, time: int, value: Any) -> bool:
        """设置值（带过期时间）"""
        return self.set(key, value, ex=time)
    
    def get_json(self, key: str) -> Optional[Any]:
        """获取 JSON 值"""
        raw = self.get(key)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None
    
    def set_json(self, key: str, value: Any, ex: Optional[int] = None) -> bool:
        """设置 JSON 值"""
        return self.set(key, json.dumps(value, ensure_ascii=False), ex=ex)
    
    def delete(self, *keys: str) -> int:
        """删除键"""
        try:
            return self.client.delete(*keys)
        except Exception as e:
            logger.error(f"Redis DELETE 失败: {e}")
            return 0
    
    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        try:
            return bool(self.client.exists(key))
        except Exception:
            return False
    
    def expire(self, key: str, time: int) -> bool:
        """设置过期时间"""
        try:
            return self.client.expire(key, time)
        except Exception as e:
            logger.error(f"Redis EXPIRE 失败: {e}")
            return False
    
    def ttl(self, key: str) -> int:
        """获取剩余过期时间"""
        try:
            return self.client.ttl(key)
        except Exception:
            return -2
    
    def scan_iter(self, match: str = "*", count: int = 200):
        """扫描键"""
        try:
            return self.client.scan_iter(match=match, count=count)
        except Exception as e:
            logger.error(f"Redis SCAN 失败: {e}")
            return iter([])
    
    def pipeline(self):
        """获取管道"""
        return self.client.pipeline()
    
    def ping(self) -> bool:
        """测试连接"""
        try:
            return self.client.ping()
        except Exception:
            return False
    
    def info(self, section: str = "memory") -> dict:
        """获取服务器信息"""
        try:
            return self.client.info(section)
        except Exception:
            return {}
    
    def flushdb(self) -> bool:
        """清空当前数据库"""
        try:
            self.client.flushdb()
            return True
        except Exception as e:
            logger.error(f"Redis FLUSHDB 失败: {e}")
            return False
