"""
配置文件热重载模块 - 暂时禁用
watchdog不可用，热重载功能已禁用
"""
import asyncio
from pathlib import Path
from typing import Callable, Dict, Any
from loguru import logger

logger.warning("ConfigWatcher已禁用，热重载功能不可用")

class ConfigWatcher:
    """配置监听器 - 占位符"""
    
    def __init__(self, config_path: Path, callback: Callable):
        self.config_path = config_path
        self.callback = callback
        logger.warning("ConfigWatcher已禁用，不会监听配置变化")
    
    def start(self):
        """启动监听（空操作）"""
        pass
    
    def stop(self):
        """停止监听（空操作）"""
        pass
    
    @property
    def is_running(self) -> bool:
        return False


async def reload_channels(event_bus, channel_manager):
    """重新加载频道配置（占位符）"""
    logger.warning("热重载功能已禁用")
    pass
