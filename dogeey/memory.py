"""
记忆系统 - 短期记忆 + 长期记忆（SQLite）
支持时间衰减和访问频率权重
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import math


class MemorySystem:
    """记忆系统管理类"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self._readonly = False

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            print(f"⚠️ 无法创建记忆数据库目录: {e}")
            self._readonly = True

        self._init_db()

        self.short_term: List[Dict] = []
        self.max_short_term = 10

    def _safe_connect(self):
        """安全连接数据库，失败时设置readonly并返回None"""
        if self._readonly:
            return None
        try:
            return sqlite3.connect(self.db_path)
        except (sqlite3.OperationalError, PermissionError, OSError) as e:
            print(f"⚠️ 数据库连接失败: {e}")
            self._readonly = True
            return None
        except Exception as e:
            print(f"⚠️ 数据库连接异常: {e}")
            self._readonly = True
            return None

    def _init_db(self):
        """初始化数据库表"""
        conn = self._safe_connect()
        if conn is None:
            return
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'fact',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 0,
                    weight REAL DEFAULT 1.0,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts 
                USING fts5(content, content=memories, content_rowid=id)
            """)
            
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            print(f"⚠️ 记忆数据库初始化失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
        except Exception as e:
            print(f"⚠️ 记忆数据库初始化失败: {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
    
    def add_long_term(self, content: str, category: str = 'fact', 
                      metadata: Optional[Dict] = None) -> int:
        """添加长期记忆"""
        if self._readonly:
            return -1

        conn = self._safe_connect()
        if conn is None:
            return -1

        try:
            cursor = conn.execute(
                """INSERT INTO memories (content, category, metadata, created_at, last_accessed)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (content, category, json.dumps(metadata or {}))
            )
            
            memory_id = cursor.lastrowid
            
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO memories_fts (rowid, content) VALUES (?, ?)",
                    (memory_id, content)
                )
            except Exception as e:
                print(f"⚠️ FTS同步失败: {e}")
            
            conn.commit()
            conn.close()
            return memory_id
        except sqlite3.OperationalError as e:
            print(f"⚠️ 添加长期记忆失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
            return -1
        except Exception as e:
            print(f"⚠️ 添加长期记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return -1
    
    def search_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """搜索相关记忆（按权重排序）"""
        self._update_all_weights()
        
        conn = self._safe_connect()
        if conn is None:
            return []

        try:
            try:
                safe_query = query.replace('"', '""')
                fts_query = f'"{safe_query}"'
                
                cursor = conn.execute("""
                    SELECT m.id, m.content, m.category, m.created_at, 
                           m.last_accessed, m.access_count, m.weight, m.metadata
                    FROM memories m
                    JOIN memories_fts f ON m.id = f.rowid
                    WHERE memories_fts MATCH ?
                    ORDER BY m.weight DESC, m.last_accessed DESC
                    LIMIT ?
                """, (fts_query, limit))
                
                results = []
                for row in cursor.fetchall():
                    memory = {
                        'id': row[0],
                        'content': row[1],
                        'category': row[2],
                        'created_at': row[3],
                        'last_accessed': row[4],
                        'access_count': row[5],
                        'weight': row[6],
                        'metadata': json.loads(row[7])
                    }
                    results.append(memory)
                
                for r in results:
                    self._update_access(r['id'])
                
                conn.close()
                return results
            except Exception as e:
                print(f"⚠️ FTS搜索失败，使用LIKE: {e}")
                like_pattern = f"%{query}%"
                cursor = conn.execute("""
                    SELECT id, content, category, created_at, 
                           last_accessed, access_count, weight, metadata
                    FROM memories
                    WHERE content LIKE ?
                    ORDER BY weight DESC, last_accessed DESC
                    LIMIT ?
                """, (like_pattern, limit))
                
                results = []
                for row in cursor.fetchall():
                    memory = {
                        'id': row[0],
                        'content': row[1],
                        'category': row[2],
                        'created_at': row[3],
                        'last_accessed': row[4],
                        'access_count': row[5],
                        'weight': row[6],
                        'metadata': json.loads(row[7])
                    }
                    results.append(memory)
                
                for r in results:
                    self._update_access(r['id'])
                
                conn.close()
                return results
        except Exception as e:
            print(f"⚠️ 搜索记忆失败: {e}")
            try:
                conn.close()
            except:
                pass
            return []
    
    def get_all_memories(self, limit: int = 50) -> List[Dict]:
        """获取所有记忆（按权重排序）"""
        self._update_all_weights()
        
        conn = self._safe_connect()
        if conn is None:
            return []

        try:
            cursor = conn.execute("""
                SELECT id, content, category, created_at, last_accessed, 
                       access_count, weight, metadata
                FROM memories
                ORDER BY weight DESC, last_accessed DESC
                LIMIT ?
            """, (limit,))
            
            results = [
                {
                    'id': row[0],
                    'content': row[1],
                    'category': row[2],
                    'created_at': row[3],
                    'last_accessed': row[4],
                    'access_count': row[5],
                    'weight': row[6],
                    'metadata': json.loads(row[7])
                }
                for row in cursor.fetchall()
            ]
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

        conn = self._safe_connect()
        if conn is None:
            return

        try:
            cursor = conn.execute("SELECT id, last_accessed, access_count FROM memories")
            
            for row in cursor.fetchall():
                memory_id, last_accessed_str, access_count = row
                
                try:
                    last_accessed = datetime.fromisoformat(last_accessed_str)
                except:
                    last_accessed = datetime.now()
                
                days_since_access = (datetime.now() - last_accessed).days
                decay_rate = 0.1
                time_decay = math.exp(-decay_rate * days_since_access)
                
                frequency_boost = math.log(access_count + 1)
                
                base_weight = 1.0
                
                new_weight = base_weight * time_decay * (1 + frequency_boost * 0.3)
                
                conn.execute(
                    "UPDATE memories SET weight = ? WHERE id = ?",
                    (new_weight, memory_id)
                )
            
            conn.commit()
            conn.close()
        except sqlite3.OperationalError as e:
            print(f"⚠️ 更新记忆权重失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
    
    def _update_access(self, memory_id: int):
        """更新记忆的访问信息"""
        if self._readonly:
            return

        conn = self._safe_connect()
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
        except sqlite3.OperationalError as e:
            print(f"⚠️ 更新记忆访问信息失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
    
    def delete_memory(self, memory_id: int) -> bool:
        """删除指定记忆"""
        if self._readonly:
            return False

        conn = self._safe_connect()
        if conn is None:
            return False

        try:
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except sqlite3.OperationalError as e:
            print(f"⚠️ 删除记忆失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
            return False
    
    def clear_short_term(self):
        """清除短期记忆"""
        self.short_term = []
    
    def add_short_term(self, role: str, content: str):
        """添加短期记忆（当前会话）"""
        self.short_term.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        
        if len(self.short_term) > self.max_short_term:
            self.short_term.pop(0)
    
    def get_short_term_context(self) -> str:
        """获取短期记忆上下文（用于提示词）"""
        if not self.short_term:
            return ""
        
        context = "短期记忆（当前会话）:\n"
        for item in self.short_term[-5:]:
            context += f"{item['role']}: {item['content']}\n"
        return context
    
    def cleanup_old_memories(self, days: int = 180):
        """清理很久未访问的记忆"""
        if self._readonly:
            return 0

        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        conn = self._safe_connect()
        if conn is None:
            return 0

        try:
            cursor = conn.execute("""
                DELETE FROM memories 
                WHERE last_accessed < ? AND weight < 0.1
            """, (cutoff_date,))
            
            deleted_count = cursor.rowcount
            
            conn.commit()
            conn.close()
            
            return deleted_count
        except sqlite3.OperationalError as e:
            print(f"⚠️ 清理旧记忆失败 (只读): {e}")
            self._readonly = True
            try:
                conn.close()
            except:
                pass
            return 0
