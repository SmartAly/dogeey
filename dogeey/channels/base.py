"""
Channel 插件标准接口 - 所有频道必须实现
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dogeey.message import Message


class Channel(ABC):
    """频道插件标准接口 - 所有频道必须实现"""
    
    def __init__(self):
        self.event_bus = None  # 事件总线引用，由ChannelManager设置
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        频道名称，如 'feishu', 'discord' 等
        必须与配置中的key一致
        """
        pass
    
    @abstractmethod
    async def configure(self, config: Dict[str, Any]) -> bool:
        """
        根据配置初始化频道
        
        Args:
            config: 该频道的配置字典
            
        Returns:
            是否初始化成功
        """
        pass
    
    @abstractmethod
    async def start(self) -> None:
        """
        启动频道监听（可以是阻塞或非阻塞）
        非阻塞实现应该在后台运行
        """
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """停止频道"""
        pass
    
    @abstractmethod
    async def send(self, message: Message) -> bool:
        """
        发送消息到该频道
        
        Args:
            message: 统一消息对象
            
        Returns:
            是否发送成功
        """
        pass
    
    @property
    @abstractmethod
    def is_running(self) -> bool:
        """频道是否正在运行"""
        pass
    
    async def health_check(self) -> Dict[str, Any]:
        """
        健康检查（可选实现）
        
        Returns:
            包含状态信息的字典
        """
        return {
            "name": self.name,
            "running": self.is_running,
            "configured": True
        }
