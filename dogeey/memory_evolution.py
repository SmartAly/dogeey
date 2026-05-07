"""
Memory Evolution System - 记忆进化系统
从字符串升级为带权重的对象，支持重要性、时间衰减、访问频率
"""

import sqlite3
import json
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class MemoryObject:
    """记忆对象 - 取代简单字符串"""
    id: Optional[int] = None
    content: str = ""
    category: str = "fact"  # fact, procedure, preference, episode, skill_reference
    created_at: datetime = None
    last_accessed: datetime = None
    access_count: int = 0
    weight: float = 1.0  # 综合权重（重要性 × 时间衰减 × 频率提升）
    importance: float = 1.0  # 重要性（0.0-2.0，由LLM或规则评估）
    decay_rate: float = 0.05  # 时间衰减率（每天衰减率）
    frequency_boost: float = 1.0  # 访问频率提升因子
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    embedding: Optional[List[float]] = None  # 可选：向量嵌入
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.last_accessed is None:
            self.last_accessed = self.created_at
    
    def update_weight(self):
        """更新综合权重（重要性 × 时间衰减 × 频率）"""
        # 时间衰减：exp(-decay_rate * days)
        days_since_access = (datetime.now() - self.last_accessed).total_seconds() / 86400
        time_decay = math.exp(-self.decay_rate * max(0, days_since_access))
        
        # 频率提升：log(access_count + 1)
        self.frequency_boost = 1.0 + math.log(self.access_count + 1) * 0.3
        
        # 综合权重
        self.weight = self.importance * time_decay * self.frequency_boost
        
        # 限制范围 [0.01, 10.0]
        self.weight = max(0.01, min(10.0, self.weight))
    
    def access(self):
        """访问记忆（更新访问时间和计数）"""
        self.last_accessed = datetime.now()
        self.access_count += 1
        self.update_weight()
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "access_count": self.access_count,
            "weight": round(self.weight, 4),
            "importance": self.importance,
            "decay_rate": self.decay_rate,
            "frequency_boost": round(self.frequency_boost, 4),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MemoryObject':
        """从字典创建"""
        import iso8601  # 简单解析
        
        def parse_dt(s):
            if not s:
                return datetime.now()
            try:
                return datetime.fromisoformat(s)
            except:
                return datetime.now()
        
        return cls(
            id=data.get("id"),
            content=data.get("content", ""),
            category=data.get("category", "fact"),
            created_at=parse_dt(data.get("created_at")),
            last_accessed=parse_dt(data.get("last_accessed")),
            access_count=data.get("access_count", 0),
            weight=data.get("weight", 1.0),
            importance=data.get("importance", 1.0),
            decay_rate=data.get("decay_rate", 0.05),
            frequency_boost=data.get("frequency_boost", 1.0),
            metadata=data.get("metadata", {})
        )


