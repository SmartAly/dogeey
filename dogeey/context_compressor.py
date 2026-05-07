"""
Context压缩机制 - 参考Hermes实现
自动监控token数，触发压缩，防止超context window
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# 默认压缩阈值（80% context window）
DEFAULT_COMPRESSION_THRESHOLD = 0.8

# 默认保留最近N条完整消息
DEFAULT_RECENT_MESSAGES_COUNT = 6


class ContextCompressor:
    """上下文压缩器 - 分层压缩策略"""
    
    def __init__(self, 
                 llm_client=None,
                 threshold: float = 200000,  # 默认200000绝对token数
                 recent_count: int = DEFAULT_RECENT_MESSAGES_COUNT):
        self.llm_client = llm_client
        # threshold可以是绝对token数(int)或比例(float < 1)
        self.threshold = threshold
        self.recent_count = recent_count
        self._estimator = None  # token估算器（延迟初始化）
        
    def estimate_tokens(self, messages: List[Dict]) -> int:
        """
        估算消息列表的token数
        优先使用tiktoken，否则用简单估算
        """
        # 尝试使用tiktoken（OpenAI官方）
        try:
            import tiktoken
            if self._estimator is None:
                # 尝试获取模型的encoding
                model = getattr(self.llm_client, 'model', 'gpt-3.5-turbo')
                try:
                    enc = tiktoken.encoding_for_model(model)
                except KeyError:
                    enc = tiktoken.get_encoding("cl100k_base")  # 默认
                self._estimator = enc
            
            total = 0
            for msg in messages:
                # 每条消息：role + content + 少量格式token
                text = msg.get('content', '')
                if isinstance(text, list):  # 多模态内容
                    text = ' '.join([p.get('text', '') if isinstance(p, dict) else str(p) for p in text])
                total += len(self._estimator.encode(text))
                total += 4  # role等格式token
            return total
        except ImportError:
            pass
        
        # 回退：简单估算（1 token ≈ 1.3 中文字符 或 4 英文字符）
        total = 0
        for msg in messages:
            text = msg.get('content', '')
            if isinstance(text, list):
                text = ' '.join([p.get('text', '') if isinstance(p, dict) else str(p) for p in text])
            # 简单启发式
            chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            others = len(text) - chinese
            total += int(chinese / 1.3 + others / 4)
        return total
    
    def get_context_window(self, model: str) -> int:
        """获取模型的context window大小"""
        # 常见模型的context window
        known_windows = {
            'gpt-3.5-turbo': 4096,
            'gpt-4': 8192,
            'gpt-4-32k': 32768,
            'gpt-4-turbo': 128000,
            'claude-3-opus': 200000,
            'claude-3-sonnet': 200000,
            'claude-2': 100000,
            'llama-3': 8192,
            'llama-2': 4096,
            'mixtral': 32768,
            'gemini-pro': 32768,
            'astron-code-latest': 8192,  # 假设
            'moonshotai/kimi-k2.5': 256000,  # 更新为256000
        }
        
        # 先查已知模型
        for key, window in known_windows.items():
            if key in model:
                return window
        
        # 默认值：8K
        return 8192
    
    def compress(self, messages: List[Dict], model: str) -> List[Dict]:
        """
        压缩消息列表
        策略：
        1. 估算当前token数
        2. 如果超过阈值，触发压缩
        3. 保留最近recent_count条完整消息
        4. 中间部分压缩成摘要（用LLM）
        5. 最旧的部分丢弃或存入记忆
        """
        if not messages:
            return messages
        
        # 估算token
        current_tokens = self.estimate_tokens(messages)
        context_window = self.get_context_window(model)
        # 阈值计算：如果threshold >= 1，视为绝对token数；否则视为比例
        if self.threshold >= 1:
            threshold_tokens = int(self.threshold)
        else:
            threshold_tokens = int(context_window * self.threshold)
        
        logger.info(f"🧮 Token统计: 当前={current_tokens}, 阈值={threshold_tokens}, 窗口={context_window}")
        
        if current_tokens <= threshold_tokens:
            logger.info("✅ Token数未超阈值，无需压缩")
            return messages
        
        logger.info(f"⚠️ Token数超阈值，开始压缩...")
        
        # 分离system消息和非system消息
        system_msgs = [m for m in messages if m.get('role') == 'system']
        other_msgs = [m for m in messages if m.get('role') != 'system']
        
        # 保留最近N条完整消息
        recent = other_msgs[-self.recent_count:] if len(other_msgs) > self.recent_count else other_msgs
        old = other_msgs[:-self.recent_count] if len(other_msgs) > self.recent_count else []
        
        # 如果有旧消息，尝试压缩
        summary = ""
        if old:
            summary = self._compress_to_summary(old)
            logger.info(f"📝 压缩完成，摘要长度: {len(summary)}字符")
        
        # 构建新消息列表
        new_messages = []
        
        # 1. 保留原有system消息，并添加新的摘要
        for sm in system_msgs:
            content = sm['content']
            if summary:
                content += f"\n\n## 历史对话摘要:\n{summary}"
            new_messages.append({"role": "system", "content": content})
        
        # 如果原来没有system消息，创建一个新的
        if not system_msgs and summary:
            new_messages.append({"role": "system", "content": f"## 历史对话摘要:\n{summary}"})
        
        # 2. 添加最近N条完整消息
        new_messages.extend(recent)
        
        # 验证压缩后的token数
        new_tokens = self.estimate_tokens(new_messages)
        logger.info(f"✅ 压缩完成: {current_tokens} -> {new_tokens} tokens (减少{current_tokens - new_tokens})")
        
        return new_messages
    
    def _compress_to_summary(self, old_messages: List[Dict]) -> str:
        """
        将旧消息压缩成摘要
        优先使用LLM，否则用简单规则
        """
        if not old_messages:
            return ""
        
        # 尝试用LLM生成摘要
        if self.llm_client:
            try:
                summary = self._llm_summarize(old_messages)
                if summary:
                    return summary
            except Exception as e:
                logger.warning(f"LLM摘要失败: {e}，使用简单规则")
        
        # 回退：简单规则摘要
        return self._simple_summarize(old_messages)
    
    def _llm_summarize(self, messages: List[Dict]) -> str:
        """用LLM生成摘要"""
        # 构造摘要prompt
        conversation = ""
        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            if isinstance(content, list):
                content = ' '.join([p.get('text', '') if isinstance(p, dict) else str(p) for p in content])
            conversation += f"\n{role}: {content[:500]}"  # 每条最多500字符
        
        prompt = f"""请简洁总结以下对话的关键信息（保留重要事实、决策、用户偏好）：
{conversation}

要求：
- 只输出摘要内容，不要额外解释
- 不超过300字
- 保留关键决策和事实
"""
        
        # 调用LLM
        try:
            if hasattr(self.llm_client, 'client'):
                # OpenAI兼容接口
                response = self.llm_client.client.chat.completions.create(
                    model=self.llm_client.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                    temperature=0.3
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return ""
    
    def _simple_summarize(self, messages: List[Dict]) -> str:
        """简单规则摘要（回退方案）"""
        # 提取用户消息的前几行
        user_msgs = [m for m in messages if m.get('role') == 'user']
        assistant_msgs = [m for m in messages if m.get('role') == 'assistant']
        
        summary = "历史对话摘要（简单版）:\n"
        if user_msgs:
            summary += f"- 用户曾询问: {user_msgs[0].get('content', '')[:100]}...\n"
        if assistant_msgs:
            summary += f"- 助手曾回复: {assistant_msgs[-1].get('content', '')[:100]}...\n"
        summary += f"- 共{len(messages)}条历史消息已压缩\n"
        return summary
