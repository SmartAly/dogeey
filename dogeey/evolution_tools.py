"""
自进化工具集 - Phase 1/1.5/2/3 工具接口
让dogeey能够主动调用自进化功能
"""
import json
from typing import Optional, List, Dict
from pathlib import Path

# ============ 延迟导入（避免循环依赖） ============
_profile = None
_persona_system = None
_memory_system = None
_skill_system = None
_metacognition = None

def _get_profile():
    global _profile
    if _profile is None:
        from dogeey.profile import UserProfile
        from dogeey.config import config
        cfg = config.load()
        profile_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        profile_path = str(Path(profile_path).parent / "user_profile.json")
        _profile = UserProfile(profile_path)
    return _profile

def _get_persona_system():
    global _persona_system
    if _persona_system is None:
        from dogeey.persona_evolution import PersonaEvolutionSystem
        _persona_system = PersonaEvolutionSystem()
    return _persona_system

def _get_memory_system():
    global _memory_system
    if _memory_system is None:
        from dogeey.memory_evolution import MemoryEvolutionSystem
        from dogeey.config import config
        cfg = config.load()
        db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        _memory_system = MemoryEvolutionSystem(db_path)
    return _memory_system

def _get_skill_system():
    global _skill_system
    if _skill_system is None:
        from dogeey.skill_evolution import SkillEvolutionSystem
        from dogeey.config import config
        cfg = config.load()
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        _skill_system = SkillEvolutionSystem(skills_dir=skills_path)
    return _skill_system

def _get_metacognition():
    global _metacognition
    if _metacognition is None:
        from dogeey.metacognition import MetaCognition
        _metacognition = MetaCognition()
    return _metacognition


# ============ Phase 1: 用户画像工具 ============

