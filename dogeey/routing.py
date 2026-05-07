"""
用户身份映射和频道间消息路由
"""
from typing import Dict, Optional, List
from loguru import logger
from dogeey.message import Message


class UserMapper:
    """用户身份跨平台映射"""
    
    def __init__(self, mapping_config: Dict[str, str] = None):
        """
        初始化用户映射器
        
        Args:
            mapping_config: 配置中的user_mapping
            格式: {"feishu:ou_abc123": "aly", "discord:123456": "aly"}
        """
        self.mapping = mapping_config or {}
    
    def get_username(self, channel: str, user_id: str) -> Optional[str]:
        """
        根据频道和用户ID获取映射的用户名
        
        Args:
            channel: 频道名称
            user_id: 平台用户ID
            
        Returns:
            映射的用户名，如果没有映射则返回None
        """
        key = f"{channel}:{user_id}"
        return self.mapping.get(key)
    
    def set_mapping(self, channel: str, user_id: str, username: str):
        """
        设置用户映射
        
        Args:
            channel: 频道名称
            user_id: 平台用户ID
            username: 统一用户名
        """
        key = f"{channel}:{user_id}"
        self.mapping[key] = username
        logger.info(f"✅ 用户映射已添加: {key} -> {username}")
    
    def remove_mapping(self, channel: str, user_id: str):
        """移除用户映射"""
        key = f"{channel}:{user_id}"
        if key in self.mapping:
            del self.mapping[key]
            logger.info(f"✅ 用户映射已移除: {key}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """获取所有映射"""
        return self.mapping.copy()
    
    def apply_to_message(self, message: Message) -> Message:
        """
        应用用户映射到消息
        
        Args:
            message: 原始消息
            
        Returns:
            应用映射后的消息（如果找到映射，username会被更新）
        """
        mapped_name = self.get_username(message.channel, message.user_id)
        if mapped_name:
            message.username = mapped_name
            logger.debug(f"用户身份映射: {message.user_id} -> {mapped_name}")
        
        return message


class MessageRouter:
    """频道间消息路由器"""
    
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.routes: List[Dict] = []  # 路由规则列表
        
        # 注册路由处理器
        event_bus.subscribe("message.received", self._handle_message)
    
    def add_route(self, from_channel: str, to_channel: str, filter_func=None):
        """
        添加路由规则
        
        Args:
            from_channel: 源频道
            to_channel: 目标频道
            filter_func: 可选的过滤函数 async def filter(message: Message) -> bool
        """
        route = {
            "from": from_channel,
            "to": to_channel,
            "filter": filter_func
        }
        self.routes.append(route)
        logger.info(f"✅ 路由规则已添加: {from_channel} -> {to_channel}")
    
    def remove_route(self, from_channel: str, to_channel: str):
        """移除路由规则"""
        self.routes = [
            r for r in self.routes 
            if not (r["from"] == from_channel and r["to"] == to_channel)
        ]
        logger.info(f"✅ 路由规则已移除: {from_channel} -> {to_channel}")
    
    def get_routes(self) -> List[Dict]:
        """获取所有路由规则"""
        return self.routes.copy()
    
    async def _handle_message(self, event):
        """处理接收到的消息，检查是否需要路由"""
        message: Message = event.data
        
        # 检查所有路由规则
        for route in self.routes:
            if route["from"] == message.channel:
                # 检查过滤条件
                if route["filter"]:
                    should_route = await route["filter"](message)
                    if not should_route:
                        continue
                
                # 执行路由：发布到目标频道
                logger.info(f"🔀 消息路由: {message.channel} -> {route['to']}")
                
                # 修改消息的channel为目标的（这样目标频道会处理）
                # 实际实现中，这里应该调用目标频道的send方法
                # 这里我们发布一个特殊事件
                from dogeey.event_bus import Event
                await self.event_bus.publish(Event(
                    type="message.route",
                    data={
                        "original": message,
                        "to_channel": route["to"]
                    },
                    source="router"
                ))
