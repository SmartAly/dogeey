"""
轻量级事件总线 - 解耦Channel和Agent
"""
from typing import Dict, List, Callable, Any
from dataclasses import dataclass
import asyncio
from loguru import logger


@dataclass
class Event:
    """事件模型"""
    type: str  # "message.received", "message.reply", etc.
    data: Any
    source: str  # channel name


class EventBus:
    """轻量级事件总线 - 解耦Channel和Agent"""
    
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._middleware: List[Callable] = []
    
    def subscribe(self, event_type: str, handler: Callable):
        """
        订阅事件
        
        Args:
            event_type: 事件类型，如 "message.received"
            handler: 异步处理函数 async def handler(event: Event)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(f"订阅事件: {event_type}")
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """取消订阅"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(handler)
                logger.debug(f"取消订阅: {event_type}")
            except ValueError:
                pass
    
    def use(self, middleware: Callable):
        """
        添加中间件（用于日志、监控等）
        
        Args:
            middleware: async def middleware(event: Event, next)
        """
        self._middleware.append(middleware)
    
    async def publish(self, event: Event):
        """
        发布事件 - 异步通知所有订阅者
        
        Args:
            event: 事件对象
        """
        # 执行中间件链
        async def next_middleware(index: int):
            if index < len(self._middleware):
                await self._middleware[index](event, lambda: next_middleware(index + 1))
            else:
                # 执行所有订阅者
                if event.type in self._subscribers:
                    tasks = []
                    for handler in self._subscribers[event.type]:
                        tasks.append(handler(event))
                    
                    # 并发执行所有处理器
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # 检查异常
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"事件处理器异常: {result}")
        
        await next_middleware(0)
        logger.debug(f"事件已发布: {event.type} from {event.source}")
