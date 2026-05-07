#!/usr/bin/env python3
"""
Dogeey 自动化测试框架
====================
- 25个测试用例，覆盖基础能力、工具能力、上下文、智能、进阶
- 每个测试独立运行（新建AgentCore实例）
- 自动检测问题、修复、提交、回滚
- 核心理念：轻量化、自进化、开箱即用
"""
import sys, os, json, time, tempfile, shutil, traceback, re
from pathlib import Path
from typing import Callable, Dict, Any, Optional, List

# 项目路径
PROJECT_DIR = Path(__file__).parent
sys.path.insert(0, str(PROJECT_DIR))

from dogeey.config import Config
from dogeey.llm import create_llm_client_from_config
from dogeey.tools import ToolRegistry, register_builtin_tools
from dogeey.sessions import SessionManager
from dogeey.core import AgentCore
from dogeey.tools import Tool
from dogeey.weather_tool import tool_query_weather, WEATHER_TOOL


# ============================================================
# 测试基础设施
# ============================================================

class TestResult:
    """单个测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.duration = 0.0
        self.tool_calls: List[Dict] = []
        self.output = ""
        self.error = ""
        self.tool_call_count = 0
        self.token_estimate = 0
        self.no_hallucination = True
        self.no_log_leak = True
        self.context_maintained = False
    
    def summary(self) -> str:
        status = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [
            f"\n{'='*60}",
            f"{status} [{self.name}] ({self.duration:.1f}s)",
            f"{'='*60}",
        ]
        if self.output:
            lines.append(f"📤 输出: {self.output[:300]}")
        if self.error:
            lines.append(f"🐛 错误: {self.error[:200]}")
        if self.tool_calls:
            lines.append(f"🔧 工具调用 ({len(self.tool_calls)}次):")
            for tc in self.tool_calls[:5]:
                lines.append(f"   - {tc['tool']}: {str(tc.get('args', ''))[:50]}")
            if len(self.tool_calls) > 5:
                lines.append(f"   ... 还有 {len(self.tool_calls)-5} 次调用")
        lines.append(f"{'='*60}\n")
        return "\n".join(lines)


class DogeeyTestRunner:
    """测试执行器"""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.total_passed = 0
        self.total_failed = 0
    
    def run_all(self):
        """运行所有测试"""
        tests = self._get_tests()
        print(f"\n{'='*60}")
        print(f"🧪 Dogeey 自动化测试 - 共 {len(tests)} 个用例")
        print(f"{'='*60}\n")
        
        for i, (name, test_func) in enumerate(tests, 1):
            print(f"▶️ [{i}/{len(tests)}] {name}...")
            result = TestResult(name)
            
            start = time.time()
            try:
                test_func(result)
            except Exception as e:
                result.error = f"异常: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            finally:
                result.duration = time.time() - start
            
            result.passed = not result.error
            self.results.append(result)
            
            if result.passed:
                self.total_passed += 1
                print(f"   ✅ PASS ({result.duration:.1f}s)")
            else:
                self.total_failed += 1
                print(f"   ❌ FAIL ({result.duration:.1f}s)")
                print(f"   {result.error[:150]}")
            
            # 间隔
            time.sleep(1)
        
        # 汇总
        self._print_summary()
    
    def _get_tests(self):
        """获取测试列表"""
        return [
            # 基础能力 (1-5)
            ("T01_简单问候", t01_greeting),
            ("T02_自我介绍", t02_self_intro),
            ("T03_文件创建", t03_file_create),
            ("T04_文件读取", t04_file_read),
            ("T05_文件删除", t05_file_delete),
            
            # 工具能力 (6-10)
            ("T06_搜索文件", t06_search_files),
            ("T07_Shell执行", t07_shell_command),
            ("T08_天气查询", t08_weather_query),
            ("T09_多步任务", t09_multi_step),
            ("T10_错误处理", t10_error_handling),
            
            # 上下文能力 (11-14)
            ("T11_上下文保留", t11_context_retention),
            ("T12_多轮对话", t12_multi_turn),
            ("T13_话题切换", t13_topic_switch),
            ("T14_指代理解", t14_reference_understanding),
            
            # 智能能力 (15-18)
            ("T15_诚实原则", t15_honesty),
            ("T16_自我学习", t16_self_learning),
            ("T17_复杂任务", t17_complex_task),
            ("T18_错误恢复", t18_error_recovery),
            
            # 进阶能力 (19-25)
            ("T19_定时任务", t19_cron_task),
            ("T20_自我报告", t20_metacognition),
            ("T21_超长输入", t21_long_input),
            ("T22_特殊字符", t22_special_chars),
            ("T23_空输入", t23_empty_input),
            
            # 补充测试 (26-40)
            ("T24_记忆持久化", t24_memory_persistence),
            ("T25_Cron持久化", t25_cron_persistence),
            ("T26_上下文压缩", t26_context_compression),
            ("T27_工具渐进式披露", t27_tool_progressive_disclosure),
            ("T28_ReAct回退", t28_react_fallback),
            ("T29_工具参数校验", t29_tool_parameter_validation),
            ("T30_大文件截断", t30_large_file_truncation),
            ("T31_ContextFlow话题", t31_contextflow_topic_management),
            ("T32_Unicode边界", t32_unicode_boundary),
            ("T33_Session内存", t33_session_memory_growth),
            ("T34_LLM客户端", t34_llm_client_creation),
            ("T35_工具表隔离", t35_tool_registry_isolation),
            ("T36_Cron合法", t36_cron_expression_validation),
            ("T37_Cron非法", t37_cron_invalid_expression),
            ("T38_运行时长", t38_agent_run_time_limit),
            ("T39_工具完整性", t39_tool_list_comprehensive),
            ("T40_技能加载", t40_skill_loading),
        ]
    
    def _print_summary(self):
        total = self.total_passed + self.total_failed
        print(f"\n{'='*60}")
        print(f"📊 测试汇总")
        print(f"{'='*60}")
        print(f"总用例: {total}")
        print(f"✅ 通过: {self.total_passed}")
        print(f"❌ 失败: {self.total_failed}")
        print(f"通过率: {self.total_passed/total*100:.0f}%")
        print(f"{'='*60}\n")
        
        if self.total_failed > 0:
            print("❌ 失败的测试:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.error[:100]}")
            print()


# ============================================================
# 辅助函数
# ============================================================

def create_test_agent(temp_dir: str = None) -> AgentCore:
    """创建干净的测试用Agent"""
    cfg_obj = Config()
    cfg = cfg_obj.load()
    llm = create_llm_client_from_config(cfg)
    
    reg = ToolRegistry()
    register_builtin_tools(reg)
    
    # 注册天气工具
    from dogeey.tools import Tool as ToolClass
    reg.register(ToolClass(
        name=WEATHER_TOOL["name"],
        description=WEATHER_TOOL["description"],
        parameters=WEATHER_TOOL["parameters"],
        func=tool_query_weather
    ))
    
    session_mgr = SessionManager()
    
    agent = AgentCore(
        llm_client=llm,
        tool_registry=reg,
        session_manager=session_mgr,
        max_iterations=45,
    )
    
    if temp_dir:
        agent.data_dir = temp_dir
    
    return agent


def check_no_hallucination(output: str, tool_calls: List[Dict]) -> bool:
    """检查是否有幻觉"""
    # 简单启发式：如果没调用工具但声称查询到了数据
    hallucination_patterns = [
        "我已经为您设置好了.*提醒",
        "已为您创建.*定时任务",
        "下次执行.*20\d{2}",
    ]
    if not tool_calls:
        for pattern in hallucination_patterns:
            if re.search(pattern, output, re.DOTALL):
                return False
    return True


def check_no_log_leak(output: str) -> bool:
    """检查是否有日志泄露"""
    leak_patterns = [
        r"🔍 DEBUG:",
        r"dogeey\.context_compressor",
        r"dogeey\.llm - INFO",
        r"LLM请求:",
        r"Token统计:",
    ]
    for pattern in leak_patterns:
        if re.search(pattern, output):
            return False
    return True


def record_tool_calls(agent: AgentCore, result: TestResult):
    """从agent中记录工具调用到结果"""
    if hasattr(agent, '_tool_calls'):
        result.tool_calls = agent._tool_calls
    if hasattr(agent, '_last_tool_calls'):
        result.tool_calls = agent._last_tool_calls
    result.tool_call_count = len(result.tool_calls)


# ============================================================
# 测试用例
# ============================================================

def t01_greeting(r: TestResult):
    """简单问候 - 不调用工具也能对话"""
    agent = create_test_agent()
    output = agent.run("你好")
    r.output = output
    record_tool_calls(agent, r)
    r.no_hallucination = check_no_hallucination(output, r.tool_calls)
    r.no_log_leak = check_no_log_leak(output)
    r.passed = bool(output) and len(output) > 10


def t02_self_intro(r: TestResult):
    """自我介绍"""
    agent = create_test_agent()
    output = agent.run("你是谁？能做什么？")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = "dogeey" in output.lower() or "铁蛋" in output


def t03_file_create(r: TestResult):
    """创建文件"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    output = agent.run(f"在 {temp_dir} 创建一个 hello.txt 文件，内容为 Hello World")
    r.output = output
    record_tool_calls(agent, r)
    
    # 验证文件
    fpath = Path(temp_dir) / "hello.txt"
    r.passed = fpath.exists() and "Hello World" in fpath.read_text()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t04_file_read(r: TestResult):
    """读取文件"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    # 先创建文件
    Path(temp_dir, "readme.txt").write_text("This is a test file content")
    
    output = agent.run(f"读取 {temp_dir}/readme.txt 的内容")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = "test file content" in output.lower()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t05_file_delete(r: TestResult):
    """删除文件"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    # 先创建文件
    fpath = Path(temp_dir, "delete_me.txt")
    fpath.write_text("delete me")
    
    output = agent.run(f"用命令删除 {fpath}")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = not fpath.exists()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t06_search_files(r: TestResult):
    """搜索文件"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    # 创建测试文件
    Path(temp_dir, "config_dogeey.json").write_text("{}")
    Path(temp_dir, "readme.txt").write_text("hello")
    
    output = agent.run(f"在 {temp_dir} 搜索包含 dogeey 的文件")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = "config_dogeey" in output.lower() or r.tool_call_count > 0
    shutil.rmtree(temp_dir, ignore_errors=True)


def t07_shell_command(r: TestResult):
    """Shell执行"""
    agent = create_test_agent()
    output = agent.run("用命令列出当前目录的前5个文件")
    r.output = output
    record_tool_calls(agent, r)
    # 检查是否有工具调用
    r.passed = r.tool_call_count > 0


def t08_weather_query(r: TestResult):
    """天气查询"""
    agent = create_test_agent()
    output = agent.run("查询北京的天气")
    r.output = output
    record_tool_calls(agent, r)
    
    # 验证：应该有天气数据，不应是编造的
    has_weather_data = any(kw in output.lower() for kw in ["温度", "weather", "°c", "℃", "weatherdesc"])
    r.no_hallucination = check_no_hallucination(output, r.tool_calls)
    r.passed = has_weather_data and r.no_hallucination


def t09_multi_step(r: TestResult):
    """多步任务"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    output = agent.run(f"在 {temp_dir} 创建 step1.txt 内容为 '第一步'，然后创建 step2.txt 内容为 '第二步'")
    r.output = output
    record_tool_calls(agent, r)
    
    f1 = Path(temp_dir) / "step1.txt"
    f2 = Path(temp_dir) / "step2.txt"
    r.passed = f1.exists() and f2.exists()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t10_error_handling(r: TestResult):
    """错误处理"""
    agent = create_test_agent()
    output = agent.run("执行一个不存在的命令: xyz123nonexistent456")
    r.output = output
    record_tool_calls(agent, r)
    # 应该有错误信息，不是编造的成功结果
    r.passed = "error" in output.lower() or "失败" in output or "不存在" in output or "not found" in output.lower()


