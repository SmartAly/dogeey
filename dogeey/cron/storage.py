"""
Cron Storage - SQLite持久化存储
断电不丢任务，重启自动恢复
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


class CronStorage:
    """SQLite存储 - 任务持久化"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = Path.home() / ".dogeey" / "cron.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
    
    def _get_connection(self):
        """获取数据库连接"""
        return sqlite3.connect(str(self.db_path))
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    schedule_type TEXT NOT NULL,  -- 'date', 'interval', 'cron'
                    schedule_config TEXT NOT NULL,  -- JSON config
                    prompt TEXT NOT NULL,
                    skills TEXT,  -- JSON array
                    deliver TEXT,
                    model TEXT,
                    status TEXT DEFAULT 'active',  -- 'active', 'paused', 'completed'
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_run TEXT,
                    next_run TEXT,
                    run_count INTEGER DEFAULT 0,
                    max_runs INTEGER,  -- NULL means infinite
                    timeout INTEGER DEFAULT 300,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,  -- 'running', 'success', 'failed', 'timeout'
                    result TEXT,
                    error_msg TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                )
            """)
            
            # 创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_job_id ON job_runs(job_id)")
            
            conn.commit()
    
    def add_job(self, job_data: Dict) -> str:
        """添加任务"""
        job_id = job_data.get("id") or self._generate_id()
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO jobs (
                    id, name, schedule_type, schedule_config, prompt, skills,
                    deliver, model, status, created_at, updated_at,
                    next_run, timeout, max_retries
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
            """, (
                job_id,
                job_data.get("name"),
                job_data["schedule_type"],
                json.dumps(job_data["schedule_config"]),
                job_data["prompt"],
                json.dumps(job_data.get("skills", [])),
                job_data.get("deliver", "origin"),
                job_data.get("model"),
                now,
                now,
                job_data.get("next_run"),
                job_data.get("timeout", 300),
                job_data.get("max_retries", 3)
            ))
            conn.commit()
        
        return job_id
    
    def update_job(self, job_id: str, updates: Dict):
        """更新任务"""
        now = datetime.now().isoformat()
        updates["updated_at"] = now
        
        set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [job_id]
        
        with self._get_connection() as conn:
            conn.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", values)
            conn.commit()
    
    def get_job(self, job_id: str) -> Optional[Dict]:
        """获取单个任务"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            
            if row:
                return self._row_to_dict(row)
        return None
    
    def get_all_jobs(self, status: str = None) -> List[Dict]:
        """获取所有任务"""
        query = "SELECT * FROM jobs"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_dict(row) for row in rows]
    
    def delete_job(self, job_id: str):
        """删除任务"""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
    
    def add_job_run(self, job_id: str, status: str, result: str = None, error_msg: str = None) -> int:
        """记录任务执行"""
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO job_runs (job_id, started_at, status, result, error_msg)
                VALUES (?, ?, ?, ?, ?)
            """, (job_id, now, status, result, error_msg))
            
            conn.execute("""
                UPDATE jobs 
                SET last_run = ?, run_count = run_count + 1, updated_at = ?
                WHERE id = ?
            """, (now, now, job_id))
            
            conn.commit()
            return cursor.lastrowid
    
    def update_job_run(self, run_id: int, status: str, result: str = None, error_msg: str = None):
        """更新任务执行记录"""
        now = datetime.now().isoformat()
        
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE job_runs 
                SET completed_at = ?, status = ?, result = ?, error_msg = ?
                WHERE id = ?
            """, (now, status, result, error_msg, run_id))
            conn.commit()
    
    def get_job_runs(self, job_id: str, limit: int = 10) -> List[Dict]:
        """获取任务的执行历史"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM job_runs 
                WHERE job_id = ? 
                ORDER BY started_at DESC 
                LIMIT ?
            """, (job_id, limit))
            rows = cursor.fetchall()
            
            return [dict(row) for row in rows]
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        import uuid
        return str(uuid.uuid4())
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """将数据库行转换为字典"""
        data = dict(row)
        
        # 解析JSON字段
        for field in ['schedule_config', 'skills']:
            if data.get(field):
                try:
                    data[field] = json.loads(data[field])
                except:
                    pass
        
        return data