def tool_profile_get(section: Optional[str] = None) -> str:
    """
    获取用户画像信息
    
    Args:
        section: 指定部分（basic/communication/preferences/work_patterns/learned_facts），不指定则返回完整画像
    
    Returns:
        用户画像JSON
    """
    try:
        profile = _get_profile()
        
        if section:
            data = profile.profile.get(section, {})
        else:
            data = profile.profile
        
        return json.dumps({
            "success": True,
            "profile": data
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_profile_learn(user_input: str, assistant_response: str) -> str:
    """
    从对话中手动触发学习（通常自动进行，此工具用于强制学习）
    
    Args:
        user_input: 用户输入
        assistant_response: 助手回复
    
    Returns:
        学习结果
    """
    try:
        profile = _get_profile()
        profile.learn_from_interaction(user_input, assistant_response, "")
        
        return json.dumps({
            "success": True,
            "message": "已从对话中学习",
            "learned_facts_count": len(profile.profile.get('learned_facts', []))
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============ Phase 1.5: 人设进化工具 ============

def tool_persona_get() -> str:
    """
    获取当前人设提示词
    
    Returns:
        当前人设的prompt片段
    """
    try:
        system = _get_persona_system()
        prompt = system.get_current_persona_prompt()
        
        return json.dumps({
            "success": True,
            "persona_prompt": prompt
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_persona_report() -> str:
    """
    获取人设进化报告
    
    Returns:
        进化报告（包含参数变化历史）
    """
    try:
        system = _get_persona_system()
        report = system.get_evolution_report()
        
        return json.dumps({
            "success": True,
            "report": report
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============ Phase 2: 记忆进化工具 ============

def tool_memory_search(query: str, limit: int = 5) -> str:
    """
    搜索长期记忆
    
    Args:
        query: 搜索关键词
        limit: 最大结果数
    
    Returns:
        匹配的记忆列表
    """
    try:
        system = _get_memory_system()
        memories = system.search_memories(query, limit=limit)
        
        results = []
        for mem in memories:
            # 转换datetime为字符串（避免JSON序列化错误）
            created_at = mem.created_at
            if hasattr(created_at, 'isoformat'):
                created_at = created_at.isoformat()
            
            results.append({
                "id": mem.id,
                "content": mem.content[:200] + "..." if len(mem.content) > 200 else mem.content,
                "weight": mem.weight,
                "access_count": mem.access_count,
                "created_at": created_at
            })
        
        return json.dumps({
            "success": True,
            "memories": results,
            "count": len(results)
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_memory_add(content: str, tags: Optional[str] = None, importance: float = 0.5) -> str:
    """
    添加长期记忆
    
    Args:
        content: 记忆内容
        tags: 标签（逗号分隔或JSON数组）
        importance: 重要性（0.0-1.0）
    
    Returns:
        添加结果
    """
    try:
        system = _get_memory_system()
        
        # 解析tags
        tag_list = []
        if tags:
            try:
                tag_list = json.loads(tags)
            except:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        
        memory_id = system.add_long_term(content, tags=tag_list, importance=importance)
        
        return json.dumps({
            "success": True,
            "message": "记忆已添加",
            "memory_id": memory_id
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_memory_manage(action: str, memory_id: Optional[int] = None, 
                       limit: int = 50, days: int = 180, min_weight: float = 0.1) -> str:
    """
    管理长期记忆
    
    Args:
        action: 操作类型（list/delete/cleanup）
        memory_id: 记忆ID（delete时需要）
        limit: 列出的最大数量（list时）
        days: 清理多少天前的记忆（cleanup时）
        min_weight: 清理时的最小权重阈值（cleanup时）
    
    Returns:
        操作结果
    """
    try:
        system = _get_memory_system()
        
        if action == "list":
            memories = system.get_all_memories(limit=limit)
            results = []
            for mem in memories:
                results.append({
                    "id": mem.id,
                    "content": mem.content[:100] + "..." if len(mem.content) > 100 else mem.content,
                    "weight": mem.weight,
                    "access_count": mem.access_count
                })
            return json.dumps({
                "success": True,
                "memories": results,
                "count": len(results)
            }, ensure_ascii=False, indent=2)
        
        elif action == "delete":
            if memory_id is None:
                return json.dumps({"success": False, "error": "delete操作需要memory_id"}, ensure_ascii=False)
            success = system.delete_memory(memory_id)
            return json.dumps({
                "success": success,
                "message": "记忆已删除" if success else "删除失败"
            }, ensure_ascii=False)
        
        elif action == "cleanup":
            deleted = system.cleanup_old_memories(days=days, min_weight=min_weight)
            return json.dumps({
                "success": True,
                "message": f"已清理 {deleted} 条旧记忆",
                "deleted_count": deleted
            }, ensure_ascii=False)
        
        else:
            return json.dumps({"success": False, "error": f"未知操作: {action}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============ Phase 3: 技能进化工具 ============

def tool_skill_combine(skill1: str, skill2: str) -> str:
    """
    组合两个技能，生成新技能
    
    Args:
        skill1: 第一个技能名
        skill2: 第二个技能名
    
    Returns:
        组合结果
    """
    try:
        system = _get_skill_system()
        result = system.combine_skills(skill1, skill2)
        
        if result:
            return json.dumps({
                "success": True,
                "message": "技能组合成功",
                "new_skill": result
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": "技能组合失败"
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_skill_suggest(task_type: str) -> str:
    """
    建议可能的技能组合
    
    Args:
        task_type: 任务类型
    
    Returns:
        建议的技能组合列表
    """
    try:
        system = _get_skill_system()
        suggestions = system.suggest_combinations(task_type)
        
        return json.dumps({
            "success": True,
            "suggestions": suggestions,
            "count": len(suggestions)
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_skill_experience(skill_name: Optional[str] = None) -> str:
    """
    查看技能经验总结
    
    Args:
        skill_name: 技能名（不指定则返回所有）
    
    Returns:
        经验总结
    """
    try:
        system = _get_skill_system()
        summary = system.get_experience_summary(skill_name)
        
        return json.dumps({
            "success": True,
            "summary": summary
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


# ============ Phase 3: 元认知工具 ============

def tool_metacognition_report() -> str:
    """
    获取完整元认知报告（能力地图+盲区+任务统计）
    动态检测已注册的工具，更新能力地图
    直接返回格式化的中文报告，避免模型误读
    """
    try:
        meta = _get_metacognition()
        
        # 动态检测已注册的工具
        available_tools = []
        cron_available = False
        tool_categories = {
            "信息处理": [],
            "技术操作": [],
            "智能分析": [],
            "沟通协作": [],
            "定时任务": []
        }
        
        try:
            from dogeey.tools import ToolRegistry, register_builtin_tools
            registry = ToolRegistry()
            register_builtin_tools(registry)
            available_tools = [t.name for t in registry.list_tools()]
            
            # 分类工具
            for tool_name in available_tools:
                if tool_name in ['read_file', 'write_file', 'search_files']:
                    tool_categories["信息处理"].append(tool_name)
                elif tool_name in ['run_command'] or tool_name.startswith('cron_'):
                    if tool_name.startswith('cron_'):
                        tool_categories["定时任务"].append(tool_name)
                    else:
                        tool_categories["技术操作"].append(tool_name)
                elif 'skill' in tool_name or 'memory' in tool_name or 'profile' in tool_name:
                    tool_categories["智能分析"].append(tool_name)
                else:
                    tool_categories["沟通协作"].append(tool_name)
            
            cron_available = len(tool_categories["定时任务"]) > 0
        except Exception as e:
            print(f"⚠️ 动态检测工具失败: {e}")
        
        # 获取元认知数据
        competence_map = meta.get_competence_map()
        blindspots = meta.get_blindspots()
        
        # 生成中文报告
        lines = []
        lines.append('▸ 🧠 "来福"元认知报告')
        lines.append('📊 能力矩阵')
        
        # 核心能力
        lines.append('✅ 核心能力')
        if tool_categories["信息处理"]:
            lines.append(f'• 🔍 信息处理: {", ".join(tool_categories["信息处理"])}')
        if tool_categories["技术操作"]:
            lines.append(f'• 💻 技术操作: {", ".join(tool_categories["技术操作"])}')
        if tool_categories["智能分析"]:
            lines.append(f'• 🧠 智能分析: {", ".join(tool_categories["智能分析"])}')
        if tool_categories["沟通协作"]:
            lines.append(f'• 💬 沟通协作: {", ".join(tool_categories["沟通协作"])}')
        
        # 定时任务能力（关键修复！）
        if cron_available:
            lines.append('• ⏰ 定时任务: ✅ 已就绪（支持创建/列表/删除/暂停/恢复/执行）')
        else:
            lines.append('• ❌ 定时任务: 未注册')
        
        # 当前局限
        lines.append('⚠️ 当前局限')
        if not cron_available:
            lines.append('• ❌ 无cron功能: 无法设置定时任务')
            lines.append('• ✅ 替代方案丰富: 可提供多种自动化方案')
        else:
            lines.append('• ✅ 无重大局限: 核心功能完备')
        
        # 应用场景
        lines.append('🎯 应用场景')
        lines.append('| 需求类型 | 解决方案 | 可行性 |')
        lines.append('|---------|---------|--------|')
        
        if cron_available:
            lines.append('| 定时提醒 | Cron定时任务 | ⭐⭐⭐⭐⭐ |')
            lines.append('| 新闻推送 | Cron+技能组合 | ⭐⭐⭐⭐ |')
        else:
            lines.append('| 定时提醒 | 系统计划任务/第三方服务 | ⭐⭐⭐⭐⭐ |')
            lines.append('| 新闻推送 | 手动查看/订阅服务 | ⭐⭐⭐⭐ |')
        
        lines.append('| 数据分析 | 直接处理+报告生成 | ⭐⭐⭐⭐⭐ |')
        lines.append('| 创意设计 | 概念生成+方案建议 | ⭐⭐⭐⭐ |')
        
        # 元认知统计
        if competence_map.get("task_types"):
            lines.append('📈 执行统计')
            best_types = meta.get_best_task_types(3)
            if best_types:
                for task_type, conf, rate, count in best_types:
                    lines.append(f'• {task_type}: 置信度{conf:.0%}, 成功率{rate:.0%} ({count}次)')
        
        # 盲区警告
        if blindspots:
            lines.append('🚨 认知盲区')
            for bs in blindspots[:3]:
                lines.append(f'• ⚠️ {bs["task_type"]}: {bs["reason"]}')
        
        # 优化建议
        lines.append('🚀 优化建议')
        lines.append('1. 短期: 建立标准化问题解决流程')
        lines.append('2. 中期: 开发自动化工具集')
        lines.append('3. 长期: 构建智能决策支持系统')
        
        lines.append('──────────────────────────────')
        lines.append('结论: 老板，这是我的"能力体检报告"！🐶✨ （虽然有局限，但解决问题的方法更多！）')
        
        return json.dumps({
            "success": True,
            "report": "\n".join(lines)
        }, ensure_ascii=False)
    
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)


def tool_metacognition_blindspots(action: str = "list", task_type: Optional[str] = None) -> str:
    """
    管理认知盲区
    
    Args:
        action: 操作类型（list/resolve）
        task_type: 任务类型（resolve时需要）
    
    Returns:
        操作结果
    """
    try:
        meta = _get_metacognition()
        
        if action == "list":
            blindspots = meta.get_blindspots()
            return json.dumps({
                "success": True,
                "blindspots": blindspots,
                "count": len(blindspots)
            }, ensure_ascii=False, indent=2)
        
        elif action == "resolve":
            if task_type is None:
                return json.dumps({"success": False, "error": "resolve操作需要task_type"}, ensure_ascii=False)
            meta.resolve_blindspot(task_type)
            return json.dumps({
                "success": True,
                "message": f"盲区已标记解决: {task_type}"
            }, ensure_ascii=False)
        
        else:
            return json.dumps({"success": False, "error": f"未知操作: {action}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)
