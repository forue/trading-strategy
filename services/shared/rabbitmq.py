"""RabbitMQ 连接管理器 - 单例模式，复用连接"""
import json
import pika
from typing import Optional, Callable
from loguru import logger


class RabbitMQManager:
    """RabbitMQ 连接管理器（单例）"""
    
    _instance: Optional["RabbitMQManager"] = None
    _connection: Optional[pika.BlockingConnection] = None
    _channel: Optional[pika.channel.Channel] = None
    _host: str = "localhost"
    _port: int = 5672
    _user: str = "guest"
    _password: str = ""
    
    def __new__(cls) -> "RabbitMQManager":
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
        """实际建立连接"""
        try:
            if self._connection and self._connection.is_open:
                return
            
            credentials = pika.PlainCredentials(self._user, self._password)
            parameters = pika.ConnectionParameters(
                host=self._host,
                port=self._port,
                credentials=credentials,
                heartbeat=0,
                blocked_connection_timeout=0,
            )
            self._connection = pika.BlockingConnection(parameters)
            self._channel = self._connection.channel()
            logger.info("RabbitMQ 连接已建立")
        except Exception as e:
            logger.error(f"RabbitMQ 连接失败: {e}")
            self._connection = None
            self._channel = None
    
    def close(self) -> None:
        """关闭连接"""
        try:
            if self._channel and self._channel.is_open:
                self._channel.close()
            if self._connection and self._connection.is_open:
                self._connection.close()
        except Exception as e:
            logger.debug(f"RabbitMQ 关闭: {e}")
        finally:
            self._connection = None
            self._channel = None
    
    def get_channel(self) -> Optional[pika.channel.Channel]:
        """获取可用的 channel，必要时重连"""
        try:
            if self._connection is None or self._connection.is_closed:
                self._do_connect()
            return self._channel
        except Exception:
            self._do_connect()
            return self._channel
    
    def declare_exchange(
        self, exchange: str = "rotation", exchange_type: str = "topic", durable: bool = True
    ) -> None:
        """声明交换机"""
        channel = self.get_channel()
        if channel:
            channel.exchange_declare(exchange=exchange, exchange_type=exchange_type, durable=durable)
    
    def publish(
        self,
        routing_key: str,
        message: dict,
        exchange: str = "rotation",
    ) -> bool:
        """发布消息（自动重连）"""
        for attempt in range(2):
            try:
                channel = self.get_channel()
                if channel and channel.is_open:
                    self.declare_exchange(exchange)
                    channel.basic_publish(
                        exchange=exchange,
                        routing_key=routing_key,
                        body=json.dumps(message, ensure_ascii=False),
                    )
                    return True
                else:
                    logger.error("RabbitMQ 通道不可用，消息未发送")
                    return False
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"RabbitMQ 发送失败，尝试重连: {e}")
                    self.close()
                else:
                    logger.error(f"RabbitMQ 消息发送失败: {e}")
                    return False
        return False
    
    def consume(
        self,
        queue: str,
        callback: Callable,
        exchange: str = "rotation",
        routing_key: str = "#",
        durable: bool = True,
    ) -> None:
        """消费消息（阻塞式，手动确认）"""
        try:
            channel = self.get_channel()
            if not channel:
                logger.error("RabbitMQ 通道不可用")
                return
            
            self.declare_exchange(exchange)
            result = channel.queue_declare(queue=queue, durable=durable)
            channel.queue_bind(exchange=exchange, queue=result.method.queue, routing_key=routing_key)

            def _wrapper(ch, method, properties, body):
                """包装回调，处理完成后手动确认"""
                try:
                    callback(ch, method, properties, body)
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                except Exception as e:
                    logger.error(f"消息处理失败，拒绝重试: {e}")
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

            channel.basic_consume(queue=result.method.queue, on_message_callback=_wrapper, auto_ack=False)
            logger.info(f"RabbitMQ 消费者启动: queue={queue}, routing_key={routing_key}")
            channel.start_consuming()
        except Exception as e:
            logger.error(f"RabbitMQ 消费失败: {e}")
