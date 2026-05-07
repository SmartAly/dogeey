"""
WebUI 后端 - FastAPI实现 (优化版)
Apple极简风格 + 暗黑模式 + 增强稳定性
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import json
import asyncio
import logging
from typing import Dict, List, Optional
from contextlib import asynccontextmanager

# 频道系统导入
from dogeey.event_bus import EventBus, Event
from dogeey.channels.manager import ChannelManager
from dogeey.routing import UserMapper, MessageRouter
from dogeey.message import Message

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 存储活跃的WebSocket连接
active_connections: List[WebSocket] = []


async def _send_friendly_reply(msg: Message, text: str):
    """发送回复到频道(带错误兜底,支持飞书Reply API)"""
    global channel_manager
    if not channel_manager:
        logger.warning("channel_manager 未初始化,无法回复")
        return
    ch = channel_manager.get_channel(msg.channel)
    if not ch:
        logger.warning(f"频道 {msg.channel} 未加载,无法回复")
        return
    metadata = getattr(msg, 'metadata', {}) or {}
    reply_metadata = {}
    if msg.id and msg.id != "unknown":
        reply_metadata["reply_to_message_id"] = msg.id
    reply = Message(
        id=f"reply-{msg.id}",
        channel=msg.channel,
        user_id="dogeey",
        username="Dogeey",
        text=text,
        reply_token=msg.reply_token,
        metadata=reply_metadata,
    )
    await ch.send(reply)


_ERROR_PREFIXES = (
    "❌", "⚠️",
    "任务执行失败", "LLM调用失败", "模型调用失败",
    "API call failed", "API failed", "HTTP 50", "HTTP 5",
    "模型服务暂时不可用", "模型服务暂时过载", "模型响应超时",
    "请求频率过高", "API Key认证失败", "请求参数错误",
)


def _detect_error(result: str) -> bool:
    """检测返回结果是否是错误消息"""
    stripped = result.strip()
    return any(stripped.startswith(p) for p in _ERROR_PREFIXES)


async def _try_provider(msg: Message, user_text: str, provider_name: str) -> Optional[str]:
    """尝试用指定provider处理消息,返回结果或None(失败)
    
    不再修改配置文件,而是通过provider_name参数直接传递给get_agent
    """
    try:
        logger.info(f"🤖 [开始] provider={provider_name}, text={user_text[:50]}...")
        
        # 1. 创建Agent
        logger.info(f"🤖 [1/4] 创建Agent...")
        agent = get_agent(provider_name=provider_name)
        logger.info(f"🤖 [1/4] Agent创建成功: model={agent.llm.model}, base_url={agent.llm.client.base_url}")
        
        # 2. 检查会话历史
        if agent.session_manager:
            history = agent.session_manager.get_current_memory()
            logger.info(f"🤖 [2/4] 会话历史: {len(history)}条")
        else:
            logger.warning(f"🤖 [2/4] 无会话管理器")
        
        # 3. 调用Agent处理
        logger.info(f"🤖 [3/4] 开始调用agent.run()...")
        result = await asyncio.to_thread(agent.run, user_text)
        
        # 4. 分析结果
        logger.info(f"🤖 [4/4] 处理完成: type={type(result).__name__}, length={len(result) if result else 0}")
        
        # 检查None
        if result is None:
            logger.error(f"❌ [失败] agent.run()返回None")
            # 尝试清空历史后重试
            if agent.session_manager:
                logger.info(f"🔄 [重试] 清空会话历史后重试...")
                agent.session_manager.clear_current_session()
                result = await asyncio.to_thread(agent.run, user_text)
                if result and result.strip() and not _detect_error(result):
                    logger.info(f"✅ [重试成功] 清空历史后调用成功 ({len(result)}字符)")
                    return result
            return None
        
        # 检查空字符串
        if not result.strip():
            logger.error(f"❌ [失败] agent.run()返回空字符串")
            logger.debug(f"   原始内容: {repr(result)}")
            # 尝试清空历史后重试
            if agent.session_manager:
                logger.info(f"🔄 [重试] 清空会话历史后重试...")
                agent.session_manager.clear_current_session()
                result = await asyncio.to_thread(agent.run, user_text)
                if result and result.strip() and not _detect_error(result):
                    logger.info(f"✅ [重试成功] 清空历史后调用成功 ({len(result)}字符)")
                    return result
            return None
        
        # 检查是否是错误消息
        if _detect_error(result):
            logger.warning(f"⚠️ [失败] 检测到错误消息前缀: {result[:100]}")
            return None
        
        # 成功
        logger.info(f"✅ [成功] 提供商 {provider_name} 返回有效结果 ({len(result)}字符)")
        logger.debug(f"   预览: {result[:200]}")
        return result
        
    except Exception as e:
        logger.error(f"❌ [异常] 提供商 {provider_name} 异常: {e}")
        import traceback
        logger.error(f"   详细堆栈:\n{traceback.format_exc()}")
        return None


async def _handle_channel_message(event: Event):
    """
    EventBus消息处理桥接 — 收到频道消息 → AI处理 → 回复
    支持provider自动fallback:当前模型挂了 → 自动切到下一个可用的
    支持飞书Reaction:收到消息添加⏳,处理完成添加✅
    """
    msg: Message = event.data
    channel_name = msg.channel
    user_text = msg.text
    msg_id = getattr(msg, 'id', 'unknown')

    if not user_text:
        return

    logger.info(f"🤖 频道消息处理: [{channel_name}] msg_id={msg_id} text={user_text[:50]}...")

    # 获取飞书消息ID(用于添加reaction)
    feishu_msg_id = ""
    if channel_name == "feishu":
        metadata = getattr(msg, 'metadata', {}) or {}
        feishu_msg_id = metadata.get("message_id", "")

    # 添加"处理中"reaction
    if feishu_msg_id:
        await _add_feishu_reaction(feishu_msg_id, "⏳")

    try:
        from dogeey.config import config
        cfg = config.load()
        providers = cfg.get("llm", {}).get("providers", [])
        current = cfg.get("llm", {}).get("current_provider", "")

        logger.info(f"🤖 当前提供商: {current}, 可用提供商: {[p.get('name') for p in providers]}")

        # 尝试当前provider
        logger.info(f"🤖 尝试使用 {current} 处理消息...")
        result = await _try_provider(msg, user_text, current)
        logger.info(f"🤖 {current} 结果: {'成功' if result else '失败'}")

        # 如果当前provider失败(返回None或空字符串),尝试其他provider
        if not result:
            logger.warning(f"⚠️ 当前提供商 {current} 失败,尝试其他提供商...")
            for p in providers:
                p_name = p.get("name", "")
                if p_name == current:
                    continue  # 跳过当前(已经试过了)
                logger.info(f"⏩ 尝试提供商: {p_name}")
                result = await _try_provider(msg, user_text, p_name)
                if result is not None:
                    logger.info(f"✅ 提供商 {p_name} 回复成功")
                    break
                else:
                    logger.warning(f"❌ 提供商 {p_name} 也失败了")

        # 所有provider都失败 → 友好消息
        if not result:
            logger.warning(f"所有提供商均失败,发送友好提示")
            # 失败时添加❌ reaction
            if feishu_msg_id:
                await _add_feishu_reaction(feishu_msg_id, "❌")
            await _send_friendly_reply(
                msg,
                "😅 抱歉,我暂时没办法回答你.\n"
                "所有模型服务都暂时不可用,请稍后再试试～"
            )
            return

        # 发送回复
        logger.info(f"📤 发送回复到 [{channel_name}]: {result[:100]}...")
        await _send_friendly_reply(msg, result)
        logger.info(f"📤 已回复 [{channel_name}]")

        # 成功时添加✅ reaction
        if feishu_msg_id:
            await _add_feishu_reaction(feishu_msg_id, "✅")

    except Exception as e:
        logger.error(f"处理频道消息失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # 异常时添加❌ reaction
        if feishu_msg_id:
            await _add_feishu_reaction(feishu_msg_id, "❌")
        await _send_friendly_reply(
            msg,
            "😅 抱歉,处理消息时出了点小问题,请稍后再试试～"
        )


async def _add_feishu_reaction(message_id: str, emoji: str = "✅"):
    """
    给飞书消息添加表情反应
    """
    try:
        global channel_manager
        if not channel_manager:
            logger.debug("channel_manager未初始化,跳过reaction")
            return
        ch = channel_manager.get_channel("feishu")
        if not ch:
            logger.debug("飞书频道未找到,跳过reaction")
            return
        if hasattr(ch, 'add_reaction'):
            success = await ch.add_reaction(message_id, emoji)
            if success:
                logger.info(f"✅ 已添加reaction {emoji} 到消息 {message_id[:20]}...")
            else:
                logger.warning(f"⚠️ 添加reaction {emoji} 失败: {message_id[:20]}...")
        else:
            logger.debug(f"频道 feishu 不支持add_reaction")
    except Exception as e:
        logger.warning(f"添加reaction异常: {e}")


async def _start_channel_manager(cm):
    """后台启动频道管理器(不阻塞WebUI启动)"""
    try:
        await cm.load_from_config()
        await cm.start_all()
        logger.info("✅ 频道系统已启动")
    except Exception as e:
        logger.warning(f"⚠️ 频道系统启动失败(WebUI继续运行): {e}")
        import traceback
        logger.debug(traceback.format_exc())


# 生命周期管理(替换已弃用的on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - 启动和关闭"""
    # ====== 启动逻辑 ======
    global channel_manager, user_mapper, message_router
    
    try:
        from dogeey.config import config
        cfg = config.load()
        
        # 1. 初始化EventBus(全局在模块顶部已创建)
        logger.info("🚀 初始化EventBus...")
        
        # 2. 注册消息处理桥接(EventBus → AgentCore)
        event_bus.subscribe("message.received", _handle_channel_message)
        logger.info("✅ 消息处理桥接已注册")
        
        # 3. 初始化UserMapper
        user_mapper = UserMapper(cfg.get("channel_defaults", {}).get("user_mapping", {}))
        logger.info(f"✅ UserMapper已初始化,映射数: {len(user_mapper.get_all_mappings())}")
        
        # 4. 初始化MessageRouter
        message_router = MessageRouter(event_bus)
        logger.info("✅ MessageRouter已初始化")
        
        # 5. 初始化ChannelManager(后台启动,不阻塞WebUI)
        try:
            channel_manager = ChannelManager(cfg, event_bus)
            # 后台启动,不阻塞WebUI启动
            asyncio.create_task(_start_channel_manager(channel_manager))
            logger.info("✅ 频道系统正在后台启动...")
        except Exception as e:
            logger.warning(f"⚠️ 频道系统初始化失败(WebUI继续运行): {e}")
            channel_manager = None
        
    except Exception as e:
        logger.error(f"启动频道系统失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    yield  # 应用运行期间
    
    # ====== 关闭逻辑 ======
    if channel_manager:
        await channel_manager.stop_all()
        logger.info("✅ 频道系统已停止")


# 创建FastAPI应用(使用lifespan)
app = FastAPI(title="Dogeey WebUI", version="1.0.0", lifespan=lifespan)

# 全局频道系统
event_bus = EventBus()
channel_manager = None
user_mapper = None
message_router = None

# 全局会话管理器(Web端使用)
web_session_manager = None


def get_config():
    """获取配置"""
    from dogeey.config import config
    return config.load()

# 挂载静态文件
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def get_session_manager():
    """获取或创建会话管理器(Web端使用)"""
    global web_session_manager
    if web_session_manager is None:
        from dogeey.sessions import SessionManager
        web_session_manager = SessionManager(storage_path="~/.dogeey/web_sessions.json")
    return web_session_manager


def get_agent(session_id: str = None, provider_name: str = None):
    """创建智能体实例（延迟初始化）
    
    Args:
        session_id: 会话ID，如果指定则使用该会话的记忆
        provider_name: 提供商名称，如果指定则覆盖配置中的current_provider
    """
    cfg = get_config()
    
    from dogeey.llm import create_llm_client_from_config
    from dogeey.core import AgentCore
    from dogeey.tools import ToolRegistry, register_builtin_tools
    from dogeey.sessions import SessionManager
    
    # 强制使用astron（因为它认证通过，openrouter已失效）
    if not provider_name:
        provider_name = 'astron'
    
    llm_client = create_llm_client_from_config(cfg, provider_override=provider_name)
    logger.info(f"✅ LLM客户端已创建: model={llm_client.model}, base_url={llm_client.client.base_url}")
    
    # 工具注册
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    
    # 可选组件
    memory_system = None
    user_profile = None
    skill_manager = None
    session_manager = None
    
    try:
        from dogeey.memory import MemorySystem
        db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        memory_system = MemorySystem(db_path)
    except Exception as e:
        logger.warning(f"记忆系统初始化失败: {e}")
    
    try:
        from dogeey.profile import UserProfile
        profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
        user_profile = UserProfile(profile_path)
    except Exception as e:
        logger.warning(f"用户画像初始化失败: {e}")
    
    try:
        from dogeey.skills import SkillManager
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        skill_manager = SkillManager(skills_path)
    except Exception as e:
        logger.warning(f"技能管理器初始化失败: {e}")
    
    # 使用Web会话管理器
    session_manager = get_session_manager()
    
    return AgentCore(
        llm_client=llm_client,
        tool_registry=tool_registry,
        memory_system=memory_system,
        user_profile=user_profile,
        skill_manager=skill_manager,
        session_manager=session_manager
    )


@app.get("/")
async def get_index():
    """返回主页面"""
    html_file = static_dir / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(encoding='utf-8'))
    return HTMLResponse(content="<h1>index.html not found</h1>")


