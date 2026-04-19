"""信号通知服务 - 外部推送通道（钉钉、企业微信）"""
import json
import httpx
from datetime import datetime
from loguru import logger
from typing import Optional


class DingTalkChannel:
    """钉钉机器人 Webhook 推送通道"""

    def __init__(self, webhook_url: str, secret: str = None, enabled: bool = False):
        self.webhook_url = webhook_url
        self.secret = secret
        self.enabled = enabled

    async def send(self, signals: list[dict], strategy_type: str, signal_date: str, is_test: bool = False):
        """发送信号到钉钉群"""
        if not self.enabled or not self.webhook_url:
            return

        try:
            # 策略类型中文映射
            strategy_map = {
                "AGGRESSIVE": "⚡激进策略",
                "MODERATE": "⚖️稳健策略", 
                "CONSERVATIVE": "🛡️保守策略"
            }
            strategy_cn = strategy_map.get(strategy_type, strategy_type)
            
            # 构建钉钉 Markdown 消息
            test_tag = "🧪【测试消息】" if is_test else "📊"
            title = f"{test_tag}板块轮动信号 - {strategy_cn}"
            text_parts = [
                f"## {title}\n",
                f"**📅 信号日期**: {signal_date}\n",
                f"**🎯 策略类型**: {strategy_cn}\n"
            ]

            if is_test:
                text_parts.append("> ⚠️ 这是一条测试消息，用于验证推送通道，非真实交易信号\n")

            buy_signals = [s for s in signals if s.get("direction") == "BUY"]
            sell_signals = [s for s in signals if s.get("direction") == "SELL"]

            if buy_signals:
                text_parts.append("### 🟢 买入信号\n")
                for i, s in enumerate(buy_signals, 1):
                    etf_info = f"（{s.get('etf_name', '')} {s.get('etf_code', '')}）" if s.get('etf_code') else ""
                    reason = s.get('reason', '')
                    # 提取关键信息
                    if "排名" in reason:
                        rank_info = reason.split("排名")[-1].split(",")[0]
                    else:
                        rank_info = ""
                    
                    text_parts.append(
                        f"**{i}. {s.get('sector_name', '')}** {etf_info}\n\n"
                        f"📊 综合评分: **{s.get('score', 0):.1f}**/10  \n"
                        f"📈 建议仓位: **{s.get('position_ratio', 0) * 100:.1f}%**  \n"
                        f"💡 信号理由: {reason[:50]}{'...' if len(reason) > 50 else ''}\n\n"
                    )

            if sell_signals:
                text_parts.append("### 🔴 卖出信号\n")
                for i, s in enumerate(sell_signals, 1):
                    etf_info = f"（{s.get('etf_name', '')} {s.get('etf_code', '')}）" if s.get('etf_code') else ""
                    reason = s.get('reason', '')
                    
                    text_parts.append(
                        f"**{i}. {s.get('sector_name', '')}** {etf_info}\n\n"
                        f"📊 综合评分: **{s.get('score', 0):.1f}**/10  \n"
                        f"⚠️ 卖出理由: {reason[:60]}{'...' if len(reason) > 60 else ''}\n\n"
                    )

            if not buy_signals and not sell_signals:
                text_parts.append("### ⏸️ 今日无信号\n")
                text_parts.append("当前市场条件未触发交易信号，建议保持现有持仓或空仓观望。\n")

            # 添加统计摘要
            total_signals = len(buy_signals) + len(sell_signals)
            text_parts.append(f"\n**📋 信号统计**\n")
            text_parts.append(f"- 买入信号: {len(buy_signals)} 个\n")
            text_parts.append(f"- 卖出信号: {len(sell_signals)} 个\n")
            text_parts.append(f"- 总计: {total_signals} 个信号\n")
            
            # 添加风险提示
            text_parts.append(f"\n**⚠️ 风险提示**\n")
            text_parts.append("1. 本信号基于量化模型生成，仅供参考\n")
            text_parts.append("2. 投资有风险，决策需谨慎\n")
            text_parts.append("3. 建议结合自身风险承受能力调整仓位\n")
            
            text_parts.append(f"\n---\n⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            body = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": "\n".join(text_parts),
                },
            }

            # 如果配置了加签密钥，计算签名
            if self.secret:
                import hashlib
                import hmac
                import base64
                import urllib.parse
                import time
                timestamp = str(round(time.time() * 1000))
                string_to_sign = f"{timestamp}\n{self.secret}"
                hmac_code = hmac.new(
                    self.secret.encode("utf-8"),
                    string_to_sign.encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                url = f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"
            else:
                url = self.webhook_url

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=body)
                result = resp.json()
                if result.get("errcode") == 0:
                    logger.info(f"钉钉推送成功: strategy={strategy_type}, signals={len(signals)}")
                else:
                    logger.warning(f"钉钉推送返回错误: {result}")

        except Exception as e:
            logger.error(f"钉钉推送失败: {e}")


