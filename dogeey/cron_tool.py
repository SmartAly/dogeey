"""
Cron定时任务工具 - 让dogeey支持定时任务
包装CronManager的API，提供工具接口
"""
import json
from typing import Optional, List, Dict

# 延迟导入，避免循环依赖
_cron_manager = None

def get_cron_manager():
    """获取CronManager实例（延迟导入）"""
    global _cron_manager
    if _cron_manager is None:
        from dogeey.cron.manager import get_cron_manager
        _cron_manager = get_cron_manager()
    return _cron_manager


def tool_cron_create(
    schedule: str,
    prompt: str,
    name: Optional[str] = None,
    deliver: str = "origin",
    model: Optional[str] = None,
    skills: Optional[str] = None,  # JSON字符串或逗号分隔
    max_retries: int = 3
) -> str:
    """
    创建定时任务
    
    Args:
        schedule: 时间计划
            - "30m" / "every 30 minutes" -> 每30分钟
            - "2h" / "every 2 hours" -> 每2小时
            - "0 9 * * *" -> 每天9点（cron表达式）
            - "2024-01-01 09:00" -> 指定时间（一次性）
        prompt: 任务提示词（给AI执行的指令）
        name: 任务名称（可选）
        deliver: 推送目标（origin/local/telegram/feishu等）
        model: 使用的模型（可选，默认当前模型）
        skills: 技能列表（JSON数组或逗号分隔字符串）
        max_retries: 最大重试次数
    
    Returns:
        任务创建结果
    """
    try:
        manager = get_cron_manager()
        
        # 解析skills
        skills_list = []
        if skills:
            try:
                # 尝试解析JSON
                skills_list = json.loads(skills)
            except:
                # 如果不是JSON，尝试逗号分隔
                skills_list = [s.strip() for s in skills.split(",") if s.strip()]
        
        # 创建任务
        job = manager.create_job(
            schedule=schedule,
            prompt=prompt,
            name=name,
            deliver=deliver,
            model=model,
            skills=skills_list,
            max_retries=max_retries
        )
        
        return json.dumps({
            "success": True,
            "message": f"定时任务已创建！",
            "job_id": job.job_id,
            "name": job.name,
            "schedule": schedule,
            "prompt": prompt,
            "deliver": deliver,
            "next_run": job.next_run
        }, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_list(include_disabled: bool = False) -> str:
    """
    列出所有定时任务
    
    Args:
        include_disabled: 是否包含已暂停的任务
    
    Returns:
        任务列表
    """
    try:
        manager = get_cron_manager()
        jobs = manager.list_jobs(include_disabled=include_disabled)
        
        if not jobs:
            return json.dumps({
                "success": True,
                "message": "当前没有定时任务",
                "jobs": []
            }, ensure_ascii=False)
        
        jobs_info = []
        for job in jobs:
            # 格式化schedule为人类可读格式
            schedule_display = job.schedule_type
            if job.schedule_type == "interval":
                seconds = job.schedule_config.get("seconds", 3600)
                if seconds < 60:
                    schedule_display = f"每{seconds}秒"
                elif seconds < 3600:
                    schedule_display = f"每{seconds//60}分钟"
                elif seconds < 86400:
                    schedule_display = f"每{seconds//3600}小时"
                else:
                    schedule_display = f"每{seconds//86400}天"
            elif job.schedule_type == "cron":
                cron_expr = job.schedule_config.get("expression", "")
                schedule_display = f"Cron: {cron_expr}"
            elif job.schedule_type == "date":
                run_date = job.schedule_config.get("run_date", "")
                schedule_display = f"一次性: {run_date}"
            
            # 从data中获取可能的额外字段
            last_run = job.data.get("last_run")
            next_run = job.data.get("next_run")
            
            jobs_info.append({
                "job_id": job.job_id,
                "name": job.name,
                "schedule": schedule_display,
                "schedule_type": job.schedule_type,
                "prompt": job.prompt[:100] + "..." if len(job.prompt) > 100 else job.prompt,
                "status": job.status,
                "next_run": next_run,
                "last_run": last_run,
                "run_count": job.run_count
            })
        
        return json.dumps({
            "success": True,
            "message": f"找到 {len(jobs)} 个定时任务",
            "jobs": jobs_info
        }, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_delete(job_id: str) -> str:
    """
    删除定时任务
    
    Args:
        job_id: 任务ID（支持模糊匹配前3位）
    
    Returns:
        删除结果
    """
    try:
        manager = get_cron_manager()
        
        # 先获取任务信息
        job = manager.get_job(job_id)
        if not job:
            return json.dumps({
                "success": False,
                "error": f"找不到任务: {job_id}"
            }, ensure_ascii=False)
        
        job_name = job.name
        full_job_id = job.job_id
        
        # 删除
        success = manager.delete_job(job_id)
        
        if success:
            return json.dumps({
                "success": True,
                "message": f"任务已删除: {job_name}",
                "job_id": full_job_id
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": "删除失败"
            }, ensure_ascii=False)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_pause(job_id: str) -> str:
    """
    暂停定时任务
    
    Args:
        job_id: 任务ID（支持模糊匹配前3位）
    
    Returns:
        暂停结果
    """
    try:
        manager = get_cron_manager()
        
        job = manager.get_job(job_id)
        if not job:
            return json.dumps({
                "success": False,
                "error": f"找不到任务: {job_id}"
            }, ensure_ascii=False)
        
        success = manager.pause_job(job_id)
        
        if success:
            return json.dumps({
                "success": True,
                "message": f"任务已暂停: {job.name}",
                "job_id": job.job_id
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": "暂停失败"
            }, ensure_ascii=False)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_resume(job_id: str) -> str:
    """
    恢复定时任务
    
    Args:
        job_id: 任务ID（支持模糊匹配前3位）
    
    Returns:
        恢复结果
    """
    try:
        manager = get_cron_manager()
        
        job = manager.get_job(job_id)
        if not job:
            return json.dumps({
                "success": False,
                "error": f"找不到任务: {job_id}"
            }, ensure_ascii=False)
        
        success = manager.resume_job(job_id)
        
        if success:
            return json.dumps({
                "success": True,
                "message": f"任务已恢复: {job.name}",
                "job_id": job.job_id
            }, ensure_ascii=False)
        else:
            return json.dumps({
                "success": False,
                "error": "恢复失败"
            }, ensure_ascii=False)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_run(job_id: str) -> str:
    """
    立即执行定时任务
    
    Args:
        job_id: 任务ID（支持模糊匹配前3位）
    
    Returns:
        执行结果
    """
    try:
        manager = get_cron_manager()
        
        job = manager.get_job(job_id)
        if not job:
            return json.dumps({
                "success": False,
                "error": f"找不到任务: {job_id}"
            }, ensure_ascii=False)
        
        # 执行
        result = manager.run_job(job_id)
        
        return json.dumps({
            "success": result.get("success", False),
            "message": f"任务已执行: {job.name}",
            "job_id": job.job_id,
            "result": result
        }, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_cron_info(job_id: str) -> str:
    """
    查看任务详情和执行历史
    
    Args:
        job_id: 任务ID（支持模糊匹配前3位）
    
    Returns:
        任务详情
    """
    try:
        manager = get_cron_manager()
        
        job = manager.get_job(job_id)
        if not job:
            return json.dumps({
                "success": False,
                "error": f"找不到任务: {job_id}"
            }, ensure_ascii=False)
        
        # 获取执行历史
        runs = manager.get_job_runs(job_id, limit=10)
        
        return json.dumps({
            "success": True,
            "job": {
                "job_id": job.job_id,
                "name": job.name,
                "schedule": job.schedule,
                "schedule_type": job.schedule_type,
                "prompt": job.prompt,
                "status": job.status,
                "deliver": job.deliver,
                "model": job.model,
                "skills": job.skills,
                "next_run": job.next_run,
                "last_run": job.last_run,
                "run_count": job.run_count,
                "created_at": job.created_at
            },
            "recent_runs": runs
        }, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)
