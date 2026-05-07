"""
ContextFlow - 话题流系统
实现自然对话流转，像人一样聊天，无需手动切换
"""

import json
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
from enum import Enum


class ContextStage(Enum):
    """上下文生命周期阶段"""
    ACTIVE = "active"      # 活跃（当前正在聊）
    DORMANT = "dormant"    # 休眠（最近聊过，但不在前台）
    ARCHIVED = "archived"   # 归档（很久没聊，只留摘要）


class Context:
    """单个话题上下文"""
    
    def __init__(self, ctx_id: str, title: str = None):
        self.id = ctx_id
        self.title = title or f"话题_{ctx_id[:8]}"
        self.messages: List[Dict] = []  # 完整对话历史
        self.summary: str = ""        # 摘要（休眠/归档时用）
        self.stage = ContextStage.ACTIVE
        self.created_at = datetime.now().isoformat()
        self.last_active = datetime.now().isoformat()
        self.message_count = 0
        self.keywords: List[str] = []  # 提取的关键词（用于快速匹配）
        
    def add_message(self, role: str, content: str):
        """添加消息"""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.message_count += 1
        self.last_active = datetime.now().isoformat()
        
        # 更新关键词（正确分词）
        import re
        words = re.findall(r'[\w]+', content.lower())
        stop_words = set([
            '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看',
            '好', '自己', '这', '他', '她', '它', '那个', '这个', '什么', '怎么', '如何'
        ])
        new_kw = set(w for w in words if len(w) > 1 and w not in stop_words)
        
        # 扩展：保留专业术语（从整个content中检查）
        tech_terms = ['cron', '定时任务', '元认知', '晨报', 'dogeey', 'llm', 'api']
        for term in tech_terms:
            if term in content.lower():
                new_kw.add(term)
        
        # 同义词映射（cron = 定时任务）
        synonym_map = {
            'cron': ['定时任务', '定时', '任务调度', '调度器'],
            '定时任务': ['cron', 'cron', '调度'],
            '元认知': ['metacognition', '自进化', '自我认知'],
            '晨报': ['morning', '晨报', '早报', '每日报告'],
        }
        content_lower = content.lower()
        for main_term, synonyms in synonym_map.items():
            if main_term in content_lower:
                new_kw.update(synonyms)
            else:
                for syn in synonyms:
                    if syn in content_lower:
                        new_kw.add(main_term)
                        break
        
        # 合并到现有关键词
        self.keywords = list(set(self.keywords) | new_kw)
        
    def get_recent(self, n: int = 3) -> List[Dict]:
        """获取最近n条消息"""
        return self.messages[-n:] if self.messages else []
    
    def to_dict(self) -> Dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "stage": self.stage.value,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": self.message_count,
            "keywords": self.keywords
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Context':
        """从字典恢复"""
        ctx = cls(ctx_id=data["id"], title=data.get("title"))
        ctx.summary = data.get("summary", "")
        ctx.stage = ContextStage(data.get("stage", "active"))
        ctx.created_at = data.get("created_at", datetime.now().isoformat())
        ctx.last_active = data.get("last_active", ctx.created_at)
        ctx.message_count = data.get("message_count", 0)
        ctx.keywords = data.get("keywords", [])
        return ctx


