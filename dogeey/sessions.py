"""
多会话管理模块
支持创建、切换、删除、列出多个对话会话
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


class ConversationSession:
    """单个对话会话"""
    
    def __init__(self, session_id: str = None, title: str = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.title = title or f"会话 {self.session_id}"
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.short_term_memory = []  # 对话历史：[{"user": ..., "assistant": ...}, ...]
        self.metadata = {}  # 额外元数据
        
    def add_message(self, user_input: str, assistant_response: str):
        """添加一条对话记录"""
        self.short_term_memory.append({
            "user": user_input,
            "assistant": assistant_response
        })
        # 限制历史长度
        if len(self.short_term_memory) > 20:
            self.short_term_memory.pop(0)
        self.updated_at = datetime.now().isoformat()
    
    def clear(self):
        """清空对话历史"""
        self.short_term_memory = []
        self.updated_at = datetime.now().isoformat()
    
    def get_info(self) -> Dict:
        """获取会话信息"""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.short_term_memory),
            "preview": self.short_term_memory[-1]["user"][:50] if self.short_term_memory else ""
        }
    
    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "short_term_memory": self.short_term_memory,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ConversationSession':
        """从字典恢复"""
        session = cls(
            session_id=data.get("session_id"),
            title=data.get("title")
        )
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.updated_at)
        session.short_term_memory = data.get("short_term_memory", [])
        session.metadata = data.get("metadata", {})
        return session


class SessionManager:
    """会话管理器"""
    
    def __init__(self, storage_path: str = "~/.dogeey/sessions.json"):
        self.storage_path = Path(storage_path).expanduser()
        self.sessions: Dict[str, ConversationSession] = {}
        self.current_session_id: Optional[str] = None
        self._load()
        
        # 如果没有会话，创建一个默认的
        if not self.sessions:
            self.create_session("默认会话")
    
    def _load(self):
        """从文件加载会话"""
        try:
            if self.storage_path.exists():
                with open(self.storage_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for session_data in data.get("sessions", []):
                        session = ConversationSession.from_dict(session_data)
                        self.sessions[session.session_id] = session
                    self.current_session_id = data.get("current_session_id")
        except Exception as e:
            print(f"⚠️ 加载会话失败: {e}")
    
    def _save(self):
        """保存会话到文件"""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "sessions": [s.to_dict() for s in self.sessions.values()],
                "current_session_id": self.current_session_id
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存会话失败: {e}")
    
    def create_session(self, title: str = None) -> ConversationSession:
        """创建新会话"""
        session = ConversationSession(title=title)
        self.sessions[session.session_id] = session
        self.current_session_id = session.session_id
        self._save()
        return session
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """获取指定会话"""
        return self.sessions.get(session_id)
    
    def get_current_session(self) -> Optional[ConversationSession]:
        """获取当前会话"""
        if self.current_session_id:
            return self.sessions.get(self.current_session_id)
        return None
    
    def switch_session(self, session_id: str) -> bool:
        """切换到指定会话"""
        if session_id in self.sessions:
            self.current_session_id = session_id
            self._save()
            return True
        return False
    
    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        if session_id not in self.sessions:
            return False
        
        # 不能删除最后一个会话
        if len(self.sessions) <= 1:
            return False
        
        del self.sessions[session_id]
        
        # 如果删除的是当前会话，切换到另一个
        if self.current_session_id == session_id:
            self.current_session_id = next(iter(self.sessions.keys()))
        
        self._save()
        return True
    
    def rename_session(self, session_id: str, new_title: str) -> bool:
        """重命名会话"""
        session = self.sessions.get(session_id)
        if not session:
            return False
        session.title = new_title
        session.updated_at = datetime.now().isoformat()
        self._save()
        return True
    
    def list_sessions(self) -> List[Dict]:
        """列出所有会话（按更新时间倒序）"""
        sessions = sorted(
            self.sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )
        return [s.get_info() for s in sessions]
    
    def clear_current_session(self):
        """清空当前会话的历史"""
        session = self.get_current_session()
        if session:
            session.clear()
            self._save()
    
    def get_current_memory(self) -> List[Dict]:
        """获取当前会话的对话历史"""
        session = self.get_current_session()
        if session:
            return session.short_term_memory
        return []
    
    def add_to_current_session(self, user_input: str, assistant_response: str):
        """添加对话到当前会话"""
        session = self.get_current_session()
        if session:
            session.add_message(user_input, assistant_response)
            self._save()