class MemoryEvolutionSystem:
    """记忆进化系统 - 管理MemoryObject的存储、检索、进化"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path.home() / ".dogeey" / "memories.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._readonly = False
        self._init_db()
        
        # 短期记忆（当前会话）
        self.short_term: List[MemoryObject] = []
        self.max_short_term = 10
    
    def _get_connection(self):
        """获取数据库连接"""
        if self._readonly:
            return None
        try:
            return sqlite3.connect(self.db_path)
        except Exception as e:
            print(f"⚠️ 数据库连接失败: {e}")
            self._readonly = True
            return None
    
    def _init_db(self):
        """初始化数据库表（简化版-无FTS）+ 自动迁移"""
        conn = self._get_connection()
        if conn is None:
            return
        
        try:
            # 创建表（如果不存在）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'fact',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 0,
                    weight REAL DEFAULT 1.0,
                    importance REAL DEFAULT 1.0,
                    decay_rate REAL DEFAULT 0.05,
                    frequency_boost REAL DEFAULT 1.0,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            
            # 执行数据库迁移（添加缺失的列）
            self._migrate_db(conn)
            
            # 创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_weight ON memories(weight DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_last_accessed ON memories(last_accessed DESC)")
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 记忆数据库初始化失败: {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
    
    def _migrate_db(self, conn):
        """
        数据库迁移：添加缺失的列（向后兼容）
        检测表中缺少的列，用ALTER TABLE添加
        """
        try:
            # 获取当前表的列信息
            cursor = conn.execute("PRAGMA table_info(memories)")
            existing_columns = {row[1] for row in cursor.fetchall()}
            
            # 定义需要的列及其定义
            required_columns = {
                "importance": "REAL DEFAULT 1.0",
                "decay_rate": "REAL DEFAULT 0.05",
                "frequency_boost": "REAL DEFAULT 1.0",
                "metadata": "TEXT DEFAULT '{}'"
            }
            
            # 检查并添加缺失的列
            for col_name, col_def in required_columns.items():
                if col_name not in existing_columns:
                    try:
                        conn.execute(f"ALTER TABLE memories ADD COLUMN {col_name} {col_def}")
                        print(f"✅ 迁移: 添加列 {col_name}")
                    except Exception as e:
                        print(f"⚠️ 迁移失败 {col_name}: {e}")
            
            conn.commit()
        except Exception as e:
            print(f"⚠️ 数据库迁移失败: {e}")
    
    def add_long_term(self, content: str, 
                     category: str = "fact",
                     importance: float = 1.0,
                     metadata: Optional[Dict] = None) -> Optional[int]:
        """添加长期记忆（返回memory_id）"""
        if self._readonly:
            return None
        
        conn = self._get_connection()
        if conn is None:
            return None
        
        try:
            now = datetime.now().isoformat()
            cursor = conn.execute("""
                INSERT INTO memories 
                (content, category, created_at, last_accessed, importance, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (content, category, now, now, importance, json.dumps(metadata or {})))
            
            memory_id = cursor.lastrowid
            # 注意：已删除FTS同步代码，只用LIKE搜索
            
            conn.commit()
            conn.close()
            return memory_id
        except Exception as e:
            print(f"⚠️ 添加长期记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return None
    
    def search_memories(self, query: str, limit: int = 5) -> List[MemoryObject]:
        """搜索相关记忆（按权重排序，使用LIKE）"""
        self._update_all_weights()
        
        conn = self._get_connection()
        if conn is None:
            return []
        
        try:
            # 只用LIKE搜索（最可靠）
            like_pattern = f"%{query}%"
            cursor = conn.execute("""
                SELECT id, content, category, created_at,
                       last_accessed, access_count, weight,
                       importance, decay_rate, frequency_boost, metadata
                FROM memories
                WHERE content LIKE ?
                ORDER BY weight DESC, last_accessed DESC
                LIMIT ?
            """, (like_pattern, limit))
            
            results = self._rows_to_objects(cursor.fetchall())
            
            # 更新访问
            for mem in results:
                self._update_access(mem.id)
            
            conn.close()
            return results
        except Exception as e:
            print(f"⚠️ 搜索记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return []
    
    def _rows_to_objects(self, rows: List[Tuple]) -> List[MemoryObject]:
        """将数据库行转换为MemoryObject列表"""
        results = []
        for row in rows:
            mem = MemoryObject(
                id=row[0],
                content=row[1],
                category=row[2],
                created_at=datetime.fromisoformat(row[3]) if row[3] else datetime.now(),
                last_accessed=datetime.fromisoformat(row[4]) if row[4] else datetime.now(),
                access_count=row[5],
                weight=row[6],
                importance=row[7],
                decay_rate=row[8],
                frequency_boost=row[9],
                metadata=json.loads(row[10]) if row[10] else {}
            )
            results.append(mem)
        return results
    
    def get_all_memories(self, limit: int = 50) -> List[MemoryObject]:
        """获取所有记忆（按权重排序）"""
        self._update_all_weights()
        
        conn = self._get_connection()
        if conn is None:
            return []
        
        try:
            cursor = conn.execute("""
                SELECT id, content, category, created_at,
                       last_accessed, access_count, weight,
                       importance, decay_rate, frequency_boost, metadata
                FROM memories
                ORDER BY weight DESC, last_accessed DESC
                LIMIT ?
            """, (limit,))
            
            results = self._rows_to_objects(cursor.fetchall())
            conn.close()
            return results
        except Exception as e:
            print(f"⚠️ 获取记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return []
    
    def _update_all_weights(self):
        """更新所有记忆的权重（时间衰减 + 频率提升）"""
        if self._readonly:
            return
        
        conn = self._get_connection()
        if conn is None:
            return
        
        try:
            cursor = conn.execute("""
                SELECT id, last_accessed, access_count, importance, decay_rate 
                FROM memories
            """)
            
            now = datetime.now()
            for row in cursor.fetchall():
                memory_id = row[0]
                last_accessed_str = row[1]
                access_count = row[2]
                importance = row[3]
                decay_rate = row[4]
                
                try:
                    last_accessed = datetime.fromisoformat(last_accessed_str)
                except:
                    last_accessed = now
                
                days_since_access = (now - last_accessed).total_seconds() / 86400
                time_decay = math.exp(-decay_rate * max(0, days_since_access))
                frequency_boost = 1.0 + math.log(access_count + 1) * 0.3
                new_weight = importance * time_decay * frequency_boost
                new_weight = max(0.01, min(10.0, new_weight))
                
                conn.execute("""
                    UPDATE memories SET weight = ? 
                    WHERE id = ?
                """, (new_weight, memory_id))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 更新记忆权重失败: {e}")
            try:
                conn.close()
            except:
                pass
    
    def _update_access(self, memory_id: int):
        """更新记忆的访问信息"""
        if self._readonly:
            return
        
        conn = self._get_connection()
        if conn is None:
            return
        
        try:
            conn.execute("""
                UPDATE memories 
                SET last_accessed = CURRENT_TIMESTAMP, 
                    access_count = access_count + 1
                WHERE id = ?
            """, (memory_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ 更新记忆访问信息失败: {e}")
            try:
                conn.close()
            except:
                pass
    
    def delete_memory(self, memory_id: int) -> bool:
        """删除指定记忆"""
        if self._readonly:
            return False
        
        conn = self._get_connection()
        if conn is None:
            return False
        
        try:
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"⚠️ 删除记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return False
    
    def cleanup_old_memories(self, days: int = 180, min_weight: float = 0.1):
        """清理很久未访问且权重低的记忆"""
        if self._readonly:
            return 0
        
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
        
        conn = self._get_connection()
        if conn is None:
            return 0
        
        try:
            cursor = conn.execute("""
                DELETE FROM memories 
                WHERE last_accessed < ? AND weight < ?
            """, (cutoff_date, min_weight))
            
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            return deleted_count
        except Exception as e:
            print(f"⚠️ 清理旧记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return 0
    
    # ========== 短期记忆（会话级）==========
    
    def add_short_term(self, role: str, content: str, 
                       importance: float = 1.0) -> MemoryObject:
        """添加短期记忆（当前会话）"""
        mem = MemoryObject(
            content=f"{role}: {content}",
            category="episode",
            importance=importance,
            metadata={"role": role, "timestamp": datetime.now().isoformat()}
        )
        self.short_term.append(mem)
        
        if len(self.short_term) > self.max_short_term:
            self.short_term.pop(0)
        
        return mem
    
    def get_short_term_context(self) -> str:
        """获取短期记忆上下文（用于提示词）"""
        if not self.short_term:
            return ""
        
        context = "短期记忆（当前会话）:\n"
        for mem in self.short_term[-5:]:
            context += f"{mem.content}\n"
        return context
    
    def clear_short_term(self):
        """清除短期记忆"""
        self.short_term = []
    
    def consolidate_memories(self) -> int:
        """巩固记忆：将重要的短期记忆转为长期记忆"""
        consolidated = 0
        for mem in self.short_term:
            # 如果重要性高或访问次数多，转为长期
            if mem.importance >= 1.5 or mem.access_count > 3:
                self.add_long_term(
                    content=mem.content,
                    category=mem.category,
                    importance=mem.importance,
                    metadata=mem.metadata
                )
                consolidated += 1
        
        return consolidated


# 导出
__all__ = ['MemoryObject', 'MemoryEvolutionSystem']
