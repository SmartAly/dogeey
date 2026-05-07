#!/usr/bin/env python3
"""
Dogeey 使用示例
展示如何在代码中直接使用Dogeey
"""
from dogeey.config import config
from dogeey.llm import create_llm_client_from_config
from dogeey.core import AgentCore
from dogeey.tools import ToolRegistry, register_builtin_tools
from dogeey.memory import MemorySystem
from dogeey.profile import UserProfile
from dogeey.skills import SkillManager

def main():
    print("🤖 Dogeey 使用示例\n")
    print("=" * 50)
    
    # 1. 加载配置
    print("\n[1] 加载配置...")
    cfg = config.load()
    print(f"✅ 配置加载成功")
    print(f"   当前提供商: {cfg.get('llm', {}).get('current_provider')}")
    
    # 2. 创建LLM客户端
    print("\n[2] 创建LLM客户端...")
    try:
        llm_client = create_llm_client_from_config(cfg)
        print(f"✅ LLM客户端创建成功")
        print(f"   模型: {llm_client.model}")
    except Exception as e:
        print(f"❌ LLM客户端创建失败: {e}")
        print("   请先配置API Key: dogeey init")
        return
    
    # 3. 注册工具
    print("\n[3] 注册工具...")
    tool_registry = ToolRegistry()
    register_builtin_tools(tool_registry)
    tools = tool_registry.list_tools()
    print(f"✅ 工具注册成功，共 {len(tools)} 个")
    for tool in tools:
        print(f"   - {tool.name}")
    
    # 4. 初始化可选组件
    print("\n[4] 初始化可选组件...")
    
    # 记忆系统
    try:
        memory = MemorySystem(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db'))
        print("✅ 记忆系统初始化成功")
    except Exception as e:
        print(f"⚠️  记忆系统初始化失败: {e}")
        memory = None
    
    # 用户画像
    try:
        from pathlib import Path
        profile_path = str(Path(cfg.get('memory', {}).get('db_path', '~/.dogeey/data/memories.db')).parent / "user_profile.json")
        profile = UserProfile(profile_path)
        print("✅ 用户画像初始化成功")
    except Exception as e:
        print(f"⚠️  用户画像初始化失败: {e}")
        profile = None
    
    # 技能管理器
    try:
        skills_path = cfg.get('skills', {}).get('path', '~/.dogeey/skills')
        skill_mgr = SkillManager(skills_path)
        print("✅ 技能管理器初始化成功")
    except Exception as e:
        print(f"⚠️  技能管理器初始化失败: {e}")
        skill_mgr = None
    
    # 5. 创建智能体
    print("\n[5] 创建智能体...")
    agent = AgentCore(
        llm_client=llm_client,
        tool_registry=tool_registry,
        memory_system=memory,
        user_profile=profile,
        skill_manager=skill_mgr
    )
    print("✅ 智能体创建成功")
    
    # 6. 示例对话
    print("\n" + "=" * 50)
    print("[6] 示例对话")
    print("=" * 50)
    
    instruction = "你好，请简单介绍一下你自己"
    print(f"\n用户: {instruction}")
    
    try:
        response = agent.run(instruction, verbose=False)
        print(f"\n智能体: {response[:200]}...")
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return
    
    print("\n" + "=" * 50)
    print("✅ 示例运行完成！")
    print("=" * 50)
    print("\n现在你可以使用以下方式运行智能体：")
    print("  CLI: dogeey run '你的指令'")
    print("  Web: dogeey webui")
    print("  代码: 参考本示例")


if __name__ == "__main__":
    main()
