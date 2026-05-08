"""
启动动画和彩色输出效果
使用 rich 库实现炫酷的终端界面
"""
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.table import Table
import time
import sys


console = Console()


def show_startup_animation():
    """显示启动动画"""
    # 清屏（可选）
    # console.clear()
    
    # 逐行显示Logo（打字机效果）
    logo_lines = [
        "             .--~~,__",
        ":-...,-------`~~'._.'",
        " `-,,,  ,_      ;'~U'",
        "  _,-' ,'`-__; '--.",
        " (_/'~~      ''''(;"
    ]
    
    console.print()
    for line in logo_lines:
        console.print(line, style="bold cyan", end="\n")
        time.sleep(0.1)
    
    console.print()
    
    # 显示版本信息（带渐变效果）
    version_text = Text("    Dogeey v1.0.0", style="bold green")
    console.print(version_text)
    
    slogan_lines = [
        "    轻量级AI智能体",
        "    越用越聪明"
    ]
    
    for line in slogan_lines:
        console.print(line, style="italic bright_black")
        time.sleep(0.15)
    
    console.print()
    
    # 加载进度条
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        # 模拟加载过程
        task1 = progress.add_task("[cyan]正在初始化核心组件...", total=100)
        task2 = progress.add_task("[green]正在加载用户画像...", total=100)
        task3 = progress.add_task("[yellow]正在连接AI模型...", total=100)
        
        # 模拟进度
        for i in range(100):
            progress.update(task1, advance=1)
            time.sleep(0.005)
        
        for i in range(100):
            progress.update(task2, advance=1)
            time.sleep(0.005)
        
        for i in range(100):
            progress.update(task3, advance=1)
            time.sleep(0.005)
    
    console.print()
    
    # 显示启动完成提示
    complete_panel = Panel(
        "[bold green]✨ Dogeey 已就绪！[/bold green]\n\n"
        "[dim]输入 /help 查看命令，直接输入开始对话[/dim]",
        title="[bold]🚀 启动完成[/bold]",
        border_style="green",
        padding=(1, 2)
    )
    console.print(complete_panel)
    console.print()


def show_typing_animation(text="思考中...", duration=1.5):
    """显示打字动画"""
    with console.status(f"[bold yellow]{text}[/bold yellow]", spinner="dots"):
        time.sleep(duration)


def create_input_box(prompt="🔍 你 "):
    """创建美化的输入提示（兼容性优先）"""
    # 重要：不要用console.print，会和readline冲突
    # 使用原生print + flush，确保提示符正确显示
    print(prompt, end="", flush=True)
    return input()


def show_welcome_for_onboarding():
    """显示引导前的欢迎信息"""
    welcome_panel = Panel(
        "[bold]🎉 初次见面！[/bold]\n\n"
        "让我了解一下您的偏好，以便提供更好的服务。\n"
        "[dim]整个过程只需回答5个问题[/dim]",
        title="[bold blue]欢迎使用 Dogeey[/bold blue]",
        border_style="blue",
        padding=(1, 2)
    )
    console.print()
    console.print(welcome_panel)
    console.print()


def show_onboarding_question(question_num, total_questions, question_text):
    """显示引导问题（美化版）"""
    header = Text(f"\n问题 {question_num}/{total_questions}", style="bold yellow")
    console.print(header)
    console.print("━" * 50, style="dim")
    console.print()
    console.print(question_text)
    console.print()


def show_confirmation(summary):
    """显示确认信息（美化版）"""
    table = Table(title="📊 您的偏好设置", show_header=True, header_style="bold green")
    table.add_column("项目", style="cyan", width=15)
    table.add_column("设置", style="white")
    
    for key, value in summary.items():
        table.add_row(key, value)
    
    console.print()
    console.print(table)
    console.print()


def show_error(message):
    """显示错误信息（美化版）"""
    console.print(f"[bold red]❌ {message}[/bold red]")


def show_warning(message):
    """显示警告信息（美化版）"""
    console.print(f"[bold yellow]⚠️ {message}[/bold yellow]")


def show_success(message):
    """显示成功信息（美化版）"""
    console.print(f"[bold green]✅ {message}[/bold green]")


def show_info(message):
    """显示提示信息（美化版）"""
    console.print(f"[bold blue]💡 {message}[/bold blue]")


def show_result_header():
    """显示结果头部"""
    console.print("━" * 50, style="dim")
    console.print("[bold]🤖 Dogeey 回复:[/bold]")
    console.print()


# 如果直接运行此文件，测试动画效果
if __name__ == "__main__":
    console.print("[bold]测试启动动画...[/bold]")
    show_startup_animation()
    
    console.print("\n[bold]测试输入提示...[/bold]")
    answer = create_input_box("测试输入: ")
    console.print(f"您输入了: {answer}")

# 别名，兼容旧代码（带下划线的版本）
show_start_up_animation = show_startup_animation


def show_model_status(model: str, provider: str, current_tokens: int, max_tokens: int):
    """显示模型状态栏 (Hermes风格，固定在输入框上方)"""
    # 获取终端宽度
    try:
        import shutil
        term_width = shutil.get_terminal_size().columns
    except:
        term_width = 120
    
    # 格式化token数 (K/M)
    def fmt_tokens(n):
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        elif n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)
    
    # 计算百分比
    pct = min(int((current_tokens / max_tokens) * 100), 100) if max_tokens > 0 else 0
    
    # 截断模型名（防止折行）
    max_model_len = 15
    if len(model) > max_model_len:
        model = model[:max_model_len-3] + "..."
    
    # 生成进度条 (20个字符宽度)
    bar_width = 20
    filled = int((pct / 100) * bar_width)
    bar = "█" * filled + "░" * (bar_width - filled)
    
    # 组装状态行
    status_line = f"{model} ({provider}) │ {fmt_tokens(current_tokens)}/{fmt_tokens(max_tokens)} │ [{bar}] {pct}%"
    
    # 限制总宽度不超过终端
    if len(status_line) > term_width - 4:
        status_line = status_line[:term_width-7] + "..."
    
    # 斑马线 (动态宽度，最大80)
    width = min(len(status_line) + 4, max(term_width, 80))
    zebra = "━" * width
    
    # 输出 (使用console避免和readline冲突)
    console.print()
    console.print(zebra, style="dim")
    console.print(f"  {status_line}", style="bold cyan")
    console.print(zebra, style="dim")
    console.print()
