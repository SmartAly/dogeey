"""
Cron Scheduler - 工业级调度器（基于APScheduler）
比OpenClaw靠谱10倍：精确调度、防并发、自动重试、持久化
"""

import sys
import time
import signal
import logging
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

# 添加项目根目录到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from dogeey.cron.storage import CronStorage
from dogeey.cron.lock import FileLock
from dogeey.cron.job import JobExecutor


# 配置日志（延迟初始化，避免模块导入时打开文件）
logger = logging.getLogger("dogeey.cron")
_logger_initialized = False

def _init_logger():
    """延迟初始化日志处理器"""
    global _logger_initialized
    if _logger_initialized:
        return
    _logger_initialized = True
    
    handlers = [logging.StreamHandler()]
    try:
        log_path = Path.home() / ".dogeey" / "cron.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path))
    except (PermissionError, OSError):
        pass  # 如果无法写入日志文件，仅使用控制台输出
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )


class APSchedulerCronScheduler:
    """基于APScheduler的工业级调度器（主力）
    
    优势：
    - 精确调度（秒级精度，不是60秒轮询）
    - 防并发（max_instances=1）
    - 自动合并（coalesce=True）
    - 错失容错（misfire_grace_time）
    - 完整Cron表达式支持
    """
    
    def __init__(self, check_interval=None, **kwargs):
        _init_logger()
        self.scheduler = BackgroundScheduler()
        self.storage = CronStorage()
        self.lock = FileLock()
        self.executor = JobExecutor(self.storage, self.lock)
        self._custom_executor = None  # 自定义执行器回调
        
        # 注册事件监听器
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)
    
    def set_job_executor(self, executor_func):
        """设置自定义任务执行器（由cli.py调用）"""
        self._custom_executor = executor_func
        logger.info("✅ 自定义任务执行器已设置")
    
    def _on_job_executed(self, event):
        """任务执行成功回调"""
        job_id = event.job_id
        logger.info(f"✅ Job executed successfully: {job_id}")
    
    def _on_job_error(self, event):
        """任务执行失败回调"""
        job_id = event.job_id
        exception = event.exception
        logger.error(f"❌ Job failed: {job_id} - {exception}")
    
    def _on_job_missed(self, event):
        """任务被跳过回调"""
        job_id = event.job_id
        logger.warning(f"⚠️ Job missed: {job_id}")
    
    def add_job_from_config(self, job_config: Dict) -> str:
        """从配置添加任务到APScheduler"""
        job_id = self.storage.add_job(job_config)
        job_data = self.storage.get_job(job_id)
        
        # 根据类型创建trigger
        trigger = self._create_trigger(job_data)
        
        # 添加任务到APScheduler
        self.scheduler.add_job(
            func=self._execute_job_wrapper,
            trigger=trigger,
            args=[job_id],
            id=job_id,
            name=job_data.get("name", job_id),
            max_instances=1,  # 防止并发执行
            coalesce=True,  # 合并错过的执行
            misfire_grace_time=60,  # 60秒内的错过执行仍会触发
            replace_existing=True  # 允许替换已存在的任务
        )
        
        logger.info(f"✅ Job added: {job_data.get('name', job_id)} (ID: {job_id})")
        return job_id
    
    def _create_trigger(self, job_data: Dict):
        """根据任务配置创建APScheduler触发器"""
        schedule_type = job_data["schedule_type"]
        config = job_data["schedule_config"]
        
        if schedule_type == "date":
            # 一次性任务
            run_date = config.get("run_date")
            if not run_date:
                run_date = datetime.now()
            else:
                # 验证日期字符串
                try:
                    # 尝试解析ISO格式日期
                    datetime.fromisoformat(run_date)
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ 无效日期字符串: {run_date}，使用当前时间")
                    run_date = datetime.now()
            return DateTrigger(run_date=run_date)
        
        elif schedule_type == "interval":
            # 间隔任务
            seconds = config.get("seconds", 3600)
            return IntervalTrigger(seconds=seconds)
        
        elif schedule_type == "cron":
            expression = config.get("expression", "")
            if expression:
                parts = expression.split()
                if len(parts) == 5:
                    return CronTrigger(
                        minute=parts[0],
                        hour=parts[1],
                        day=parts[2],
                        month=parts[3],
                        day_of_week=parts[4]
                    )
            return CronTrigger(
                minute=config.get("minute", "*"),
                hour=config.get("hour", "*"),
                day=config.get("day", "*"),
                month=config.get("month", "*"),
                day_of_week=config.get("day_of_week", "*")
            )
        
        else:
            raise ValueError(f"Unknown schedule type: {schedule_type}")
    
    def _execute_job_wrapper(self, job_id: str):
        """任务执行包装器（APScheduler调用）"""
        try:
            # 如果设置了自定义执行器，使用它
            if self._custom_executor:
                result = self._custom_executor(job_id)
            else:
                result = self.executor.execute_job_by_id(job_id)
            
            if result.get("success"):
                logger.info(f"✅ Job {job_id} completed successfully "
                          f"(duration: {result.get('duration', 0):.2f}s)")
            else:
                logger.warning(f"⚠️ Job {job_id} failed: {result.get('error', 'Unknown error')}")
        
        except Exception as e:
            logger.error(f"❌ Error executing job {job_id}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def start(self, blocking=False):
        """启动调度器
        
        Args:
            blocking: 是否阻塞当前线程（True=独立运行模式, False=后台运行模式）
        """
        self._setup_signal_handlers()
        
        logger.info("=" * 60)
        logger.info("dogeey Cron Scheduler (APScheduler) starting...")
        logger.info("=" * 60)
        
        # 从数据库加载所有active任务
        jobs = self.storage.get_all_jobs(status="active")
        logger.info(f"Loading {len(jobs)} active jobs...")
        
        for job_data in jobs:
            try:
                self._load_existing_job(job_data)
            except Exception as e:
                job_id = job_data.get('id', 'unknown')
                logger.error(f"Failed to load job {job_id}: {e}")
                try:
                    self.storage.delete_job(job_id)
                    logger.info(f"Deleted invalid job: {job_id}")
                except:
                    pass
        
        logger.info(f"Loaded {len(self.scheduler.get_jobs())} jobs")
        
        self.scheduler.start()
        logger.info("Scheduler is running...")
        
        if blocking:
            try:
                self.scheduler.block()
            except (KeyboardInterrupt, SystemExit):
                logger.info("Received shutdown signal")
            finally:
                self.shutdown()
    
    def _load_existing_job(self, job_data: Dict):
        """加载已有任务到APScheduler（不插入数据库）"""
        job_id = job_data["id"]
        
        # 创建触发器
        trigger = self._create_trigger(job_data)
        
        # 添加到APScheduler
        self.scheduler.add_job(
            func=self._execute_job_wrapper,
            trigger=trigger,
            args=[job_id],
            id=job_id,
            name=job_data.get("name", job_id),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
            replace_existing=True
        )
        
        logger.info(f"✅ Job loaded: {job_data.get('name', job_id)} (ID: {job_id})")
    
    def _setup_signal_handlers(self):
        """设置信号处理器（优雅退出）"""
        def signal_handler(sig, frame):
            logger.info(f"📨 Received signal {sig}, shutting down...")
            self.shutdown()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def shutdown(self):
        """停止调度器"""
        logger.info("🛑 Shutting down scheduler...")
        try:
            self.scheduler.shutdown(wait=False)
            logger.info("✅ Scheduler stopped")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
    
    def add_job(self, job_config: Dict) -> str:
        """添加任务（外部接口）"""
        return self.add_job_from_config(job_config)
    
    def list_jobs(self, status: str = None) -> List[Dict]:
        """列出任务"""
        return self.storage.get_all_jobs(status=status)
    
    def status(self) -> Dict:
        """获取调度器状态"""
        from datetime import datetime
        all_jobs = self.storage.get_all_jobs()
        active_jobs = self.storage.get_all_jobs(status="active")
        now = datetime.now().isoformat()
        
        return {
            "running": self.scheduler.running,
            "check_interval": getattr(self, '_check_interval', 60),
            "total_jobs": len(all_jobs),
            "enabled_jobs": len(active_jobs),
            "due_jobs": 0,
            "apscheduler_jobs": len(self.scheduler.get_jobs()),
        }
    
    def delete_job(self, job_id: str):
        """删除任务"""
        # 从APScheduler移除
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass  # 任务可能不在调度器中
        
        # 从数据库删除
        self.storage.delete_job(job_id)
        logger.info(f"🗑️ Job deleted: {job_id}")
    
    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """获取任务状态"""
        return self.storage.get_job(job_id)
    
    def run_job_manually(self, job_id: str) -> Dict:
        """手动执行任务（非调度）"""
        logger.info(f"🔧 Manual execution request: {job_id}")
        return self.executor.execute_job_by_id(job_id)


# 命令行接口
def main():
    """Cron调度器命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="dogeey Cron Scheduler (APScheduler)")
    parser.add_argument(
        "action",
        choices=["start", "run", "list", "delete", "status"],
        help="Action to perform"
    )
    parser.add_argument("--job-id", help="Job ID (for run/delete/status)")
    parser.add_argument("--config", help="Job config JSON file (for add)")
    
    args = parser.parse_args()
    
    scheduler = APSchedulerCronScheduler()
    
    if args.action == "start":
        scheduler.start()
    
    elif args.action == "run":
        if not args.job_id:
            print("❌ Error: --job-id required for 'run' action")
            return
        result = scheduler.run_job_manually(args.job_id)
        print(result)
    
    elif args.action == "list":
        jobs = scheduler.list_jobs()
        print(f"📋 Total jobs: {len(jobs)}")
        for job in jobs:
            print(f"\n--- Job: {job['name']} ---")
            print(f"  ID: {job['id']}")
            print(f"  Status: {job['status']}")
            print(f"  Type: {job['schedule_type']}")
            print(f"  Runs: {job['run_count']}")
            if job.get('next_run'):
                print(f"  Next run: {job['next_run']}")
    
    elif args.action == "delete":
        if not args.job_id:
            print("❌ Error: --job-id required for 'delete' action")
            return
        scheduler.delete_job(args.job_id)
        print(f"🗑️ Job {args.job_id} deleted")
    
    elif args.action == "status":
        if not args.job_id:
            print("❌ Error: --job-id required for 'status' action")
            return
        status = scheduler.get_job_status(args.job_id)
        if status:
            print(f"📊 Job Status: {status['name']}")
            print(f"  ID: {status['id']}")
            print(f"  Status: {status['status']}")
            print(f"  Type: {status['schedule_type']}")
            print(f"  Prompt: {status['prompt'][:50]}...")
            print(f"  Runs: {status['run_count']}")
            if status.get('last_run'):
                print(f"  Last run: {status['last_run']}")
        else:
            print(f"❌ Job {args.job_id} not found")


# 全局调度器实例
_scheduler_instance = None

def get_scheduler(check_interval=None, **kwargs) -> APSchedulerCronScheduler:
    """获取调度器单例"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = APSchedulerCronScheduler(check_interval=check_interval, **kwargs)
    return _scheduler_instance


if __name__ == "__main__":
    main()
