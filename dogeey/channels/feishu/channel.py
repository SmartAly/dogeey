"""
飞书频道完整实现 - 轮询/Webhook/WebSocket三模式
对齐Hermes，支持三种连接方式
"""
import os
import sys
import time
import json
import logging
import asyncio
import threading
from typing import Dict, Any, Optional
from loguru import logger
from dataclasses import dataclass, field

from dogeey.channels.base import Channel
from dogeey.message import Message, MessageType
from dogeey.event_bus import EventBus, Event

# 提前导入lark_oapi ws客户端（在async上下文外，确保独立事件循环创建）
try:
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    from lark_oapi.ws import Client as FeishuWSClient
    _LARK_AVAILABLE = True
except ImportError:
    _LARK_AVAILABLE = False
    EventDispatcherHandler = None
    FeishuWSClient = None


@dataclass
class FeishuSettings:
    """飞书配置项"""
    app_id: str = ""
    app_secret: str = ""
    domain_name: str = "feishu"  # "feishu" 或 "lark"
    connection_mode: str = "polling"  # "polling", "webhook" 或 "websocket"
    encrypt_key: str = ""
    verification_token: str = ""
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8765
    webhook_path: str = "/webhook/feishu"
    poll_interval: float = 3.0  # 轮询间隔（秒）
    chat_ids: list = None  # 要轮询的chat_id列表

# 飞书Reaction表情编码映射表（官方标准 - 大写）
FEISHU_EMOJI_MAP = {
    "✅": "CheckMark",
    "👍": "THUMBSUP",
    "🙌": "RAISED_HANDS",
    "❤️": "HEART",
    "👋": "WAVE",
    "🎉": "TADA",
    "😄": "SMILE",
    "👏": "CLAP",
    "⏳": "THINKING",
    "🤔": "THINKING",
    "❌": "CrossMark",
    "❎": "CrossMark",
}


