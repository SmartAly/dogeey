"""
Cron Job - 任务定义和执行器
支持超时、重试、详细日志
"""

import json
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path

# 添加项目根目录到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dogeey.cron.storage import CronStorage
from dogeey.cron.lock import FileLock, LockContext


class CronJob:
    """Cron任务 - 定义+执行"""
    
    def __init__(self, storage: CronStorage, lock: FileLock, job_data: Dict):
        self.storage = storage
        self.lock = lock
        self.data = job_data
        self.job_id = job_data["id"]
        self.name = job_data.get("name", self.job_id)
        
        # 解析配置
        self.schedule_type = job_data["schedule_type"]
        self.schedule_config = job_data["schedule_config"]
        self.prompt = job_data["prompt"]
        self.skills = job_data.get("skills", [])
        self.deliver = job_data.get("deliver", "origin")
        self.model = job_data.get("model")
        self.timeout = job_data.get("timeout", 300)
        self.max_retries = job_data.get("max_retries", 3)
        self.run_count = job_data.get("run_count", 0)
        self.max_runs = job_data.get("max_runs")
        self.next_run = job_data.get("next_run")
        self.status = job_data.get("status", "active")
    
    def should_run_now(self) -> bool:
        """判断任务是否该执行了"""
        if self.data["status"] != "active":
            return False
        
        next_run = self.data.get("next_run")
        if not next_run:
            return True
        
        try:
            next_time = datetime.fromisoformat(next_run)
            return datetime.now() >= next_time
        except Exception:
            return False
    
    def calculate_next_run(self) -> Optional[str]:
        """计算下次执行时间"""
        if self.max_runs and self.run_count >= self.max_runs:
            return None  # 不再执行
        
        now = datetime.now()
        
        if self.schedule_type == "date":
            # 一次性任务
            return None
        
        elif self.schedule_type == "interval":
            # 周期任务
            interval_seconds = self.schedule_config.get("seconds", 3600)
            return (now + timedelta(seconds=interval_seconds)).isoformat()
        
        elif self.schedule_type == "cron":
            # Cron表达式（简化版）
            # 格式: "30 9 * * *" (每天9:30)
            # 这里用简单实现，生产环境建议用croniter库
            cron_expr = self.schedule_config.get("expression", "0 * * * *")
            return self._parse_cron_next(cron_expr, now)
        
        return None
    
    def _parse_cron_next(self, cron_expr: str, now: datetime) -> str:
        """简化版cron解析（下次执行时间）
        支持标准5段格式: minute hour day month weekday
        """
        parts = cron_expr.split()
        if len(parts) != 5:
            return (now + timedelta(hours=1)).isoformat()
        
        minute_str, hour_str, day_str, month_str, weekday_str = parts
        
        next_time = now.replace(second=0, microsecond=0)
        
        try:
            if minute_str == "*":
                next_time += timedelta(minutes=1)
            else:
                target_minute = int(minute_str)
                if next_time.minute >= target_minute:
                    next_time = next_time.replace(minute=target_minute)
                    if hour_str == "*":
                        next_time += timedelta(hours=1)
                else:
                    next_time = next_time.replace(minute=target_minute)
        except ValueError:
            next_time += timedelta(minutes=1)
        
        try:
            if hour_str != "*":
                target_hour = int(hour_str)
                if next_time.hour > target_hour or (next_time.hour == target_hour and now.minute > int(minute_str) if minute_str != "*" else False):
                    next_time = next_time.replace(hour=target_hour, minute=int(minute_str) if minute_str != "*" else 0)
                    next_time += timedelta(days=1)
                else:
                    next_time = next_time.replace(hour=target_hour)
        except ValueError:
            pass
        
        try:
            if weekday_str != "*":
                target_weekday = int(weekday_str)
                current_weekday = next_time.weekday()
                if current_weekday > target_weekday:
                    days_ahead = 7 - current_weekday + target_weekday
                elif current_weekday < target_weekday:
                    days_ahead = target_weekday - current_weekday
                else:
                    if next_time <= now:
                        days_ahead = 7
                    else:
                        days_ahead = 0
                if days_ahead > 0:
                    next_time += timedelta(days=days_ahead)
        except ValueError:
            pass
        
        try:
            if day_str != "*":
                target_day = int(day_str)
                if next_time.day != target_day:
                    if next_time.day < target_day:
                        next_time = next_time.replace(day=target_day)
                    else:
                        if next_time.month == 12:
                            next_time = next_time.replace(year=next_time.year + 1, month=1, day=target_day)
                        else:
                            next_time = next_time.replace(month=next_time.month + 1, day=target_day)
        except ValueError:
            pass
        
        try:
            if month_str != "*":
                target_month = int(month_str)
                if next_time.month != target_month:
                    if next_time.month < target_month:
                        next_time = next_time.replace(month=target_month, day=1)
                    else:
                        next_time = next_time.replace(year=next_time.year + 1, month=target_month, day=1)
        except ValueError:
            pass
        
        return next_time.isoformat()
    
    def execute(self) -> Dict:
        """执行任务（带锁、超时、重试）"""
        lock_name = f"cron_job_{self.job_id}"
        
        # 1. 获取锁（防止重复执行）
        with LockContext(self.lock, lock_name, timeout=5) as ctx:
            if not ctx.acquired:
                return {
                    "success": False,
                    "error": f"Failed to acquire lock for job {self.name}"
                }
            
            # 2. 记录开始
            run_id = self.storage.add_job_run(
                job_id=self.job_id,
                status="running"
            )
            
            start_time = time.time()
            
            try:
                # 3. 执行（带超时）
                result = self._execute_with_timeout()
                
                # 4. 记录成功
                self.storage.update_job_run(
                    run_id=run_id,
                    status="success",
                    result=result[:1000] if result else None  # 限制长度
                )
                
                # 5. 更新任务状态
                updates = {}
                next_run = self.calculate_next_run()
                if next_run:
                    updates["next_run"] = next_run
                else:
                    updates["status"] = "completed"
                
                self.storage.update_job(self.job_id, updates)
                
                return {
                    "success": True,
                    "result": result,
                    "duration": time.time() - start_time
                }
            
            except Exception as e:
                # 记录失败
                error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
                
                self.storage.update_job_run(
                    run_id=run_id,
                    status="failed",
                    error_msg=error_msg[:1000]  # 限制长度
                )
                
                # 检查是否需要重试
                retry_count = self.data.get("retry_count", 0)
                if retry_count < self.max_retries:
                    # 更新重试计数
                    self.storage.update_job(self.job_id, {
                        "retry_count": retry_count + 1
                    })
                    
                    # 稍后重试（指数退避）
                    retry_delay = 2 ** retry_count  # 1, 2, 4, 8...
                    next_retry = (datetime.now() + timedelta(seconds=retry_delay)).isoformat()
                    self.storage.update_job(self.job_id, {
                        "next_run": next_retry
                    })
                    
                    return {
                        "success": False,
                        "error": f"Job failed, retrying in {retry_delay}s: {str(e)}",
                        "retry_count": retry_count + 1
                    }
                else:
                    # 重试次数用尽
                    return {
                        "success": False,
                        "error": f"Job failed after {self.max_retries} retries: {str(e)}"
                    }
    
    def _execute_with_timeout(self) -> str:
        """带超时的任务执行（简化版）"""
        # TODO: 这里应该调用dogeey的核心执行逻辑
        # 目前先返回模拟结果
        
        # 模拟任务执行
        time.sleep(1)  # 模拟耗时
        
        return f"Job '{self.name}' executed at {datetime.now().isoformat()}\nPrompt: {self.prompt}"
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return self.data.copy()


class JobExecutor:
    """任务执行器 - 批量执行"""
    
    def __init__(self, storage: CronStorage, lock: FileLock):
        self.storage = storage
        self.lock = lock
    
    def execute_due_jobs(self) -> List[Dict]:
        """执行所有到期的任务"""
        jobs_data = self.storage.get_all_jobs(status="active")
        results = []
        
        for job_data in jobs_data:
            job = CronJob(self.storage, self.lock, job_data)
            
            if job.should_run_now():
                print(f"Executing job: {job.name}")
                result = job.execute()
                results.append({
                    "job_id": job.job_id,
                    "name": job.name,
                    **result
                })
        
        return results
    
    def execute_job_by_id(self, job_id: str) -> Dict:
        """执行指定任务"""
        job_data = self.storage.get_job(job_id)
        
        if not job_data:
            return {
                "success": False,
                "error": f"Job not found: {job_id}"
            }
        
        job = CronJob(self.storage, self.lock, job_data)
        return job.execute()