@app.get("/api/config")
async def api_get_config():
    """获取当前配置"""
    try:
        cfg = get_config()
        # 隐藏敏感信息
        safe_cfg = json.loads(json.dumps(cfg))
        if 'llm' in safe_cfg:
            for provider in safe_cfg['llm'].get('providers', []):
                if 'api_key' in provider:
                    provider['api_key'] = '***'
        return safe_cfg
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/memories")
async def api_get_memories(limit: int = 50):
    """获取记忆列表"""
    try:
        from dogeey.memory import MemorySystem
        from dogeey.config import config
        cfg = get_config()
        db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        mem = MemorySystem(db_path)
        memories = mem.get_all_memories(limit)
        return memories
    except Exception as e:
        logger.error(f"获取记忆失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/memories/{memory_id}")
async def api_delete_memory(memory_id: int):
    """删除记忆"""
    try:
        from dogeey.memory import MemorySystem
        from dogeey.config import config
        cfg = get_config()
        db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
        mem = MemorySystem(db_path)
        success = mem.delete_memory(memory_id)
        return {"success": success}
    except Exception as e:
        logger.error(f"删除记忆失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/skills")
async def api_get_skills(brief: bool = True):
    """获取技能列表"""
    try:
        from dogeey.skills import SkillManager
        from dogeey.config import config
        cfg = get_config()
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        mgr = SkillManager(skills_path)
        return mgr.list_skills(brief=brief)
    except Exception as e:
        logger.error(f"获取技能失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/skills/{name}")
