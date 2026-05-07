"""
智能体核心 - ReAct引擎 + 任务监督系统
"""
import json
import re
import time
from typing import List, Dict, Optional, Any
from .llm import LLMClient
from .tools import ToolRegistry
from .memory import MemorySystem
from .profile import UserProfile
from .skills import SkillManager
from .task_supervisor import TaskStatus, ErrorType, TaskResult, RetryPolicy
from .metacognition import MetaCognition
from .context_compressor import ContextCompressor


# ReAct提示词模板（强化版 - 文本ReAct模式专用）
REACT_PROMPT = """你是一个智能助手，可以使用工具来完成任务。

{user_profile}

## 可用工具:
{tools_description}

## 相关记忆:
{memories}

## 核心规则（必须遵守）:
1. **必须**使用工具来完成任务，不要直接回答——即使是简单的"hello"也要用工具
2. **必须**严格按照下面的格式输出——不要输出任何格式外的内容
3. 每次只能执行一个工具调用
4. Action必须是上述可用工具之一
5. Action Input必须是有效的JSON格式
6. 工具调用后等待Observation，不要自己编造Observation
7. 只有确定最终答案后，才输出Final Answer
8. **严禁**输出推理过程或解释，只输出Thought/Action/Final Answer格式
9. **严禁**输出"让我想想"、"回顾规则"等内心独白

## 输出格式（严格遵循，只输出这些，其他一概不要）:

**如果需要调用工具:**
```
Thought: [你的思考过程]
Action: [工具名称]
Action Input: {{"参数名": "参数值"}}
```

**如果已获得足够信息，给出最终答案:**
```
Thought: 我现在知道最终答案了
Final Answer: [给用户的最终回答]
```

## 重要提示:
- 不要输出Observation，Observation是系统提供的
- 不要同时输出多个Action
- 如果不知道答案，使用搜索工具，不要瞎编
- **严禁**在没有调用工具的情况下直接给出Final Answer

## 示例对话:

用户: 北京今天天气怎么样？
助手:
Thought: 我需要查询北京的天气信息，应该使用weather工具
Action: weather
Action Input: {{"city": "北京"}}

Observation: {{"city": "北京", "temperature": "15°C", "condition": "晴"}}

助手:
Thought: 我已经获得了北京的天气信息，可以回答用户了
Final Answer: 北京今天天气晴朗，气温15°C，适合外出活动。

---
现在开始回答用户的问题（记住：必须先调用工具，不要直接回答）:
"""


FUNCTION_CALLING_PROMPT = """你是一个智能助手，名叫"铁蛋"（Dogeey）。你的职责是诚实、不推诿、不糊弄、解决问题。

{user_profile}

## 你的能力：
你有大量可用工具来帮助用户完成任务。**每次收到用户消息，你必须选择并调用至少一个工具**，即使是简单的问候也要用工具（如 tool_list_all 或 read_file）来做点什么。

## 核心规则：
1. 绝对不要直接回答用户问题，必须通过工具调用
2. 即使你觉得"这不需要工具"，也必须随便选一个工具用
3. 工具调用后，根据工具结果再给出最终答案
4. 如果你不知道答案，用工具去查；不要猜测

## 回答风格:
- 简洁实用，直奔主题
- 不啰嗦、不卖弄
- 像有经验的老工程师一样说话

## 相关记忆:
{memories}
"""


class AgentCore:
    """智能体核心 - ReAct模式 + 任务监督 + 元认知 + ContextFlow"""
    
    def __init__(self, llm_client: LLMClient, tool_registry: ToolRegistry, 
                 memory_system: Optional[MemorySystem] = None,
                 user_profile: Optional[UserProfile] = None,
                 skill_manager: Optional[SkillManager] = None,
                 max_iterations: int = 100,
                 session_manager: Optional[Any] = None,
                 loaded_skills: Optional[List[Dict]] = None,
                 data_dir: str = None):
        self.llm = llm_client
        self.tools = tool_registry
        self.memory = memory_system
        self.profile = user_profile
        self.skills = skill_manager
        self.max_iterations = max_iterations
        self.session_manager = session_manager
        # 短期记忆现在从session_manager获取，这里保留作为fallback
        self.short_term_memory = []  # 短期记忆（当前会话）
        # 已加载的技能（通过/skill load命令加载）
        self.loaded_skills = loaded_skills or []
        # 元认知模块（自我学习系统）
        self.metacognition = MetaCognition(data_dir=data_dir)
        print("🧠 元认知模块已加载")
        
        # Context压缩器（参考Hermes）
        self.context_compressor = ContextCompressor(llm_client=self.llm)
        print("🧮 Context压缩器已加载")
        try:
            from dogeey.context_flow import ContextManager
            self.context_manager = ContextManager(llm_client=llm_client)
            self._current_context_id = None
            print("🔄 ContextFlow话题流已加载")
        except ImportError:
            self.context_manager = None
            self._current_context_id = None
            print("⚠️ ContextFlow未安装，话题流功能不可用")
        except Exception as e:
            self.context_manager = None
            self._current_context_id = None
            print(f"⚠️ ContextFlow初始化失败: {e}")
