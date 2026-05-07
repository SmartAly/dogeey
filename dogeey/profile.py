"""
用户画像系统 - 学习用户习惯并动态更新人设
优化版：支持初次引导、渐进式学习、Token优化
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import hashlib


# 初次见面引导问题
ONBOARDING_QUESTIONS = [
    {
        "id": "name",
        "question": "怎么称呼您？",
        "default": "老板",
        "type": "text"
    },
    {
        "id": "role",
        "question": "您是做什么工作的？（如：程序员、产品经理、学生等）",
        "default": "未知",
        "type": "text"
    },
    {
        "id": "timezone",
        "question": "您在哪个时区？（如：Asia/Shanghai, America/New_York）",
        "default": "Asia/Shanghai",
        "type": "text"
    },
    {
        "id": "output_style",
        "question": "您希望我怎么回复？（可多选）\n  1. 结构化输出（用emoji、分段、项目符号）\n  2. 简洁直接（少废话，直接给答案）\n  3. 详细解释（带背景知识和原理）\n  4. 创意风格（活泼、有趣）\n请输入编号（如：1,3）：",
        "default": "1",
        "type": "multi_choice"
    },
    {
        "id": "persona_preference",
        "question": "您希望我是什么人设？\n  1. 专业助手（严谨、高效、解决问题）\n  2. 铁蛋风格（直爽、不推诿、东北话）\n  3. 幽默朋友（轻松、开玩笑、陪伴）\n  4. 自定义（告诉我您想要什么风格）\n请选择：",
        "default": "1",
        "type": "choice"
    }
]

# Token预算配置
TOKEN_BUDGET = {
    "critical": 200,    # 核心信息（必须注入）
    "contextual": 300,  # 上下文信息（按需注入）
    "historical": 200,  # 历史纠正（只在相关时注入）
}


def compress_text(text: str, max_length: int = 100) -> str:
    """压缩文本到指定长度，保留关键信息"""
    if len(text) <= max_length:
        return text
    # 简单策略：保留前max_length-3个字符加...
    return text[:max_length-3] + "..."


class UserProfile:
    """用户画像管理类（优化版）"""
    
    def __init__(self, profile_path: str):
        self.profile_path = Path(profile_path)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = None
        self._dirty = False
        self._save_interval = 5
        self._change_count = 0
        self.load()
    
    def load(self):
        """加载用户画像"""
        if self.profile_path.exists():
            try:
                with open(self.profile_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        self.profile = json.loads(content)
                    else:
                        self.profile = self._create_default_profile()
                        self.save()
            except (json.JSONDecodeError, Exception) as e:
                print(f"⚠️ 用户画像文件损坏，使用默认配置: {e}")
                self.profile = self._create_default_profile()
                self.save()
        else:
            self.profile = self._create_default_profile()
            self.save()
    
    def _create_default_profile(self) -> Dict:
        """创建默认配置文件（需要引导）"""
        return {
            "meta": {
                "version": "2.0",
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "needs_onboarding": True,  # 标记需要初次引导
                "onboarding_completed": False
            },
            "user": {
                "name": "用户",
                "role": "未知",
                "timezone": "Asia/Shanghai",
                "language": "中文"
            },
            "communication": {
                "style": "professional",  # professional, tieguai, humorous, custom
                "output_format": {
                    "structured": True,  # 是否使用结构化输出
                    "use_emoji": True,
                    "use_bullet_points": True,
                    "use_dividers": True,
                    "paragraph_length": "2-3 lines"
                },
                "verbosity": "balanced"  # concise, balanced, detailed
            },
            "preferences": {
                "default_model": None,
                "favorite_tools": [],
                "custom_instructions": ""  # 用户自定义的人设要求
            },
            "learned_facts": [],  # 从交互中学到的稳定事实（压缩存储）
            "corrections": [],  # 用户纠正记录（只保留最近10条）
            "interaction_stats": {
                "total_conversations": 0,
                "total_tool_calls": 0,
                "most_used_tools": {},
                "active_days": [],
                "common_tasks": []
            }
        }
    
    def save(self):
        """保存用户画像"""
        self.profile['meta']['last_updated'] = datetime.now().isoformat()
        with open(self.profile_path, 'w', encoding='utf-8') as f:
            json.dump(self.profile, f, indent=2, ensure_ascii=False)
        self._dirty = False
    
    def needs_onboarding(self) -> bool:
        """检查是否需要初次引导"""
        return self.profile.get('meta', {}).get('needs_onboarding', True)
    
    def complete_onboarding(self, answers: Dict[str, str]):
        """根据初次引导的答案生成人设"""
        # 解析答案
        name = answers.get('name', '老板')
        role = answers.get('role', '未知')
        timezone = answers.get('timezone', 'Asia/Shanghai')
        output_style = answers.get('output_style', '1')
        persona = answers.get('persona_preference', '1')
        
        # 更新用户基本信息
        self.profile['user']['name'] = name
        self.profile['user']['role'] = role
        self.profile['user']['timezone'] = timezone
        
        # 解析输出风格（多选）
        style_map = {
            '1': {'structured': True, 'use_emoji': True, 'use_bullet_points': True, 'use_dividers': True},
            '2': {'structured': False, 'use_emoji': False, 'use_bullet_points': False, 'use_dividers': False, 'verbosity': 'concise'},
            '3': {'structured': True, 'use_emoji': False, 'use_bullet_points': True, 'use_dividers': False, 'verbosity': 'detailed'},
            '4': {'structured': True, 'use_emoji': True, 'use_bullet_points': True, 'use_dividers': True, 'verbosity': 'balanced'}
        }
        
        chosen_styles = output_style.split(',')
        # 合并多个风格选择
        final_style = {'structured': False, 'use_emoji': False, 'use_bullet_points': False, 'use_dividers': False}
        for choice in chosen_styles:
            choice = choice.strip()
            if choice in style_map:
                final_style.update(style_map[choice])
        
        self.profile['communication']['output_format'].update(final_style)
        
        # 解析人设风格
        persona_map = {
            '1': 'professional',
            '2': 'tieguai',
            '3': 'humorous',
            '4': 'custom'
        }
        self.profile['communication']['style'] = persona_map.get(persona, 'professional')
        
        # 如果选择自定义，记录用户的具体要求
        if persona == '4':
            self.profile['preferences']['custom_instructions'] = answers.get('custom_persona', '')
        
        # 标记引导完成
        self.profile['meta']['needs_onboarding'] = False
        self.profile['meta']['onboarding_completed'] = True
        
        self.save()
    
    def get(self, key: str, default=None):
        """获取画像值（支持点号路径）"""
        keys = key.split('.')
        value = self.profile
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value):
        """设置画像值"""
        keys = key.split('.')
        target = self.profile
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
    
    def learn_from_interaction(self, user_input: str, assistant_response: str, 
                               tool_calls: list = None):
        """从交互中学习（优化版）"""
        # 更新交互统计
        self.profile['interaction_stats']['total_conversations'] += 1
        
        # 记录活跃日期
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in self.profile['interaction_stats']['active_days']:
            self.profile['interaction_stats']['active_days'].append(today)
            # 只保留最近30天
            if len(self.profile['interaction_stats']['active_days']) > 30:
                self.profile['interaction_stats']['active_days'] = \
                    self.profile['interaction_stats']['active_days'][-30:]
        
        # 学习工具使用模式
        if tool_calls:
            self.profile['interaction_stats']['total_tool_calls'] += len(tool_calls)
            most_used = self.profile['interaction_stats']['most_used_tools']
            for call in tool_calls:
                tool_name = call.get('tool') if isinstance(call, dict) else str(call)
                most_used[tool_name] = most_used.get(tool_name, 0) + 1
        
        # 提取稳定事实（从用户输入中识别关键信息）
        self._extract_facts(user_input)
        
        # 更新工作模式
        self._update_work_patterns(user_input)
        
        self._change_count += 1
        self._dirty = True
        if self._change_count >= self._save_interval:
            self.save()
            self._change_count = 0
    
    def _extract_facts(self, user_input: str):
        """从用户输入中提取稳定事实（压缩存储）"""
        # 检测提到的工具/软件
        tools_mentioned = []
        known_tools = ['python', 'docker', 'git', 'kubernetes', 'k8s', 'sql', 'linux', 'macos', 'windows']
        for tool in known_tools:
            if tool in user_input.lower():
                tools_mentioned.append(tool)
        
        if tools_mentioned:
            fav_tools = self.profile['preferences']['favorite_tools']
            for t in tools_mentioned:
                if t not in fav_tools:
                    fav_tools.append(t)
            # 只保留最近10个
            self.profile['preferences']['favorite_tools'] = fav_tools[-10:]
        
        # 检测任务类型
        task_keywords = {
            "代码": ["代码", "编程", "函数", "class", "def", "代码审查"],
            "文件": ["文件", "读取", "写入", "保存", "编辑"],
            "搜索": ["搜索", "查找", "找", "查询", "搜索一下"],
            "分析": ["分析", "统计", "总结", "报告"],
            "生成": ["生成", "创建", "写", "制作", "画"]
        }
        
        for task_type, keywords in task_keywords.items():
            if any(kw in user_input for kw in keywords):
                if task_type not in self.profile['interaction_stats']['common_tasks']:
                    self.profile['interaction_stats']['common_tasks'].append(task_type)
                    # 只保留最近5个
                    if len(self.profile['interaction_stats']['common_tasks']) > 5:
                        self.profile['interaction_stats']['common_tasks'] = \
                            self.profile['interaction_stats']['common_tasks'][-5:]
    
    def _update_work_patterns(self, user_input: str):
        """更新工作模式（检测输出偏好）"""
        # 如果用户明确要求某种格式，记录下来
        if "emoji" in user_input and ("不要" in user_input or "别用" in user_input):
            self.profile['communication']['output_format']['use_emoji'] = False
        if "结构化" in user_input and ("不要" in user_input or "别用" in user_input):
            self.profile['communication']['output_format']['structured'] = False
        
        # 检测用户对回复长度的反馈
        if "太长了" in user_input or "简短" in user_input:
            self.profile['communication']['verbosity'] = 'concise'
        elif "详细" in user_input or "展开" in user_input:
            self.profile['communication']['verbosity'] = 'detailed'
    
    def add_correction(self, original: str, corrected: str, reason: str):
        """记录用户纠正（优化版：压缩存储）"""
        correction = {
            'original': compress_text(original, 100),
            'corrected': compress_text(corrected, 100),
            'reason': compress_text(reason, 50),
            'timestamp': datetime.now().isoformat(),
            'hash': hashlib.md5(f"{original}{corrected}".encode()).hexdigest()[:8]  # 去重用
        }
        
        # 检查是否已存在相似纠正（去重）
        existing_hashes = [c.get('hash') for c in self.profile['corrections']]
        if correction['hash'] not in existing_hashes:
            self.profile['corrections'].append(correction)
            # 只保留最近10条
            if len(self.profile['corrections']) > 10:
                self.profile['corrections'] = self.profile['corrections'][-10:]
            self.save()
    
    def get_prompt_context(self, max_tokens: int = 500) -> str:
        """
        生成用于LLM提示词的用户画像上下文（Token优化版）
        分层注入策略：
        1. 核心信息（必须）：用户称呼、人设风格、关键偏好
        2. 上下文信息（可选）：工作模式、常用工具
        3. 历史纠正（按需）：只在相关时注入
        """
        ctx_parts = []
        current_tokens = 0
        
        # === 第一层：核心信息（必须注入） ===
        core_info = "📋 用户信息:\n"
        user = self.profile.get('user', {})
        core_info += f"- 称呼: {user.get('name', '用户')}\n"
        core_info += f"- 角色: {user.get('role', '未知')}\n"
        core_info += f"- 时区: {user.get('timezone', 'Asia/Shanghai')}\n"
        
        style = self.profile.get('communication', {}).get('style', 'professional')
        style_desc = {
            'professional': '专业助手（严谨、高效）',
            'tieguai': '铁蛋风格（直爽、不推诿、东北话）',
            'humorous': '幽默朋友（轻松、有趣）',
            'custom': self.profile.get('preferences', {}).get('custom_instructions', '自定义')
        }.get(style, '专业助手')
        core_info += f"- 人设: {style_desc}\n"
        
        ctx_parts.append(core_info)
        current_tokens += len(core_info)  # 粗略估算
        
        # === 第二层：输出格式偏好 ===
        output = self.profile.get('communication', {}).get('output_format', {})
        if any([output.get('structured'), output.get('use_emoji'), 
                output.get('use_bullet_points'), output.get('use_dividers')]):
            format_info = "📝 输出格式偏好:\n"
            if output.get('structured'):
                format_info += "- 使用结构化输出（emoji、分段、项目符号）\n"
            if output.get('use_emoji'):
                format_info += "- 使用emoji图标\n"
            if output.get('paragraph_length'):
                format_info += f"- 段落长度: {output.get('paragraph_length')}\n"
            
            # 检查token预算
            if current_tokens + len(format_info) <= max_tokens:
                ctx_parts.append(format_info)
                current_tokens += len(format_info)
        
        # === 第三层：工作模式（如果token允许）===
        stats = self.profile.get('interaction_stats', {})
        if stats.get('common_tasks') or self.profile.get('preferences', {}).get('favorite_tools'):
            work_info = "💼 工作模式:\n"
            if stats.get('common_tasks'):
                work_info += f"- 常见任务: {', '.join(stats['common_tasks'][:3])}\n"
            if self.profile['preferences'].get('favorite_tools'):
                work_info += f"- 常用工具: {', '.join(self.profile['preferences']['favorite_tools'][:5])}\n"
            
            if current_tokens + len(work_info) <= max_tokens:
                ctx_parts.append(work_info)
                current_tokens += len(work_info)
        
        # === 第四层：历史纠正（只在token充裕时注入最近3条） ===
        corrections = self.profile.get('corrections', [])
        if corrections and current_tokens < max_tokens - 100:
            correction_info = "⚠️ 避免重复的错误:\n"
            for corr in corrections[-3:]:  # 只取最近3条
                correction_info += f"- {corr['reason']}\n"
            
            if current_tokens + len(correction_info) <= max_tokens:
                ctx_parts.append(correction_info)
        
        return "\n".join(ctx_parts)
    
    def to_dict(self) -> Dict:
        """返回完整画像字典（用于调试）"""
        return self.profile.copy()

# 导入click用于引导流程
try:
    import click
    HAS_CLICK = True
except ImportError:
    HAS_CLICK = False


def run_onboarding(profile: UserProfile) -> bool:
    """
    执行初次见面引导流程
    返回：是否成功完成引导
    """
    if not HAS_CLICK:
        print("⚠️ 需要click库来运行引导流程")
        return False
    
    click.echo()
    click.echo("🎉 初次见面！让我了解一下您的偏好，以便提供更好的服务。")
    click.echo()
    click.echo("━" * 50)
    click.echo("📝 初次见面引导")
    click.echo("━" * 50)
    click.echo()
    
    answers = {}
    
    for i, q in enumerate(ONBOARDING_QUESTIONS, 1):
        click.echo(f"问题 {i}/{len(ONBOARDING_QUESTIONS)}")
        click.echo(q['question'])
        click.echo()
        
        if q['type'] == 'multi_choice':
            answer = click.prompt("您的选择", default=q['default'], show_default=True)
        else:
            answer = click.prompt("您的回答", default=q['default'], show_default=True)
        
        answers[q['id']] = answer
        click.echo()
    
    # 如果选择自定义人设，额外询问
    if answers.get('persona_preference') == '4':
        click.echo("请描述您希望我是什么风格：")
        custom = click.prompt("自定义人设", default="", show_default=False)
        answers['custom_persona'] = custom
    
    # 确认
    click.echo("━" * 50)
    click.echo("📊 您的偏好设置：")
    click.echo(f"  称呼: {answers.get('name')}")
    click.echo(f"  职业: {answers.get('role')}")
    click.echo(f"  时区: {answers.get('timezone')}")
    click.echo(f"  输出风格: {answers.get('output_style')}")
    click.echo(f"  人设: {answers.get('persona_preference')}")
    click.echo("━" * 50)
    click.echo()
    
    if click.confirm("确认以上信息无误？"):
        profile.complete_onboarding(answers)
        click.echo()
        click.echo("✅ 引导完成！现在开始为您服务...")
        click.echo()
        return True
    else:
        click.echo("🔄 重新进行引导...")
        return run_onboarding(profile)


if __name__ == '__main__':
    # 测试引导流程
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name
    
    profile = UserProfile(temp_path)
    if profile.needs_onboarding():
        run_onboarding(profile)
        print("\n生成的人设：")
        print(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False))
    
    import os
    os.unlink(temp_path)