class WeComChannel:
    """企业微信机器人 Webhook 推送通道"""

    def __init__(self, webhook_url: str, enabled: bool = False):
        self.webhook_url = webhook_url
        self.enabled = enabled

    async def send(self, signals: list[dict], strategy_type: str, signal_date: str, is_test: bool = False):
        """发送信号到企业微信群"""
        if not self.enabled or not self.webhook_url:
            return

        try:
            # 策略类型中文映射（与企业微信的Markdown格式兼容）
            strategy_map = {
                "AGGRESSIVE": "⚡激进策略",
                "MODERATE": "⚖️稳健策略", 
                "CONSERVATIVE": "🛡️保守策略"
            }
            strategy_cn = strategy_map.get(strategy_type, strategy_type)
            
            # 构建企业微信 Markdown 消息
            test_tag = "🧪【测试消息】" if is_test else "📊"
            title = f"{test_tag}板块轮动信号 - {strategy_cn}"
            content_parts = [
                f"## {title}\n",
                f"**📅 信号日期**: {signal_date}\n",
                f"**🎯 策略类型**: {strategy_cn}\n"
            ]

            if is_test:
                content_parts.append("> ⚠️ 这是一条测试消息，用于验证推送通道，非真实交易信号\n")

            buy_signals = [s for s in signals if s.get("direction") == "BUY"]
            sell_signals = [s for s in signals if s.get("direction") == "SELL"]

            if buy_signals:
                content_parts.append("### 🟢 买入信号\n")
                for i, s in enumerate(buy_signals, 1):
                    etf_info = f"（{s.get('etf_name', '')} {s.get('etf_code', '')}）" if s.get('etf_code') else ""
                    reason = s.get('reason', '')
                    # 提取关键信息
                    if "排名" in reason:
                        rank_info = reason.split("排名")[-1].split(",")[0]
                    else:
                        rank_info = ""
                    
                    content_parts.append(
                        f"**{i}. {s.get('sector_name', '')}** {etf_info}\n\n"
                        f"📊 综合评分: **{s.get('score', 0):.1f}**/10  \n"
                        f"📈 建议仓位: **{s.get('position_ratio', 0) * 100:.1f}%**  \n"
                        f"💡 信号理由: {reason[:50]}{'...' if len(reason) > 50 else ''}\n\n"
                    )

            if sell_signals:
                content_parts.append("### 🔴 卖出信号\n")
                for i, s in enumerate(sell_signals, 1):
                    etf_info = f"（{s.get('etf_name', '')} {s.get('etf_code', '')}）" if s.get('etf_code') else ""
                    reason = s.get('reason', '')
                    
                    content_parts.append(
                        f"**{i}. {s.get('sector_name', '')}** {etf_info}\n\n"
                        f"📊 综合评分: **{s.get('score', 0):.1f}**/10  \n"
                        f"⚠️ 卖出理由: {reason[:60]}{'...' if len(reason) > 60 else ''}\n\n"
                    )

            if not buy_signals and not sell_signals:
                content_parts.append("### ⏸️ 今日无信号\n")
                content_parts.append("当前市场条件未触发交易信号，建议保持现有持仓或空仓观望。\n")

            # 添加统计摘要
            total_signals = len(buy_signals) + len(sell_signals)
            content_parts.append(f"\n**📋 信号统计**\n")
            content_parts.append(f"- 买入信号: {len(buy_signals)} 个\n")
            content_parts.append(f"- 卖出信号: {len(sell_signals)} 个\n")
            content_parts.append(f"- 总计: {total_signals} 个信号\n")
            
            # 添加风险提示
            content_parts.append(f"\n**⚠️ 风险提示**\n")
            content_parts.append("1. 本信号基于量化模型生成，仅供参考\n")
            content_parts.append("2. 投资有风险，决策需谨慎\n")
            content_parts.append("3. 建议结合自身风险承受能力调整仓位\n")
            
            content_parts.append(f"\n---\n⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            body = {
                "msgtype": "markdown",
                "markdown": {
                    "content": "\n".join(content_parts),
                },
            }

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self.webhook_url, json=body)
                result = resp.json()
                if result.get("errcode") == 0:
                    logger.info(f"企业微信推送成功: strategy={strategy_type}, signals={len(signals)}")
                else:
                    logger.warning(f"企业微信推送返回错误: {result}")

        except Exception as e:
            logger.error(f"企业微信推送失败: {e}")


class NotifyChannelManager:
    """推送通道管理器 - 统一管理所有外部推送通道"""

    def __init__(self):
        self.dingtalk = DingTalkChannel(webhook_url="", enabled=False)
        self.wecom = WeComChannel(webhook_url="", enabled=False)

    def load_config(self, config: dict):
        """从配置字典加载推送通道配置"""
        dt_cfg = config.get("dingtalk", {})
        self.dingtalk = DingTalkChannel(
            webhook_url=dt_cfg.get("webhook_url", ""),
            secret=dt_cfg.get("secret", ""),
            enabled=dt_cfg.get("enabled", False),
        )

        wecom_cfg = config.get("wecom", {})
        self.wecom = WeComChannel(
            webhook_url=wecom_cfg.get("webhook_url", ""),
            enabled=wecom_cfg.get("enabled", False),
        )

        logger.info(f"推送通道配置已加载: 钉钉={'启用' if self.dingtalk.enabled else '禁用'}, 企业微信={'启用' if self.wecom.enabled else '禁用'}")

    def get_config(self) -> dict:
        """获取当前推送通道配置"""
        return {
            "dingtalk": {
                "enabled": self.dingtalk.enabled,
                "webhook_url": self.dingtalk.webhook_url,
                "secret": self.dingtalk.secret,
            },
            "wecom": {
                "enabled": self.wecom.enabled,
                "webhook_url": self.wecom.webhook_url,
            },
        }

    async def push_signal(self, signals: list[dict], strategy_type: str, signal_date: str, is_test: bool = False):
        """向所有已启用的通道推送信号"""
        if not signals:
            return

        # 检查策略类型是否在推送范围内
        # 由调用方过滤

        if self.dingtalk.enabled:
            await self.dingtalk.send(signals, strategy_type, signal_date, is_test=is_test)

        if self.wecom.enabled:
            await self.wecom.send(signals, strategy_type, signal_date, is_test=is_test)

        logger.info(f"外部推送完成: strategy={strategy_type}, 钉钉={'✓' if self.dingtalk.enabled else '✗'}, 企业微信={'✓' if self.wecom.enabled else '✗'}")


# 全局实例
notify_manager = NotifyChannelManager()
