#!/usr/bin/env python3
"""
飞书消息监听 + AI回复
完全复用 dogeey.cli 的 Agent 初始化流程
"""
import asyncio
import json
import sys
import os
import logging
from pathlib import Path

# 配置日志（与dogeey其他模块一致）
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-5s | %(name)s:%(funcName)s:%(lineno)d - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dogeey.channels.feishu.channel import FeishuChannel
from dogeey.message import Message, MessageType
from dogeey.event_bus import EventBus, Event
from dogeey.core import AgentCore
from dogeey.llm import create_llm_client_from_config
from dogeey.tools import ToolRegistry, register_builtin_tools
from dogeey.sessions import SessionManager

LOG_FILE = "/tmp/dogeey_messages.json"

# 全局agent实例
agent_instance = None
feishu_channel = None


def create_agent():
    """创建Agent实例 - 完全复制 dogeey.cli.init_agent() 的初始化流程"""
    from dogeey.profile import UserProfile
    from dogeey.memory import MemorySystem
    
    # 使用 Config 类加载配置（与 cli.py 完全一致）
    from dogeey.config import Config
    cfg_obj = Config()
    try:
        cfg = cfg_obj.load()
    except Exception as e:
        logger.warning(f"⚠️ 配置加载失败: {e}")
        cfg = {"llm": {"providers": [], "current_provider": "openai", "timeout": 120}}
    
    # 初始化会话管理器
    session_manager = SessionManager()
    
    # LLM 客户端 - 与 cli.py 完全一致
    llm_client = create_llm_client_from_config(cfg)
    logger.info(f"✅ LLM客户端已创建: {cfg['llm']['current_provider']}")
    
    # 工具注册
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    
    # 可选组件 - 与 cli.py 完全一致
    memory_system = None
    user_profile = None
    skill_manager = None
    
    try:
        db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        memory_system = MemorySystem(db_path)
        logger.info(f"✅ 记忆系统已加载")
    except Exception as e:
        logger.warning(f"⚠️ 记忆系统初始化失败: {e}")
    
    try:
        profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
        user_profile = UserProfile(profile_path)
        logger.info(f"✅ 用户画像已加载: {profile_path}")
    except Exception as e:
        logger.warning(f"⚠️ 用户画像初始化失败: {e}")
    
    try:
        from dogeey.skills import SkillManager
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        skill_manager = SkillManager(skills_path)
        logger.info(f"✅ 技能管理器已加载: {skills_path}")
    except Exception as e:
        logger.warning(f"⚠️ 技能管理器初始化失败: {e}")
    
    # AgentCore - 与 cli.py 完全一致
    agent = AgentCore(
        llm_client=llm_client,
        tool_registry=tool_registry,
        memory_system=memory_system,
        user_profile=user_profile,
        skill_manager=skill_manager,
        session_manager=session_manager,
        loaded_skills=[],
    )
    return agent


async def handle_message(event):
    """处理收到的消息"""
    global agent_instance, feishu_channel
    
    msg = event.data
    
    # 构造日志信息
    log_data = {
        "timestamp": asyncio.get_event_loop().time(),
        "message_id": msg.id,
        "user_id": msg.user_id,
        "text": msg.text,
        "reply_token": msg.reply_token,
        "metadata": msg.metadata
    }
    
    # 写入文件
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    
    logger.info(f"📨 收到消息: {msg.text[:50]}...")
    logger.debug(f"   reply_token: {msg.reply_token}")
    logger.debug(f"   user_id: {msg.user_id}")
    
    # 初始化agent（延迟初始化）
    if agent_instance is None:
        logger.info("🤖 初始化AI Agent...")
        try:
            agent_instance = create_agent()
            logger.info("✅ AI Agent已就绪")
        except Exception as e:
            logger.error(f"❌ Agent初始化失败: {e}")
            return
    
    # 让AI处理消息
    logger.info(f"🧠 [开始] AI处理消息: {msg.text[:50]}...")
    
    # 检查agent状态
    if agent_instance and hasattr(agent_instance, 'llm') and agent_instance.llm:
        logger.info(f"🧠 [1/3] 使用模型: {agent_instance.llm.model}")
    else:
        logger.warning(f"🧠 [1/3] Agent状态异常，可能没有正确初始化")
    
    try:
        logger.info(f"🧠 [2/3] 调用agent.run()...")
        response = await asyncio.to_thread(agent_instance.run, msg.text)
        
        # 检查结果
        logger.info(f"🧠 [3/3] 处理完成: type={type(response).__name__}, length={len(response) if response else 0}")
        
        # 检查None
        if response is None:
            logger.error(f"❌ [失败] agent.run()返回None")
            response = "😅 抱歉，处理失败（返回空）。请稍后再试～"
        
        # 检查空字符串
        elif not response.strip():
            logger.error(f"❌ [失败] agent.run()返回空字符串")
            logger.debug(f"   原始内容: {repr(response)}")
            response = "😅 抱歉，处理失败（无内容）。请稍后再试～"
        
        # 成功
        else:
            logger.info(f"✅ [成功] AI回复生成成功 ({len(response)}字符)")
            logger.debug(f"   预览: {response[:200]}")
            
    except Exception as e:
        logger.error(f"❌ [异常] AI处理异常: {e}")
        import traceback
        logger.error(f"   详细堆栈:\n{traceback.format_exc()}")
        response = "😅 抱歉，处理消息时出了点问题。请稍后再试～"
    
    # 发送回复
    if feishu_channel and msg.reply_token:
        reply_msg = Message(
            id=f"reply_{msg.id}",
            channel="feishu",
            user_id="dogeey",
            username="dogeey",
            text=response,
            type=MessageType.TEXT,
            metadata={"reply_token": msg.reply_token}
        )
        try:
            await feishu_channel.send(reply_msg)
            logger.info(f"📤 已发送回复到飞书")
        except Exception as e:
            logger.error(f"❌ 发送失败: {e}")


async def main():
    """主入口"""
    global feishu_channel
    
    logger.info("=" * 60)
    logger.info("🤖 Dogeey 飞书监听启动")
    logger.info("=" * 60)
    logger.info(f"日志文件: {LOG_FILE}")
    logger.info("请给 dogeey 发送消息...")
    logger.info("=" * 60)
    
    # 创建事件总线
    event_bus = EventBus()
    
    # 订阅消息事件
    event_bus.subscribe("message.received", handle_message)
    
    # 初始化飞书频道
    config_path = os.path.expanduser("~/.dogeey/config.json")
    feishu_config = {}
    
    # 尝试从配置文件读取
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            feishu_raw = config.get("channels", {}).get("feishu", {})
            # 配置可能在 config 子键里（新格式），也可能直接在这层（旧格式）
            feishu_config = feishu_raw.get("config", feishu_raw)
    except Exception as e:
        print(f"⚠️ 无法读取配置文件: {e}")
    
    # Fallback：如果配置不完整，使用硬编码配置
    if not feishu_config.get("app_id") or not feishu_config.get("app_secret"):
        logger.warning("⚠️ 配置不完整，使用默认配置")
        feishu_config = {
            "app_id": "cli_a97c08ec4478dcd4",
            "app_secret": "tPKmofpVLgwpOTjLSGnhidtalCVfSqrQ",
            "connection_mode": "websocket",
            "domain_name": "feishu"
        }
    
    feishu_channel = FeishuChannel()
    feishu_channel.event_bus = event_bus  # ⚠️ 关键：把EventBus赋值给channel！
    await feishu_channel.configure(feishu_config)
    await feishu_channel.start()
    
    # 保持运行
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 已退出")