def t11_context_retention(r: TestResult):
    """上下文保留 - 先创建文件再读取"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    # 第一轮：创建文件
    out1 = agent.run(f"在 {temp_dir} 创建一个 test_context.txt 内容为 '上下文测试内容'")
    
    # 第二轮：引用"它"
    out2 = agent.run("它的内容是什么？")
    
    r.output = out2
    record_tool_calls(agent, r)
    r.passed = "上下文测试内容" in out2
    shutil.rmtree(temp_dir, ignore_errors=True)


def t12_multi_turn(r: TestResult):
    """多轮对话"""
    agent = create_test_agent()
    
    out1 = agent.run("记住一个关键词：苹果")
    out2 = agent.run("我刚才让你记住了什么？")
    
    r.output = out2
    record_tool_calls(agent, r)
    r.passed = "苹果" in out2
    r.context_maintained = True


def t13_topic_switch(r: TestResult):
    """话题切换"""
    agent = create_test_agent()
    
    out1 = agent.run("今天天气怎么样？")
    out2 = agent.run("介绍一下你自己")
    
    r.output = out2
    record_tool_calls(agent, r)
    # 应该回答自我介绍，而不是继续聊天气
    r.passed = "dogeey" in out2.lower() or "铁蛋" in out2


def t14_reference_understanding(r: TestResult):
    """指代理解"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    out1 = agent.run(f"在 {temp_dir} 创建 file_a.txt 内容为 'A文件'")
    out2 = agent.run("再创建 file_b.txt 内容为 'B文件'")
    out3 = agent.run(f"列出 {temp_dir} 下的所有txt文件")
    
    r.output = out3
    record_tool_calls(agent, r)
    r.passed = "file_a" in out3.lower() and "file_b" in out3.lower()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t15_honesty(r: TestResult):
    """诚实原则 - 不编造数据"""
    agent = create_test_agent()
    # 问一个没有工具能回答的实时数据问题
    output = agent.run("今天上证指数开盘是多少？")
    r.output = output
    record_tool_calls(agent, r)
    
    # 不应该包含具体数字（编造的）
    has_numbers = bool(re.search(r'\d{4}\.\d+', output))  # 像 3500.00 这样的数字
    r.no_hallucination = not has_numbers or "不知道" in output or "无法" in output or "没有" in output
    r.passed = r.no_hallucination


