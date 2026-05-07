"""
配置驱动的频道管理器
"""
import importlib
import sys
from pathlib import Path
from typing import Dict, Type, Optional
from loguru import logger

from dogeey.channels.base import Channel
from dogeey.event_bus import EventBus


class ChannelManager:
    """配置驱动的频道管理器"""
    
    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.channels: Dict[str, Channel] = {}
        self._channel_classes: Dict[str, Type[Channel]] = {}
        
        # 自动发现内置频道
        self._discover_builtin_channels()
    
    def _discover_builtin_channels(self):
        """自动发现dogeey/channels/目录下的插件"""
        channels_dir = Path(__file__).parent
        
        # 扫描子目录
        for item in channels_dir.iterdir():
            if not item.is_dir():
                continue
            
            # 检查是否有channel.py
            channel_file = item / "channel.py"
            if not channel_file.exists():
                continue
            
            channel_name = item.name
            logger.info(f"发现频道插件: {channel_name}")
            
            try:
                # 动态导入
                module_path = f"dogeey.channels.{channel_name}.channel"
                module = importlib.import_module(module_path)
                
                # 查找Channel的子类
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and 
                        issubclass(attr, Channel) and 
                        attr != Channel):
                        self._channel_classes[channel_name] = attr
                        logger.info(f"  注册频道类: {attr_name}")
                        break
                else:
                    logger.warning(f"  {channel_name} 中未找到Channel实现")
                    
            except Exception as e:
                logger.error(f"加载频道 {channel_name} 失败: {e}")
    
    async def load_from_config(self) -> int:
        """
        根据config.json加载频道
        
        Returns:
            成功加载的频道数量
        """
        channels_config = self.config.get("channels", {})
        loaded_count = 0
        
        for name, cfg in channels_config.items():
            if not cfg.get("enabled", False):
                logger.info(f"频道 {name} 未启用，跳过")
                continue
            
            if name not in self._channel_classes:
                logger.warning(f"频道 {name} 未找到实现")
                continue
            
            # 实例化
            channel_class = self._channel_classes[name]
            try:
                channel = channel_class()
            except Exception as e:
                logger.error(f"实例化频道 {name} 失败: {e}")
                continue
            
            # 配置
            channel_config = cfg.get("config", {})
            try:
                success = await channel.configure(channel_config)
                if not success:
                    logger.error(f"频道 {name} 配置失败")
                    continue
            except Exception as e:
                logger.error(f"配置频道 {name} 异常: {e}")
                continue
            
            # 设置event_bus引用
            channel.event_bus = self.event_bus
            
            self.channels[name] = channel
            loaded_count += 1
            logger.info(f"频道 {name} 加载成功")
        
        return loaded_count
    
    async def start_all(self):
        """启动所有已加载的频道"""
        for name, channel in self.channels.items():
            try:
                await channel.start()
                logger.info(f"频道 {name} 已启动")
            except Exception as e:
                logger.error(f"启动频道 {name} 失败: {e}")
    
    async def stop_all(self):
        """停止所有频道"""
        for name, channel in self.channels.items():
            try:
                await channel.stop()
                logger.info(f"频道 {name} 已停止")
            except Exception as e:
                logger.error(f"停止频道 {name} 失败: {e}")
    
    def get_channel(self, name: str) -> Optional[Channel]:
        """获取指定频道"""
        return self.channels.get(name)
    
    async def list_channels(self) -> Dict[str, dict]:
        """列出所有频道状态（异步，支持协程health_check）"""
        result = {}
        for name, channel in self.channels.items():
            try:
                health = channel.health_check()
                if hasattr(health, '__await__'):
                    result[name] = await health
                else:
                    result[name] = health
            except Exception as e:
                result[name] = {
                    "name": name,
                    "running": False,
                    "error": str(e)
                }
        return result