class ContinuityDetector:
    """
    延续性检测器 - 渐进式判断（90%情况不用LLM）
    核心：判断用户输入是否延续当前对话
    """
    
    def __init__(self, llm_client=None):
        self.llm = llm_client
        # 简单的关键词提取（无需外部依赖）
        self._stop_words = set([
            '的', '了', '是', '在', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看',
            '好', '自己', '这', '他', '她', '它', '那个', '这个', '什么', '怎么', '如何'
        ])
        
    def is_continuation(self, user_input: str, context: Context) -> bool:
        """
        渐进式判断：成本递减
        第1层：规则过滤（0成本，80%情况）
        第2层：关键词重叠（0成本，15%情况）
        第3层：LLM判断（有成本，只有5%疑难情况）
        """
        # 第1层：快速规则
        if context.message_count == 0:
            return False  # 空上下文，肯定不是延续
        # 检测代词引用（它、那个、刚才...）
        has_pronoun = self._has_pronoun_reference(user_input)
        
        if has_pronoun:
            # 检查：代词指代的是否是当前上下文？
            # 关键：输入中是否包含当前上下文的关键词？
            ctx_kw = set(context.keywords) if context.keywords else set()
            input_kw = set(self._extract_keywords(user_input))
            
            # 如果输入和当前上下文没有关键词重叠，代词很可能指代其他上下文
            if len(input_kw & ctx_kw) == 0:
                # 代词不指代当前上下文，继续后面的检查
                pass
            else:
                # 输入包含当前上下文的关键词，可能是延续
                recent_text = " ".join([m.get("content", "") for m in context.get_recent(3)])
                if self._has_entity(recent_text):
                    # 前文有实体+输入有代词+有共同关键词 → 很可能是延续
                    return True
        
        # 第2层：关键词重叠
        input_kw = self._extract_keywords(user_input)
        ctx_kw = set(context.keywords) if context.keywords else self._extract_keywords(
            " ".join([m.get("content", "") for m in context.get_recent(5)])
        )
        
        if not ctx_kw:
            # 如果上下文没有关键词，用全部历史
            ctx_kw = self._extract_keywords(
                " ".join([m.get("content", "") for m in context.messages])
            )
        
        overlap = len(input_kw & ctx_kw)
        total = max(len(input_kw), 1)
        overlap_ratio = overlap / total
        
        if overlap_ratio > 0.5 and len(input_kw) >= 2:
            return True  # 关键词重叠高
        if overlap_ratio < 0.1 and len(input_kw) >= 2:
            return False  # 关键词完全不搭
        
        # 第3层：不确定情况，保守策略（不调LLM，保证速度）
        # 重叠率在0.1-0.5之间，可能是新话题，也可能是延续
        # 保守处理：返回False，让上层去搜索其他上下文或创建新话题
        return False
    
    def _has_pronoun_reference(self, text: str) -> bool:
        """检测代词引用"""
        pronouns = ['它', '他', '她', '那个', '这个', '刚才', '之前', '还是', '现在', '那个啥']
        return any(p in text for p in pronouns)
    
    def _has_entity(self, text: str) -> bool:
        """检测文本中是否有实体（名词、专业术语等）"""
        # 简单判断：长度>1的词，且不是停用词
        import re
        words = re.findall(r'[\w]+', text.lower())
        entities = [w for w in words if len(w) > 1 and w not in self._stop_words]
        return len(entities) > 0
    
    def _extract_keywords(self, text: str) -> set:
        """简单关键词提取（基于词频，无外部依赖）"""
        # 简单分词（按空格和标点）
        import re
        words = re.findall(r'[\w]+', text.lower())
        # 过滤停用词和短词
        keywords = set(w for w in words if len(w) > 1 and w not in self._stop_words)
        
        # 扩展：保留"cron"、"定时任务"等复合概念
        # 简单处理：如果文本包含某个专业术语，直接加入
        tech_terms = ['cron', '定时任务', '元认知', '晨报', 'dogeey', 'llm', 'api']
        for term in tech_terms:
            if term in text.lower():
                keywords.add(term)
        
        # 同义词映射（cron = 定时任务）
        synonym_map = {
            'cron': ['定时任务', '定时', '任务调度', '调度器'],
            '定时任务': ['cron', 'cron', '调度'],
            '元认知': ['metacognition', '自进化', '自我认知'],
            '晨报': ['morning', '晨报', '早报', '每日报告'],
        }
        
        text_lower = text.lower()
        for main_term, synonyms in synonym_map.items():
            if main_term in text_lower:
                keywords.update(synonyms)
            else:
                for syn in synonyms:
                    if syn in text_lower:
                        keywords.add(main_term)
                        break
        
        return keywords
    
    def _llm_judge(self, user_input: str, context: Context) -> bool:
        """用LLM判断延续性（只有疑难情况才调用）"""
        try:
            recent = context.get_recent(3)
            recent_text = "\n".join([f"{m['role']}: {m['content']}" for m in recent])
            
            prompt = f"""最近对话:
{recent_text}

用户新输入: "{user_input}"

新输入是否延续最近对话？只需回答 YES 或 NO。
"""
            # 假设llm有ask方法
            response = self.llm.ask(prompt, max_tokens=3)
            return "YES" in response.upper()
        except Exception as e:
            print(f"⚠️ LLM判断失败: {e}")
            return True  # 失败时保守处理


