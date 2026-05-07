"""
Persona Evolution System - 人设进化系统
人设参数从配置文件变成可自动调整的
支持基于交互反馈、元认知评估的动态调优
"""

import json
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path


class PersonaParameters:
    """人设参数 - 可动态调整的参数集合"""
    
    def __init__(self, profile_data: Dict = None):
        """从用户画像数据初始化"""
        profile = profile_data or {}
        comm = profile.get("communication", {})
        output = comm.get("output_format", {})
        
        # 核心参数（可动态调整）
        self.verbosity = comm.get("verbosity", "balanced")  # concise, balanced, detailed
        self.structured = output.get("structured", True)
        self.use_emoji = output.get("use_emoji", True)
        self.use_bullet_points = output.get("use_bullet_points", True)
        self.use_dividers = output.get("use_dividers", True)
        self.paragraph_length = output.get("paragraph_length", "2-3 lines")
        
        # 风格参数
        self.style = comm.get("style", "professional")  # professional, tieguai, humorous, custom
        
        # 动态权重（用于调整）
        self.verbosity_weight = 1.0  # 详细度权重
        self.structured_weight = 1.0  # 结构化权重
        self.emoji_weight = 1.0  # emoji权重
        self.formalness = 0.5  # 正式程度 (0=非常随意, 1=非常正式)
        
        # 学习率和适应度
        self.learning_rate = 0.1  # 参数调整步长
        self.adaptability = 0.8  # 适应度 (0=固化, 1=高度可塑)
        self.last_adjustment = None  # 上次调整时间
        
        # 历史调整记录
        self.adjustment_history: List[Dict] = []
    
    def to_dict(self) -> Dict:
        """转换为字典（用于保存）"""
        return {
            "verbosity": self.verbosity,
            "structured": self.structured,
            "use_emoji": self.use_emoji,
            "use_bullet_points": self.use_bullet_points,
            "use_dividers": self.use_dividers,
            "paragraph_length": self.paragraph_length,
            "style": self.style,
            "verbosity_weight": self.verbosity_weight,
            "structured_weight": self.structured_weight,
            "emoji_weight": self.emoji_weight,
            "formalness": self.formalness,
            "learning_rate": self.learning_rate,
            "adaptability": self.adaptability,
            "last_adjustment": self.last_adjustment,
            "adjustment_history": self.adjustment_history[-20:]  # 最近20条
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'PersonaParameters':
        """从字典恢复"""
        params = cls()
        params.verbosity = data.get("verbosity", "balanced")
        params.structured = data.get("structured", True)
        params.use_emoji = data.get("use_emoji", True)
        params.use_bullet_points = data.get("use_bullet_points", True)
        params.use_dividers = data.get("use_dividers", True)
        params.paragraph_length = data.get("paragraph_length", "2-3 lines")
        params.style = data.get("style", "professional")
        params.verbosity_weight = data.get("verbosity_weight", 1.0)
        params.structured_weight = data.get("structured_weight", 1.0)
        params.emoji_weight = data.get("emoji_weight", 1.0)
        params.formalness = data.get("formalness", 0.5)
        params.learning_rate = data.get("learning_rate", 0.1)
        params.adaptability = data.get("adaptability", 0.8)
        params.last_adjustment = data.get("last_adjustment")
        params.adjustment_history = data.get("adjustment_history", [])
        return params
    
    def adjust_based_on_feedback(self, feedback: str, score: float):
        """根据用户反馈和评分调整参数
        
        Args:
            feedback: 用户反馈文本
            score: 评分 (0.0-1.0，1.0为满分)
        """
        adjustments = []
        old_values = self.to_dict()
        
        # 1. 调整详细度
        if "太长了" in feedback or "简短" in feedback or score < 0.4:
            if self.verbosity != "concise":
                self.verbosity = "concise"
                self.verbosity_weight = max(0.1, self.verbosity_weight - self.learning_rate)
                adjustments.append(f"详细度 → 简洁 (score={score:.2f})")
        elif "详细" in feedback or "展开" in feedback or score > 0.8:
            if self.verbosity != "detailed":
                self.verbosity = "detailed"
                self.verbosity_weight = min(2.0, self.verbosity_weight + self.learning_rate)
                adjustments.append(f"详细度 → 详细 (score={score:.2f})")
        
        # 2. 调整emoji使用
        if "别用emoji" in feedback or "不要表情" in feedback:
            if self.use_emoji:
                self.use_emoji = False
                self.emoji_weight = max(0.1, self.emoji_weight - self.learning_rate)
                adjustments.append("emoji → 禁用")
        elif "多emoji" in feedback or "表情不错" in feedback:
            if not self.use_emoji:
                self.use_emoji = True
                self.emoji_weight = min(2.0, self.emoji_weight + self.learning_rate)
                adjustments.append("emoji → 启用")
        
        # 3. 调整结构化
        if "别分段" in feedback or "不要结构" in feedback:
            if self.structured:
                self.structured = False
                self.structured_weight = max(0.1, self.structured_weight - self.learning_rate)
                adjustments.append("结构化 → 禁用")
        elif "结构不错" in feedback or "分段好" in feedback:
            if not self.structured:
                self.structured = True
                self.structured_weight = min(2.0, self.structured_weight + self.learning_rate)
                adjustments.append("结构化 → 启用")
        
        # 4. 根据评分调整正式程度
        if score < 0.3:
            # 评分很低，可能是风格不匹配
            self.formalness = max(0.0, self.formalness - self.learning_rate * 2)
            adjustments.append(f"正式程度降低 (score={score:.2f})")
        elif score > 0.9:
            # 评分很高，保持当前风格
            self.formalness = min(1.0, self.formalness + self.learning_rate * 0.5)
            adjustments.append(f"正式程度提升 (score={score:.2f})")
        
        # 记录调整历史
        if adjustments:
            self.adjustment_history.append({
                "timestamp": datetime.now().isoformat(),
                "feedback": feedback,
                "score": score,
                "adjustments": adjustments
            })
            self.last_adjustment = datetime.now().isoformat()
        
        return adjustments
    
    def adjust_based_on_metacognition(self, metacognition_result: Dict):
        """根据元认知评估结果调整人设
        
        Args:
            metacognition_result: 元认知评估结果，包含overall_score等
        """
        if not metacognition_result:
            return []
        
        overall_score = metacognition_result.get("overall_score", 0.5)
        task_type = metacognition_result.get("task_type", "unknown")
        adjustments = []
        
        # 如果任务表现差，调整人设参数
        if overall_score < 0.5:
            # 可能是输出格式不适合该任务类型
            if task_type == "code_generation" and self.structured:
                # 代码生成可能不需要太多结构化
                self.structured = False
                self.structured_weight = max(0.1, self.structured_weight - self.learning_rate)
                adjustments.append(f"任务{task_type}表现差，关闭结构化输出")
            
            elif task_type == "conversation" and not self.use_emoji:
                # 对话任务可能更适合用emoji
                self.use_emoji = True
                self.emoji_weight = min(2.0, self.emoji_weight + self.learning_rate)
                adjustments.append(f"任务{task_type}表现差，启用emoji")
        
        # 记录
        if adjustments:
            self.adjustment_history.append({
                "timestamp": datetime.now().isoformat(),
                "trigger": "metacognition",
                "task_type": task_type,
                "score": overall_score,
                "adjustments": adjustments
            })
            self.last_adjustment = datetime.now().isoformat()
        
        return adjustments
    
    def get_prompt_instructions(self) -> str:
        """生成用于提示词的人设指令"""
        instructions = []
        
        # 风格
        style_map = {
            "professional": "严谨、高效、专业",
            "tieguai": "直爽、不推诿、东北话风格",
            "humorous": "轻松、有趣、幽默",
            "custom": "自定义风格"
        }
        style_desc = style_map.get(self.style, "专业")
        instructions.append(f"你是一个{style_desc}的助手。")
        
        # 输出格式
        if self.structured:
            instructions.append("使用结构化输出：emoji图标、短段落（2-3行）、清晰分段、项目符号•和---分隔。")
        else:
            instructions.append("使用自然段落输出，无需特殊格式。")
        
        # 详细度
        if self.verbosity == "concise":
            instructions.append("回复要简洁直接，避免冗长。")
        elif self.verbosity == "detailed":
            instructions.append("回复要详细全面，包含背景知识和原理。")
        else:
            instructions.append("回复要平衡详略，重点突出。")
        
        # emoji
        if not self.use_emoji:
            instructions.append("不要使用emoji表情。")
        
        return "\n".join(instructions)


class PersonaEvolutionSystem:
    """人设进化系统 - 管理动态人设调整"""
    
    def __init__(self, profile_path: str = None):
        if profile_path is None:
            profile_path = Path.home() / ".dogeey" / "persona_params.json"
        self.params_path = Path(profile_path)
        self.params_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 加载参数
        self.parameters = self._load_parameters()
        
        # 调整统计
        self.total_adjustments = 0
        self.positive_adjustments = 0
    
    def _load_parameters(self) -> PersonaParameters:
        """加载人设参数"""
        if self.params_path.exists():
            try:
                with open(self.params_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return PersonaParameters.from_dict(data)
            except Exception as e:
                print(f"⚠️ 加载人设参数失败: {e}")
        
        return PersonaParameters()
    
    def save_parameters(self):
        """保存人设参数"""
        try:
            with open(self.params_path, 'w', encoding='utf-8') as f:
                json.dump(self.parameters.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 保存人设参数失败: {e}")
    
    def process_user_feedback(self, feedback: str, score: float) -> List[str]:
        """处理用户反馈，调整人设
        
        Returns:
            调整列表（用于日志）
        """
        adjustments = self.parameters.adjust_based_on_feedback(feedback, score)
        
        if adjustments:
            self.total_adjustments += len(adjustments)
            if score >= 0.5:
                self.positive_adjustments += 1
            
            self.save_parameters()
            print(f"🎭 人设已调整: {', '.join(adjustments)}")
        
        return adjustments
    
    def process_metacognition(self, metacognition_result: Dict) -> List[str]:
        """处理元认知结果，调整人设
        
        Returns:
            调整列表（用于日志）
        """
        adjustments = self.parameters.adjust_based_on_metacognition(metacognition_result)
        
        if adjustments:
            self.total_adjustments += len(adjustments)
            self.save_parameters()
            print(f"🎭 人设已根据元认知调整: {', '.join(adjustments)}")
        
        return adjustments
    
    def get_current_persona_prompt(self) -> str:
        """获取当前人设的提示词指令"""
        return self.parameters.get_prompt_instructions()
    
    def reset_to_defaults(self):
        """重置为人设默认值"""
        self.parameters = PersonaParameters()
        self.save_parameters()
        print("🎭 人设已重置为默认值")
    
    def get_evolution_report(self) -> str:
        """生成人设进化报告"""
        lines = []
        lines.append("🎭 人设进化报告")
        lines.append("=" * 50)
        
        params = self.parameters
        lines.append(f"\n当前人设风格: {params.style}")
        lines.append(f"详细度: {params.verbosity} (权重: {params.verbosity_weight:.2f})")
        lines.append(f"结构化输出: {'✅' if params.structured else '❌'} (权重: {params.structured_weight:.2f})")
        lines.append(f"Emoji使用: {'✅' if params.use_emoji else '❌'} (权重: {params.emoji_weight:.2f})")
        lines.append(f"正式程度: {params.formalness:.2f}")
        lines.append(f"学习率: {params.learning_rate:.2f}")
        lines.append(f"适应度: {params.adaptability:.2f}")
        
        lines.append(f"\n总调整次数: {self.total_adjustments}")
        if self.total_adjustments > 0:
            positive_rate = self.positive_adjustments / self.total_adjustments
            lines.append(f"积极调整比例: {positive_rate:.1%}")
        
        # 最近调整
        if params.adjustment_history:
            lines.append("\n最近调整:")
            for adj in params.adjustment_history[-5:]:
                timestamp = adj.get("timestamp", "")[:19]
                trigger = adj.get("trigger", "feedback")
                score = adj.get("score", 0)
                adjustments = adj.get("adjustments", [])
                lines.append(f"  {timestamp} ({trigger}, score={score:.2f})")
                for a in adjustments:
                    lines.append(f"    - {a}")
        
        return "\n".join(lines)


# 导出
__all__ = ['PersonaParameters', 'PersonaEvolutionSystem']
