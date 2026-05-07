# Dogeey 🤖

**轻量级AI智能体框架 - 支持多平台、多模型、自我进化**

[![Version](https://img.shields.io/badge/version-1.1.0-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()
[![Python](https://img.shields.io/badge/python-3.10+-blueviolet)]()

---

## 📋 项目概述

Dogeey 是一个轻量级 AI 智能体框架，借鉴 OpenClaw 和 Hermes 的设计理念，具备记忆系统、用户画像、自我进化能力，并支持多平台消息接入（飞书、Web 等）。

- 🧠 **记忆系统** - 长期+短期记忆，SQLite+FTS5全文搜索，时间衰减权重
- 📚 **技能库** - 可复用技能，渐进式披露节省 token
- 🎭 **用户画像** - 自动学习用户习惯，持续进化
- 🔄 **自我进化** - 任务成功后自动总结为技能
- 🌐 **多平台接入** - 飞书（WebSocket）、Web UI、CLI
- ⏰ **定时任务** - Cron 调度器，支持自然语言创建定时任务
- 🔀 **多模型支持** - OpenAI 兼容 API，支持多提供商自动 fallback
- ⚡ **轻量核心** - 核心代码模块化，易于扩展

---

## 🚀 快速开始

### 1. 安装

```bash
# 基础版（仅CLI）
pip install -e .

# 完整版（含WebUI、飞书接入等）
pip install -e ".[full]"
```

### 2. 初始化

```bash
dogeey init
```

按提示输入：
- API Key（支持 OpenAI/DeepSeek/Claude/Astron 等）
- API Base URL
- 默认模型

或使用环境变量：

```bash
export DOGEEY_API_KEY="sk-..."
export DOGEEY_BASE_URL="https://api.openai.com/v1"
export DOGEEY_MODEL="gpt-4o"
```

### 3. 使用

**CLI 模式：**
```bash
# 运行指令
dogeey run "帮我分析当前目录结构"

# 详细模式（查看推理过程）
dogeey run "生成一个Python爬虫" -v

# 不使用记忆/画像
dogeey run "指令" --no-memory --no-profile
```

**Web UI 模式：**
```bash
dogeey webui
# 访问 http://localhost:8080
```

**飞书接入：**
```bash
# 配置飞书 app_id 和 app_secret 后
python3 listen_feishu.py
# 或通过 Web UI 的频道系统自动启动
```

---

## 📖 CLI 命令

| 命令 | 说明 |
|------|------|
| `dogeey init` | 初始化配置（交互式引导） |
| `dogeey run <指令>` | 运行智能体执行指令 |
| `dogeey webui` | 启动 Web 管理界面 |
| `dogeey config show` | 查看当前配置 |
| `dogeey config add-provider` | 添加模型提供商 |
| `dogeey config list-providers` | 列出所有提供商 |
| `dogeey config set-default <name>` | 设置默认提供商 |
| `dogeey uninstall` | 卸载（清除数据） |

---

## 🏗️ 架构设计

```
dogeey/
├── dogeey/
│   ├── cli.py              # CLI 入口（Click）
│   ├── config.py           # 配置管理
│   ├── llm.py              # LLM 调用封装（支持多提供商 fallback）
│   ├── core.py             # 智能体核心（FC + ReAct 双模式引擎）
│   ├── tools.py            # 工具系统（渐进式披露）
│   ├── task_supervisor.py  # 任务监督（数据结构）
│   ├── memory.py           # 记忆系统（SQLite + FTS5）
│   ├── profile.py          # 用户画像
│   ├── skills.py           # 技能库管理
│   ├── skill_evolution.py  # 技能自进化
│   ├── metacognition.py    # 元认知（自我学习）
│   ├── context_flow.py     # 上下文话题流
│   ├── context_compressor.py # 上下文压缩
│   ├── sessions.py         # 会话管理
│   ├── event_bus.py        # 事件总线
│   ├── message.py          # 消息模型
│   ├── routing.py          # 消息路由
│   ├── cron/               # 定时任务模块
│   │   ├── job.py          # Cron 表达式解析
│   │   ├── scheduler.py    # 调度器
│   │   ├── manager.py      # 管理器
│   │   └── storage.py      # 存储
│   ├── channels/           # 多平台接入
│   │   ├── base.py         # 频道基类
│   │   ├── manager.py      # 频道管理器
│   │   └── feishu/         # 飞书接入
│   │       └── channel.py  # 飞书 WebSocket
│   └── web/
│       ├── backend.py      # FastAPI 后端
│       └── static/
│           └── index.html  # Web UI 前端
├── listen_feishu.py        # 独立飞书监听脚本
├── skills/                 # 技能库目录
│   └── skill_index.json    # 技能索引
└── start.sh                # 快速启动脚本
```

---

## 🛠️ 内置工具

| 工具 | 说明 |
|------|------|
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件 |
| `search_files` | 搜索文件内容或文件名 |
| `run_command` | 执行 Shell 命令 |
| `tool_list_all` | 列出所有可用工具 |
| `memory_search` | 搜索记忆 |
| `memory_add` / `memory_delete` | 管理记忆 |
| `profile_get` / `profile_update` | 用户画像管理 |
| `skill_list` / `skill_load` | 技能管理 |
| `cron_create` / `cron_list` / `cron_delete` | 定时任务管理 |
| `context_switch` / `context_list` | 上下文话题管理 |
| `metacognition_reflect` | 元认知反思 |

### 渐进式披露

工具系统采用三级渐进式披露，避免 prompt 过大：

- **Level 1** - 工具索引（仅名称，~200 tokens）
- **Level 2** - 工具简述（名称+一句话描述，~500 tokens）
- **Level 3** - 完整描述（含参数、示例，按需加载）

---

## 🧠 记忆系统

### 记忆类型

- **短期记忆** - 当前会话上下文
- **长期记忆** - SQLite 持久化，支持：
  - 时间衰减权重（越久越淡）
  - 访问频率提升
  - FTS5 全文搜索

### 权重公式

```
weight = base_weight × exp(-decay_rate × days) × log(access_count + 1)
```

---

## 🔄 双模式执行引擎

Dogeey 支持两种执行模式，自动检测最优方式：

### Function Calling 模式（优先）
- 当有可用工具时自动启用
- 模型直接调用工具，无需解析 ReAct 格式
- 轻量 prompt（~300 chars）

### ReAct 文本模式（备用）
- Thought → Action → Observation → Final Answer 循环
- 适用于不支持 Function Calling 的模型
- 强制工具调用，禁止无工具回答

---

## 🌐 多平台接入

### 飞书（Feishu）
- **WebSocket 模式**（推荐）：无需公网 IP，实时推送
- **轮询模式**：主动拉取消息
- **Webhook 模式**：需要公网地址
- 支持文本、Markdown、富文本回复
- 支持消息 Reaction（⏳处理中、✅完成、❌失败）

### Web UI
- FastAPI + Vanilla JS
- 对话界面、记忆管理、技能库、用户画像、系统配置

### CLI
- 直接命令行交互

---

## ⏰ 定时任务

支持 Cron 表达式创建定时任务：

```bash
# 每天 9:00 执行
dogeey run "每天早上9点提醒我喝水"
```

- 5 段 Cron 表达式（分钟 小时 日 月 星期）
- 持久化存储
- 任务锁防止重复执行
- 支持自然语言创建

---

## 📦 技术栈

- **语言**: Python 3.10+
- **LLM**: OpenAI 兼容 API（支持多提供商自动 fallback）
- **记忆**: SQLite + FTS5 全文搜索
- **Web**: FastAPI + WebSocket + Vanilla JS
- **CLI**: Click
- **飞书**: lark-oapi SDK
- **依赖**: 核心模块轻量化

---

## 📝 配置文件

配置文件：`~/.dogeey/config.json`

```json
{
  "version": "1.1.0",
  "llm": {
    "providers": [
      {
        "name": "openai",
        "api_key": "sk-...",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4-turbo"],
        "default_model": "gpt-4o"
      }
    ],
    "current_provider": "openai"
  },
  "memory": {
    "db_path": "~/.dogeey/data/memories.db",
    "max_short_term": 10,
    "decay_rate": 0.1
  },
  "skills": {
    "path": "~/.dogeey/skills",
    "auto_learn": true
  },
  "channels": {
    "feishu": {
      "enabled": true,
      "connection_mode": "websocket",
      "config": {
        "app_id": "cli_xxx",
        "app_secret": "xxx"
      }
    }
  },
  "webui": {
    "enabled": true,
    "port": 8080,
    "host": "127.0.0.1"
  }
}
```

---

## 🚧 开发状态

- [x] Phase 1: 项目骨架 + 配置系统
- [x] Phase 2: LLM 核心 + ReAct 引擎
- [x] Phase 3: 工具系统
- [x] Phase 4: 记忆系统
- [x] Phase 5: 用户画像 + 学习
- [x] Phase 6: 技能库 + 自我进化
- [x] Phase 7: Web UI 管理后台
- [x] Phase 8: 多平台接入（飞书）+ 定时任务
- [x] Phase 9: FC/ReAct 双模式引擎 + 工具系统优化
- [x] Phase 10: 核心 Bug 修复 + 稳定性提升
- [ ] Phase 11: 打包 + 文档 + 正式发布

---

## 🤝 贡献

欢迎提交 Issue 和 PR！

---

## 📄 许可

MIT License

---

**Dogeey** - 让 AI 智能体越用越聪明！ 🚀
