#!/usr/bin/env python3
"""
Dogeey 最终验证脚本
验证所有组件是否正常工作（无需API Key）
"""
import sys
import os
import tempfile

def print_separator():
    print("=" * 60)

def print_success(msg):
    print(f"✅ {msg}")

def print_error(msg):
    print(f"❌ {msg}")

def print_info(msg):
    print(f"ℹ️  {msg}")

def main():
    print_separator()
    print("   Dogeey v1.0.0 - 最终验证")
    print_separator()
    print()
    
    all_passed = True
    
    # 1. 检查项目结构
    print("[1] 检查项目结构...")
    required_files = [
        "dogeey/__init__.py",
        "dogeey/cli.py",
        "dogeey/config.py",
        "dogeey/llm.py",
        "dogeey/core.py",
        "dogeey/tools.py",
        "dogeey/memory.py",
        "dogeey/profile.py",
        "dogeey/skills.py",
        "dogeey/web/__init__.py",
        "dogeey/web/backend.py",
        "dogeey/web/static/index.html",
        "setup.py",
        "README.md",
        "DELIVERY.md",
        "test_basic.py",
        "example_usage.py",
        "start.sh",
        "verify.py"
    ]
    
    missing_files = [f for f in required_files if not os.path.exists(f)]
    
    if missing_files:
        print_error(f"缺少文件: {missing_files}")
        all_passed = False
    else:
        print_success(f"所有必需文件存在 ({len(required_files)} 个)")
    
    # 2. 验证Python语法
    print("\n[2] 验证Python语法...")
    python_files = [
        "dogeey/__init__.py",
        "dogeey/cli.py",
        "dogeey/config.py",
        "dogeey/llm.py",
        "dogeey/core.py",
        "dogeey/tools.py",
        "dogeey/memory.py",
        "dogeey/profile.py",
        "dogeey/skills.py",
        "dogeey/web/backend.py",
        "test_basic.py",
        "example_usage.py",
        "verify.py"
    ]
    
    syntax_errors = []
    for f in python_files:
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as file:
                    compile(file.read(), f, 'exec')
            except SyntaxError as e:
                syntax_errors.append(f"{f}: {e}")
    
    if syntax_errors:
        print_error("语法错误:")
        for err in syntax_errors:
            print(f"   {err}")
        all_passed = False
    else:
        print_success(f"所有Python文件语法正确 ({len(python_files)} 个)")
    
    # 3. 测试模块导入
    print("\n[3] 测试模块导入...")
    try:
        import dogeey
        from dogeey import config, tools, memory, profile, skills
        print_success("核心模块导入成功")
    except ImportError as e:
        print_error(f"导入失败: {e}")
        all_passed = False
    
    # 4. 测试工具系统
    print("\n[4] 测试工具系统...")
    try:
        from dogeey.tools import ToolRegistry, register_builtin_tools
        registry = ToolRegistry()
        register_builtin_tools(registry)
        tools_list = registry.list_tools()
        if len(tools_list) == 4:
            print_success(f"工具系统正常，已注册 {len(tools_list)} 个工具")
        else:
            print_error(f"工具数量不对: {len(tools_list)}")
            all_passed = False
    except Exception as e:
        print_error(f"工具系统失败: {e}")
        all_passed = False
    
    # 5. 测试记忆系统
    print("\n[5] 测试记忆系统...")
    try:
        from dogeey.memory import MemorySystem
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        
        mem = MemorySystem(db_path)
        mid = mem.add_long_term("测试记忆", "test")
        if mid > 0:
            print_success("记忆系统正常，可添加记忆")
        else:
            print_error("记忆添加失败")
            all_passed = False
        
        os.unlink(db_path)
    except Exception as e:
        print_error(f"记忆系统失败: {e}")
        all_passed = False
    
    # 6. 测试用户画像
    print("\n[6] 测试用户画像...")
    try:
        from dogeey.profile import UserProfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            profile_path = f.name
        
        profile = UserProfile(profile_path)
        profile.learn_from_interaction("测试", "回复")
        print_success("用户画像正常，可学习")
        
        os.unlink(profile_path)
    except Exception as e:
        print_error(f"用户画像失败: {e}")
        all_passed = False
    
    # 7. 测试CLI命令（无API Key）
    print("\n[7] 测试CLI命令...")
    try:
        from click.testing import CliRunner
        from dogeey.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        if result.exit_code == 0:
            print_success("CLI命令正常")
        else:
            print_error(f"CLI失败: {result.output}")
            all_passed = False
    except Exception as e:
        print_error(f"CLI测试失败: {e}")
        all_passed = False
    
    # 总结
    print()
    print_separator()
    if all_passed:
        print("   ✅ 所有验证通过！Dogeey v1.0.0 可用版本已就绪")
        print_separator()
        print()
        print("📦 交付内容:")
        print("   • 核心模块: config, llm, core, tools, memory, profile, skills")
        print("   • CLI命令: init, run, webui, config, uninstall")
        print("   • WebUI: FastAPI后端 + 管理界面")
        print("   • 文档: README.md, DELIVERY.md")
        print("   • 示例: example_usage.py")
        print("   • 测试: test_basic.py, verify.py")
        print()
        print("🚀 快速开始:")
        print("   1. 配置: dogeey init")
        print("   2. CLI: dogeey run '你的指令'")
        print("   3. Web: dogeey webui")
        print("   4. 测试: python3 verify.py")
        print()
        print("🎉 Dogeey v1.0.0 交付完成！")
        return 0
    else:
        print("   ❌ 验证未完全通过，请检查上述错误")
        print_separator()
        return 1


if __name__ == "__main__":
    sys.exit(main())
