"""
CLI 入口 - Claude Code 风格交互
"""
import sys
import os
import readline  # 启用更好的行编辑支持（退格、方向键、历史记录）
import click
import json
from pathlib import Path
from datetime import datetime
from .config import config, DEFAULT_CONFIG_DIR
from .ascii_art import get_logo, get_small_logo
from .fancy_output import (
    console, show_startup_animation, show_welcome_for_onboarding,
    show_onboarding_question, show_confirmation, show_error, show_success, 
    show_info, show_warning,
    show_result_header, create_input_box
)
from .cron.manager import get_cron_manager
from .cron.scheduler import get_scheduler


# ============ 交互式对话会话 ============
class DogeeySession:
    """Dogeey 交互会话（类似 Claude Code）"""
    
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.agent = None
        self.llm_client = None
        self.history = []  # 会话历史
        self.session_manager = None
        # 定时任务
        self.cron_manager = None
        self.scheduler = None
        # 频道管理
        self.event_bus = None
        self.channel_manager = None
        
    def init_agent(self):
        """初始化智能体"""
        try:
            from .llm import create_llm_client_from_config
            from .core import AgentCore
            from .tools import ToolRegistry, register_builtin_tools
            from .sessions import SessionManager
            
            cfg = config.load()
            
            # 初始化会话管理器
            self.session_manager = SessionManager()
            
            # LLM 客户端
            self.llm_client = create_llm_client_from_config(cfg)
            
            # [已禁用] 强制切换到kimi-k2.5 - 由配置文件控制
            # 原代码会忽略current_provider设置，强制使用openrouter
            # 如需使用kimi，请在config.json中配置current_provider为openrouter
            pass
            
            # 工具注册
            tool_registry = ToolRegistry()
            register_builtin_tools(tool_registry)
            
            # 可选组件
            memory_system = None
            user_profile = None
            skill_manager = None
            
            try:
                from .memory import MemorySystem
                db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
                memory_system = MemorySystem(db_path)
            except:
                pass
            
            try:
                from .profile import UserProfile
                profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
                user_profile = UserProfile(profile_path)
            except:
                pass
            
            try:
                from .skills import SkillManager
                skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
                skill_manager = SkillManager(skills_path)
            except:
                pass
            
            self.agent = AgentCore(
                llm_client=self.llm_client,
                tool_registry=tool_registry,
                memory_system=memory_system,
                user_profile=user_profile,
                skill_manager=skill_manager,
                session_manager=self.session_manager,
                loaded_skills=getattr(self, '_loaded_skills', [])
            )
            
            # 初始化定时任务系统
            self._init_cron_system()
            

            # 初始化频道系统（飞书等）
            self._init_channels()

            return True
        except Exception as e:
            click.echo(f"❌ 初始化失败: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return False

    
    # ============ 定时任务系统初始化 ============
    
    def _init_cron_system(self):
        """初始化定时任务系统"""
        try:
            # 初始化管理器
            self.cron_manager = get_cron_manager()
            
            # 初始化调度器
            self.scheduler = get_scheduler(check_interval=60)
            self.scheduler.cron_manager = self.cron_manager
            
            # 设置任务执行器
            self.scheduler.set_job_executor(self._execute_cron_job)
            
            # 启动调度器（后台线程）
            self.scheduler.start()
            
            if self.verbose:
                click.echo("✅ 定时任务系统已初始化")
        except Exception as e:
            if self.verbose:
                click.echo(f"⚠️ 定时任务系统初始化失败: {e}")
    
    # ============ 频道系统初始化 ============
    
    def _init_channels(self):
        """初始化并启动频道（飞书等）"""
        try:
            import asyncio
            from dogeey.event_bus import EventBus
            from dogeey.channels.manager import ChannelManager
            
            cfg = config.load()
            channels_config = cfg.get("channels", {})
            
            if not channels_config:
                if self.verbose:
                    click.echo("⚠️ 未配置任何频道")
                return
            
            self.event_bus = EventBus()
            self.channel_manager = ChannelManager(cfg, self.event_bus)
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.channel_manager.load_from_config())
                    asyncio.ensure_future(self.channel_manager.start_all())
                    click.echo("✅ 频道系统已在运行中的事件循环上调度")
                else:
                    loop.run_until_complete(self.channel_manager.load_from_config())
                    loop.run_until_complete(self.channel_manager.start_all())
                    click.echo("✅ 频道系统已启动")
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loaded = loop.run_until_complete(self.channel_manager.load_from_config())
                if loaded and loaded > 0:
                    loop.run_until_complete(self.channel_manager.start_all())
                    click.echo(f"✅ 已启动 {loaded} 个频道")
            
            self.event_bus.subscribe("message.received", self._handle_channel_message)
            click.echo("✅ 消息处理器已注册（飞书等频道可以回复了）")
                    
        except Exception as e:
            click.echo(f"⚠️ 频道系统初始化失败: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
    
    async def _handle_channel_message(self, event):
        """
        处理来自频道的消息（飞书/Discord等）
        这是修复"已读不回"问题的关键代码！
        """
        from dogeey.message import Message, MessageType
        import asyncio
        
        msg = event.data
        channel_name = msg.channel  # 如 "feishu"
        
        # 找到对应的频道实例（用于发送回复）
        channel = self.channel_manager.get_channel(channel_name)
        if not channel:
            click.echo(f"⚠️ 未找到频道: {channel_name}")
            return
        
        click.echo(f"📨 收到来自 {channel_name} 的消息: {msg.text[:50]}...")
        
        # 检查agent是否就绪
        if not self.agent:
            click.echo("⚠️ Agent未初始化，无法处理消息")
            return
        
        # 🤖 让AI处理消息（在线程中运行，因为agent.run是同步的）
        try:
            click.echo(f"🧠 AI处理中...")
            response = await asyncio.to_thread(self.agent.run, msg.text)
            click.echo(f"✅ AI回复: {response[:100]}...")
        except Exception as e:
            response = f"抱歉，处理消息时出错了: {str(e)}"
            click.echo(f"❌ AI处理错误: {e}")
        
        # 📤 发送回复
        if msg.reply_token and response:
            reply_msg = Message(
                id=f"reply_{msg.id}",
                channel=channel_name,
                user_id="dogeey",
                username="dogeey",
                text=response,
                type=MessageType.TEXT,
                reply_token=msg.reply_token,
                metadata={"reply_to_message_id": msg.id}
            )
            
            try:
                await channel.send(reply_msg)
                click.echo(f"📤 已回复到 {channel_name}")
            except Exception as e:
                click.echo(f"❌ 发送回复失败: {e}")
        else:
            click.echo(f"⚠️ 缺少reply_token，无法回复")
    
    def _execute_cron_job(self, job) -> str:
        """执行定时任务（任务执行器）"""
        try:
            # 创建独立的agent来执行任务
            from .llm import create_llm_client_from_config
            from .core import AgentCore
            from .tools import ToolRegistry, register_builtin_tools
            
            cfg = config.load()
            
            # 使用任务指定的模型/provider（如果有的话）
            llm_client = create_llm_client_from_config(cfg)
            if job.model:
                llm_client.model = job.model
            if job.provider:
                # 这里需要根据provider重新创建client
                pass  # 简化版，暂时不实现
            
            # 创建工具注册表
            tool_registry = ToolRegistry()
            register_builtin_tools(tool_registry)
            
            # 创建agent
            agent = AgentCore(
                llm_client=llm_client,
                tool_registry=tool_registry,
                memory_system=None,  # 定时任务不使用记忆
                user_profile=None,  # 不使用用户画像
                skill_manager=None,  # 不使用技能（除非任务指定）
                loaded_skills=job.skills if job.skills else []
            )
            
            # 执行任务
            result = agent.run(job.prompt, verbose=False)
            
            # 根据deliver设置处理投递（简化版：只保存到文件）
            if job.deliver == "local" or not job.deliver or job.deliver == "origin":
                # 保存到文件
                output_dir = Path.home() / ".dogeey" / "cron" / "output"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                output_file = output_dir / f"{job.job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(f"# Cron Job: {job.name}\n")
                    f.write(f"# Time: {datetime.now().isoformat()}\n")
                    f.write(f"# Prompt: {job.prompt}\n\n")
                    f.write(result)
                
                return f"任务执行完成，结果已保存: {output_file}\n\n{result}"
            else:
                # 其他deliver方式暂不实现
                return f"任务执行完成（deliver={job.deliver}）\n\n{result}"
        
        except Exception as e:
            error_msg = f"任务执行失败: {str(e)}"
            if self.verbose:
                import traceback
                traceback.print_exc()
            return error_msg
    
    # ============ 会话管理方法 ============
    
    def _list_sessions(self):
        """列出所有会话"""
        if not self.session_manager:
            click.echo("❌ 会话管理器未初始化")
            return
        
        sessions = self.session_manager.list_sessions()
        current_id = self.session_manager.current_session_id
        
        if not sessions:
            click.echo("📭 没有会话，使用 /new 创建")
            return
        
        click.echo("📝 会话列表:")
        click.echo("━" * 50)
        for sess in sessions:
            marker = "➤" if sess['session_id'] == current_id else "  "
            click.echo(f"{marker} [{sess['session_id']}] {sess['title']}")
            click.echo(f"   消息数: {sess['message_count']} | 更新: {sess['updated_at'][:19]}")
            if sess['preview']:
                click.echo(f"   预览: {sess['preview']}...")
            click.echo()
        click.echo("━" * 50)
        click.echo("💡 使用 /switch <id> 切换会话")
    
    def _create_session(self, title: str = None):
        """创建新会话"""
        if not self.session_manager:
            click.echo("❌ 会话管理器未初始化")
            return
        
        session = self.session_manager.create_session(title or "")
        click.echo(f"✅ 已创建会话: [{session.session_id}] {session.title}")
        click.echo(f"   现在切换到新会话了，可以开始对话！")
    
    def _switch_session(self, session_id: str):
        """切换会话"""
        if not self.session_manager:
            click.echo("❌ 会话管理器未初始化")
            return
        
        # 如果只输入了部分ID，尝试模糊匹配
        if len(session_id) < 8:
            matches = [s for s in self.session_manager.sessions.keys() if s.startswith(session_id)]
            if len(matches) == 1:
                session_id = matches[0]
            elif len(matches) > 1:
                click.echo(f"❌ 多个匹配: {matches}")
                return
        
        if self.session_manager.switch_session(session_id):
            session = self.session_manager.get_current_session()
            click.echo(f"✅ 已切换到会话: [{session.session_id}] {session.title}")
            click.echo(f"   消息数: {len(session.short_term_memory)}")
        else:
            click.echo(f"❌ 找不到会话: {session_id}")
            click.echo(f"   使用 /sessions 查看所有会话")
    
    def _delete_session(self, session_id: str):
        """删除会话"""
        if not self.session_manager:
            click.echo("❌ 会话管理器未初始化")
            return
        
        # 如果只输入了部分ID，尝试模糊匹配
        if len(session_id) < 8:
            matches = [s for s in self.session_manager.sessions.keys() if s.startswith(session_id)]
            if len(matches) == 1:
                session_id = matches[0]
            elif len(matches) > 1:
                click.echo(f"❌ 多个匹配: {matches}")
                return
        
        session = self.session_manager.get_session(session_id)
        if not session:
            click.echo(f"❌ 找不到会话: {session_id}")
            return
        
        # 确认删除
        confirm = click.prompt(f"确认删除会话 [{session_id}] {session.title}? (yes/no)", default="no")
        if confirm.lower() == "yes":
            if self.session_manager.delete_session(session_id):
                click.echo(f"✅ 已删除会话: {session.title}")
            else:
                click.echo("❌ 删除失败（可能是最后一个会话）")
        else:
            click.echo("取消删除")
    
    def _rename_session(self, session_id: str, new_title: str):
        """重命名会话"""
        if not self.session_manager:
            click.echo("❌ 会话管理器未初始化")
            return
        
        # 如果只输入了部分ID，尝试模糊匹配
        if len(session_id) < 8:
            matches = [s for s in self.session_manager.sessions.keys() if s.startswith(session_id)]
            if len(matches) == 1:
                session_id = matches[0]
            elif len(matches) > 1:
                click.echo(f"❌ 多个匹配: {matches}")
                return
        
        if self.session_manager.rename_session(session_id, new_title):
            click.echo(f"✅ 已重命名会话为: {new_title}")
        else:
            click.echo(f"❌ 找不到会话: {session_id}")
    
    def show_status(self):
        """显示系统状态（不包含Logo，Logo由调用方控制）"""
        click.echo()
        
        # 系统状态卡片
        click.echo("━" * 50)
        click.echo("📊 系统状态")
        click.echo("━" * 50)
        
        if self.llm_client:
            click.echo(f"🤖 模型: {self.llm_client.model}")
        
        cfg = config.load()
        providers = cfg.get('llm', {}).get('providers', [])
        if providers:
            click.echo(f"📡 提供商: {len(providers)} 个已配置")
        
        click.echo()
        click.echo("组件状态:")
        click.echo(f"  🧠 记忆系统: {'✅ 已加载' if self.agent and self.agent.memory else '❌ 未启用'}")
        click.echo(f"  👤 用户画像: {'✅ 已加载' if self.agent and self.agent.profile else '❌ 未启用'}")
        click.echo(f"  📚 技能库: {'✅ 已加载' if self.agent and self.agent.skills else '❌ 未启用'}")
        
        click.echo()
        click.echo("━" * 50)
        click.echo()
        
        # 快速提示
        click.echo("💡 快速开始:")
        click.echo("  • 直接输入文字开始对话")
        click.echo("  • 输入 /help 查看所有命令")
        click.echo("  • 输入 /quit 或 Ctrl+D 退出")
        click.echo()
        click.echo("━" * 50)
        click.echo()
    
    def run_interactive(self):
        """运行交互式会话"""
        if not self.init_agent():
            return
        
        import sys
        import time
        
        # 如果没有TTY（后台运行），进入服务模式
        if not sys.stdin.isatty():
            # 检查是否有频道在运行
            has_channels = self.channel_manager and len(self.channel_manager.channels) > 0
            if not has_channels:
                click.echo("⚠️  Dogeey 服务模式需要频道才能运行。")
                click.echo("   当前没有启用的频道，直接退出。")
                return
            
            click.echo("🤖 Dogeey 服务模式已启动（无交互终端）")
            click.echo("   频道已运行，可以接收消息。按 Ctrl+C 或输入 /exit 退出。")
            try:
                while True:
                    # 检查是否有输入（非阻塞）
                    import select
                    if select.select([sys.stdin], [], [], 1)[0]:
                        line = sys.stdin.readline().strip()
                        if line == '/exit':
                            break
                    # 否则继续等待
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
            # 清理频道
            if self.channel_manager:
                import asyncio
                try:
                    asyncio.run(self.channel_manager.stop_all())
                except Exception:
                    pass
            click.echo("\n👋 再见！")
            return
        
        # 检查是否需要初次引导
        needs_onboarding = False
        if self.agent and self.agent.profile:
            needs_onboarding = self.agent.profile.needs_onboarding()
        
        if needs_onboarding:
            # 需要引导：显示完整启动动画
            try:
                show_startup_animation()
            except Exception as e:
                # 如果动画失败，降级到简单输出
                click.echo(get_logo())
                click.echo()
            
            # 显示欢迎信息，然后进入引导流程
            show_welcome_for_onboarding()
            
            from .profile import run_onboarding
            if not run_onboarding(self.agent.profile):
                show_error("引导流程未完成，使用默认配置继续...")
                # 标记为已完成，避免下次再提示
                self.agent.profile.profile['meta']['needs_onboarding'] = False
                self.agent.profile.profile['meta']['onboarding_completed'] = True
                self.agent.profile.save()
            
            # 引导完成后显示完整系统状态
            click.echo()
            self.show_status()
        else:
            # 不需要引导：直接显示简单Logo和系统状态
            click.echo(get_logo())
            click.echo()
            self.show_status()
        
        # 设置readline支持（历史记录、更好的编辑）
        # 重要：必须在第一次input()之前初始化
        histfile = os.path.join(os.path.expanduser("~"), ".dogeey_history")
        try:
            if os.path.exists(histfile) and os.access(histfile, os.R_OK):
                readline.read_history_file(histfile)
            readline.set_history_length(1000)
        except (FileNotFoundError, PermissionError, OSError) as e:
            if self.verbose:
                show_warning(f"无法加载历史记录: {e}")
        
        def save_history():
            try:
                readline.write_history_file(histfile)
            except (PermissionError, OSError):
                pass
        
        import atexit
        atexit.register(save_history)
        
        # 输入提示符（用cyan蓝色，不干扰readline）
        input_prompt = "\001\033[36m\002>>> \001\033[0m\002"
        
        # 注册退出时的清理函数（停止调度器）
        def cleanup_cron():
            if self.scheduler:
                try:
                    self.scheduler.shutdown()
                    if self.verbose:
                        click.echo("✅ 定时任务系统已停止")
                except Exception as e:
                    if self.verbose:
                        click.echo(f"⚠️ 停止定时任务系统时出错: {e}")
        
        import atexit
        atexit.register(cleanup_cron)
        
        # 注册退出时的清理函数（停止channels）
        def cleanup_channels():
            import asyncio
            if self.channel_manager:
                try:
                    asyncio.run(self.channel_manager.stop_all())
                    click.echo("✅ 频道已停止")
                except Exception as e:
                    if self.verbose:
                        click.echo(f"⚠️ 停止频道时出错: {e}")
        
        import atexit
        atexit.register(cleanup_channels)
        
        click.echo()
        click.echo("💡 提示: 输入 /help 查看命令 | Ctrl+D 退出 | 上下键查看历史")
        click.echo()
        
        while True:
            try:
                # 显示模型状态栏 (固定在输入框上方)
                if self.llm_client:
                    model = self.llm_client.model
                    # 获取provider名称
                    cfg = config.load()
                    provider = cfg.get('llm', {}).get('current_provider', 'unknown')
                    
                    # 获取当前token数
                    current_tokens = 0
                    max_tokens = 256000  # 默认值
                    
                    # 尝试从agent获取历史并估算token
                    if self.agent:
                        try:
                            from dogeey.context_compressor import ContextCompressor
                            compressor = ContextCompressor()
                            
                            # 获取历史消息
                            messages = []
                            if hasattr(self.agent, 'short_term_memory'):
                                for mem in self.agent.short_term_memory:
                                    if isinstance(mem, dict):
                                        if 'user' in mem:
                                            messages.append({'role': 'user', 'content': mem['user']})
                                        if 'assistant' in mem:
                                            messages.append({'role': 'assistant', 'content': mem['assistant']})
                            
                            if messages:
                                current_tokens = compressor.estimate_tokens(messages)
                            max_tokens = compressor.get_context_window(model)
                        except Exception as e:
                            if self.verbose:
                                show_warning(f"估算token失败: {e}")
                    
                    # 显示状态栏
                    from .fancy_output import show_model_status
                    show_model_status(model, provider, current_tokens, max_tokens)
                
                # 显示输入提示符（带颜色）
                print(input_prompt, end="", flush=True)
                user_input = input()
                
                # 处理命令
                if not user_input.strip():
                    continue
                
                if user_input.startswith('/'):
                    if self._handle_command(user_input):
                        cleanup_channels()  # 退出前停止channels
                        break
                    continue
                
                # 执行指令
                self._execute_instruction(user_input)
                
            except EOFError:
                # Ctrl+D 退出
                cleanup_channels()  # 退出前停止channels
                click.echo("\n👋 再见！")
                break
            except KeyboardInterrupt:
                # Ctrl+C 中断当前操作，但不退出
                click.echo("\n⚠️ 操作已取消")
                continue
            except Exception as e:
                show_error(f"错误: {e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
    
    def _handle_command(self, cmd):
        """处理斜杠命令"""
        cmd = cmd.lower().strip()
        
        if cmd in ['/quit', '/exit', '/q']:
            click.echo("👋 再见！")
            return True
        
        elif cmd in ['/help', '/h']:
            self._show_help()
        
        elif cmd.startswith('/model '):
            model = cmd[7:].strip()
            if self.llm_client:
                old = self.llm_client.model
                self.llm_client.model = model
                click.echo(f"✅ 模型已切换: {old} → {model}")
        
        elif cmd.startswith('/provider '):
            provider_name = cmd[10:].strip()
            cfg = config.load()
            providers = cfg.get('llm', {}).get('providers', [])
            
            # 查找provider
            found = False
            for p in providers:
                if p['name'] == provider_name:
                    found = True
                    break
            
            if not found:
                click.echo(f"❌ 找不到提供商: {provider_name}")
                click.echo(f"   可用: {[p['name'] for p in providers]}")
                return False
            
            # 切换current_provider
            cfg['llm']['current_provider'] = provider_name
            from dogeey.config import config as cfg_module
            cfg_module.set('llm.current_provider', provider_name)
            cfg_module.save()
            
            # 重新初始化agent（使用新provider）
            click.echo(f"✅ 已切换到提供商: {provider_name}")
            click.echo("⚠️  需要重启dogeey才能生效（或输入 /reload）")
        
        elif cmd == '/reload':
            click.echo("🔄 重新初始化智能体...")
            if self.init_agent():
                click.echo("✅ 重新初始化成功")
            else:
                click.echo("❌ 重新初始化失败")
        
        elif cmd == '/status':
            self.show_status()
        
        # ============ 元认知命令 ============
        elif cmd in ['/metacognition', '/mc']:
            if self.agent:
                report = self.agent.get_metacognition_report()
                click.echo(report)
            else:
                click.echo("❌ 智能体未初始化")
        
        elif cmd == '/blindspots':
            if self.agent:
                blindspots = self.agent.get_blindspots()
                if blindspots:
                    click.echo("🔴 已识别盲区:")
                    for bs in blindspots:
                        click.echo(f"  • {bs['task_type']}: {bs['reason']}")
                else:
                    click.echo("✅ 暂未发现盲区")
            else:
                click.echo("❌ 智能体未初始化")
        
        elif cmd == '/learning-plan':
            if self.agent:
                plan = self.agent.get_learning_plan()
                click.echo("📚 学习计划:")
                if plan.get('target_blindspots'):
                    click.echo("\n🎯 针对盲区:")
                    for t in plan['target_blindspots']:
                        click.echo(f"  • {t['task_type']}: {t['reason']}")
                if plan.get('target_weak_types'):
                    click.echo("\n📉 针对薄弱环节:")
                    for t in plan['target_weak_types']:
                        click.echo(f"  • {t['task_type']}: 置信度{t['confidence']:.0%}")
                if plan.get('actions'):
                    click.echo("\n💡 行动建议:")
                    for action in plan['actions']:
                        click.echo(f"  • {action}")
            else:
                click.echo("❌ 智能体未初始化")
        
        elif cmd.startswith('/rate '):
            # 格式: /rate <评分>
            rating = cmd[6:].strip()
            if not rating:
                click.echo("❌ 格式: /rate <评分>")
                click.echo("   例如: /rate 5星、/rate 4分、/rate great")
            elif self.agent:
                # 获取最近一次用户输入
                recent_input = ""
                if self.session_manager:
                    history = self.session_manager.get_current_memory()
                    if history:
                        recent_input = history[-1].get('user', '') if isinstance(history[-1], dict) else ''
                elif self.agent.short_term_memory:
                    recent_input = self.agent.short_term_memory[-1].get('user', '')
                
                if not recent_input:
                    click.echo("❌ 未找到最近的对话记录")
                else:
                    result = self.agent.rate_response(recent_input, rating)
                    click.echo(result)
            else:
                click.echo("❌ 智能体未初始化")
        
        elif cmd == '/clear':
            if self.agent:
                if self.session_manager:
                    self.session_manager.clear_current_session()
                    click.echo("✅ 当前会话历史已清除")
                else:
                    self.agent.clear_memory()
                    click.echo("✅ 短期记忆已清除")
        
        elif cmd in ['/reflect', '/reflection']:
            if self.agent:
                reflection = self.agent.metacognition.generate_daily_reflection()
                click.echo(reflection)
            else:
                click.echo("❌ 智能体未初始化")
        
        elif cmd.startswith('/run '):
            instruction = cmd[5:].strip()
            self._execute_instruction(instruction)
        
        elif cmd == '/verbose':
            self.verbose = not self.verbose
            click.echo(f"✅ 详细模式: {'开' if self.verbose else '关'}")
        
        # ============ 会话管理命令 ============
        elif cmd == '/sessions' or cmd == '/sess':
            self._list_sessions()
        
        elif cmd.startswith('/new '):
            title = cmd[5:].strip()
            self._create_session(title)
        
        elif cmd.startswith('/switch '):
            session_id = cmd[8:].strip()
            self._switch_session(session_id)
        
        elif cmd.startswith('/delete '):
            session_id = cmd[8:].strip()
            self._delete_session(session_id)
        
        elif cmd == '/rename ':
            # 格式: /rename <session_id> <new_title>
            parts = cmd[8:].strip().split(' ', 1)
            if len(parts) < 2:
                click.echo("❌ 格式: /rename <session_id> <new_title>")
            else:
                self._rename_session(parts[0], parts[1])
        
        # ============ 技能管理命令 ============
        elif cmd == '/skills' or cmd == '/skills all':
            self._list_skills(brief=(cmd == '/skills'))
        
        elif cmd.startswith('/skill load '):
            skill_name = cmd[12:].strip()
            self._load_skill(skill_name)
        
        elif cmd.startswith('/skill save '):
            # 格式: /skill save <name> <category> <keywords>
            parts = cmd[12:].strip().split(' ', 2)
            if len(parts) < 3:
                click.echo("❌ 格式: /skill save <name> <category> <keywords>")
                click.echo("   例: /skill save web-scraping web 'scrape, crawl, extract'")
            else:
                name, category, keywords = parts[0], parts[1], parts[2]
                self._save_skill_interactive(name, category, keywords)
        
        elif cmd.startswith('/skill delete '):
            skill_name = cmd[14:].strip()
            self._delete_skill(skill_name)
        
        elif cmd.startswith('/skill show '):
            skill_name = cmd[12:].strip()
            self._show_skill(skill_name)
        
        # ============ 定时任务命令 ============
        elif cmd.startswith('/cron'):
            self._handle_cron_command(cmd)
        
        else:
            click.echo("❌ 未知命令，输入 /help 查看帮助")
        
        return False
    
    # ============ 技能管理方法 ============
    
    def _list_skills(self, brief: bool = True):
        """列出所有技能"""
        if not self.agent or not self.agent.skills:
            click.echo("❌ 技能系统未初始化")
            return
        
        skills = self.agent.skills.list_skills(brief=brief)
        
        if not skills:
            click.echo("📭 技能库为空，使用 /skill save 添加技能")
            return
        
        click.echo("📚 技能库" if brief else "📚 技能库（完整）")
        click.echo("━" * 50)
        
        for skill in skills:
            click.echo(f"• {skill['name']}")
            click.echo(f"  分类: {skill.get('category', '未分类')}")
            click.echo(f"  描述: {skill.get('description', '无')}")
            if not brief:
                click.echo(f"  关键词: {', '.join(skill.get('trigger_keywords', []))}")
                click.echo(f"  Token成本: ~{skill.get('token_cost', 0)}")
                click.echo(f"  使用次数: {skill.get('success_count', 0)}")
            click.echo()
        
        click.echo("━" * 50)
        if brief:
            click.echo("💡 使用 /skills all 查看完整信息")
        click.echo("💡 使用 /skill show <name> 查看技能详情")
        click.echo("💡 使用 /skill load <name> 加载技能到上下文")
    
    def _load_skill(self, name: str):
        """加载技能内容（注入到下一次对话）"""
        if not self.agent or not self.agent.skills:
            click.echo("❌ 技能系统未初始化")
            return
        
        skill = self.agent.skills.load_skill(name)
        if not skill:
            click.echo(f"❌ 找不到技能: {name}")
            return
        
        # 将技能内容存储到session，下次对话时注入
        if not hasattr(self, '_loaded_skills'):
            self._loaded_skills = []
        
        # 避免重复加载
        if name not in [s['name'] for s in self._loaded_skills]:
            self._loaded_skills.append({
                'name': skill.name,
                'content': skill.full_content if hasattr(skill, 'full_content') else ''
            })
            click.echo(f"✅ 技能已加载: {name}")
            click.echo(f"   下次对话时将自动注入技能内容")
            if hasattr(skill, 'full_content') and skill.full_content:
                preview = skill.full_content[:200].replace('\n', ' ')
                click.echo(f"   预览: {preview}...")
        else:
            click.echo(f"⚠️  技能已加载: {name}")
    
    def _save_skill_interactive(self, name: str, category: str, keywords: str):
        """交互式保存技能"""
        if not self.agent or not self.agent.skills:
            click.echo("❌ 技能系统未初始化")
            return
        
        click.echo(f"📝 创建技能: {name}")
        click.echo(f"   分类: {category}")
        click.echo(f"   关键词: {keywords}")
        click.echo()
        click.echo("请输入技能描述（单行或直接回车使用默认）:")
        description = input("> ").strip()
        
        if not description:
            description = f"技能: {name}"
        
        click.echo()
        click.echo("请输入技能完整内容（SKILL.md格式，以空行结束）:")
        click.echo("提示: 可以包含YAML frontmatter（可选）")
        click.echo("---")
        
        content_lines = []
        while True:
            try:
                line = input()
                if line == "" and content_lines and content_lines[-1] == "":
                    break
                content_lines.append(line)
            except EOFError:
                break
        
        full_content = '\n'.join(content_lines).strip()
        
        if not full_content:
            click.echo("❌ 内容不能为空")
            return
        
        # 解析关键词
        keyword_list = [k.strip() for k in keywords.split(',')]
        
        # 注册技能
        self.agent.skills.register_skill(
            name=name,
            category=category,
            description=description,
            trigger_keywords=keyword_list,
            full_content=full_content
        )
        
        click.echo(f"✅ 技能已保存: {name}")
        click.echo(f"   路径: {self.agent.skills.skills_path / name / 'SKILL.md'}")
    
    def _delete_skill(self, name: str):
        """删除技能"""
        if not self.agent or not self.agent.skills:
            click.echo("❌ 技能系统未初始化")
            return
        
        # 确认
        confirm = click.prompt(f"确认删除技能 '{name}'? (yes/no)", default="no")
        if confirm.lower() != "yes":
            click.echo("取消删除")
            return
        
        if self.agent.skills.delete_skill(name):
            click.echo(f"✅ 技能已删除: {name}")
        else:
            click.echo(f"❌ 找不到技能: {name}")
    
    def _show_skill(self, name: str):
        """显示技能详情"""
        if not self.agent or not self.agent.skills:
            click.echo("❌ 技能系统未初始化")
            return
        
        skill = self.agent.skills.load_skill(name)
        if not skill:
            click.echo(f"❌ 找不到技能: {name}")
            return
        
        click.echo(f"📚 技能详情: {skill.name}")
        click.echo("━" * 50)
        click.echo(f"分类: {skill.category}")
        click.echo(f"描述: {skill.description}")
        click.echo(f"关键词: {', '.join(skill.trigger_keywords)}")
        click.echo(f"Token成本: ~{skill.token_cost}")
        click.echo(f"使用次数: {skill.success_count}")
        click.echo(f"最后使用: {skill.last_used[:19] if skill.last_used else '从未使用'}")
        click.echo(f"创建时间: {skill.created_at[:19]}")
        
        if hasattr(skill, 'full_content') and skill.full_content:
            click.echo()
            click.echo("完整内容:")
            click.echo("---")
            # 显示前1000字符
            content_preview = skill.full_content[:1000]
            if len(skill.full_content) > 1000:
                content_preview += "\n... (内容过长，已截断)"
            click.echo(content_preview)
        
        click.echo("━" * 50)
    
    # ============ 定时任务管理命令 ============
    
    def _cron_list(self, include_disabled: bool = False):
        """列出所有定时任务"""
        if not self.cron_manager:
            click.echo("❌ 定时任务系统未初始化")
            return
        
        jobs = self.cron_manager.list_jobs(include_disabled=include_disabled)
        
        if not jobs:
            click.echo("📭 没有定时任务，使用 /cron create 创建")
            return
        
        click.echo("⏰ 定时任务列表")
        click.echo("━" * 50)
        
        for job in jobs:
            status = "✅ 启用" if job.enabled else "⏸️  暂停"
            click.echo(f"• [{job.job_id}] {job.name}")
            click.echo(f"  状态: {status}")
            click.echo(f"  计划: {job.schedule}")
            click.echo(f"  提示词: {job.prompt[:60]}...")
            click.echo(f"  下次运行: {job.next_run[:19] if job.next_run else '未设置'}")
            click.echo(f"  运行次数: {job.run_count}")
            if job.max_runs:
                click.echo(f"  最大次数: {job.max_runs}")
            click.echo()
        
        click.echo("━" * 50)
        click.echo("💡 使用 /cron delete <id> 删除任务")
        click.echo("💡 使用 /cron pause/resume <id> 暂停/恢复任务")
        click.echo("💡 使用 /cron run <id> 立即运行任务")
    
    def _cron_create(self, schedule: str, prompt: str, name: str = None, deliver: str = "local"):
        """创建定时任务"""
        if not self.cron_manager:
            click.echo("❌ 定时任务系统未初始化")
            return
        
        if not schedule or not prompt:
            click.echo("❌ 格式: /cron create <schedule> <prompt>")
            click.echo("   例: /cron create '30m' '帮我总结今天的新闻'")
            click.echo("   支持格式: '30m', 'every 2h', '0 9 * * *'")
            return
        
        try:
            job = self.cron_manager.create_job(
                schedule=schedule,
                prompt=prompt,
                name=name,
                deliver=deliver
            )
            
            click.echo(f"✅ 定时任务已创建: {job.name}")
            click.echo(f"   ID: {job.job_id}")
            click.echo(f"   下次运行: {job.next_run[:19] if job.next_run else '未设置'}")
            click.echo(f"   投递方式: {deliver}")
        except Exception as e:
            click.echo(f"❌ 创建任务失败: {e}")
    
    def _cron_delete(self, job_id: str):
        """删除定时任务"""
        if not self.cron_manager:
            click.echo("❌ 定时任务系统未初始化")
            return
        
        # 确认
        job = self.cron_manager.get_job(job_id)
        if not job:
            click.echo(f"❌ 找不到任务: {job_id}")
            return
        
        confirm = click.prompt(f"确认删除任务 '{job.name}'? (yes/no)", default="no")
        if confirm.lower() != "yes":
            click.echo("取消删除")
            return
        
        if self.cron_manager.delete_job(job_id):
            click.echo(f"✅ 任务已删除: {job.name}")
        else:
            click.echo(f"❌ 删除失败")
    
    def _cron_pause(self, job_id: str):
        """暂停定时任务"""
        if not self.cron_manager:
            click.echo("❌ 定时任务系统未初始化")
            return
        
        if self.cron_manager.pause_job(job_id):
            click.echo(f"✅ 任务已暂停: {job_id}")
        else:
            click.echo(f"❌ 操作失败，找不到任务: {job_id}")
    
    def _cron_resume(self, job_id: str):
        """恢复定时任务"""
        if not self.cron_manager:
            click.echo("❌ 定时任务系统未初始化")
            return
        
        if self.cron_manager.resume_job(job_id):
            click.echo(f"✅ 任务已恢复: {job_id}")
        else:
            click.echo(f"❌ 操作失败，找不到任务: {job_id}")
    
    def _cron_run_now(self, job_id: str):
        """立即运行任务"""
        if not self.scheduler:
            click.echo("❌ 调度器未初始化")
            return
        
        click.echo(f"🚀 立即运行任务: {job_id}")
        result = self.scheduler.run_job_now(job_id)
        
        if result:
            click.echo("✅ 任务执行完成")
            click.echo(f"   结果长度: {len(result)} 字符")
        else:
            click.echo("❌ 任务执行失败")
    
    def _cron_status(self):
        """查看调度器状态"""
        if not self.scheduler:
            click.echo("❌ 调度器未初始化")
            return
        
        status = self.scheduler.status()
        
        click.echo("⏰ 定时任务调度器状态")
        click.echo("━" * 50)
        click.echo(f"运行状态: {'✅ 运行中' if status['running'] else '❌ 已停止'}")
        click.echo(f"检查间隔: {status['check_interval']} 秒")
        click.echo(f"总任务数: {status['total_jobs']}")
        click.echo(f"启用任务: {status['enabled_jobs']}")
        click.echo(f"到期任务: {status['due_jobs']}")
        click.echo("━" * 50)
    
    def _handle_cron_command(self, cmd: str):
        """处理所有/cron开头的命令"""
        parts = cmd.split(' ', 2)
        # 解析子命令：/cron, /cron list, /cron create, etc.
        if len(parts) >= 2:
            subcmd = f"{parts[0]}/{parts[1]}"  # 例如 /cron/create
            action = parts[1].lower()
        else:
            subcmd = parts[0].lower()
            action = None
        
        # 处理 /cron (无参数) 或 /cron list
        if subcmd == '/cron' or subcmd == '/cron/list':
            include_all = len(parts) > 2 and 'all' in parts[2]
            self._cron_list(include_disabled=include_all)
        elif subcmd == '/cron/create':
            if len(parts) < 3:
                click.echo("❌ 格式: /cron create <schedule> <prompt>")
                click.echo("   例: /cron create '30m' '帮我总结今天的新闻'")
                return
            rest = parts[2]
            # 解析schedule和prompt
            import re
            # 匹配两个单引号字符串：'schedule' 'prompt'
            pattern = r"'([^']+)'\s+'([^']+)'"  # 两个单引号字符串，中间有空白
            match = re.match(pattern, rest)
            
            if not match:
                # 尝试简单解析：第一个词是schedule，剩余是prompt
                words = rest.split(' ', 1)
                if len(words) < 2:
                    click.echo("❌ 格式错误，schedule和prompt都需要用引号括起来")
                    click.echo("   例: /cron create '30m' '提示词'")
                    return
                schedule = words[0].strip().strip("'\"")
                prompt = words[1].strip().strip("'\"")
            else:
                schedule = match.group(1)
                prompt = match.group(2)
            
            if not prompt:
                click.echo("❌ 缺少提示词")
                return
            self._cron_create(schedule, prompt)
        elif subcmd == '/cron/delete':
            if len(parts) < 3:
                click.echo("❌ 格式: /cron delete <id>")
                return
            job_id = parts[2].strip()
            self._cron_delete(job_id)
        elif subcmd == '/cron/pause':
            if len(parts) < 3:
                click.echo("❌ 格式: /cron pause <id>")
                return
            job_id = parts[2].strip()
            self._cron_pause(job_id)
        elif subcmd == '/cron/resume':
            if len(parts) < 3:
                click.echo("❌ 格式: /cron resume <id>")
                return
            job_id = parts[2].strip()
            self._cron_resume(job_id)
        elif subcmd == '/cron/run':
            if len(parts) < 3:
                click.echo("❌ 格式: /cron run <id>")
                return
            job_id = parts[2].strip()
            self._cron_run_now(job_id)
        elif subcmd == '/cron/status':
            self._cron_status()
        else:
            click.echo("❌ 未知cron命令")
            click.echo("   可用: list, create, delete, pause, resume, run, status")
    
    def _show_help(self):
        """显示帮助"""
        click.echo("""
📖 Dogeey 命令指南
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎮 基础命令:
  /help, /h        - 显示此帮助
  /quit, /exit, /q - 退出程序
  /status          - 查看系统状态

⚙️  配置命令:
  /model <名称>    - 切换使用的模型
  /clear           - 清除当前会话历史
  /verbose         - 切换详细模式

🚀 执行命令:
  /run <指令>      - 执行单次指令（不进入对话）

📚 技能管理:
  /skills          - 列出技能（简要）
  /skills all      - 列出技能（完整信息）
  /skill load <名称>    - 加载技能到上下文
  /skill show <名称>    - 查看技能详情
  /skill save <n> <c> <k> - 保存新技能
                    n=名称, c=分类, k=关键词(逗号分隔)
  /skill delete <名称>  - 删除技能

💬 会话管理:
  /sessions, /sess - 列出所有会话
  /new <标题>      - 创建新会话（标题可选）
  /switch <id>     - 切换到指定会话
  /delete <id>     - 删除指定会话
  /rename <id> <标题> - 重命名会话

⏰ 定时任务:
  /cron list [all]  - 列出任务（all=包含禁用）
  /cron create 'schedule' 'prompt' - 创建定时任务
                    schedule支持: '30m', 'every 2h', '0 9 * * *'
  /cron delete <id> - 删除任务
  /cron pause <id>  - 暂停任务
  /cron resume <id> - 恢复任务
  /cron run <id>    - 立即运行任务
  /cron status       - 查看调度器状态

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💬 对话模式:
  直接输入文字开始对话，Dogeey 会:
  • 自动拆解任务步骤
  • 智能调用工具执行
  • 记住对话上下文
  • 学习你的习惯偏好

💡 提示: 使用方向键 ↑↓ 查看历史命令
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")
    
    def _execute_instruction(self, instruction):
        """执行指令（使用任务监督系统）"""
        if not self.agent:
            show_error("智能体未初始化")
            return
        
        try:
            # 显示处理中（简单提示）
            click.echo("🤔 思考中...")
            click.echo()
            
            # 使用监督系统执行，获取详细结果
            # 注意：这里可能会等很久（API限速、网络延迟等）
            try:
                result = self.agent.run_with_result(instruction, verbose=self.verbose)
            except Exception as inner_e:
                # 捕获run_with_result内部的异常
                show_error(f"执行过程中出错: {inner_e}")
                if self.verbose:
                    import traceback
                    traceback.print_exc()
                return
            
            # 显示结果
            show_result_header()
            
            if result.is_success():
                # 成功
                console.print(result.answer)
                
                # 详细模式：显示统计信息
                if self.verbose:
                    console.print()
                    console.print("━" * 50, style="dim")
                    console.print("[bold]📊 任务统计[/bold]")
                    console.print("━" * 50, style="dim")
                    console.print(f"✅ 状态: [bold green]成功[/bold green]")
                    console.print(f"🔄 步骤: {result.steps} 轮")
                    console.print(f"🔧 工具调用: {len(result.tool_calls)} 次")
                    
                    if result.tool_calls:
                        console.print()
                        console.print("工具调用记录:")
                        for i, call in enumerate(result.tool_calls, 1):
                            tool_name = call.get('tool', 'unknown')
                            console.print(f"  {i}. {tool_name}")
            else:
                # 失败 - 给出明确原因
                show_error("任务执行失败")
                console.print()
                console.print(f"原因: {result.error_msg}")
                
                # 详细模式：显示更多信息
                if self.verbose:
                    console.print()
                    console.print("━" * 50, style="dim")
                    console.print("[bold]📊 失败详情[/bold]")
                    console.print("━" * 50, style="dim")
                    console.print(f"❌ 状态: [bold red]失败[/bold red] (类型: {result.error_type.value})")
                    console.print(f"🔄 步骤: {result.steps} 轮")
                    console.print(f"🔧 工具调用: {len(result.tool_calls)} 次")
                    
                    if result.tool_calls:
                        console.print()
                        console.print("工具调用记录:")
                        for i, call in enumerate(result.tool_calls, 1):
                            tool_name = call.get('tool', 'unknown')
                            console.print(f"  {i}. {tool_name}")
            
            click.echo()
            click.echo("━" * 50)
            click.echo()
            
        except Exception as e:
            click.echo()
            click.echo("━" * 50)
            show_error(f"执行出错: {e}")
            click.echo("━" * 50)
            click.echo()
            
            if self.verbose:
                import traceback
                console.print("[bold]详细错误信息:[/bold]")
                traceback.print_exc()
                click.echo()


# ============ CLI 命令定义 ============
@click.group(invoke_without_command=True)
@click.version_option(version="1.0.0", prog_name="dogeey")
@click.option('--verbose', '-v', is_flag=True, help="详细输出")
@click.pass_context
def cli(ctx, verbose):
    """Dogeey - 轻量级AI智能体"""
    
    # 如果没有子命令，进入交互模式
    if ctx.invoked_subcommand is None:
        session = DogeeySession(verbose=verbose)
        session.run_interactive()


@cli.command()
def init():
    """初始化配置（首次运行引导）"""
    click.echo(get_logo())
    click.echo()
    click.echo("🎉 欢迎使用 Dogeey！")
    click.echo()
    
    # 加载当前配置
    cfg = config.load()
    
    # 选择提供商
    click.echo("📡 选择大模型提供商：")
    click.echo()
    providers = [
        "1. OpenAI兼容API（OpenAI/DeepSeek/硅基流动等）",
        "2. Anthropic Claude",
        "3. Google Gemini",
        "4. 自定义（高级）"
    ]
    for p in providers:
        click.echo(f"   {p}")
    click.echo()
    
    choice = click.prompt("请输入选项编号", type=int, default=1)
    
    # 根据选择设置提供商
    provider_name = "openai"
    base_url = "https://api.openai.com/v1"
    
    if choice == 1:
        provider_name = "openai"
        base_url = click.prompt("API Base URL", default="https://api.openai.com/v1")
    elif choice == 4:
        provider_name = click.prompt("提供商名称", default="custom")
        base_url = click.prompt("API Base URL")
    
    # API Key
    click.echo()
    click.echo("🔑 API Key 配置")
    api_key = click.prompt("输入API Key（或设置环境变量DOGEEY_API_KEY）",
                      default="", show_default=False)
    if not api_key:
        api_key = "从环境变量读取"
    
    # 模型选择
    click.echo()
    click.echo("🤖 模型配置")
    model = click.prompt("选择默认模型", default="gpt-4o")
    
    # WebUI端口
    click.echo()
    click.echo("🌐 WebUI 配置")
    port = click.prompt("WebUI端口（默认8080）", default=8080, type=int)
    
    # 保存配置
    click.echo()
    if api_key != "从环境变量读取":
        config.add_provider(provider_name, api_key, base_url, [model], model)
    else:
        config.add_provider(provider_name, "${DOGEEY_API_KEY}", base_url, [model], model)
    
    config.set("webui.port", port)
    config.save()
    
    click.echo("✅ 配置完成！")
    click.echo(f"   配置文件: {config.config_file}")
    click.echo()
    click.echo("🚀 现在可以开始使用了：")
    click.echo("   dogeey        # 进入交互模式")
    click.echo("   dogeey run '指令'  # 单次执行")
    click.echo()


@cli.command()
@click.argument("instruction")
@click.option("--model", help="临时使用其他模型")
@click.option("--verbose", "-v", is_flag=True, help="详细输出")
@click.option("--no-memory", is_flag=True, help="不使用记忆系统")
@click.option("--no-profile", is_flag=True, help="不使用用户画像")
def run(instruction, model, verbose, no_memory, no_profile):
    """运行智能体执行指令（单次）"""
    from .llm import create_llm_client_from_config
    from .core import AgentCore
    from .tools import ToolRegistry, register_builtin_tools
    from .sessions import SessionManager
    
    click.echo(f"📝 指令: {instruction}\n")
    
    try:
        cfg = config.load()
        
        llm_client = create_llm_client_from_config(cfg)
        
        if model:
            llm_client.model = model
        
        tool_registry = ToolRegistry()
        register_builtin_tools(tool_registry)
        
        session_manager = SessionManager()
        
        memory_system = None
        if not no_memory:
            try:
                from .memory import MemorySystem
                db_path = cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')
                memory_system = MemorySystem(db_path)
            except Exception as e:
                if verbose:
                    click.echo(f"⚠️  记忆系统初始化失败: {e}")
        
        # 创建用户画像（可选）
        user_profile = None
        if not no_profile:
            try:
                from .profile import UserProfile
                profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
                user_profile = UserProfile(profile_path)
            except Exception as e:
                if verbose:
                    click.echo(f"⚠️  用户画像初始化失败: {e}")
        
        # 创建技能管理器（可选）
        skill_manager = None
        try:
            from .skills import SkillManager
            skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
            skill_manager = SkillManager(skills_path)
        except Exception as e:
            if verbose:
                click.echo(f"⚠️  技能系统初始化失败: {e}")
        
        agent = AgentCore(
            llm_client=llm_client,
            tool_registry=tool_registry,
            memory_system=memory_system,
            user_profile=user_profile,
            skill_manager=skill_manager,
            session_manager=session_manager
        )
        
        # 显示系统状态
        if verbose:
            click.echo("━" * 50)
            click.echo("📊 系统状态")
            click.echo("━" * 50)
            click.echo(f"🤖 模型: {llm_client.model}")
            click.echo(f"🧠 记忆系统: {'✅' if memory_system else '❌'}")
            click.echo(f"👤 用户画像: {'✅' if user_profile else '❌'}")
            click.echo(f"📚 技能库: {'✅' if skill_manager else '❌'}")
            click.echo(f"🔧 可用工具: {[t.name for t in tool_registry.list_tools()]}")
            click.echo("━" * 50)
            click.echo()
        
        # 执行
        click.echo("🤔 执行中...")
        click.echo()
        
        result = agent.run(instruction, verbose=verbose)
        
        # 显示结果
        click.echo("━" * 50)
        click.echo("🤖 Dogeey 回复:")
        click.echo()
        click.echo(result)
        click.echo()
        click.echo("━" * 50)
        click.echo()
        
    except Exception as e:
        click.echo()
        click.echo("━" * 50)
        click.echo(f"❌ 错误: {str(e)}")
        click.echo("━" * 50)
        click.echo()
        
        if verbose:
            import traceback
            click.echo("详细错误信息:")
            traceback.print_exc()
            click.echo()


@cli.command()
@click.option("--host", default="127.0.0.1", help="监听地址")
@click.option("--port", default=8080, type=int, help="监听端口")
@click.option("--daemon", is_flag=True, help="后台运行")
def webui(host, port, daemon):
    """启动Web管理界面"""
    click.echo(get_small_logo())
    click.echo(f"🌐 正在启动WebUI: http://{host}:{port}\n")
    
    try:
        import uvicorn
        from .web.backend import app
        
        if daemon:
            click.echo("🚧 后台运行模式开发中，暂不支持")
            return
        
        click.echo("按 Ctrl+C 停止服务\n")
        uvicorn.run(app, host=host, port=port)
    except ImportError:
        click.echo("❌ 缺少Web依赖，请安装: pip install dogeey[web]")
    except Exception as e:
        click.echo(f"❌ 启动失败: {str(e)}")


@cli.group()
def config_cmd():
    """配置管理"""
    pass


@config_cmd.command(name="show")
def config_show():
    """查看当前配置"""
    cfg = config.load()
    click.echo(json.dumps(cfg, indent=2, ensure_ascii=False))


@config_cmd.command(name="path")
def config_path():
    """查看配置文件路径"""
    click.echo(str(config.config_file))


@config_cmd.command(name="add-provider")
@click.argument("name")
@click.option("--api-key", required=True, help="API Key")
@click.option("--base-url", default="https://api.openai.com/v1", help="API Base URL")
@click.option("--models", help="可用模型列表（逗号分隔）")
@click.option("--default-model", help="默认模型")
def config_add_provider(name, api_key, base_url, models, default_model):
    """添加模型提供商"""
    model_list = models.split(',') if models else []
    if not default_model and model_list:
        default_model = model_list[0]
    
    config.load()
    config.add_provider(name, api_key, base_url, model_list, default_model)
    config.save()
    
    click.echo(f"✅ 已添加提供商: {name}")
    if default_model:
        click.echo(f"   默认模型: {default_model}")


@config_cmd.command(name="list-providers")
def config_list_providers():
    """列出所有模型提供商"""
    cfg = config.load()
    providers = cfg.get('llm', {}).get('providers', [])
    
    if not providers:
        click.echo("未配置任何提供商，请先运行: dogeey init")
        return
    
    click.echo("配置的模型提供商:")
    for p in providers:
        click.echo(f"\n📡 {p['name']}")
        click.echo(f"   Base URL: {p.get('base_url', 'N/A')}")
        click.echo(f"   模型: {', '.join(p.get('models', []))}")
        click.echo(f"   默认: {p.get('default_model', 'N/A')}")
    
    current = cfg.get('llm', {}).get('current_provider')
    click.echo(f"\n当前使用: {current}")


@config_cmd.command(name="set-default")
@click.argument("provider_name")
def config_set_default(provider_name):
    """设置默认提供商"""
    config.load()
    providers = config.get('llm.providers', [])
    
    if not any(p['name'] == provider_name for p in providers):
        click.echo(f"❌ 找不到提供商: {provider_name}")
        return
    
    config.set('llm.current_provider', provider_name)
    config.save()
    click.echo(f"✅ 已切换默认提供商: {provider_name}")


@config_cmd.command(name="remove-provider")
@click.argument("provider_name")
def config_remove_provider(provider_name):
    """删除模型提供商"""
    config.load()
    providers = config.get('llm.providers', [])
    
    new_providers = [p for p in providers if p['name'] != provider_name]
    if len(new_providers) == len(providers):
        click.echo(f"❌ 找不到提供商: {provider_name}")
        return
    
    config.set('llm.providers', new_providers)
    
    # 如果删除的是当前提供商，清空选择
    if config.get('llm.current_provider') == provider_name:
        config.set('llm.current_provider', None)
    
    config.save()
    click.echo(f"✅ 已删除提供商: {provider_name}")


@cli.command()
def uninstall():
    """卸载Dogeey（清除所有数据）"""
    click.echo("⚠️  这将删除以下目录和文件：")
    click.echo(f"  - {config.config_dir}")
    
    confirm = click.prompt("确认删除？(yes/no)", default="no")
    if confirm.lower() == "yes":
        import shutil
        if config.config_dir.exists():
            shutil.rmtree(config.config_dir)
        click.echo("✅ Dogeey 已完全卸载")
    else:
        click.echo("取消卸载")


# ============ Channel 命令组 ============
@cli.group()
def channel():
    """频道管理（飞书、Discord等）"""
    pass


@channel.command(name="list")
def channel_list():
    """列出所有频道及其状态"""
    cfg = config.load()
    channels = cfg.get("channels", {})
    
    if not channels:
        click.echo("未配置任何频道")
        return
    
    click.echo("配置的频道:")
    for name, cfg in channels.items():
        status = "✅ 已启用" if cfg.get("enabled") else "❌ 未启用"
        click.echo(f"\n📡 {name}")
        click.echo(f"   状态: {status}")
        click.echo(f"   类型: {cfg.get('type', 'plugin')}")


@channel.command(name="enable")
@click.argument("channel_name")
def channel_enable(channel_name):
    """启用指定频道"""
    cfg = config.load()
    if "channels" not in cfg:
        cfg["channels"] = {}
    
    if channel_name not in cfg["channels"]:
        cfg["channels"][channel_name] = {}
    
    cfg["channels"][channel_name]["enabled"] = True
    config.save()
    click.echo(f"✅ 频道 {channel_name} 已启用")


@channel.command(name="disable")
@click.argument("channel_name")
def channel_disable(channel_name):
    """禁用指定频道"""
    cfg = config.load()
    if channel_name in cfg.get("channels", {}):
        cfg["channels"][channel_name]["enabled"] = False
        config.save()
        click.echo(f"✅ 频道 {channel_name} 已禁用")
    else:
        click.echo(f"❌ 未找到频道: {channel_name}")


@channel.command(name="status")
@click.argument("channel_name")
def channel_status(channel_name):
    """查看指定频道状态"""
    cfg = config.load()
    channels = cfg.get("channels", {})
    
    if channel_name not in channels:
        click.echo(f"❌ 未找到频道: {channel_name}")
        return
    
    ch_cfg = channels[channel_name]
    click.echo(f"频道: {channel_name}")
    click.echo(f"  启用: {'是' if ch_cfg.get('enabled') else '否'}")
    click.echo(f"  类型: {ch_cfg.get('type', 'plugin')}")
    
    # 尝试获取运行时状态（如果可能）
    try:
        from dogeey.event_bus import EventBus
        from dogeey.channels.manager import ChannelManager
        import asyncio
        
        async def check():
            bus = EventBus()
            mgr = ChannelManager(cfg, bus)
            await mgr.load_from_config()
            ch = mgr.get_channel(channel_name)
            if ch:
                health = ch.health_check()
                click.echo(f"  运行时配置: {health.get('configured')}")
                click.echo(f"  运行中: {health.get('running')}")
            else:
                click.echo("  未加载（可能未启用或配置错误）")
        
        asyncio.run(check())
    except Exception as e:
        click.echo(f"  运行时状态检查失败: {e}")


@channel.command(name="start")
@click.argument("channel_name")
def channel_start(channel_name):
    """启动指定频道（需要dogeey运行中）"""
    click.echo("⚠️  频道启动已集成到dogeey主程序中")
    click.echo("   请通过以下方式之一启动频道：")
    click.echo("   1. 启动WebUI: dogeey webui")
    click.echo("   2. 交互模式: dogeey")
    click.echo(f"\n确保 {channel_name} 在配置中已启用")


@channel.command(name="stop")
@click.argument("channel_name")
def channel_stop(channel_name):
    """停止指定频道"""
    click.echo("⚠️  频道停止功能开发中")
    click.echo("   请重启dogeey以停止频道")


@channel.command(name="reload")
def channel_reload():
    """重新加载频道配置"""
    click.echo("⚠️  配置重载功能开发中")
    click.echo("   请重启dogeey以应用新配置")


if __name__ == "__main__":
    cli()
