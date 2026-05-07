"""
工具系统 - 工具注册、发现和执行
"""
import json
import subprocess
from typing import Dict, List, Any, Optional
from pydantic import BaseModel


class Tool:
    """工具定义"""
    def __init__(self, name: str, description: str, parameters: Dict, func):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters
        }


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool):
        """注册工具"""
        self._tools[tool.name] = tool
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self._tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """列出所有工具"""
        return list(self._tools.values())
    
    def get_tools_index(self) -> str:
        """Level 1: 工具索引（仅名称，~100字符，最轻量）"""
        return ", ".join(self._tools.keys())

    def get_tools_brief(self) -> str:
        """Level 2: 工具简述（名称+一句话描述，~500字符）"""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    def get_tools_description(self) -> str:
        """Level 3: 工具完整描述（名称+描述+参数，仅需要时使用）"""
        desc = ""
        for tool in self._tools.values():
            desc += f"- {tool.name}: {tool.description}\n"
            if tool.parameters:
                desc += f"  参数: {json.dumps(tool.parameters, ensure_ascii=False)}\n"
        return desc
    
    def get_tools_schema(self) -> List[Dict]:
        """
        获取工具的OpenAI格式schema（用于function calling）
        返回: [{"type": "function", "function": {...}}, ...]
        """
        schema = []
        for tool in self._tools.values():
            func_def = {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters if tool.parameters else {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            schema.append({
                "type": "function",
                "function": func_def
            })
        return schema
    
    def exists(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tools
    
    def get_tools_name_list(self) -> List[str]:
        """获取所有工具名称列表"""
        return list(self._tools.keys())
    
    def execute(self, name: str, input_data: Any) -> str:
        """执行工具（execute_tool的别名，兼容不同调用方式）"""
        return self.execute_tool(name, input_data)

    def execute_tool(self, name: str, input_data: Any) -> str:
        """执行工具"""
        tool = self._tools.get(name)
        if not tool:
            return f"错误: 找不到工具 '{name}'"
        
        try:
            # 如果input_data是字符串，尝试解析为JSON
            if isinstance(input_data, str):
                try:
                    input_data = json.loads(input_data)
                except:
                    pass
            
            # 调用工具函数
            if isinstance(input_data, dict):
                result = tool.func(**input_data)
            elif isinstance(input_data, list):
                result = tool.func(*input_data)
            else:
                result = tool.func(input_data)
            
            return str(result)
        except Exception as e:
            return f"工具执行错误: {str(e)}"


# ============ 内置工具 ============

def tool_read_file(path: str, offset: int = 1, limit: int = 100) -> str:
    """读取文件内容"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 分页读取
        start = max(0, offset - 1)
        end = min(len(lines), start + limit)
        
        if start >= len(lines):
            return f"文件为空或offset超出范围"
        
        content = "".join(lines[start:end])
        result = f"文件: {path} (第{start+1}-{end}行，共{len(lines)}行)\n\n{content}"
        
        if end < len(lines):
            result += f"\n... 还有 {len(lines) - end} 行未显示"
        
        return result
    except FileNotFoundError:
        return f"错误: 文件不存在 {path}"
    except Exception as e:
        return f"读取错误: {str(e)}"


def tool_write_file(path: str, content: str) -> str:
    """写入文件（覆盖）"""
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"文件已写入: {path}"
    except Exception as e:
        return f"写入错误: {str(e)}"


def tool_search_files(pattern: str, path: str = ".", target: str = "content", 
                      file_glob: str = None, limit: int = 50) -> str:
    """搜索文件内容或文件名"""
    import os
    import re
    
    results = []
    
    try:
        if target == "files":
            # 搜索文件名
            for root, dirs, files in os.walk(path):
                for file in files:
                    if re.match(pattern.replace("*", ".*"), file):
                        results.append(os.path.join(root, file))
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
            return f"找到 {len(results)} 个文件:\n" + "\n".join(results[:limit])
        else:
            # 搜索文件内容
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file_glob and not file.endswith(file_glob.replace("*", "")):
                        continue
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for i, line in enumerate(f, 1):
                                if re.search(pattern, line):
                                    results.append(f"{filepath}:{i}: {line.strip()}")
                                    if len(results) >= limit:
                                        break
                    except:
                        pass
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            return f"找到 {len(results)} 处匹配:\n" + "\n".join(results[:limit])
    except Exception as e:
        return f"搜索错误: {str(e)}"


def tool_run_command(command: str) -> str:
    """执行shell命令"""
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=30
        )
        output = result.stdout
        if result.stderr:
            output += f"\n错误输出:\n{result.stderr}"
        output += f"\n退出码: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "命令执行超时（30秒）"
    except Exception as e:
        return f"命令执行错误: {str(e)}"


def register_builtin_tools(registry: ToolRegistry):
    """注册内置工具"""
    # 文件读取工具
    registry.register(Tool(
        name="read_file",
        description="读取文本文件内容，支持分页",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "offset": {"type": "integer", "description": "起始行号（从1开始）", "default": 1},
                "limit": {"type": "integer", "description": "读取行数", "default": 100}
            },
            "required": ["path"]
        },
        func=tool_read_file
    ))
    
    # 文件写入工具
    registry.register(Tool(
        name="write_file",
        description="写入内容到文件（覆盖）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"}
            },
            "required": ["path", "content"]
        },
        func=tool_write_file
    ))
    
    # 文件搜索工具
    registry.register(Tool(
        name="search_files",
        description="搜索文件内容或文件名",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索模式（正则）"},
                "path": {"type": "string", "description": "搜索路径", "default": "."},
                "target": {"type": "string", "description": "搜索目标: content或files", "default": "content"},
                "file_glob": {"type": "string", "description": "文件过滤模式", "default": None},
                "limit": {"type": "integer", "description": "最大结果数", "default": 50}
            },
            "required": ["pattern"]
        },
        func=tool_search_files
    ))
    
    # Shell命令工具
    registry.register(Tool(
        name="run_command",
        description="执行shell命令",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"}
            },
            "required": ["command"]
        },
        func=tool_run_command
    ))
    
    # ============ Cron定时任务工具 ============
    try:
        from dogeey.cron_tool import (
            tool_cron_create,
            tool_cron_list,
            tool_cron_delete,
            tool_cron_pause,
            tool_cron_resume,
            tool_cron_run,
            tool_cron_info
        )
        
        # 创建定时任务
        registry.register(Tool(
            name="cron_create",
            description="创建定时任务（每天自动执行）",
            parameters={
                "type": "object",
                "properties": {
                    "schedule": {"type": "string", "description": "时间计划: '30m'(30分钟), '2h'(2小时), '0 9 * * *'(每天9点), '2024-01-01 09:00'(指定时间)"},
                    "prompt": {"type": "string", "description": "任务提示词（给AI执行的指令）"},
                    "name": {"type": "string", "description": "任务名称（可选）"},
                    "deliver": {"type": "string", "description": "推送目标: origin/local/telegram/feishu", "default": "origin"},
                    "model": {"type": "string", "description": "使用的模型（可选）"},
                    "skills": {"type": "string", "description": "技能列表（JSON数组或逗号分隔）"},
                    "max_retries": {"type": "integer", "description": "最大重试次数", "default": 3}
                },
                "required": ["schedule", "prompt"]
            },
            func=tool_cron_create
        ))
        
        # 列出定时任务
        registry.register(Tool(
            name="cron_list",
            description="列出所有定时任务",
            parameters={
                "type": "object",
                "properties": {
                    "include_disabled": {"type": "boolean", "description": "是否包含已暂停的任务", "default": False}
                }
            },
            func=tool_cron_list
        ))
        
        # 删除定时任务
        registry.register(Tool(
            name="cron_delete",
            description="删除定时任务",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID（支持模糊匹配前3位）"}
                },
                "required": ["job_id"]
            },
            func=tool_cron_delete
        ))
        
        # 暂停定时任务
        registry.register(Tool(
            name="cron_pause",
            description="暂停定时任务",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID（支持模糊匹配前3位）"}
                },
                "required": ["job_id"]
            },
            func=tool_cron_pause
        ))
        
        # 恢复定时任务
        registry.register(Tool(
            name="cron_resume",
            description="恢复已暂停的定时任务",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID（支持模糊匹配前3位）"}
                },
                "required": ["job_id"]
            },
            func=tool_cron_resume
        ))
        
        # 立即执行任务
        registry.register(Tool(
            name="cron_run",
            description="立即执行定时任务（不管时间）",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID（支持模糊匹配前3位）"}
                },
                "required": ["job_id"]
            },
            func=tool_cron_run
        ))
        
        # 查看任务详情
        registry.register(Tool(
            name="cron_info",
            description="查看任务详情和执行历史",
            parameters={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID（支持模糊匹配前3位）"}
                },
                "required": ["job_id"]
            },
            func=tool_cron_info
        ))
        
        print("✅ Cron定时任务工具已注册")
    except ImportError as e:
        print(f"⚠️ Cron工具导入失败（未安装依赖？）: {e}")
    
    # ============ 自进化工具 (Phase 1/1.5/2/3) ============
    try:
        from dogeey.evolution_tools import (
            tool_profile_get,
            tool_profile_learn,
            tool_persona_get,
            tool_persona_report,
            tool_memory_search,
            tool_memory_add,
            tool_memory_manage,
            tool_skill_combine,
            tool_skill_suggest,
            tool_skill_experience,
            tool_metacognition_report,
            tool_metacognition_blindspots
        )
        
        # Phase 1: 用户画像工具
        registry.register(Tool(
            name="profile_get",
            description="获取用户画像信息（偏好、习惯、时区等）",
            parameters={
                "type": "object",
                "properties": {
                    "section": {"type": "string", "description": "指定部分: basic/communication/preferences/work_patterns/learned_facts（不填则返回完整画像）"}
                }
            },
            func=tool_profile_get
        ))
        
        registry.register(Tool(
            name="profile_learn",
            description="手动触发从对话中学习（通常自动进行）",
            parameters={
                "type": "object",
                "properties": {
                    "user_input": {"type": "string", "description": "用户输入"},
                    "assistant_response": {"type": "string", "description": "助手回复"}
                },
                "required": ["user_input", "assistant_response"]
            },
            func=tool_profile_learn
        ))
        
        # Phase 1.5: 人设进化工具
        registry.register(Tool(
            name="persona_get",
            description="获取当前人设提示词（铁蛋风格等）",
            parameters={"type": "object", "properties": {}},
            func=tool_persona_get
        ))
        
        registry.register(Tool(
            name="persona_report",
            description="获取人设进化报告（参数变化历史）",
            parameters={"type": "object", "properties": {}},
            func=tool_persona_report
        ))
        
        # Phase 2: 记忆进化工具
        registry.register(Tool(
            name="memory_search",
            description="搜索长期记忆",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "最大结果数", "default": 5}
                },
                "required": ["query"]
            },
            func=tool_memory_search
        ))
        
        registry.register(Tool(
            name="memory_add",
            description="添加长期记忆",
            parameters={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "记忆内容"},
                    "tags": {"type": "string", "description": "标签（逗号分隔或JSON数组）"},
                    "importance": {"type": "number", "description": "重要性 0.0-1.0", "default": 0.5}
                },
                "required": ["content"]
            },
            func=tool_memory_add
        ))
        
        registry.register(Tool(
            name="memory_manage",
            description="管理长期记忆（列表/删除/清理）",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "操作: list/delete/cleanup", "enum": ["list", "delete", "cleanup"]},
                    "memory_id": {"type": "integer", "description": "记忆ID（delete时需要）"},
                    "limit": {"type": "integer", "description": "列表数量", "default": 50},
                    "days": {"type": "integer", "description": "清理多少天前的（cleanup时）", "default": 180},
                    "min_weight": {"type": "number", "description": "清理的最小权重阈值", "default": 0.1}
                },
                "required": ["action"]
            },
            func=tool_memory_manage
        ))
        
        # Phase 3: 技能进化工具
        registry.register(Tool(
            name="skill_combine",
            description="组合两个技能，生成新技能",
            parameters={
                "type": "object",
                "properties": {
                    "skill1": {"type": "string", "description": "第一个技能名"},
                    "skill2": {"type": "string", "description": "第二个技能名"}
                },
                "required": ["skill1", "skill2"]
            },
            func=tool_skill_combine
        ))
        
        registry.register(Tool(
            name="skill_suggest",
            description="建议可能的技能组合（根据任务类型）",
            parameters={
                "type": "object",
                "properties": {
                    "task_type": {"type": "string", "description": "任务类型"}
                },
                "required": ["task_type"]
            },
            func=tool_skill_suggest
        ))
        
        registry.register(Tool(
            name="skill_experience",
            description="查看技能经验总结",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "技能名（不填返回所有）"}
                }
            },
            func=tool_skill_experience
        ))
        
        # Phase 3: 元认知工具
        registry.register(Tool(
            name="metacognition_report",
            description="获取完整元认知报告（能力地图+盲区+任务统计）",
            parameters={"type": "object", "properties": {}},
            func=tool_metacognition_report
        ))
        
        registry.register(Tool(
            name="metacognition_blindspots",
            description="管理认知盲区（列出/标记解决）",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "操作: list/resolve", "enum": ["list", "resolve"]},
                    "task_type": {"type": "string", "description": "任务类型（resolve时需要）"}
                },
                "required": ["action"]
            },
            func=tool_metacognition_blindspots
        ))
        
        print("✅ 自进化工具已注册 (Phase 1/1.5/2/3)")
    except ImportError as e:
        print(f"⚠️ 自进化工具导入失败: {e}")
    
    # ============ 工具清单工具 ============
    def tool_list_all() -> str:
        """列出所有已注册的工具（分类显示）"""
        tools = registry.list_tools()
        
        # 分类
        categories = {
            "信息处理": [],
            "系统操作": [],
            "定时任务": [],
            "工具查询": [],
            "用户画像": [],
            "人设进化": [],
            "记忆系统": [],
            "技能系统": [],
            "元认知": []
        }
        
        for tool in tools:
            if tool.name in ['read_file', 'write_file', 'search_files']:
                categories["信息处理"].append(tool.name)
            elif tool.name == 'run_command':
                categories["系统操作"].append(tool.name)
            elif tool.name.startswith('cron_'):
                categories["定时任务"].append(tool.name)
            elif tool.name == 'tool_list_all':
                categories["工具查询"].append(tool.name)
            elif 'profile_' in tool.name:
                categories["用户画像"].append(tool.name)
            elif 'persona_' in tool.name:
                categories["人设进化"].append(tool.name)
            elif 'memory_' in tool.name:
                categories["记忆系统"].append(tool.name)
            elif 'skill_' in tool.name:
                categories["技能系统"].append(tool.name)
            elif 'metacognition_' in tool.name:
                categories["元认知"].append(tool.name)
        
        # 生成报告
        lines = []
        lines.append('▸ 🛠️ "来福"工具箱')
        lines.append('📋 已注册工具清单')
        
        for category, tools_list in categories.items():
            if tools_list:
                emoji = {
                    "信息处理": "🔍",
                    "系统操作": "💻",
                    "定时任务": "⏰",
                    "用户画像": "👤",
                    "人设进化": "🎭",
                    "记忆系统": "🧠",
                    "技能系统": "🎯",
                    "元认知": "🧠"
                }.get(category, "🔧")
                lines.append(f'{emoji} {category}类')
                for tool_name in tools_list:
                    lines.append(f'• {tool_name}: {registry.get_tool(tool_name).description}')
        
        lines.append('──────────────────────────────')
        lines.append(f'🎯 工具能力速查')
        lines.append('| 工具 | 功能 | 典型用途 |')
        lines.append('|------|------|----------|')
        
        # 添加典型用途
        typical_uses = {
            'read_file': '查看日志、配置文件',
            'write_file': '保存报告、生成文档',
            'search_files': '查找代码、文档内容',
            'run_command': '系统管理、脚本运行',
            'cron_create': '设置定时提醒、自动推送',
            'cron_list': '查看所有定时任务',
            'profile_get': '获取用户偏好和习惯',
            'memory_search': '搜索历史记忆'
        }
        
        for tool in tools[:8]:  # 只显示前8个
            use = typical_uses.get(tool.name, '通用功能')
            lines.append(f'| {tool.name} | {tool.description[:10]}... | {use} |')
        
        lines.append('──────────────────────────────')
        lines.append('结论: 老板，这就是"来福"的全部家当！🐶✨')
        
        return "\n".join(lines)
    
    # ============ 工具Schema查询工具 (方案2：Brief模式 + 工具查询) ============
    def tool_get_schema(tool_name: str) -> str:
        """获取指定工具的完整OpenAI function calling schema
        
        用于方案2：默认只传brief列表，需要时用这个工具获取完整schema
        这样能大幅减少token消耗（从~5000降到~400）
        """
        tool = registry.get_tool(tool_name)
        if not tool:
            # 尝试模糊匹配
            matches = [t for t in registry.list_tools() if tool_name.lower() in t.name.lower()]
            if matches:
                tool = matches[0]
            else:
                return f"❌ 工具不存在: {tool_name}\n可用工具: {', '.join(t.name for t in registry.list_tools())}"
        
        # 构建OpenAI function calling格式
        schema = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters if tool.parameters else {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        
        return json.dumps(schema, ensure_ascii=False, indent=2)
    
    registry.register(Tool(
        name="tool_list_all",
        description="列出所有已注册的工具（分类显示，准确查询）",
        parameters={"type": "object", "properties": {}},
        func=tool_list_all
    ))
    
    # 工具Schema查询工具（方案2：减少token消耗）
    registry.register(Tool(
        name="tool_get_schema",
        description="获取指定工具的完整schema（用于方案2：减少token消耗）",
        parameters={
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "工具名称（支持模糊匹配）"}
            },
            "required": ["tool_name"]
        },
        func=tool_get_schema
    ))
    
    print(f"✅ 工具清单工具已注册 (共{len(registry.list_tools())}个工具)")