async def api_get_skill(name: str):
    """获取技能详情"""
    try:
        from dogeey.skills import SkillManager
        from dogeey.config import config
        cfg = get_config()
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        mgr = SkillManager(skills_path)
        skill = mgr.load_skill(name)
        if not skill:
            return JSONResponse(status_code=404, content={"error": "技能不存在"})
        return {
            "name": skill.name,
            "category": skill.category,
            "description": skill.description,
            "trigger_keywords": skill.trigger_keywords,
            "token_cost": skill.token_cost,
            "success_count": skill.success_count,
            "last_used": skill.last_used,
            "created_at": skill.created_at,
            "full_content": getattr(skill, 'full_content', None)
        }
    except Exception as e:
        logger.error(f"获取技能详情失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/skills/{name}")
async def api_delete_skill(name: str):
    """删除技能"""
    try:
        from dogeey.skills import SkillManager
        from dogeey.config import config
        cfg = get_config()
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        mgr = SkillManager(skills_path)
        if mgr.delete_skill(name):
            return {"success": True, "message": f"技能 '{name}' 已删除"}
        else:
            return JSONResponse(status_code=404, content={"error": "技能不存在"})
    except Exception as e:
        logger.error(f"删除技能失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/profile")
async def api_get_profile():
    """获取用户画像"""
    try:
        from dogeey.profile import UserProfile
        from dogeey.config import config
        cfg = get_config()
        profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
        profile = UserProfile(profile_path)
        return profile.to_dict()
    except Exception as e:
        logger.error(f"获取画像失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket端点 - 实时对话(优化版)"""
    await websocket.accept()
    active_connections.append(websocket)
    logger.info(f"WebSocket连接建立,当前连接数: {len(active_connections)}")
    
    agent = None
    session_manager = None
    try:
        # 创建智能体实例和会话管理器
        agent = get_agent()
        session_manager = get_session_manager()
        
        # 确保有当前会话(如果没有就创建一个)
        if not session_manager.get_current_session():
            session = session_manager.create_session("默认会话")
            logger.info(f"自动创建默认会话: {session.session_id}")
        
        # 发送连接成功消息(包含当前会话信息)
        current = session_manager.get_current_session()
        await websocket.send_json({
            "type": "system",
            "content": f"✅ Dogeey 已连接!当前会话: {current.title}"
        })
        
        # 通知前端刷新会话列表
        await websocket.send_json({
            "type": "sessions_update",
            "sessions": session_manager.list_sessions(),
            "current_session_id": session_manager.current_session_id
        })
        
        while True:
            # 接收消息
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                # 超时,发送心跳
                await websocket.send_json({"type": "ping"})
                continue
            
            # 处理session_id(可能是init消息或普通消息)
            session_id = data.get("session_id")
            if session_id and session_manager:
                session_manager.switch_session(session_id)
                logger.info(f"切换到会话: {session_id}")
            
            instruction = data.get("message", "")
            verbose = data.get("verbose", False)
            
            if not instruction:
                await websocket.send_json({"type": "error", "content": "消息为空"})
                continue
            
            # 发送开始信号
            await websocket.send_json({
                "type": "start",
                "content": f"🤔 正在思考: {instruction[:50]}..."
            })
            
            try:
                # 在线程池中执行,避免阻塞事件循环
                result = await asyncio.to_thread(agent.run, instruction, verbose)
                
                # 发送结果
                await websocket.send_json({
                    "type": "response",
                    "content": result
                })
                
                # 发送完成信号
                await websocket.send_json({
                    "type": "end",
                    "content": "✅ 执行完成"
                })
                
                # 对话完成,推送会话列表更新(更新消息数)
                await websocket.send_json({
                    "type": "sessions_update",
                    "sessions": session_manager.list_sessions(),
                    "current_session_id": session_manager.current_session_id
                })
                
            except Exception as e:
                logger.error(f"执行指令失败: {e}")
                await websocket.send_json({
                    "type": "error",
                    "content": f"执行出错: {str(e)}"
                })
        
    except WebSocketDisconnect:
        logger.info("WebSocket连接断开")
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        if websocket in active_connections:
            active_connections.remove(websocket)
    finally:
        # 清理
        if websocket in active_connections:
            active_connections.remove(websocket)
        logger.info(f"WebSocket连接清理完成,当前连接数: {len(active_connections)}")


async def broadcast(message: dict):
    """广播消息给所有连接的客户端"""
    disconnected = []
    for conn in active_connections:
        try:
            await conn.send_json(message)
        except:
            disconnected.append(conn)
    
    # 清理断开的连接
    for conn in disconnected:
        if conn in active_connections:
            active_connections.remove(conn)


@app.get("/api/providers")
async def api_get_providers():
    """列出所有配置的模型和提供商"""
    try:
        cfg = get_config()
        providers = cfg.get('llm', {}).get('providers', [])
        current = cfg.get('llm', {}).get('current_provider', '')
        
        result = []
        for p in providers:
            result.append({
                "name": p.get('name'),
                "models": p.get('models', []),
                "default_model": p.get('default_model'),
                "is_current": p.get('name') == current
            })
        return {"providers": result, "current": current}
    except Exception as e:
        logger.error(f"获取提供商列表失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/provider")
async def api_set_provider(data: dict):
    """切换当前默认提供商"""
    try:
        provider_name = data.get('name', '')
        if not provider_name:
            return JSONResponse(status_code=400, content={"error": "缺少name字段"})
        
        cfg = get_config()
        providers = cfg.get('llm', {}).get('providers', [])
        
        # 验证provider是否存在
        found = False
        for p in providers:
            if p.get('name') == provider_name:
                found = True
                break
        
        if not found:
            return JSONResponse(status_code=404, content={"error": f"找不到提供商: {provider_name}"})
        
        # 更新配置
        from dogeey.config import config as cfg_module
        cfg_module.set('llm.current_provider', provider_name)
        cfg_module.save()
        
        return {"success": True, "current_provider": provider_name}
    except Exception as e:
        logger.error(f"切换提供商失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# =========== 飞书Webhook路由 ===========
@app.post("/webhook/feishu")
async def feishu_webhook(request: Request):
    """飞书事件回调接口 - 快速响应版(避免平台超时)"""
    try:
        body_bytes = await request.body()
        body_str = body_bytes.decode('utf-8')

        logger.debug(f"飞书Webhook原始请求: {body_str[:500]}")

        try:
            body = json.loads(body_str)
        except json.JSONDecodeError as e:
            logger.error(f"飞书Webhook JSON解析失败: {e}")
            logger.error(f"原始请求体: {body_str[:500]}")
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

        headers = dict(request.headers)

        if not channel_manager:
            logger.error("Channel manager未初始化")
            return JSONResponse(status_code=503, content={"error": "Channel manager not initialized"})

        feishu_channel = channel_manager.get_channel("feishu")
        if not feishu_channel:
            logger.warning("飞书频道未加载")
            return JSONResponse(status_code=404, content={"error": "Feishu channel not found"})

        header = body.get("header", {})
        event_type = header.get("event_type", "")

        if event_type == "url_verification":
            result = await feishu_channel.handle_webhook(body, headers)
            return result

        async def _process_in_background():
            try:
                await feishu_channel.handle_webhook(body, headers)
            except Exception as e:
                logger.error(f"飞书Webhook后台处理异常: {e}")
                import traceback
                logger.error(traceback.format_exc())

        asyncio.create_task(_process_in_background())
        return JSONResponse(content={"success": True})

    except Exception as e:
        logger.error(f"飞书Webhook处理失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=500, content={"error": str(e)})


# =========== 频道健康检查 ===========
@app.get("/api/channels/health")
async def api_channels_health():
    """获取所有频道健康状态"""
    try:
        if not channel_manager:
            return JSONResponse(status_code=503, content={"error": "Channel manager not initialized"})
        
        channels_status = await channel_manager.list_channels()
        return {
            "status": "ok",
            "channels": channels_status,
            "watcher_running": False
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# =========== 路由管理 ===========
@app.get("/api/routes")
async def api_get_routes():
    """获取所有消息路由规则"""
    if not message_router:
        return JSONResponse(status_code=503, content={"error": "Message router not initialized"})
    
    return {"routes": message_router.get_routes()}


# =========== 用户映射管理 ===========
@app.get("/api/user-mapping")
async def api_get_user_mapping():
    """获取所有用户映射"""
    if not user_mapper:
        return JSONResponse(status_code=503, content={"error": "User mapper not initialized"})
    
    return {"mappings": user_mapper.get_all_mappings()}


@app.post("/api/user-mapping")
async def api_add_user_mapping(data: dict):
    """添加用户映射"""
    if not user_mapper:
        return JSONResponse(status_code=503, content={"error": "User mapper not initialized"})
    
    channel = data.get("channel")
    user_id = data.get("user_id")
    username = data.get("username")
    
    if not all([channel, user_id, username]):
        return JSONResponse(status_code=400, content={"error": "缺少必要参数"})
    
    user_mapper.set_mapping(channel, user_id, username)
    
    # 保存到配置
    from dogeey.config import config
    cfg = config.load()
    if "channel_defaults" not in cfg:
        cfg["channel_defaults"] = {}
    if "user_mapping" not in cfg["channel_defaults"]:
        cfg["channel_defaults"]["user_mapping"] = {}
    
    key = f"{channel}:{user_id}"
    cfg["channel_defaults"]["user_mapping"][key] = username
    config.save()
    
    return {"success": True, "mapping": f"{key} -> {username}"}


# 旧的事件处理已迁移到lifespan中
# 无需保留on_event装饰的函数


# ============ 会话管理 API ============

@app.get("/api/sessions")
async def api_list_sessions():
    """列出所有会话"""
    try:
        sm = get_session_manager()
        sessions = sm.list_sessions()
        current_id = sm.current_session_id
        return {
            "sessions": sessions,
            "current_session_id": current_id
        }
    except Exception as e:
        logger.error(f"列出会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/sessions/create")
async def api_create_session(data: dict):
    """创建新会话"""
    try:
        title = data.get("title", "")
        sm = get_session_manager()
        session = sm.create_session(title)
        return {
            "success": True,
            "session": session.get_info()
        }
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/sessions/switch")
async def api_switch_session(data: dict):
    """切换会话"""
    try:
        session_id = data.get("session_id", "")
        if not session_id:
            return JSONResponse(status_code=400, content={"error": "缺少session_id"})
        
        sm = get_session_manager()
        if sm.switch_session(session_id):
            session = sm.get_current_session()
            return {
                "success": True,
                "session": session.get_info()
            }
        else:
            return JSONResponse(status_code=404, content={"error": f"找不到会话: {session_id}"})
    except Exception as e:
        logger.error(f"切换会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    """删除会话"""
    try:
        sm = get_session_manager()
        if sm.delete_session(session_id):
            return {"success": True}
        else:
            return JSONResponse(status_code=400, content={"error": "删除失败(可能是最后一个会话)"})
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/sessions/rename")
async def api_rename_session(data: dict):
    """重命名会话"""
    try:
        session_id = data.get("session_id", "")
        new_title = data.get("title", "")
        
        if not session_id or not new_title:
            return JSONResponse(status_code=400, content={"error": "缺少必要参数"})
        
        sm = get_session_manager()
        if sm.rename_session(session_id, new_title):
            return {"success": True}
        else:
            return JSONResponse(status_code=404, content={"error": f"找不到会话: {session_id}"})
    except Exception as e:
        logger.error(f"重命名会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/sessions/clear")
async def api_clear_session():
    """清空当前会话历史"""
    try:
        sm = get_session_manager()
        sm.clear_current_session()
        return {"success": True}
    except Exception as e:
        logger.error(f"清空会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/current-session")
async def api_get_current_session():
    """获取当前会话信息"""
    try:
        sm = get_session_manager()
        session = sm.get_current_session()
        if session:
            return {
                "session_id": session.session_id,
                "title": session.title,
                "message_count": len(session.short_term_memory)
            }
        return JSONResponse(status_code=404, content={"error": "没有活跃会话"})
    except Exception as e:
        logger.error(f"获取当前会话失败: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
