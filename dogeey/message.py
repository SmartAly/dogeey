"""
统一消息模型 - 所有频道转换成此格式
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional


class MessageType(Enum):
    """消息类型"""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    EVENT = "event"


@dataclass
class Message:
    """统一消息格式 - 所有Channel转换成此格式"""
    id: str
    channel: str          # "feishu", "discord", etc.
    user_id: str
    username: str
    text: str
    type: MessageType = MessageType.TEXT
    metadata: Dict[str, Any] = field(default_factory=dict)  # 原始平台数据
    reply_token: Optional[str] = None  # 用于回复
    
    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            "id": self.id,
            "channel": self.channel,
            "user_id": self.user_id,
            "username": self.username,
            "text": self.text,
            "type": self.type.value,
            "metadata": self.metadata,
            "reply_token": self.reply_token
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """从字典创建"""
        return cls(
            id=data["id"],
            channel=data["channel"],
            user_id=data["user_id"],
            username=data["username"],
            text=data["text"],
            type=MessageType(data.get("type", "text")),
            metadata=data.get("metadata", {}),
            reply_token=data.get("reply_token")
        )