#     
    def run(self, user_input: str, verbose: bool = False) -> str:
        """
        执行用户指令（带监督系统）
        返回: 最终回答字符串
        """
        # ContextFlow：如果context_manager可用，使用它
        context = None
        if hasattr(self, 'context_manager') and self.context_manager:
            context = self.context_manager.get_context_for_input(user_input)
            if hasattr(self, '_current_context_id'):
                self._current_context_id = context.id
            
            if verbose:
                active_ctx = self.context_manager.get_active_context()
                if active_ctx:
                    print(f"🔄 使用上下文: {active_ctx.title} ({active_ctx.message_count}条消息)")
        
        # 检查是否需要求助（元认知：知道自己不行）
        should_ask, reason, suggestion = self.metacognition.should_ask_help(user_input)
        if should_ask and verbose:
            print(f"🤔 元认知提醒: {reason}")
            print(f"💡 {suggestion}")
        
        # 将用户输入添加到上下文（如果可用）
        if context:
            context.add_message("user", user_input)
        
        # 创建任务监督器
        print(f"🔍 DEBUG: run() - 准备创建TaskSupervisor, verbose={verbose}")
        supervisor = TaskSupervisor(
            max_iterations=self.max_iterations,
            verbose=verbose
        )
        print(f"🔍 DEBUG: run() - TaskSupervisor已创建")
        
        # 执行任务
        print(f"🔍 DEBUG: run() - 准备调用supervisor.execute()")
        result = supervisor.execute(
            agent_core=self,
            user_input=user_input
        )
        print(f"🔍 DEBUG: run() - supervisor.execute()已返回, result={result.status if result else None}")
        
        # 元认知：记录任务执行结果
        _ctx_id = getattr(self, '_current_context_id', None)
        if result.is_success():
            if context:
                context.add_message("assistant", result.answer)
            
            self.metacognition.record_task_execution(
                user_input=user_input,
                success=True,
                duration=result.duration,
                tool_calls_count=len(result.tool_calls) if result.tool_calls else 0,
                context_id=_ctx_id
            )
            
            self._update_memory_and_profile(user_input, {
                "final_answer": result.answer
            }, result.tool_calls or [])
            
            if result.tool_calls and len(result.tool_calls) >= 2:
                try:
                    self.evolve_skill_from_task(
                        user_input=user_input,
                        tool_calls=result.tool_calls,
                        final_answer=result.answer
                    )
                except Exception as e:
                    if verbose:
                        print(f"⚠️ 技能进化失败: {e}")
            
            try:
                assessment = self.metacognition.self_assess(
                    user_input=user_input,
                    final_answer=result.answer,
                    task_result=result
                )
                if verbose:
                    print(f"\n🧠 元认知自我评估:")
                    print(f"   综合得分: {assessment['overall_score']:.2f}")
                    print(f"   反思: {assessment['reflection']}")
                    if assessment['improvement_suggestions']:
                        print(f"   改进建议: {', '.join(assessment['improvement_suggestions'])}")
            except Exception as e:
                if verbose:
                    print(f"⚠️ 元认知评估失败: {e}")
            
            return result.answer
        else:
            # 失败：记录失败
            self.metacognition.record_task_execution(
                user_input=user_input,
                success=False,
                error_type=result.error_type.value if result.error_type else None,
                context_id=_ctx_id
            )
            
            # 失败反思
            try:
                assessment = self.metacognition.self_assess(
                    user_input=user_input,
                    final_answer="",
                    task_result=result
                )
                if verbose:
                    print(f"\n🧠 元认知失败反思:")
                    print(f"   综合得分: {assessment['overall_score']:.2f}")
                    print(f"   反思: {assessment['reflection']}")
            except Exception as e:
                pass
            
            # 失败：返回明确的错误信息
            return f"❌ 任务执行失败\n原因: {result.error_msg}\n类型: {result.error_type.value}"
    
    def run_with_result(self, user_input: str, verbose: bool = False) -> TaskResult:
        """
        执行用户指令（返回完整TaskResult）
        用于需要详细信息的场景
        """
        supervisor = TaskSupervisor(
            max_iterations=self.max_iterations,
            verbose=verbose
        )
        return supervisor.execute(
            agent_core=self,
            user_input=user_input
        )
    
    def _build_function_calling_messages(self, user_input: str, include_history: bool = True, context: Any = None) -> List[Dict]:
        """
        构建用于function calling模式的消息列表
        与文本ReAct不同，这里不用教LLM输出格式，只描述角色和规则
        """
        profile_context = ""
        if self.profile:
            profile_context = self.profile.get_prompt_context()

        memories_context = ""
        if self.memory:
            relevant_memories = self.memory.search_memories(user_input, limit=3)
            if relevant_memories:
                memories_context = "\n".join([f"- {mem['content']}" for mem in relevant_memories])

        skill_context = ""
        if self.skills:
            for loaded_skill in self.loaded_skills:
                if loaded_skill.get('content'):
                    skill_context += f"\n\n### 技能: {loaded_skill['name']}\n{loaded_skill['content']}"
            recommended_skills = self.skills.recommend_skills(user_input, limit=2)
            for skill in recommended_skills:
                if skill.name not in [s['name'] for s in self.loaded_skills]:
                    full_skill = self.skills.load_skill(skill.name)
                    if full_skill and hasattr(full_skill, 'full_content') and full_skill.full_content:
                        skill_context += f"\n\n### 技能: {skill.name}\n{full_skill.full_content}"

        system_content = FUNCTION_CALLING_PROMPT.format(
            user_profile=profile_context,
            memories=memories_context
        )
        if skill_context:
            system_content += f"\n\n## 参考技能文档:\n{skill_context}"

        messages = [{"role": "system", "content": system_content}]

        if include_history:
            active_context = None
            if context:
                active_context = context
            elif hasattr(self, 'context_manager') and self.context_manager:
                active_context = self.context_manager.get_active_context()

            if active_context:
                recent_msgs = active_context.messages[-12:]
                if hasattr(active_context, 'title') and active_context.title:
                    messages[0]["content"] += f"\n[当前话题: {active_context.title}]"
                messages.extend(recent_msgs)
            else:
                history = []
                if self.session_manager:
                    history = self.session_manager.get_current_memory()
                else:
                    history = self.short_term_memory
                if history:
                    recent_turns = history[-6:]
                    for turn in recent_turns:
                        messages.append({"role": "user", "content": turn['user']})
                        messages.append({"role": "assistant", "content": turn['assistant']})

        messages.append({"role": "user", "content": user_input})

        # Context压缩（参考Hermes）
        if hasattr(self, 'context_compressor') and self.context_compressor:
            messages = self.context_compressor.compress(messages, self.llm.model)

        return messages

    def _build_messages(self, user_input: str, include_history: bool = True, context: Any = None) -> List[Dict]:
        """
        构建LLM消息列表（支持上下文连续对话）
        参考Hermes机制：
        1. System消息包含工具描述、用户画像、相关记忆
        2. 历史对话作为独立的user/assistant消息
        3. 当前问题作为最后一条user消息
        
        新增：如果传入context，使用context的消息作为历史
              如果没传context，尝试从context_manager获取当前活跃上下文
        """
        # 工具描述（Level 2: 渐进式披露 - 名称+一句话描述）
        tools_desc = self.tools.get_tools_brief()
        
        # 长期记忆（相关记忆）
        memories_context = ""
        if self.memory:
            relevant_memories = self.memory.search_memories(user_input, limit=3)
            if relevant_memories:
                memories_context = "相关记忆:\n"
                for mem in relevant_memories:
                    memories_context += f"- {mem['content']}\n"
        
        # 用户画像上下文
        profile_context = ""
        if self.profile:
            profile_context = self.profile.get_prompt_context()
        
        # 技能推荐（渐进式披露）
        skill_context = ""
        if self.skills:
            # 1. 加载手动加载的技能（通过/skill load命令）
            for loaded_skill in self.loaded_skills:
                if loaded_skill.get('content'):
                    skill_context += f"\n\n### 技能: {loaded_skill['name']}\n"
                    skill_context += loaded_skill['content']
            
            # 2. 推荐相关技能（自动推荐，limit=2）
            recommended_skills = self.skills.recommend_skills(user_input, limit=2)
            for skill in recommended_skills:
                # 避免重复加载
                if skill.name not in [s['name'] for s in self.loaded_skills]:
                    full_skill = self.skills.load_skill(skill.name)
                    if full_skill and hasattr(full_skill, 'full_content') and full_skill.full_content:
                        skill_context += f"\n\n### 技能: {skill.name}\n"
                        skill_context += full_skill.full_content
            
            # 将技能上下文添加到tools_desc（如果有的话）
            if skill_context:
                tools_desc += "\n\n## 可用技能（参考）\n"
                tools_desc += "以下是你可以参考的技能文档，根据用户问题选择合适的技能："
                tools_desc += skill_context
                tools_desc += "\n\n注意：技能文档是参考性的，你可以根据情况调整使用。"
        
        # 构建System消息（不包含对话历史）
        system_content = REACT_PROMPT.format(
            user_profile=profile_context,
            tools_description=tools_desc,
            memories=memories_context,
            user_input="",  # 当前问题不放在system里
            short_term_memory=""  # 历史对话不放在system里
        )
        
        messages = [
            {"role": "system", "content": system_content}
        ]
        
        # 添加历史对话（作为独立的user/assistant消息）
        if include_history:
            # 决定使用哪个上下文
            active_context = None
            if context:
                active_context = context
            elif hasattr(self, 'context_manager') and self.context_manager:
                active_context = self.context_manager.get_active_context()
            
            if active_context:
                # 使用context的消息历史
                # 注意：过滤掉system角色消息，避免与messages[0]冲突导致NotFirstSystem错误
                all_msgs = active_context.messages[-12:]
                recent_msgs = [m for m in all_msgs if m.get("role") != "system"]
                
                # 如果有标题，合并到主system消息中
                if hasattr(active_context, 'title') and active_context.title:
                    messages[0]["content"] += f"\n[当前话题: {active_context.title}]"
                
                messages.extend(recent_msgs)
                if getattr(self, 'verbose', False):
                    print(f"📜 使用上下文历史: {len(recent_msgs)}条消息")
            else:
                # 原有逻辑：从session_manager获取
                history = []
                if self.session_manager:
                    history = self.session_manager.get_current_memory()
                else:
                    history = self.short_term_memory
                
                # 添加历史对话
                if history:
                    recent_turns = history[-6:]  # 最近6轮
                    for turn in recent_turns:
                        messages.append({"role": "user", "content": turn['user']})
                        messages.append({"role": "assistant", "content": turn['assistant']})
        
        # 添加当前用户问题
        messages.append({
            "role": "user",
            "content": user_input
        })

        # Context压缩（参考Hermes）
        if hasattr(self, 'context_compressor') and self.context_compressor:
            messages = self.context_compressor.compress(messages, self.llm.model)

        return messages
    
    def _update_memory_and_profile(self, user_input: str, parsed: Dict, tool_calls: List[Dict]):
        """更新记忆系统和用户画像"""
        # 获取最终答案
        final_answer = parsed.get("final_answer") or ""
        
        # 更新短期记忆：优先使用session_manager
        if self.session_manager:
            self.session_manager.add_to_current_session(user_input, final_answer)
        else:
            # Fallback: 使用原来的short_term_memory
            self.short_term_memory.append({
                "user": user_input,
                "assistant": final_answer
            })
            # 限制短期记忆长度
            if len(self.short_term_memory) > 10:
                self.short_term_memory.pop(0)
        
        # 更新长期记忆
        if self.memory:
            self.memory.add_long_term(
                content=f"用户: {user_input}\n助手: {final_answer}",
                category="conversation"
            )
        
        # 更新用户画像
        if self.profile:
            self.profile.learn_from_interaction(
                user_input=user_input,
                assistant_response=final_answer,
                tool_calls=tool_calls
            )
        
        # 更新技能使用统计
        if self.skills and tool_calls:
            for call in tool_calls:
                if 'tool' in call:
                    self.skills.update_skill_usage(call['tool'], success=True)
    
    def clear_memory(self):
        """清除短期记忆"""
        self.short_term_memory = []
    
    def get_metacognition_report(self) -> str:
        """获取元认知状态报告（对外接口）"""
        return self.metacognition.generate_status_report()
    
    def get_blindspots(self) -> List[Dict]:
        """获取盲区列表"""
        return self.metacognition.get_blindspots()
    
    def resolve_blindspot(self, task_type: str):
        """标记盲区已解决"""
        self.metacognition.resolve_blindspot(task_type)
    
    def get_learning_plan(self) -> Dict:
        """获取学习计划"""
        return self.metacognition.generate_learning_plan()
    
    def rate_response(self, user_input: str, rating: str) -> str:
        """处理用户反馈评分
        
        Args:
            user_input: 原始用户输入
            rating: 评分字符串，如 "5星"、"3分"、"great"等
        
        Returns:
            反馈确认消息
        """
        if not self.metacognition:
            return "❌ 元认知模块未初始化"
        
        # 获取最近的任务类型
        task_type = self.metacognition._classify_task(user_input)
        
        # 解析评分
        score = self.metacognition._parse_user_feedback(rating)
        if score is None:
            return f"❌ 无法解析评分: {rating}\n请使用格式: 5星、3分、5、great等"
        
        # 更新最近一次执行记录的反馈
        if task_type in self.metacognition.competence_map["task_types"]:
            stats = self.metacognition.competence_map["task_types"][task_type]
            if stats["recent_results"]:
                stats["recent_results"][-1]["user_feedback"] = rating
                # 重新计算置信度（考虑用户反馈）
                sample_factor = min(1.0, stats["total_count"] / 20.0)
                # 用户反馈影响置信度
                user_confidence = score
                stats["confidence"] = (stats["success_rate"] * sample_factor + 
                                        user_confidence * 0.3 + 
                                        0.3 * (1 - sample_factor))
                
                # 保存到文件
                self.metacognition._save_json(
                    self.metacognition.competence_file, 
                    self.metacognition.competence_map
                )
                
                return f"✅ 感谢反馈！评分 {rating} 已记录 (得分: {score:.1f}/1.0)"
        
        return "⚠️ 未找到对应任务记录"
    
    def evolve_skill_from_task(self, user_input: str, tool_calls: List[Dict], final_answer: str) -> Optional[Dict]:
        """
        从任务执行经验生成技能（自我进化）
        返回生成的技能数据，如果不需要生成则返回None
        """
        if not self.skills:
            return None
        
        # 1. 检查是否值得生成技能（复杂度判断）
        if not self._is_task_complex_enough(user_input, tool_calls):
            return None
        
        # 2. 构造prompt，让LLM生成技能文档
        skill_prompt = self._build_skill_generation_prompt(user_input, tool_calls, final_answer)
        
        # 3. 调用LLM生成技能
        try:
            skill_response = self.llm.chat([
                {"role": "system", "content": "你是一个技能文档生成器。根据任务执行历史，生成可复用的技能文档。"},
                {"role": "user", "content": skill_prompt}
            ], temperature=0.3)
        except Exception as e:
            print(f"⚠️ 技能生成失败: {e}")
            return None
        
        # 4. 解析LLM响应，提取技能数据
        skill_data = self._parse_skill_response(skill_response, user_input)
        if not skill_data:

            return None
        
        # 5. 注册技能到技能库
        try:
            self.skills.register_skill(
                name=skill_data['name'],
                category=skill_data.get('category', 'auto-generated'),
                description=skill_data.get('description', user_input),
                trigger_keywords=skill_data.get('trigger_keywords', []),
                full_content=skill_data.get('full_content', skill_response)
            )
            print(f"🧬 技能自我进化: 新技能 '{skill_data['name']}' 已生成并注册")
            return skill_data
        except Exception as e:
            print(f"⚠️ 技能注册失败: {e}")
            return None
    
    def _is_task_complex_enough(self, user_input: str, tool_calls: List[Dict]) -> bool:
        """判断任务是否复杂到值得生成技能"""
        # 条件1: 工具调用次数 >= 3
        if len(tool_calls) >= 3:
            return True
        
        # 条件2: 任务描述包含多个步骤关键词
        step_keywords = ['然后', '接着', '再', '最后', '第一步', '第二步', '首先', '其次', '然后']
        if any(kw in user_input for kw in step_keywords):
            return True
        
        # 条件3: 使用了多种不同的工具
        unique_tools = set(call.get('tool', '') for call in tool_calls)
        if len(unique_tools) >= 2:
            return True
        
        return False
    
    def _build_skill_generation_prompt(self, user_input: str, tool_calls: List[Dict], final_answer: str) -> str:
        """构造技能生成prompt"""
        tool_calls_str = "\n".join([
            f"- {call.get('tool', 'unknown')}: {call.get('args', {})}"
            for call in tool_calls
        ])
        
        return f"""请根据以下任务执行历史，生成一个可复用的技能文档。

## 任务描述
{user_input}

## 执行的工具调用
{tool_calls_str}

## 最终答案
{final_answer}

## 要求
生成一个技能文档，包含：
1. YAML frontmatter（name, category, description, trigger_keywords）
2. Markdown格式的步骤说明
3. 示例代码或命令（如果有）

格式：
---
name: skill-name
category: appropriate-category
description: 简短描述
trigger_keywords:
  - keyword1
  - keyword2
---

# 技能名称

## 适用场景
...

## 步骤
...

## 注意事项
...

请只返回技能文档内容，不要添加其他解释。"""
    
    def _parse_skill_response(self, response: str, user_input: str) -> Optional[Dict]:
        """解析LLM响应，提取技能数据"""
        import re
        try:
            import yaml
        except ImportError:
            yaml = None
        
        # 尝试解析YAML frontmatter
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, response, re.DOTALL)
        
        if match:
            try:
                if yaml is None:
                    raise ImportError("PyYAML not installed")
                metadata = yaml.safe_load(match.group(1))
                full_content = match.group(2)
                
                # 生成技能名称（如果YAML中没有）
                name = metadata.get('name')
                if not name:
                    # 从用户输入生成一个简短的名称
                    name = user_input.replace(' ', '-')[:30].lower()
                
                return {
                    'name': name,
                    'category': metadata.get('category', 'auto-generated'),
                    'description': metadata.get('description', user_input),
                    'trigger_keywords': metadata.get('trigger_keywords', []),
                    'full_content': response
                }
            except Exception as e:
                print(f"⚠️ 解析技能YAML失败: {e}")
        
        # 如果没有YAML frontmatter，使用整个响应作为内容
        name = user_input.replace(' ', '-')[:30].lower()
        return {
            'name': name,
            'category': 'auto-generated',
            'description': user_input,
            'trigger_keywords': [],
            'full_content': response
        }


