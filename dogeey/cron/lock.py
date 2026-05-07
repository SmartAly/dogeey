"""
File Lock - 防止多实例重复执行任务
跨平台：Linux/macOS用fcntl，Windows用msvcrt
"""

import os
import time
from pathlib import Path
from typing import Optional


class FileLock:
    """文件锁 - 进程级互斥"""
    
    def __init__(self, lock_dir: str = None):
        if lock_dir is None:
            lock_dir = Path.home() / ".dogeey" / "locks"
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = None
        self.file_handle = None
    
    def acquire(self, lock_name: str, timeout: int = 10) -> bool:
        """获取锁（带超时）
        
        Returns:
            True: 获取成功
            False: 获取失败（超时或被占用）
        """
        self.lock_file = self.lock_dir / f"{lock_name}.lock"
        lock_file_str = str(self.lock_file)
        
        # 尝试获取锁（最多timeout秒）
        for attempt in range(timeout * 10):  # 每0.1秒尝试一次
            try:
                if os.name == 'nt':  # Windows
                    import msvcrt
                    self.file_handle = open(lock_file_str, 'w')
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_RLCK, 1)
                else:  # Linux/macOS
                    import fcntl
                    self.file_handle = open(lock_file_str, 'w')
                    fcntl.flock(self.file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                
                # 写入进程信息
                self.file_handle.write(f"PID: {os.getpid()}\n")
                self.file_handle.flush()
                
                return True
            except (IOError, OSError):
                # 锁被占用
                if self.file_handle:
                    self.file_handle.close()
                    self.file_handle = None
                
                if attempt < timeout * 10 - 1:
                    time.sleep(0.1)
                else:
                    return False
        
        return False
    
    def release(self):
        """释放锁"""
        if self.file_handle:
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle, fcntl.LOCK_UN)
                
                self.file_handle.close()
            except Exception:
                pass
            
            self.file_handle = None
        
        # 删除锁文件
        if self.lock_file and self.lock_file.exists():
            try:
                self.lock_file.unlink()
            except Exception:
                pass
    
    def is_locked(self, lock_name: str) -> bool:
        """检查锁是否被占用"""
        lock_file = self.lock_dir / f"{lock_name}.lock"
        
        if not lock_file.exists():
            return False
        
        try:
            if os.name == 'nt':
                import msvcrt
                f = open(str(lock_file), 'w')
                msvcrt.locking(f.fileno(), msvcrt.LK_RLCK, 1)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.close()
            else:
                import fcntl
                f = open(str(lock_file), 'w')
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                f.close()
            
            # 如果能获取锁，说明没被占用
            return False
        except (IOError, OSError):
            # 获取不到锁，说明被占用
            return True
    
    def cleanup_stale_locks(self, max_age_minutes: int = 60):
        """清理过期锁（进程可能崩溃了）"""
        now = time.time()
        
        for lock_file in self.lock_dir.glob("*.lock"):
            try:
                # 检查文件修改时间
                mtime = lock_file.stat().st_mtime
                age_minutes = (now - mtime) / 60
                
                if age_minutes > max_age_minutes:
                    # 检查进程是否还活着
                    if os.name != 'nt':
                        try:
                            with open(lock_file, 'r') as f:
                                content = f.read()
                                if 'PID:' in content:
                                    pid = int(content.split('PID:')[1].strip())
                                    
                                    # 检查进程是否存在
                                    try:
                                        os.kill(pid, 0)  # 不真的杀进程，只是检查
                                    except ProcessLookupError:
                                        # 进程不存在，清理锁
                                        lock_file.unlink()
                                        print(f"Cleaned stale lock: {lock_file.name}")
                        except Exception:
                            pass
            except Exception:
                pass


# 上下文管理器
class LockContext:
    """锁上下文管理器"""
    
    def __init__(self, file_lock: FileLock, lock_name: str, timeout: int = 10):
        self.file_lock = file_lock
        self.lock_name = lock_name
        self.timeout = timeout
        self.acquired = False
    
    def __enter__(self):
        self.acquired = self.file_lock.acquire(self.lock_name, self.timeout)
        if not self.acquired:
            raise TimeoutError(f"Failed to acquire lock: {self.lock_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            self.file_lock.release()
            self.acquired = False