class ContextManager:
    """
    上下文管理器 - 像人脑一样管理多个对话上下文
    自动流转，无需用户干预
    """
    
    def __init__(self, llm_client=None, max_active: int = 5, max_cache: int = 10):
        self.llm = llm_client
        self.contexts: Dict[str, Context] = {}
        self.active_ctx_id: Optional[str] = None
        self.detector = ContinuityDetector(llm_client)
        self.max_active = max_active
        self.cache = {}  # 简单LRU缓存
        self.cache_order = []  # LRU顺序
        self.max_cache = max_cache
        
    def get_context_for_input(self, user_input: str, history: list = None) -> Context:
        """
        根据用户输入，返回应该使用的上下文
        完全自动，无需用户干预
        """
        # 情况1：当前有活跃上下文，检查是否延续
        if self.active_ctx_id and self.active_ctx_id in self.contexts:
            ctx = self.contexts[self.active_ctx_id]
            if self.detector.is_continuation(user_input, ctx):
                return ctx
        
        # 情况2：不延续当前，搜索其他上下文
        best_match = self._find_related_context(user_input)
        if best_match:
            # 切换到找到的上下文
            self.active_ctx_id = best_match.id
            best_match.last_active = datetime.now().isoformat()
            print(f"🔄 回到话题: {best_match.title}")
            return best_match
        
        # 情况3：都不相关，创建新上下文
        return self._create_new_context(user_input)
    
    def _find_related_context(self, user_input: str) -> Optional[Context]:
        """搜索相关的上下文（关键词匹配+标题匹配）"""
        input_kw = self.detector._extract_keywords(user_input)
        input_lower = user_input.lower()
        
        best_match = None
        best_score = 0
        
        for ctx_id, ctx in self.contexts.items():
            if ctx_id == self.active_ctx_id:
                continue  # 已经检查过当前了
            
            # 计算关键词重叠得分
            ctx_kw = set(ctx.keywords) if ctx.keywords else self.detector._extract_keywords(
                " ".join([m.get("content", "") for m in ctx.messages[-10:]])
            )
            
            if not ctx_kw:
                continue
                
            overlap = len(input_kw & ctx_kw)
            score = overlap
            
            # 标题匹配加分（输入包含标题关键词）
            title_lower = ctx.title.lower()
            title_kw = set(self.detector._extract_keywords(ctx.title))
            title_match = len(input_kw & title_kw)
            score += title_match * 2  # 标题匹配权重更高
            
            # 输入包含上下文标题中的专业术语，直接高分
            tech_terms = ['cron', '定时任务', '晨报', '元认知', 'dogeey']
            for term in tech_terms:
                if term in input_lower and term in title_lower:
                    score += 10  # 专业术语匹配，高分
                    break
            
            if score > best_score:
                best_score = score
                best_match = ctx
        
        # 至少2分才算相关（关键词重叠2个，或标题匹配+关键词）
        return best_match if best_score >= 2 else None
    
    def _create_new_context(self, first_message: str) -> Context:
        """创建新上下文"""
        import uuid
        ctx_id = f"ctx_{uuid.uuid4().hex[:8]}"
        ctx = Context(ctx_id=ctx_id)
        
        # 生成标题（简单版：取前20字）
        title = first_message[:20] + ("..." if len(first_message) > 20 else "")
        ctx.title = title
        
        # 提取关键词
        ctx.keywords = list(self.detector._extract_keywords(first_message))
        
        self.contexts[ctx_id] = ctx
        self.active_ctx_id = ctx_id
        
        print(f"🆕 新话题: {ctx.title}")
        return ctx
    
    def get_active_context(self) -> Optional[Context]:
        """获取当前活跃上下文"""
        if self.active_ctx_id:
            return self.contexts.get(self.active_ctx_id)
        return None
    
    def get_all_contexts(self) -> List[Context]:
        """获取所有上下文（用于展示）"""
        return list(self.contexts.values())
    
    def auto_cleanup(self):
        """自动清理：保持系统精简"""
        # 1. 限制活跃上下文数量
        if len(self.contexts) > self.max_active:
            # 把最久没用的移到缓存
            oldest_id = min(
                self.contexts.keys(),
                key=lambda x: self.contexts[x].last_active
            )
            ctx = self.contexts.pop(oldest_id)
            self._add_to_cache(oldest_id, ctx)
        
        # 2. 流转生命周期（活跃→休眠→归档）
        self._transition_contexts()
    
    def _transition_contexts(self):
        """流转上下文生命周期"""
        now = datetime.now()
        
        for ctx_id, ctx in list(self.contexts.items()):
            days_since_active = (now - datetime.fromisoformat(ctx.last_active)).days
            
            if days_since_active > 30:
                # 归档：很久没聊
                self._archive_context(ctx)
                del self.contexts[ctx_id]
                print(f"📦 上下文已归档（30天未活跃）: {ctx.title}")
            elif days_since_active > 7:
                # 休眠：一周没聊
                if ctx.stage != ContextStage.DORMANT:
                    self._dormant_context(ctx)
                    print(f"😴 上下文休眠（7天未活跃）: {ctx.title}")
    
    def _dormant_context(self, ctx: Context):
        """休眠：生成摘要，压缩消息"""
        if not ctx.summary and self.llm:
            # 用LLM生成摘要（一次性成本）
            try:
                messages_text = "\n".join([
                    f"{m['role']}: {m['content']}" for m in ctx.messages[-10:]
                ])
                prompt = f"""请总结以下对话（100字以内）:
{messages_text}

只输出摘要，不要其他内容。
"""
                ctx.summary = self.llm.ask(prompt, max_tokens=100)
            except Exception as e:
                print(f"⚠️ 生成摘要失败: {e}")
                ctx.summary = f"关于{ctx.title}的讨论"
        
        # 压缩：只保留最后3轮 + 摘要
        ctx.messages = ctx.messages[-6:]  # 最后3轮
        ctx.stage = ContextStage.DORMANT
        print(f"✅ 上下文已休眠: {ctx.title}")
    
    def _archive_context(self, ctx: Context):
        """归档：极简存储"""
        # 生成摘要（如果没有）
        if not ctx.summary:
            ctx.summary = f"关于{ctx.title}的讨论（{ctx.message_count}条消息）"
        
        # 清空消息，只保留元数据
        ctx.messages = []
        ctx.stage = ContextStage.ARCHIVED
        print(f"✅ 上下文已归档: {ctx.title}")
    
    def _add_to_cache(self, ctx_id: str, ctx: Context):
        """添加到LRU缓存"""
        if ctx_id in self.cache_order:
            self.cache_order.remove(ctx_id)
        self.cache_order.append(ctx_id)
        self.cache[ctx_id] = ctx
        
        # 淘汰最久没用的
        if len(self.cache) > self.max_cache:
            oldest = self.cache_order.pop(0)
            del self.cache[oldest]
    
    def build_context_messages(self, context: Context) -> List[Dict]:
        """为LLM构建消息列表"""
        messages = []
        
        # 1. 如果是切换回来的，加个提示
        if context.message_count > 0 and context.id == self.active_ctx_id:
            # 检查是否是刚切换回来的（简化判断）
            messages.append({
                "role": "system",
                "content": f"🔄 回到话题: {context.title}"
            })
        
        # 2. 添加上下文历史
        messages.extend(context.messages)
        
        return messages