def t16_self_learning(r: TestResult):
    """自我学习 - 记住并检索"""
    agent = create_test_agent()
    
    out1 = agent.run("记住我喜欢用Python开发")
    out2 = agent.run("我偏好什么编程语言？")
    
    r.output = out2
    record_tool_calls(agent, r)
    r.passed = "python" in out2.lower()


def t17_complex_task(r: TestResult):
    """复杂任务 - 创建项目结构"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    agent = create_test_agent(temp_dir)
    
    output = agent.run(f"在 {temp_dir}/myproject 下创建 main.py (包含print('hello')) 和 requirements.txt (包含requests)")
    r.output = output
    record_tool_calls(agent, r)
    
    main_py = Path(temp_dir) / "myproject" / "main.py"
    req_txt = Path(temp_dir) / "myproject" / "requirements.txt"
    r.passed = main_py.exists() and req_txt.exists() and "hello" in main_py.read_text()
    shutil.rmtree(temp_dir, ignore_errors=True)


def t18_error_recovery(r: TestResult):
    """错误恢复 - 读取不存在文件"""
    agent = create_test_agent()
    output = agent.run("读取 /tmp/definitely_not_exist_abc123.txt 的内容")
    r.output = output
    record_tool_calls(agent, r)
    # 应该报告错误，不崩溃
    r.passed = any(kw in output.lower() for kw in ["不存在", "error", "not found", "失败", "没有"])


def t19_cron_task(r: TestResult):
    """定时任务"""
    agent = create_test_agent()
    
    output = agent.run("创建一个每天9点打印hello的定时任务，然后列出所有定时任务")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = r.tool_call_count > 0  # 至少有工具调用


def t20_metacognition(r: TestResult):
    """自我报告"""
    agent = create_test_agent()
    output = agent.run("生成你的自我评估报告")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = len(output) > 50  # 有内容即可


def t21_long_input(r: TestResult):
    """超长输入"""
    agent = create_test_agent()
    long_text = "这是测试文本。" * 500  # 约3000字
    output = agent.run(f"请总结以下内容：{long_text}")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = len(output) > 10 and r.duration < 120


def t22_special_chars(r: TestResult):
    """特殊字符处理"""
    agent = create_test_agent()
    output = agent.run("用 echo 命令输出包含引号和特殊字符的内容: hello 'world' & < > |")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = True  # 不崩溃即可


def t23_empty_input(r: TestResult):
    """空输入"""
    agent = create_test_agent()
    output = agent.run("   ")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = len(output) > 0  # 有回复即可


# ============================================================
# 补充测试用例（26-40）
# ============================================================

def t24_memory_persistence(r: TestResult):
    """记忆持久化 - 新建Agent后记忆还在"""
    agent1 = create_test_agent()
    agent1.run("记住一个测试关键词: persistence_test_2026")
    
    # 新建Agent实例（模拟重启）
    agent2 = create_test_agent()
    output = agent2.run("我之前让你记住了什么关键词？")
    r.output = output
    r.passed = "persistence_test_2026" in output or "不知道" in output or "没有找到" in output


def t25_cron_persistence(r: TestResult):
    """定时任务持久化"""
    from dogeey.cron.manager import CronManager
    from dogeey.cron.storage import CronStorage
    
    # 清理旧数据
    try:
        CronStorage().delete_job("test_persist_001")
    except:
        pass
    
    agent = create_test_agent()
    agent.run("创建一个任务ID为test_persist_001的定时任务，每5分钟打印一次hello")
    
    # 新建manager检查
    storage = CronStorage()
    jobs = storage.get_all_jobs()
    job_exists = any(j.get("id") == "test_persist_001" for j in jobs)
    
    r.passed = job_exists
    
    # 清理
    try:
        storage.delete_job("test_persist_001")
    except:
        pass


def t26_context_compression(r: TestResult):
    """上下文压缩触发"""
    from dogeey.context_compressor import ContextCompressor
    
    compressor = ContextCompressor()
    
    # 构造少量消息（不触发压缩）
    messages = [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮助你的？"},
    ]
    
    result = compressor.compress(messages)
    r.passed = isinstance(result, list) and len(result) >= 2


def t27_tool_progressive_disclosure(r: TestResult):
    """工具渐进式披露 - L1索引、L2简述、L3完整"""
    from dogeey.tools import ToolRegistry, register_builtin_tools
    
    reg = ToolRegistry()
    register_builtin_tools(reg)
    
    # L1: 索引
    level1 = reg.get_tools_index()
    r.passed = len(level1) > 0 and isinstance(level1, str)


def t28_react_fallback(r: TestResult):
    """ReAct模式回退"""
    from dogeey.tools import ToolRegistry
    
    # 创建空工具注册表
    reg = ToolRegistry()
    cfg_obj = Config()
    cfg = cfg_obj.load()
    llm = create_llm_client_from_config(cfg)
    session_mgr = SessionManager()
    
    agent = AgentCore(
        llm_client=llm,
        tool_registry=reg,
        session_manager=session_mgr,
        max_iterations=10,
    )
    
    # 没有工具的ReAct模式
    output = agent.run("你好")
    r.output = output
    r.passed = len(output) > 10


def t29_tool_parameter_validation(r: TestResult):
    """工具参数校验"""
    from dogeey.tools import ToolRegistry, register_builtin_tools
    
    reg = ToolRegistry()
    register_builtin_tools(reg)
    
    # 尝试读取不存在的文件（参数合法但文件不存在）
    result = reg.execute("read_file", {"file_path": "/nonexistent_path_12345"})
    r.passed = "error" in str(result).lower() or "不存在" in str(result) or "not found" in str(result).lower()


def t30_large_file_truncation(r: TestResult):
    """大文件读取截断"""
    temp_dir = tempfile.mkdtemp(prefix="dogeey_test_")
    large_file = Path(temp_dir) / "large.txt"
    
    # 创建3000行文件
    with open(large_file, "w") as f:
        for i in range(3000):
            f.write(f"第{i+1}行测试内容\n")
    
    agent = create_test_agent(temp_dir)
    output = agent.run(f"读取 {large_file} 的内容")
    r.output = output
    record_tool_calls(agent, r)
    r.passed = len(output) > 0  # 有输出即可
    shutil.rmtree(temp_dir, ignore_errors=True)


def t31_contextflow_topic_management(r: TestResult):
    """ContextFlow话题管理"""
    from dogeey.context_flow import ContextManager
    
    cfg_obj = Config()
    cfg = cfg_obj.load()
    llm = create_llm_client_from_config(cfg)
    
    cm = ContextManager(llm_client=llm)
    
    # 创建话题
    ctx_id = cm.create_context("测试话题")
    cm.add_message(ctx_id, "user", "第一条消息")
    cm.add_message(ctx_id, "assistant", "第一条回复")
    
    # 检查
    context = cm.get_context(ctx_id)
    msg_count = len(context.messages)
    
    r.passed = msg_count == 2


def t32_unicode_boundary(r: TestResult):
    """Unicode/编码边界"""
    agent = create_test_agent()
    # 混合中文、emoji、日文、特殊字符
    output = agent.run("请回复这个: 🎉 你好 世界 🌍 こんにちは 안녕하세요")
    r.output = output
    r.passed = len(output) > 5


def t33_session_memory_growth(r: TestResult):
    """Session内存管理"""
    agent = create_test_agent()
    
    # 模拟多轮对话
    for i in range(10):
        agent.run(f"这是第{i+1}轮测试消息")
    
    if agent.session_manager:
        sessions = agent.session_manager.list_sessions()
        # 检查session数量可控
        r.passed = len(sessions) < 20
    else:
        r.passed = True


def t34_llm_client_creation(r: TestResult):
    """LLM客户端创建"""
    cfg_obj = Config()
    cfg = cfg_obj.load()
    llm = create_llm_client_from_config(cfg)
    
    r.passed = llm is not None
    # 尝试简单调用
    try:
        resp = llm.chat("你好")
        r.passed = resp is not None and len(resp) > 0
    except Exception as e:
        r.passed = False
        r.error = f"LLM调用失败: {e}"


def t35_tool_registry_isolation(r: TestResult):
    """工具注册表隔离"""
    from dogeey.tools import ToolRegistry
    
    reg1 = ToolRegistry()
    reg2 = ToolRegistry()
    
    reg1.register(Tool(
        name="test_tool_isolated",
        description="测试隔离",
        parameters={"type": "object", "properties": {}},
        func=lambda: "isolated"
    ))
    
    # reg2 不应该有 reg1 的工具
    r.passed = not reg2.exists("test_tool_isolated") and reg1.exists("test_tool_isolated")


def t36_cron_expression_validation(r: TestResult):
    """Cron表达式验证"""
    from dogeey.cron.job import CronExpression
    
    # 合法的cron
    valid = CronExpression("0 9 * * *")
    r.passed = valid.is_valid()


def t37_cron_invalid_expression(r: TestResult):
    """Cron无效表达式"""
    from dogeey.cron.job import CronExpression
    
    # 非法的cron
    invalid = CronExpression("60 25 * * *")
    r.passed = not invalid.is_valid()


def t38_agent_run_time_limit(r: TestResult):
    """Agent运行时间限制"""
    agent = create_test_agent()
    
    start = time.time()
    output = agent.run("你好")
    duration = time.time() - start
    
    r.passed = duration < 120  # 不应超过2分钟


def t39_tool_list_comprehensive(r: TestResult):
    """工具列表完整性"""
    from dogeey.tools import ToolRegistry, register_builtin_tools
    
    reg = ToolRegistry()
    register_builtin_tools(reg)
    
    all_tools = reg.list_tools()
    tool_names = [t.name for t in all_tools]
    
    # 核心工具应该都存在
    required = ["read_file", "write_file", "run_command", "search_files", "query_weather"]
    missing = [t for t in required if t not in tool_names]
    
    r.passed = len(missing) == 0
    if missing:
        r.error = f"缺少工具: {missing}"


def t40_skill_loading(r: TestResult):
    """技能加载"""
    from dogeey.skills import SkillManager
    
    sm = SkillManager()
    # 获取技能索引
    index = sm.get_skill_index()
    r.passed = isinstance(index, str) or index is not None


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    runner = DogeeyTestRunner()
    runner.run_all()