class TaskSupervisor:
    """
    ReAct引擎执行器（唯一版本，已合并 task_supervisor.py）
    优先使用 function calling 模式（轻量 prompt，不会崩 Astron）
    文本 ReAct 作为 fallback
    """

    def __init__(self, max_iterations: int = 10, verbose: bool = False,
                 mode: str = "auto"):
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.mode = mode
        self.retry_policy = RetryPolicy()
        self._logger = __import__("logging").getLogger(__name__)

    def execute(self, agent_core: AgentCore, user_input: str) -> TaskResult:
        print(f"🔍 DEBUG: 进入execute(), user_input={user_input[:50]}")
        start_time = time.time()
        try:
            self.retry_policy.reset()
            self._tool_calls = []
            self._tool_call_made = False

            mode = self._detect_mode(agent_core)
            if self.verbose:
                self._logger.info(f"🚀 ReAct引擎启动 (模式: {mode}, 最大迭代: {self.max_iterations})")
            
            # 简单问候：直接回复（不调用工具）
            simple_greetings = ["你好", "hi", "hello", "嗨", "嗨~", "你好！", "hi！", "hello！"]
            user_input_lower = user_input.lower()
            is_simple_greeting = False
            for g in simple_greetings:
                if g in user_input_lower:
                    is_simple_greeting = True
                    break
            
            # 强制使用ReAct引擎，不跳过 - 老板要求所有请求必须走ReAct
            # if is_simple_greeting:
            #     if self.verbose:
            #         self._logger.info(f"   💬 简单问候，使用直接回复模式")
            #     return self._execute_direct_reply(agent_core, user_input, start_time)
            
            if mode == "function_calling":
                return self._execute_function_calling(agent_core, user_input, start_time)
            else:
                return self._execute_text_react(agent_core, user_input, start_time)
        except Exception as e:
            duration = time.time() - start_time
            if self.verbose:
                import traceback
                self._logger.error(traceback.format_exc())
            return TaskResult(
                status=TaskStatus.FAILED,
                error_type=ErrorType.LLM_ERROR,
                error_msg=str(e),
                duration=duration
            )

    def _detect_mode(self, agent_core: AgentCore) -> str:
        """检测应该使用哪种模式"""
        if self.mode != "auto":
            return self.mode
        # 默认使用function_calling模式
        return "function_calling"

    def _execute_direct_reply(self, agent_core: AgentCore, user_input: str, start_time: float) -> TaskResult:
        """直接回复模式（不调用工具）"""
        if self.verbose:
            self._logger.info(f"   💬 直接回复模式（不调用工具）")
        
        # 构建简单消息：只用system+user，不调工具
        messages = [
            {"role": "system", "content": "你是智能助手，请直接回复用户，简洁友好。"},
            {"role": "user", "content": user_input}
        ]
        
        try:
            response_text = agent_core.llm.chat(messages)
            duration = time.time() - start_time
            if self.verbose:
                self._logger.info(f"   ✅ 直接回复完成 ({duration:.2f}秒)")
            return TaskResult(
                status=TaskStatus.SUCCESS,
                answer=response_text or "你好！",
                steps=1,
                duration=duration
            )
        except Exception as e:
            duration = time.time() - start_time
            return TaskResult(
                status=TaskStatus.FAILED,
                error_type=ErrorType.LLM_ERROR,
                error_msg=f"直接回复失败: {str(e)}",
                duration=duration
            )

    def _execute_function_calling(self, agent_core: AgentCore, user_input: str, start_time: float) -> TaskResult:
        messages = agent_core._build_function_calling_messages(user_input)
        tool_schemas = agent_core.tools.get_tools_schema()
        fc_no_tool_count = 0

        for step in range(1, self.max_iterations + 1):
            if self.verbose:
                self._logger.info(f"🔄 FC步骤 {step}/{self.max_iterations}")

            try:
                response_msg = agent_core.llm.chat_with_tools(
                    messages=messages,
                    tools=tool_schemas
                )

                if hasattr(response_msg, 'tool_calls') and response_msg.tool_calls:
                    fc_no_tool_count = 0
                    self._tool_call_made = True
                    for tool_call in response_msg.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args_str = tool_call.function.arguments

                        if self.verbose:
                            self._logger.info(f"   🔧 调用: {tool_name}, args: {tool_args_str[:100]}")

                        if isinstance(tool_args_str, str):
                            try:
                                tool_args = json.loads(tool_args_str)
                            except json.JSONDecodeError:
                                tool_args = {"raw": tool_args_str}
                        else:
                            tool_args = tool_args_str

                        tool_result = agent_core.tools.execute(tool_name, tool_args)

                        if self.verbose:
                            self._logger.info(f"   📊 结果: {str(tool_result)[:100]}")

                        messages.append({
                            "role": "assistant",
                            "content": response_msg.content or "",
                            "tool_calls": [{
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": tool_args_str if isinstance(tool_args_str, str) else json.dumps(tool_args_str)
                                }
                            }]
                        })
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(tool_result)
                        })
                        self._record_tool_call(tool_name, tool_args, str(tool_result))
                else:
                    if self._tool_call_made:
                        # 已经调用过工具，接受当前消息作为最终答案
                        final_answer = response_msg.content or ""
                        duration = time.time() - start_time
                        return TaskResult(status=TaskStatus.SUCCESS, answer=final_answer,
                                          steps=step, tool_calls=self._tool_calls, duration=duration)
                    fc_no_tool_count += 1
                    if self.verbose:
                        self._logger.warning(f"⚠️ 模型未调用工具 (第{fc_no_tool_count}次)，内容: {(response_msg.content or '')[:150]}")

                    if fc_no_tool_count >= 2:
                        if self.verbose:
                            self._logger.info(f"🔄 连续{fc_no_tool_count}次不调用工具，切换文本ReAct")
                        return self._execute_text_react(agent_core, user_input, start_time)

                    messages.append({"role": "assistant", "content": response_msg.content or ""})
                    messages.append({"role": "user", "content": f"上一轮没有调用任何工具。必须使用工具来完成 '{user_input}'。请选择一个合适的工具。"})

            except Exception as e:
                if self.verbose:
                    self._logger.warning(f"⚠️ FC异常，切换文本ReAct: {e}")
                return self._execute_text_react(agent_core, user_input, start_time)

        duration = time.time() - start_time
        return TaskResult(status=TaskStatus.TIMEOUT, error_type=ErrorType.TIMEOUT,
                          error_msg=f"达到最大迭代 ({self.max_iterations})", steps=self.max_iterations, duration=duration)

    def _execute_text_react(self, agent_core: AgentCore, user_input: str, start_time: float) -> TaskResult:
        print(f"🔍 DEBUG: 进入_execute_text_react(), user_input={user_input[:50]}")
        
        messages = agent_core._build_messages(user_input)

        for step in range(1, self.max_iterations + 1):
            if self.verbose:
                self._logger.info(f"🔄 ReAct步骤 {step}/{self.max_iterations}")
            
            try:
                response_text = agent_core.llm.chat(messages)
                
                # 检查连续空回复（防止死循环）
                if not response_text or not response_text.strip():
                    self._empty_reply_count = getattr(self, '_empty_reply_count', 0) + 1
                    if self._empty_reply_count >= 3:
                        duration = time.time() - start_time
                        self._logger.error(f"❌ 连续{self._empty_reply_count}次空回复，跳出循环")
                        return TaskResult(
                            status=TaskStatus.FAILED,
                            error_type=ErrorType.LLM_ERROR,
                            error_msg=f"LLM连续返回空回复（可能不理解消息格式），已尝试{self._empty_reply_count}次",
                            steps=step,
                            duration=duration
                        )
                    
                    if self.verbose:
                        self._logger.warning(f"⚠️ 步骤 {step}: 空回复（连续第{self._empty_reply_count}次）")
                    messages.append({"role": "assistant", "content": ""})
                    continue
                else:
                    # 重置空回复计数
                    self._empty_reply_count = 0

                if self.verbose:
                    self._logger.info(f"   💭 回复: {response_text[:150]}...")

                # 成功解析，重置无效回复计数
                self._invalid_reply_count = 0
                
                parsed = self._parse_react_response(response_text)

                if parsed["type"] == "final_answer":
                    # 连续无效回复检测（防止死循环）
                    if not self._tool_call_made:
                        self._invalid_reply_count = getattr(self, '_invalid_reply_count', 0) + 1
                        if self._invalid_reply_count >= 3:
                            duration = time.time() - start_time
                            self._logger.error(f"❌ 连续{self._invalid_reply_count}次未调用工具就给Final Answer，跳出循环")
                            return TaskResult(
                                status=TaskStatus.FAILED,
                                error_type=ErrorType.LLM_ERROR,
                                error_msg=f"LLM连续{self._invalid_reply_count}次未调用工具就给出Final Answer，已尝试{self._invalid_reply_count}次。最后回复: {response_text[:200]}",
                                steps=step,
                                duration=duration
                            )
                        
                        if self.verbose:
                            self._logger.warning(f"   ⚠️ 未调用任何工具就给出Final Answer (连续第{self._invalid_reply_count}次)，拒绝并要求先使用工具")
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content": "❌ 还没有调用过任何工具！必须先调用工具获取信息，才能给出Final Answer。请重新开始，先选择一个工具。"})
                        continue

                    final_answer = parsed["content"]
                    duration = time.time() - start_time
                    if self.verbose:
                        self._logger.info(f"✅ 最终答案 ({len(final_answer)}字符)")

                    if agent_core.session_manager:
                        agent_core.session_manager.add_to_current_session(user_input, final_answer)
                    else:
                        agent_core.short_term_memory.append({"user": user_input, "assistant": final_answer})
                        if len(agent_core.short_term_memory) > 10:
                            agent_core.short_term_memory.pop(0)

                    return TaskResult(status=TaskStatus.SUCCESS, answer=final_answer,
                                      steps=step, tool_calls=self._tool_calls, duration=duration)

                elif parsed["type"] == "action":
                    self._tool_call_made = True
                    tool_name = parsed["action"]
                    tool_input = parsed["action_input"]

                    if self.verbose:
                        self._logger.info(f"   🔧 Action: {tool_name}, Input: {str(tool_input)[:100]}")

                    if not agent_core.tools.exists(tool_name):
                        observation = f"找不到工具 '{tool_name}'。可用: {agent_core.tools.get_tools_index()}"
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content": f"Observation: {observation}"})
                        continue

                    tool_result = agent_core.tools.execute(tool_name, tool_input)

                    if self.verbose:
                        self._logger.info(f"   📊 Observation: {str(tool_result)[:100]}")

                    self._record_tool_call(tool_name, tool_input, str(tool_result))
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({"role": "user", "content": f"Observation: {tool_result}"})

                else:
                    # 未知格式：直接作为最终答案返回（兜底策略）
                    # 这是为了让不遵循ReAct格式的模型（如推理模型）也能工作
                    if self.verbose:
                        self._logger.warning(f"⚠️ 无法解析ReAct格式，直接返回模型输出作为答案")
                    
                    duration = time.time() - start_time
                    final_answer = response_text
                    
                    # 保存到会话历史
                    if agent_core.session_manager:
                        agent_core.session_manager.add_to_current_session(user_input, final_answer)
                    else:
                        agent_core.short_term_memory.append({"user": user_input, "assistant": final_answer})
                        if len(agent_core.short_term_memory) > 10:
                            agent_core.short_term_memory.pop(0)
                    
                    return TaskResult(status=TaskStatus.SUCCESS, answer=final_answer,
                                      steps=step, tool_calls=self._tool_calls, duration=duration)

            except Exception as e:
                if self.verbose:
                    import traceback
                    self._logger.error(traceback.format_exc())
                return TaskResult(status=TaskStatus.FAILED, error_type=ErrorType.LLM_ERROR,
                                  error_msg=f"步骤 {step}: {str(e)}", steps=step,
                                  duration=time.time() - start_time)

        duration = time.time() - start_time
        return TaskResult(status=TaskStatus.TIMEOUT, error_type=ErrorType.TIMEOUT,
                          error_msg=f"达到最大迭代 ({self.max_iterations})", steps=self.max_iterations, duration=duration)

    def _parse_react_response(self, text: str) -> Dict[str, Any]:
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        final_pattern = r'^Final Answer:\s*(.*?)(?=\n\n|\Z)'
        final_matches = list(re.finditer(final_pattern, text, re.DOTALL | re.IGNORECASE | re.MULTILINE))
        if final_matches:
            return {"type": "final_answer", "content": final_matches[-1].group(1).strip()}

        action_pattern = r'^Action:\s*(\w+)'
        action_matches = list(re.finditer(action_pattern, text, re.IGNORECASE | re.MULTILINE))
        input_pattern = r'^Action Input:\s*(\{.*\}|.+)'
        input_matches = list(re.finditer(input_pattern, text, re.DOTALL | re.MULTILINE))

        if action_matches:
            action_name = action_matches[-1].group(1).strip()
            action_input = "{}"
            if input_matches:
                action_input = input_matches[-1].group(1).strip()
            try:
                if action_input.startswith("{"):
                    action_input = json.loads(action_input)
            except Exception:
                pass
            return {"type": "action", "action": action_name, "action_input": action_input}

        return {"type": "unknown", "content": text}

    def _is_invalid_action_response(self, text: str) -> bool:
        invalid_actions = ["final", "final_answer", "none", "answer", "response"]
        text_lower = text.lower()
        for invalid in invalid_actions:
            if re.search(rf'action:\s*{invalid}', text_lower):
                return True
        return False

    def _record_tool_call(self, tool_name: str, tool_input: Any, tool_result: str):
        self._tool_calls.append({"tool": tool_name, "input": tool_input, "output": tool_result})


