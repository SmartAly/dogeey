"""
LLM调用封装 - 支持OpenAI兼容API
带自动重试、优雅错误处理、抑制SDK内部日志
"""
import os
import time
import logging
import re
from openai import OpenAI
from typing import List, Dict, Optional, Iterator

# 抑制OpenAI SDK内部的httpx重试日志（我们自己控制重试）
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


class LLMClient:
    """LLM客户端封装（带自动重试）"""
    
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 120):
        # 清除代理环境变量，避免 SDK 走代理导致认证失败
        for env_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            if env_key in os.environ:
                del os.environ[env_key]
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0  # 自己控制重试，不用SDK默认的
        )
        self.model = model
        self.timeout = timeout
        self._logger = logging.getLogger(__name__)
    
    def chat(self, messages: List[Dict], temperature: float = 0.7,
             max_tokens: int = 2000, stream: bool = False):
        """发送聊天请求（带指数退避重试）"""
        # 重试策略：递增间隔，给不稳定API更多恢复时间
        retry_delays = [3, 8, 20]  # 秒：3s → 8s → 20s

        # 记录请求信息（用于调试）
        self._logger.info(f"LLM请求: model={self.model}, messages={len(messages)}, max_tokens={max_tokens}")

        for attempt in range(len(retry_delays) + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=stream,
                    timeout=self.timeout  # 添加超时保护
                )

                if stream:
                    return self._handle_stream(response)
                else:
                    message = response.choices[0].message
                    # 优先检查reasoning_content（astron等推理模型特有字段）
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        content = message.reasoning_content
                        self._logger.info(f"LLM响应成功(推理模型): content_length={len(content)}")
                    else:
                        content = message.content
                        self._logger.info(f"LLM响应成功: content_length={len(content) if content else 0}")
                    return content

            except Exception as e:
                err_str = str(e)
                status_code = self._extract_status_code(err_str)

                # 记录详细错误信息
                self._logger.error(f"LLM调用异常 (attempt {attempt+1}): status_code={status_code}, error={err_str[:200]}")

                # 401/403 → 凭据问题，不重试
                if status_code in (401, 403):
                    raise Exception(f"🔑 API Key认证失败，请检查配置")

                # 400 → 参数问题，不重试
                if status_code == 400:
                    raise Exception(f"📦 请求参数错误，请检查模型名称或消息格式")

                # 还有重试次数
                if attempt < len(retry_delays):
                    delay = retry_delays[attempt]
                    self._logger.warning(
                        f"LLM调用失败 ({attempt+1}/{len(retry_delays)+1}) "
                        f"HTTP {status_code}，{delay}秒后重试..."
                    )
                    time.sleep(delay)
                else:
                    # 所有重试用完 → 友好错误信息
                    msg = self._format_final_error(status_code, err_str)
                    raise Exception(msg)
    
    def _extract_status_code(self, err_str: str) -> int:
        """从错误字符串中提取HTTP状态码"""
        match = re.search(r'(\d{3})', err_str)
        if match:
            return int(match.group(1))
        return 0
    
    def _format_final_error(self, status_code: int, err_str: str) -> str:
        """格式化最终错误消息（用户友好）"""
        friendly = {
            502: "模型服务暂时不可用（502 Bad Gateway），请稍后再试",
            503: "模型服务暂时过载（503 Service Unavailable），请稍后再试",
            504: "模型响应超时（504 Gateway Timeout），可能是请求量太大",
            429: "请求频率过高（429 Rate Limit），请稍后再试",
        }
        msg = friendly.get(status_code)
        if msg:
            return msg
        # 兜底：不暴露原始技术细节
        return f"模型调用失败（HTTP {status_code}），请稍后再试"
    
    def _handle_stream(self, response) -> Iterator[str]:
        """处理流式响应"""
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def chat_with_tools(self, messages: List[Dict], tools: List[Dict], temperature: float = 0.7):
        """支持工具调用的聊天（带重试）"""
        retry_delays = [2, 5]
        last_error = None
        
        for attempt in range(len(retry_delays) + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature,
                    max_tokens=2000
                )
                return response.choices[0].message
            except Exception as e:
                last_error = e
                err_str = str(e)
                status_code = self._extract_status_code(err_str)
                
                if status_code in (401, 403, 400):
                    raise
                
                if attempt < len(retry_delays):
                    delay = retry_delays[attempt]
                    self._logger.warning(f"chat_with_tools失败 ({attempt+1}/3) HTTP {status_code}，{delay}秒后重试...")
                    time.sleep(delay)
        
        raise last_error if last_error else Exception("chat_with_tools: 未知错误")


def create_llm_client_from_config(config_dict: Dict, provider_override: str = None) -> LLMClient:
    """从配置字典创建LLM客户端
    
    Args:
        config_dict: 配置字典
        provider_override: 可选，直接指定提供商名称（覆盖配置中的current_provider）
    """
    provider = provider_override or config_dict.get("llm", {}).get("current_provider")
    providers = config_dict.get("llm", {}).get("providers", [])
    
    if not provider:
        raise ValueError("未配置模型提供商，请先运行: dogeey init")
    
    provider_config = None
    for p in providers:
        if p["name"] == provider:
            provider_config = p
            break
    
    if not provider_config:
        raise ValueError(f"找不到提供商配置: {provider}")
    
    api_key = provider_config.get("api_key", "")
    if api_key.startswith("${") and api_key.endswith("}"):
        env_var = api_key[2:-1]
        api_key = __import__("os").environ.get(env_var, "")
    
    if not api_key:
        raise ValueError("API Key未配置，请设置环境变量或重新配置")
    
    base_url = provider_config.get("base_url", "https://api.openai.com/v1")
    model = provider_config.get("default_model", "gpt-4o")
    timeout = config_dict.get("llm", {}).get("timeout", 120)
    
    logging.getLogger(__name__).info(
        f"🔧 创建LLM客户端: provider={provider}, model={model}, base_url={base_url}"
    )
    
    return LLMClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout
    )
