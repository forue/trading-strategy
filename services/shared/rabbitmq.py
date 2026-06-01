"""RabbitMQ 连接管理器 - 单例模式，复用连接"""
import json
import threading
import pika
from typing import Optional, Callable
from loguru import logger


class RabbitMQManager:
    """RabbitMQ 连接管理器（单例）

    发布和消费使用独立的 channel，避免 pika 线程安全问题。
    """

    _instance: Optional["RabbitMQManager"] = None
    _lock = threading.Lock()

    _connection: Optional[pika.BlockingConnection] = None
    _publish_channel: Optional[pika.channel.Channel] = None
    _consume_channel: Optional[pika.channel.Channel] = None

    _host: str = "localhost"
    _port: int = 5672
    _user: str = "guest"
    _password: str = ""
    _exchange_declared: bool = False

    def __new__(cls) -> "RabbitMQManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def connect(
        self,
        host: str = "localhost",
        port: int = 5672,
        user: str = "guest",
        password: str = "",
    ) -> None:
        """建立连接"""
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._do_connect()

    def _do_connect(self) -> None:
        """实际建立连接，仅为发布 channel 声明交换机"""
        try:
            if self._connection and self._connection.is_open:
                return

            credentials = pika.PlainCredentials(self._user, self._password)
            parameters = pika.ConnectionParameters(
                host=self._host,
                port=self._port,
                credentials=credentials,
                heartbeat=60,
                blocked_connection_timeout=300,
            )
            self._connection = pika.BlockingConnection(parameters)
            self._publish_channel = self._connection.channel()
            self._consume_channel = None
            self._exchange_declared = False
            logger.info("RabbitMQ 连接已建立")
        except Exception as e:
            logger.error(f"RabbitMQ 连接失败: {e}")
            self._connection = None
            self._publish_channel = None
            self._consume_channel = None

    def close(self) -> None:
        """关闭连接"""
        try:
            if self._consume_channel and self._consume_channel.is_open:
                self._consume_channel.close()
            if self._publish_channel and self._publish_channel.is_open:
                self._publish_channel.close()
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception as e:
            logger.debug(f"RabbitMQ 关闭: {e}")
        finally:
            self._connection = None
            self._publish_channel = None
            self._consume_channel = None
            self._exchange_declared = False

    def _get_publish_channel(self) -> Optional[pika.channel.Channel]:
        """获取发布 channel，必要时重连"""
        try:
            if self._connection is None or self._connection.is_closed:
                self._do_connect()
            if self._publish_channel is None or self._publish_channel.is_closed:
                self._publish_channel = self._connection.channel()
            return self._publish_channel
        except Exception:
            self._do_connect()
            return self._publish_channel

    def _get_consume_channel(self) -> Optional[pika.channel.Channel]:
        """获取消费 channel（独立于发布 channel），必要时重连"""
        try:
            if self._connection is None or self._connection.is_closed:
                self._do_connect()
            if self._consume_channel is None or self._consume_channel.is_closed:
                self._consume_channel = self._connection.channel()
            return self._consume_channel
        except Exception:
            self._do_connect()
            if self._connection and self._connection.is_open:
                self._consume_channel = self._connection.channel()
            return self._consume_channel

    def _ensure_exchange(self, exchange: str = "rotation", exchange_type: str = "topic"):
        """声明交换机（仅首次调用时执行，后续幂等跳过）"""
        if self._exchange_declared:
            return
        channel = self._get_publish_channel()
        if channel:
            channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=True)
            self._exchange_declared = True

    def publish(
        self,
        routing_key: str,
        message: dict,
        exchange: str = "rotation",
    ) -> bool:
        """发布消息（自动重连，最多 3 次尝试）"""
        for attempt in range(3):
            try:
                channel = self._get_publish_channel()
                if channel and channel.is_open:
                    self._ensure_exchange(exchange)
                    channel.basic_publish(
                        exchange=exchange,
                        routing_key=routing_key,
                        body=json.dumps(message, ensure_ascii=False),
                    )
                    if attempt > 0:
                        logger.info(f"RabbitMQ 发布成功(第{attempt + 1}次尝试): {routing_key}")
                    return True
                else:
                    logger.warning(f"RabbitMQ 发布通道不可用(尝试{attempt + 1}/3)")
                    self.close()
            except Exception as e:
                logger.warning(f"RabbitMQ 发送失败(尝试{attempt + 1}/3): {e}")
                self.close()
        logger.error(f"RabbitMQ 消息发布最终失败(3次): routing_key={routing_key}")
        return False

    def consume(
        self,
        queue: str,
        callback: Callable,
        exchange: str = "rotation",
        routing_key: str = "#",
        durable: bool = True,
    ) -> None:
        """消费消息（阻塞式，自动重连，使用独立 channel，手动确认）"""
        import time as _time
        retry_delay = 5  # 初始重连间隔（秒）
        max_delay = 60   # 最大重连间隔

        while True:
            try:
                # 重连前先重置消费 channel
                if self._consume_channel and not self._consume_channel.is_closed:
                    try:
                        self._consume_channel.close()
                    except Exception:
                        pass
                self._consume_channel = None

                channel = self._get_consume_channel()
                if not channel:
                    logger.error(f"RabbitMQ 消费通道不可用，{retry_delay}秒后重试")
                    _time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, max_delay)
                    continue

                channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
                result = channel.queue_declare(queue=queue, durable=durable)
                channel.queue_bind(exchange=exchange, queue=result.method.queue, routing_key=routing_key)

                # 流控：每次只拉取 1 条消息，处理完再拿下一条，防止慢消费者积压
                channel.basic_qos(prefetch_count=1)

                def _wrapper(ch, method, properties, body):
                    """包装回调，处理完成后手动确认"""
                    try:
                        callback(ch, method, properties, body)
                        ch.basic_ack(delivery_tag=method.delivery_tag)
                    except Exception as e:
                        # 消息处理失败：重试 1 次（requeue），仍失败则丢弃（避免死循环）
                        retry_count = (properties.headers or {}).get("x-retry-count", 0)
                        if retry_count < 1:
                            logger.warning(f"消息处理失败，重试({retry_count + 1}/1): {e}")
                            # 无法直接修改 headers 重试，采用 requeue
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        else:
                            logger.error(f"消息处理失败(已重试)，丢弃: {e}")
                            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

                channel.basic_consume(queue=result.method.queue, on_message_callback=_wrapper, auto_ack=False)
                logger.info(f"RabbitMQ 消费者启动: queue={queue}, routing_key={routing_key}")
                retry_delay = 5  # 连接成功，重置重连间隔
                channel.start_consuming()
            except Exception as e:
                logger.error(f"RabbitMQ 消费断开: {e}，{retry_delay}秒后重连")
                _time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)
