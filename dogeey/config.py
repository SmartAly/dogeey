"""
配置管理系统
支持配置文件、环境变量、命令行参数三层配置
"""
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any


DEFAULT_CONFIG_DIR = Path.home() / ".dogeey"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


def get_default_config() -> Dict[str, Any]:
    """返回默认配置"""
    return {
        "version": "1.0.0",
        "llm": {
            "providers": [],
            "current_provider": None,
            "timeout": 60
        },
        "memory": {
            "db_path": str(DEFAULT_CONFIG_DIR / "data" / "memories.db"),
            "max_short_term": 10,
            "decay_rate": 0.1
        },
        "skills": {
            "path": str(DEFAULT_CONFIG_DIR / "skills"),
            "auto_learn": True
        },
        "webui": {
            "enabled": True,
            "port": 8080,
            "host": "127.0.0.1"
        },
        "tools": {
            "enabled": ["file_ops", "shell"],
            "disabled": []
        },
        "channels": {
            "webui": {
                "enabled": False,  # WebUI通过FastAPI直接运行，不走Channel系统
                "type": "builtin",
                "config": {}
            }
        },
        "channel_defaults": {
            "reply_in_channel": True,
            "user_mapping": {}
        }
    }


class Config:
    """配置管理类"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / "config.json"
        self._config = None
    
    def load(self) -> Dict[str, Any]:
        """加载配置（合并默认值、配置文件、环境变量）"""
        # 1. 默认配置
        config = get_default_config()
        
        # 2. 配置文件
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                self._deep_merge(config, file_config)
        
        # 3. 环境变量覆盖
        self._apply_env_overrides(config)
        
        self._config = config
        return config
    
    def save(self, config: Dict[str, Any] = None):
        """保存配置到文件"""
        config = config or self._config
        if config is None:
            raise ValueError("No config to save")

        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except PermissionError as e:
            import logging
            logging.getLogger(__name__).warning(
                f"无法写入配置文件 (权限不足): {self.config_file} — {e}"
            )
        except OSError as e:
            import logging
            logging.getLogger(__name__).warning(
                f"无法写入配置文件 (OS错误): {self.config_file} — {e}"
            )
    
    def get(self, key: str, default=None):
        """获取配置值（支持点号路径）"""
        if self._config is None:
            self.load()
        
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value):
        """设置配置值"""
        if self._config is None:
            self.load()
        
        keys = key.split('.')
        target = self._config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
    
    def _deep_merge(self, base: Dict, override: Dict):
        """深度合并两个字典"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value
    
    def _apply_env_overrides(self, config: Dict):
        """应用环境变量覆盖"""
        env_mapping = {
            "DOGEEY_API_KEY": "llm.providers.0.api_key",
            "DOGEEY_BASE_URL": "llm.providers.0.base_url",
            "DOGEEY_MODEL": "llm.providers.0.default_model",
            "DOGEEY_DATA_DIR": "memory.db_path",
        }
        
        for env_var, config_path in env_mapping.items():
            value = os.environ.get(env_var)
            if value:
                self._set_nested(config, config_path, value)
    
    def _set_nested(self, config: Dict, path: str, value):
        """设置嵌套字典值（支持列表索引，如 providers.0.api_key）"""
        keys = path.split('.')
        target = config
        
        for k in keys[:-1]:
            # 检查是否是列表索引（纯数字）
            if k.isdigit():
                idx = int(k)
                # 确保target是列表且长度足够
                if isinstance(target, list):
                    # 如果是列表但索引不够，扩展列表
                    while len(target) <= idx:
                        target.append({})
                    target = target[idx]
                else:
                    # 如果不是列表但用了数字索引，转为列表
                    # 这种情况不应该发生，但防御性编程
                    new_list = []
                    for i in range(idx + 1):
                        new_list.append({})
                    # 替换原target为列表
                    # 注意：这里需要更复杂的逻辑，暂时报错
                    raise ValueError(f"路径 {path} 试图用数字索引访问非列表对象")
            else:
                # 字典访问
                if k not in target:
                    target[k] = {}
                target = target[k]
        
        # 设置最终值（同样处理列表索引）
        last_key = keys[-1]
        if last_key.isdigit():
            idx = int(last_key)
            if isinstance(target, list):
                while len(target) <= idx:
                    target.append(None)
                target[idx] = value
            else:
                raise ValueError(f"路径 {path} 试图用数字索引访问非列表对象")
        else:
            target[last_key] = value
    
    def add_provider(self, name: str, api_key: str, base_url: str, models: list, default_model: str = None):
        """添加模型提供商"""
        if self._config is None:
            self.load()
        
        provider = {
            "name": name,
            "api_key": api_key,
            "base_url": base_url,
            "models": models,
            "default_model": default_model or models[0] if models else None
        }
        
        # 检查是否已存在
        for i, p in enumerate(self._config["llm"]["providers"]):
            if p["name"] == name:
                self._config["llm"]["providers"][i] = provider
                break
        else:
            self._config["llm"]["providers"].append(provider)
        
        if not self._config["llm"]["current_provider"]:
            self._config["llm"]["current_provider"] = name
    
    def get_current_provider(self) -> Optional[Dict]:
        """获取当前提供商配置"""
        if self._config is None:
            self.load()
        
        current = self._config["llm"]["current_provider"]
        for p in self._config["llm"]["providers"]:
            if p["name"] == current:
                return p
        return None


# 全局配置实例
config = Config()
