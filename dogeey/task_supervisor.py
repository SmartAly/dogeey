"""
任务监督系统 - 数据结构定义
TaskSupervisor 执行引擎已合并到 core.py
"""
import time
from enum import Enum
from typing import Optional, List, Dict, Any


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class ErrorType(Enum):
    """错误类型分类"""
    NONE = "none"
    PARSE_ERROR = "parse_error"
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    NO_ANSWER = "no_answer"
    TIMEOUT = "timeout"
    INVALID_ACTION = "invalid_action"
    USER_INTERRUPT = "user_interrupt"


class TaskResult:
    """任务执行结果"""
    def __init__(self, status: TaskStatus, answer: str = None,
                 error_type: ErrorType = ErrorType.NONE,
                 error_msg: str = None, steps: int = 0,
                 tool_calls: List[Dict] = None,
                 duration: float = None):
        self.status = status
        self.answer = answer
        self.error_type = error_type
        self.error_msg = error_msg
        self.steps = steps
        self.tool_calls = tool_calls or []
        self.duration = duration
        self.intermediate_steps = []

    def is_success(self) -> bool:
        return self.status == TaskStatus.SUCCESS

    def to_dict(self) -> Dict:
        return {
            "status": self.status.value,
            "answer": self.answer,
            "error_type": self.error_type.value if self.error_type else None,
            "error_msg": self.error_msg,
            "steps": self.steps,
            "tool_calls_count": len(self.tool_calls),
            "duration": self.duration
        }

    def __str__(self):
        duration_str = f", 耗时: {self.duration:.2f}秒" if self.duration else ""
        if self.is_success():
            return f"✅ 任务成功完成 (步骤: {self.steps}{duration_str})"
        else:
            return f"❌ 任务失败: {self.error_msg} (类型: {self.error_type.value})"


class RetryPolicy:
    """重试策略"""
    def __init__(self, max_retries: int = 2, retry_on_tool_error: bool = True):
        self.max_retries = max_retries
        self.retry_on_tool_error = retry_on_tool_error
        self._retry_counts = {}

    def should_retry(self, error_type: ErrorType, context: str = "") -> bool:
        if error_type == ErrorType.TOOL_ERROR and self.retry_on_tool_error:
            key = f"tool_{context}"
            count = self._retry_counts.get(key, 0)
            if count < self.max_retries:
                self._retry_counts[key] = count + 1
                return True
        return False

    def reset(self):
        self._retry_counts.clear()
