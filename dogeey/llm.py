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

logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


class LLMClient:
    """LLM客户端封装（带自动重试）"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 120):
        for env_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            if env_key in os.environ:
                del os.environ[env_key]

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            default_headers={
                "HTTP-Referer": "https://github.com/SmartAly/dogeey",
                "X-Title": "dogeey",
            }
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
                    
                    # 多模型兼容：不同厂商的推理内容字段名不同
                    content = None
                    
                    # 1. 优先检查 reasoning_content（astron等）
                    if hasattr(message, 'reasoning_content') and message.reasoning_content:
                        content = message.reasoning_content
                    # 2. 检查 reasoning（OpenRouter/tencent hy3等）
                    elif hasattr(message, 'reasoning') and message.reasoning:
                        content = message.reasoning
                    # 3. 标准 content 字段
                    elif message.content:
                        content = message.content
                    # 4. 检查 model_extra 中的 reasoning（OpenAI SDK 新版本）
                    else:
                        extra = getattr(message, 'model_extra', None)
                        if extra and extra.get('reasoning'):
                            content = extra['reasoning']
                    
                    if content:
                        self._logger.info(f"LLM响应成功: content_length={len(content)}")
                        return content
                    else:
                        # 内容为空，可能是模型响应异常
                        self._logger.warning(f"LLM响应内容为空，原始响应: {str(response)[:100]}")
                        return ""

            except Exception as e:
                err_str = str(e)
                status_code = self._extract_status_code(err_str, e)

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
    
    def _extract_status_code(self, err_str: str, exc: Exception = None) -> int:
        """从错误字符串或异常类型中提取HTTP状态码"""
        match = re.search(r'(\d{3})', err_str)
        if match:
            return int(match.group(1))
        if exc is not None:
            cls_name = exc.__class__.__name__
            sdk_codes = {
                'InternalServerError': 500,
                'RateLimitError': 429,
                'BadRequestError': 400,
                'AuthenticationError': 401,
                'PermissionDeniedError': 403,
                'NotFoundError': 404,
                'UnprocessableEntityError': 422,
                'APITimeoutError': 408,
            }
            return sdk_codes.get(cls_name, 0)
        return 0
    
    def _format_final_error(self, status_code: int, err_str: str) -> str:
        """格式化最终错误消息（用户友好）"""
        friendly = {
            500: "模型服务内部错误（500），请稍后再试",
            502: "模型服务暂时不可用（502 Bad Gateway），请稍后再试",
            503: "模型服务暂时过载（503 Service Unavailable），请稍后再试",
            504: "模型响应超时（504 Gateway Timeout），可能是请求量太大",
            429: "请求频率过高（429 Rate Limit），请稍后再试",
        }
        msg = friendly.get(status_code)
        if msg:
            return msg
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
                status_code = self._extract_status_code(err_str, e)
                
                if status_code in (401, 403, 400):
                    raise
                
                if attempt < len(retry_delays):
                    delay = retry_delays[attempt]
                    self._logger.warning(f"chat_with_tools失败 ({attempt+1}/3) HTTP {status_code}，{delay}秒后重试...")
                    time.sleep(delay)
        
        raise last_error if last_error else Exception("chat_with_tools: 未知错误")


def create_llm_client_from_config(config_dict: Dict, provider_override: str = None) -> LLMClient:
    """从配置字典创建LLM客户端
    
    如果主提供商不可用，自动切换到备用提供商。
    """
    provider = provider_override or config_dict.get("llm", {}).get("current_provider")
    providers = config_dict.get("llm", {}).get("providers", [])
    
    if not provider:
        raise ValueError("未配置模型提供商，请先运行: dogeey init")
    
    # 构建候选列表：主提供商 + 备用提供商
    fallback_names = config_dict.get("llm", {}).get("fallback_providers", [])
    if isinstance(fallback_names, list) and fallback_names:
        candidate_names = [provider] + [fn for fn in fallback_names if fn != provider]
    else:
        # 默认 fallback
        if provider == "openrouter":
            candidate_names = ["openrouter", "astron"]
        elif provider == "astron":
            candidate_names = ["astron", "openrouter"]
        else:
            candidate_names = [provider]
    
    # 尝试每个提供商
    last_error = None
    for candidate_name in candidate_names:
        candidate_config = None
        for p in providers:
            if p["name"] == candidate_name:
                candidate_config = p
                break
        
        if not candidate_config:
            continue
        
        api_key = candidate_config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.environ.get(env_var, "")
        
        if not api_key:
            continue
        
        base_url = candidate_config.get("base_url", "https://api.openai.com/v1")
        model = candidate_config.get("default_model", "gpt-4o")
        timeout = config_dict.get("llm", {}).get("timeout", 120)
        
        try:
            # 使用 LLMClient.chat() 方法测试连接（会自动处理 reasoning 字段）
            test_client = LLMClient(api_key=api_key, base_url=base_url, model=model, timeout=15)
            result = test_client.chat([{"role": "user", "content": "你好"}], max_tokens=10)
            # 只要没有异常就算成功（即使内容为空）
            if candidate_name != provider:
                logging.getLogger(__name__).warning(
                    f"⚠️ 主提供商 {provider} 不可用，切换到备用: {candidate_name} ({model})"
                )
            logging.getLogger(__name__).info(
                f"🔧 创建LLM客户端: provider={candidate_name}, model={model}, base_url={base_url}"
            )
            return test_client
            
        except Exception as e:
            last_error = e
            logging.getLogger(__name__).warning(f"⚠️ 提供商 {candidate_name} 连接失败: {e}")
            continue
    
    raise last_error or ValueError("所有提供商均不可用")