class FeishuChannel(Channel):
    """飞书频道 - 支持三种模式"""

    def __init__(self):
        self.app_id: str = ""
        self.app_secret: str = ""
        self._is_running: bool = False
        self.event_bus: Optional[EventBus] = None
        self._settings: Optional[FeishuSettings] = None
        self._access_token: str = ""
        self._token_expires: float = 0
        
        # 轮询相关
        self._poll_thread: Optional[threading.Thread] = None
        
        # WebSocket相关（延迟导入）
        self._ws_available: bool = False
        self._ws_client: Optional[Any] = None
        self._ws_thread: Optional[threading.Thread] = None
        
        # 消息去重
        self._seen_message_ids: Dict[str, float] = {}
        self._dedup_cache_size: int = 100

    @property
    def name(self) -> str:
        return "feishu"

    async def configure(self, config: Dict[str, Any]) -> bool:
        """根据配置初始化频道"""
        try:
            # 解析chat_ids
            chat_ids_str = config.get("chat_ids", "")
            chat_ids = []
            if chat_ids_str:
                if isinstance(chat_ids_str, str):
                    chat_ids = [x.strip() for x in chat_ids_str.split(",") if x.strip()]
                elif isinstance(chat_ids_str, list):
                    chat_ids = chat_ids_str
            
            # 创建配置
            settings = FeishuSettings(
                app_id=config.get("app_id", ""),
                app_secret=config.get("app_secret", ""),
                domain_name=config.get("domain_name", "feishu"),
                connection_mode=config.get("connection_mode", "polling").lower(),
                encrypt_key=config.get("encrypt_key", ""),
                verification_token=config.get("verification_token", ""),
                webhook_host=config.get("webhook_host", "127.0.0.1"),
                webhook_port=config.get("webhook_port", 8765),
                webhook_path=config.get("webhook_path", "/webhook/feishu"),
                poll_interval=float(config.get("poll_interval", 3.0)),
                chat_ids=chat_ids
            )
            
            self._settings = settings
            self.app_id = settings.app_id
            self.app_secret = settings.app_secret
            
            # 验证必要配置
            if not all([self.app_id, self.app_secret]):
                logger.error("飞书频道配置失败: 缺少app_id或app_secret")
                return False
            
            logger.info(f"✅ 飞书频道配置成功 (app_id: {self.app_id[:10]}...)")
            logger.info(f"   连接模式: {settings.connection_mode}")
            if settings.chat_ids:
                logger.info(f"   轮询聊天数: {len(settings.chat_ids)}")
            else:
                if settings.connection_mode == "polling":
                    logger.warning("   未配置chat_ids，轮询模式可能无法工作！")
            return True
            
        except Exception as e:
            logger.error(f"飞书频道配置异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def start(self) -> None:
        """启动飞书频道"""
        if not self._settings:
            logger.error("未配置，无法启动")
            return
        
        self._is_running = True
        
        if self._settings.connection_mode == "websocket":
            await self._start_websocket_mode()
        elif self._settings.connection_mode == "webhook":
            await self._start_webhook_mode()
        else:  # polling模式（默认）
            await self._start_polling_mode()
        
        logger.info(f"🚀 飞书频道已启动 (模式: {self._settings.connection_mode})")

    async def _start_polling_mode(self):
        """启动轮询模式 - 主动拉消息，不需要公网地址！"""
        logger.info("✅ 轮询模式已启动")
        logger.info(f"   轮询间隔: {self._settings.poll_interval}秒")
        logger.info("⚠️  无需公网地址，dogeey主动拉取消息")
        
        def poll_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self._is_running:
                try:
                    loop.run_until_complete(self._poll_messages())
                except Exception as e:
                    logger.error(f"轮询异常: {e}")
                time.sleep(self._settings.poll_interval)
            loop.close()
        
        self._poll_thread = threading.Thread(target=poll_loop, daemon=True)
        self._poll_thread.start()

    async def _poll_messages(self):
        """轮询飞书消息 - 真正拉取！"""
        try:
            # 获取token
            token = await self._get_access_token()
            if not token:
                return
            
            if not self._settings or not self._settings.chat_ids:
                return
            
            import httpx
            
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                for chat_id in self._settings.chat_ids:
                    try:
                        url = "https://open.feishu.cn/open-apis/im/v1/messages"
                        headers = {"Authorization": f"Bearer {token}"}
                        params = {
                            "container_id": chat_id,
                            "container_id_type": "chat",
                            "page_size": 10,
                            "sort_type": "ByCreateTimeDesc"
                        }
                        
                        response = await client.get(url, headers=headers, params=params)
                        
                        if response.status_code != 200:
                            continue
                        
                        result = response.json()
                        if result.get("code") != 0:
                            continue
                        
                        messages = result.get("data", {}).get("items", [])
                        
                        for msg_data in messages:
                            msg_id = msg_data.get("message_id", "")
                            
                            # 去重
                            if msg_id in self._seen_message_ids:
                                continue
                            
                            self._seen_message_ids[msg_id] = time.time()
                            
                            # 清理过期记录
                            if len(self._seen_message_ids) > self._dedup_cache_size:
                                oldest_key = min(self._seen_message_ids, key=self._seen_message_ids.get)
                                del self._seen_message_ids[oldest_key]
                            
                            # 只处理文本消息
                            msg_type = msg_data.get("message_type", "")
                            if msg_type != "text":
                                continue
                            
                            # 提取文本
                            content = msg_data.get("body", {}).get("content", "")
                            try:
                                content_dict = json.loads(content)
                                text = content_dict.get("text", "")
                            except:
                                text = content
                            
                            # 🤔 先添加"思考中"表情反应
                            await self.add_reaction(msg_id, "🤔")
                            logger.info(f"🤔 已添加'思考中'表情到消息 {msg_id[:20]}...")
                            
                            # 构造统一消息
                            msg = Message(
                                id=msg_id,
                                channel=self.name,
                                user_id=msg_data.get("sender", {}).get("id", ""),
                                username=msg_data.get("sender", {}).get("id", ""),
                                text=text,
                                type=MessageType.TEXT,
                                metadata=msg_data,
                                reply_token=chat_id
                            )
                            
                            logger.info(f"📨 轮询到飞书消息: {text[:50]}...")
                            
                            # 发布到EventBus
                            if self.event_bus:
                                from dogeey.event_bus import Event
                                await self.event_bus.publish(Event(
                                    type="message.received",
                                    data=msg,
                                    source=self.name
                                ))
                    
                    except Exception as e:
                        logger.error(f"处理chat {chat_id} 失败: {e}")
        
        except Exception as e:
            logger.error(f"轮询消息失败: {e}")

    async def _start_websocket_mode(self):
        """
        启动WebSocket模式 - 飞书官方实时通信
        支持私聊(p2p) + 群聊，无需chat_ids，无需公网地址
        """
        logger.info("🔌 初始化WebSocket模式...")
        try:
            if not _LARK_AVAILABLE:
                logger.error("lark_oapi 未安装，无法启动WebSocket模式")
                self._is_running = False
                return
            
            # 获取主事件循环引用（用于跨线程调度）
            main_loop = asyncio.get_running_loop()
            self.main_loop = main_loop
            
            
            # 创建事件处理器，注册各类事件回调
            logger.info(f"[WS] 创建EventDispatcherHandler, encrypt_key={'有' if self._settings.encrypt_key else '无'}, verification_token={'有' if self._settings.verification_token else '无'}")
            
            event_handler = EventDispatcherHandler.builder(
                encrypt_key=self._settings.encrypt_key or "",
                verification_token=self._settings.verification_token or ""
            ).register_p2_im_message_receive_v1(
                self.on_message_received
            ).register_p2_im_message_message_read_v1(
                self.on_message_read
            ).register_p2_im_message_reaction_created_v1(
                self.on_reaction_created
            ).build()
            
            logger.info(f"[WS] ✅ EventDispatcherHandler已创建，注册了3个事件回调")
            
            # 创建WebSocket客户端（新版API，传入domain）
            from lark_oapi.core.const import FEISHU_DOMAIN, LARK_DOMAIN
            domain = FEISHU_DOMAIN if self._settings.domain_name != "lark" else LARK_DOMAIN
            self._ws_client = FeishuWSClient(
                app_id=self.app_id,
                app_secret=self.app_secret,
                event_handler=event_handler,
                domain=domain
            )
            
            # 在新线程中启动（添加重连保护）
            import lark_oapi.ws.client as _ws_client_module
            
            def run_ws():
                """WebSocket线程，带重连保护"""
                retry_count = 0
                max_retries = 10
                
                while self._is_running and retry_count < max_retries:
                    try:
                        ws_loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(ws_loop)
                        # patch模块级loop为线程本地loop
                        _ws_client_module.loop = ws_loop
                        
                        # 更新main_loop引用（重要！确保调用能到达）
                        self.main_loop = ws_loop
                        
                        logger.info(f"[WS] WebSocket线程启动 (尝试 {retry_count + 1}/{max_retries})")
                        self._ws_client.start()
                        
                        # 如果start()返回（连接断开），则重连
                        logger.warning("[WS] WebSocket连接断开，准备重连...")
                        retry_count += 1
                        if retry_count < max_retries:
                            import time
                            time.sleep(min(retry_count * 2, 10))  # 指数退避，最多等10秒
                        
                    except Exception as e:
                        logger.error(f"[WS] WebSocket线程异常: {e}")
                        retry_count += 1
                        if retry_count < max_retries:
                            import time
                            time.sleep(min(retry_count * 2, 10))
                
                if retry_count >= max_retries:
                    logger.error("[WS] ❌ WebSocket重连次数用尽，停止重连")
                    self._is_running = False
            
            self._ws_thread = threading.Thread(target=run_ws, daemon=True)
            self._ws_thread.start()
            
            # 等待连接
            import time
            time.sleep(2)
            
            self._ws_available = True
            logger.info("✅ WebSocket模式已启动")
            logger.info("   支持私聊(p2p) + 群聊，实时接收消息")
            
        except Exception as e:
            logger.error(f"WebSocket模式启动失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._is_running = False

    async def _start_webhook_mode(self):
        """启动Webhook模式（备用，需要公网地址）"""
        logger.info(f"✅ Webhook模式已启动")
        logger.info(f"   Webhook路径: {self._settings.webhook_path}")
        logger.info(f"⚠️  需要公网地址，飞书才能回调")

    async def stop(self) -> None:
        """停止频道"""
        self._is_running = False
        
        # 新版ws.Client没有显式stop方法，daemon线程会在进程退出时自动结束
        # 对于WebSocket连接，设置_running标志后，如果连接断开就不会重连
        if self._ws_client:
            logger.info("🛑 WebSocket客户端已标记停止（daemon线程自动退出）")
        
        logger.info("🛑 飞书频道已停止")

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _markdown_to_feishu_post(self, text: str) -> dict:
        """
        将Markdown文本转换为飞书post消息的JSON结构
        支持：加粗、标题、列表、分隔线、换行、链接
        """
        import re
        
        # 飞书post消息结构
        post_content = []
        lines = text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 空行 → 跳过
            if not line.strip():
                i += 1
                continue
            
            # 标题 (# ## ###) 
            if line.startswith('#'):
                level = len(line) - len(line.lstrip('#'))
                title_text = line.lstrip('#').strip()
                # 解析内联格式
                parts = self._parse_inline_markdown(title_text)
                # 根据标题级别添加装饰
                if level == 1:
                    parts = [{"tag": "text", "text": "📌 "}] + parts
                elif level == 2:
                    parts = [{"tag": "text", "text": "▸ "}] + parts
                # 标题加粗
                for p in parts:
                    if p.get("tag") == "text" and "bold" not in p.get("style", []):
                        p["style"] = p.get("style", []) + ["bold"]
                post_content.append(parts)
                i += 1
                continue
            
            # 分隔线 (---)
            if line.strip() == '---':
                post_content.append([
                    {"tag": "text", "text": "─" * 30}
                ])
                i += 1
                continue
            
            # 有序列表 (1. 2. 3.)
            if re.match(r'^\d+\.\s', line):
                while i < len(lines) and re.match(r'^\d+\.\s', lines[i]):
                    # 保留序号，并加粗
                    item_match = re.match(r'^(\d+\.\s)(.*)', lines[i])
                    if item_match:
                        prefix = item_match.group(1)
                        item_text = item_match.group(2).strip()
                        # 序号加粗，后面跟正文
                        parts = [
                            {"tag": "text", "text": prefix, "style": ["bold"]}
                        ] + self._parse_inline_markdown(item_text)
                        post_content.append(parts)
                    i += 1
                continue
            
            # 无序列表 (- * +)
            if re.match(r'^[-*+]\s', line):
                while i < len(lines) and re.match(r'^[-*+]\s', lines[i]):
                    # 保留列表符号，转换为 •
                    item_match = re.match(r'^([-*+]\s)(.*)', lines[i])
                    if item_match:
                        item_text = item_match.group(2).strip()
                        # 解析内联格式
                        parts = [{"tag": "text", "text": "• "}] + self._parse_inline_markdown(item_text)
                        post_content.append(parts)
                    i += 1
                continue
            
            # 普通段落：处理内联格式（加粗、链接等）
            paragraph_lines = []
            while i < len(lines) and lines[i].strip() and not lines[i].startswith('#') and not re.match(r'^[-*+\d]+\.\s', lines[i]) and lines[i].strip() != '---':
                paragraph_lines.append(lines[i])
                i += 1
            
            if paragraph_lines:
                para_text = ' '.join(paragraph_lines)
                # 转换内联Markdown
                parts = self._parse_inline_markdown(para_text)
                post_content.append(parts)
        
        # 如果没有内容，返回原文本
        if not post_content:
            post_content = [[{"tag": "text", "text": text}]]
        
        return {
            "zh_cn": {
                "title": "",
                "content": post_content
            }
        }
    
    def _parse_inline_markdown(self, text: str) -> list:
        """
        解析内联Markdown语法，返回飞书post的元素数组
        支持：**加粗**、*斜体*、`代码`、[链接](url)
        """
        import re
        
        parts = []
        last_end = 0
        
        # 收集所有匹配（按位置排序）
        matches = []
        
        # **加粗**（允许内部有空格）
        for m in re.finditer(r'\*\*(.+?)\*\*', text):
            matches.append((m.start(), m.end(), 'bold', m.group(1)))
        
        # *斜体*（不要在**加粗**内部匹配）
        for m in re.finditer(r'(?<!\*)\*(?!\*)(.+?)\*(?!\*)', text):
            matches.append((m.start(), m.end(), 'italic', m.group(1)))
        
        # `代码`
        for m in re.finditer(r'`([^`]+)`', text):
            matches.append((m.start(), m.end(), 'code', m.group(1)))
        
        # [链接](url)
        for m in re.finditer(r'\[([^\]]+)\]\(([^\)]+)\)', text):
            matches.append((m.start(), m.end(), 'link', m.group(1), m.group(2)))
        
        # 按位置排序
        matches.sort(key=lambda x: (x[0], x[1]))
        
        for match in matches:
            start, end = match[0], match[1]
            # 添加前面的普通文本
            if start > last_end:
                parts.append({"tag": "text", "text": text[last_end:start]})
            
            if match[2] == 'bold':
                parts.append({"tag": "text", "text": match[3], "style": ["bold"]})
            elif match[2] == 'italic':
                parts.append({"tag": "text", "text": match[3], "style": ["italic"]})
            elif match[2] == 'code':
                parts.append({"tag": "text", "text": f"`{match[3]}`", "style": ["code"]})
            elif match[2] == 'link':
                parts.append({"tag": "a", "text": match[3], "href": match[4]})
            
            last_end = end
        
        # 添加剩余文本
        if last_end < len(text):
            parts.append({"tag": "text", "text": text[last_end:]})
        
        return parts if parts else [{"tag": "text", "text": text}]

    async def send(self, message: Message) -> bool:
        """发送消息到飞书（支持Markdown格式转换）"""
        token = await self._get_access_token()
        if not token:
            logger.error("无法获取access_token，发送失败")
            return False

        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }

            chat_id = message.reply_token or ""
            if not chat_id:
                logger.error("未提供chat_id，无法发送消息")
                return False

            # 检测是否包含Markdown语法
            import re
            has_markdown = bool(re.search(r'(\*\*|#+\s|^\d+\.\s|^[-*+]\s|^---$)', message.text, re.MULTILINE))
            
            if has_markdown:
                # 使用post类型发送富文本
                msg_type = "post"
                post_content = self._markdown_to_feishu_post(message.text)
                content = json.dumps(post_content)
                logger.info(f"📝 使用post类型发送富文本消息 (检测到Markdown)")
                logger.debug(f"转换后的post内容: {json.dumps(post_content, ensure_ascii=False)[:200]}...")
            else:
                # 纯文本
                msg_type = "text"
                content = json.dumps({"text": message.text})
                logger.info(f"📝 使用text类型发送纯文本消息")

            metadata = getattr(message, 'metadata', {}) or {}
            reply_to_msg_id = metadata.get("reply_to_message_id") or metadata.get("message_id") or ""

            response = None
            async with httpx.AsyncClient(timeout=30.0) as client:
                if reply_to_msg_id:
                    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{reply_to_msg_id}/reply"
                    payload = {"content": content, "msg_type": msg_type}
                    response = await client.post(url, headers=headers, json=payload)

                    if response.status_code == 200:
                        result = response.json()
                        if result.get("code") == 0:
                            logger.info(f"📤 已回复飞书消息: {message.text[:50]}...")
                            return True
                        else:
                            error_code = result.get("code", 0)
                            logger.warning(f"飞书回复API失败 (code={error_code})，降级为新消息")
                            reply_to_msg_id = ""
                    else:
                        logger.warning(f"飞书回复API HTTP失败 ({response.status_code})，降级为新消息")
                        reply_to_msg_id = ""

                if not reply_to_msg_id:
                    url = "https://open.feishu.cn/open-apis/im/v1/messages"
                    if chat_id.startswith('ou_'):
                        receive_id_type = "open_id"
                    elif chat_id.startswith('oc_'):
                        receive_id_type = "chat_id"
                    else:
                        receive_id_type = "chat_id"
                    params = {"receive_id_type": receive_id_type}
                    payload = {
                        "receive_id": chat_id,
                        "msg_type": msg_type,
                        "content": content,
                    }
                    response = await client.post(
                        url, headers=headers, params=params, json=payload
                    )

            if response is None:
                logger.error("飞书消息发送失败: 无响应")
                return False

            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    logger.info(f"📤 消息已发送到飞书: {message.text[:50]}...")
                    return True
                else:
                    logger.error(f"飞书API返回错误: {result}")
                    return False
            else:
                logger.error(f"飞书API请求失败: {response.status_code} {response.text}")
                return False

        except Exception as e:
            logger.error(f"发送飞书消息异常: {e}")
            return False

    async def add_reaction(self, message_id: str, emoji: str = "🤔") -> bool:
        """
        给消息添加表情反应（Reacting功能）- 使用飞书官方SDK
        :param message_id: 消息ID
        :param emoji: 表情符号，默认🤔(思考中)，会自动映射为飞书编码
        :return: 是否成功
        """
        if not message_id:
            logger.warning("message_id为空，无法添加reaction")
            return False
        token = await self._get_access_token()
        if not token:
            logger.error("无法获取access_token，添加reaction失败")
            return False
        
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody
            
            # 将emoji字符转换为飞书编码
            emoji_code = FEISHU_EMOJI_MAP.get(emoji, "THINKING")
            
            logger.info(f"添加reaction: message_id={message_id[:30]}, emoji={emoji} → code={emoji_code}")
            
            # 使用enable_set_token(True)，通过RequestOption传入token
            client = lark.Client.builder() \
                .enable_set_token(True) \
                .log_level(lark.LogLevel.WARNING) \
                .build()
            
            # 使用字典传入emoji_type（飞书SDK支持的类型）
            body = CreateMessageReactionRequestBody.builder() \
                .reaction_type({"emoji_type": emoji_code}) \
                .build()
            
            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(body) \
                .build()
            
            option = lark.RequestOption.builder() \
                .tenant_access_token(token) \
                .build()
            
            response = await asyncio.to_thread(
                client.im.v1.message_reaction.create,
                request,
                option
            )
            
            if response and getattr(response, "success", lambda: False)():
                logger.info(f"✅ 已添加表情反应 {emoji_code} 到消息 {message_id[:20]}...")
                return True
            else:
                logger.warning(
                    f"❌ 添加reaction失败: code={getattr(response, 'code', None)}, "
                    f"msg={getattr(response, 'msg', None)}"
                )
                return False
                
        except ImportError:
            logger.error("❌ lark_oapi 未安装，无法使用官方SDK添加reaction")
            return False
        except Exception as e:
            logger.error(f"添加reaction异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def _get_access_token(self) -> str:
        """动态获取tenant_access_token"""
        now = time.time()
        if self._access_token and now < self._token_expires - 60:
            return self._access_token
        
        try:
            import httpx
            
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            
            async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
                response = await client.post(url, json=payload)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    self._access_token = result.get("tenant_access_token", "")
                    expire = result.get("expire", 7200)
                    self._token_expires = now + expire
                    logger.debug(f"✅ 获取access_token成功，有效期: {expire}秒")
                    return self._access_token
                else:
                    logger.error(f"获取access_token失败: {result}")
            else:
                logger.error(f"获取access_token请求失败: {response.status_code} {response.text}")
        except Exception as e:
            logger.error(f"获取access_token异常: {e}")
        
        return ""

    async def handle_webhook(self, body: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
        """处理飞书Webhook回调"""
        try:
            header = body.get("header", {})
            event_type = header.get("event_type")
            
            # URL验证挑战
            if event_type == "url_verification":
                challenge = body.get("challenge")
                logger.info("✅ 飞书URL验证挑战")
                return {"challenge": challenge}
            
            # 签名验证（可选）
            if headers and self._settings and self._settings.verification_token:
                if not self._verify_signature(headers, body):
                    logger.warning("飞书回调签名验证失败")
                    return {"success": False, "error": "signature verification failed"}
            
            # 处理消息接收事件
            if event_type == "im.message.receive_v1":
                await self._handle_webhook_message(body)
                return {"success": True}
            
            else:
                logger.warning(f"未处理的事件类型: {event_type}")
                return {"success": True}
                
        except Exception as e:
            logger.error(f"处理飞书Webhook失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}

    async def _handle_webhook_message(self, body: Dict[str, Any]):
        """处理Webhook接收的消息"""
        header = body.get("header", {})
        event = body.get("event", {})
        sender = event.get("sender", {})
        message = event.get("message", {})
        chat_type = message.get("chat_type", "")
        real_msg_id = message.get("message_id", "")
        chat_id = message.get("chat_id") or real_msg_id

        msg = Message(
            id=real_msg_id,
            channel=self.name,
            user_id=sender.get("user_id", ""),
            username=sender.get("user_id", ""),
            text=self._extract_message_content(message),
            type=self._get_message_type(message),
            metadata={
                "chat_type": chat_type,
                "sender_type": sender.get("sender_type", ""),
                "message_type": message.get("message_type", "text"),
                "message_id": real_msg_id,
                "raw_event": body,
            },
            reply_token=chat_id
        )
        
        logger.info(f"📨 收到飞书消息(Webhook): {msg.text[:50]}...")
        
        # 🤔 先添加"思考中"表情反应
        await self.add_reaction(real_msg_id, "🤔")
        logger.info(f"🤔 已添加'思考中'表情到消息 {real_msg_id[:20]}...")
        
        # 发布到EventBus
        if self.event_bus:
            from dogeey.event_bus import Event
            await self.event_bus.publish(Event(
                type="message.received",
                data=msg,
                source=self.name
            ))

    def _verify_signature(self, headers: Dict[str, str], body: Dict[str, Any]) -> bool:
        """验证飞书回调签名"""
        if not self._settings or not self._settings.verification_token:
            return True
        
        try:
            import hashlib
            import hmac
            import base64
            
            verification_token = self._settings.verification_token
            
            timestamp = headers.get("x-lark-request-timestamp", "")
            nonce = headers.get("x-lark-request-nonce", "")
            signature = headers.get("x-lark-signature", "")
            
            content = f"{timestamp}{nonce}{json.dumps(body)}"
            
            hmac_code = hmac.new(
                verification_token.encode("utf-8"),
                content.encode("utf-8"),
                hashlib.sha256
            ).digest()
            
            expected_signature = base64.b64encode(hmac_code).decode("utf-8")
            return expected_signature == signature
        except Exception as e:
            logger.error(f"验证签名异常: {e}")
            return False

    def _extract_message_content(self, message: Dict[str, Any]) -> str:
        """提取消息文本内容"""
        msg_type = message.get("message_type", "text")
        content = message.get("content", "")
        
        try:
            if msg_type == "text":
                content_dict = json.loads(content)
                return content_dict.get("text", "")
            elif msg_type == "image":
                return "[图片]"
            elif msg_type == "file":
                return "[文件]"
            else:
                return f"[{msg_type}消息]"
        except Exception:
            return content

    def _get_message_type(self, message: Dict[str, Any]) -> MessageType:
        """根据飞书消息类型返回统一类型"""
        msg_type = message.get("message_type", "text")
        if msg_type == "image":
            return MessageType.IMAGE
        elif msg_type == "file":
            return MessageType.FILE
        else:
            return MessageType.TEXT

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        return {
            "name": self.name,
            "running": self._is_running,
            "configured": bool(self.app_id and self.app_secret),
            "connection_mode": self._settings.connection_mode if self._settings else "unknown",
            "has_token": bool(self._access_token),
            "ws_available": self._ws_available,
            "webhook_path": self._settings.webhook_path if self._settings else "/webhook/feishu"
        }

    def on_message_received(self, event_data):
        """飞书消息回调 - 在lark_oapi内部线程调用（参考Hermes模式）"""
        # 🔥 铁证：这个方法到底有没有被调用？
        logger.warning(f"[WS] 🔥🔥 on_message_received 被调用了！event_data type: {type(event_data)}")
        try:
            import json as _json
            import re
            
            header = event_data.header
            event = event_data.event
            message = event.message
            sender = event.sender
            
            logger.info(f"[WS] 收到飞书事件: msg_type={message.message_type}, chat_id={message.chat_id}")
            
            # 只处理文本消息
            if message.message_type != "text":
                logger.info(f"[WS] 跳过非文本消息: {message.message_type}")
                return
            
            # 解析content (JSON)
            text = message.content or ""
            try:
                content_dict = _json.loads(text)
                text = content_dict.get("text", "")
            except Exception:
                pass
            
            # 去掉@bot的文本
            text = re.sub(r'@_user_1\s*', '', text).strip()
            
            # 获取发送者信息
            sender_id = ""
            sender_open_id = ""
            if sender.sender_id:
                sender_id = sender.sender_id.user_id or sender.sender_id.open_id or ""
                sender_open_id = sender.sender_id.open_id or ""
            
            chat_id = getattr(message, 'chat_id', "") or ""
            chat_type = getattr(message, 'chat_type', "") or "p2p"
            msg_id = getattr(message, 'message_id', "") or ""
            
            # 构建Message
            from dogeey.message import Message, MessageType
            msg = Message(
                id=msg_id,
                channel=self.name,
                user_id=sender_id,
                username=sender_id,
                text=text,
                type=MessageType.TEXT,
                reply_token=chat_id,
                metadata={
                    "chat_type": chat_type,
                    "message_type": message.message_type,
                    "message_id": msg_id,
                }
            )
            
            logger.info(f"📨 飞书消息({chat_type}): {text[:50]}...")
            
            # 调度到主事件循环（参考Hermes模式）
            if self.event_bus and hasattr(self, 'main_loop') and self.main_loop and not self.main_loop.is_closed():
                logger.info(f"[WS] 调度到主事件循环: msg_id={msg.id[:20]}...")
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._handle_ws_message_async(msg),
                        self.main_loop
                    )
                    # 添加错误回调（学习Hermes）
                    future.add_done_callback(
                        lambda f: f.exception() if f.exception() else None
                    )
                except Exception as e:
                    logger.error(f"[WS] 调度到主循环失败: {e}")
            else:
                logger.warning(f"[WS] 无法发布事件: event_bus={self.event_bus is not None}, main_loop={getattr(self, 'main_loop', None)}")
        
        except Exception as e:
            logger.error(f"处理飞书WebSocket消息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _handle_ws_message_async(self, msg):
        """异步处理WebSocket消息（参考Hermes的_handle_message_event_data）"""
        try:
            # 先添加thinking reaction（可选，失败不影响主流程）
            if msg.id:
                try:
                    await self.add_reaction(msg.id, "🤔")
                    logger.info(f"🤔 已添加'思考中'表情到消息 {msg.id[:20]}...")
                except Exception as e:
                    logger.warning(f"🤔 添加reaction失败（忽略）: {e}")
            
            # 发布到EventBus（必须成功）
            await self.event_bus.publish(Event(
                type="message.received",
                data=msg,
                source=self.name
            ))
            logger.info(f"[WS] ✅ 事件已发布到EventBus")
        except Exception as e:
            logger.error(f"[WS] 异步处理消息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def on_message_read(self, event_data):
        """处理消息已读事件 - 无需特殊处理"""
        pass

    def on_reaction_created(self, event_data):
        """处理表情回应事件 - 无需特殊处理"""
        pass

