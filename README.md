# 通用 Agent MVP

**版本：V0.01**（封闭版本，作为初始提交记录；后续手动推送到 GitHub）

一个跨模型提供商的通用助手 agent，基于 LangChain / LangGraph 构建，支持
网络搜索、代码执行、内部知识库检索、第三方业务 API 四类能力，并接入了
OpenClaw 作为多渠道测试/使用入口，附带一个用真实运行记录驱动的评估看板。

## 这是什么

- **不锁定单一模型厂商**：模型层通过 `langchain.chat_models.init_chat_model`
  统一封装，切换 Anthropic / OpenAI / Google / NVIDIA / MiniMax 只改一个
  配置字符串，agent 的工具、middleware、调用方式完全不用变。
- **四个工具能力**：网络搜索（Brave Search）、代码执行（自建 Docker
  沙箱，免费无需注册）、内部知识库检索（占位，待接入真实数据源）、
  第三方业务 API（占位，待接入具体服务）。
- **跨调用的对话记忆**：用 LangGraph 的 SQLite checkpointer，按调用来源
  （比如"来自哪个 OpenClaw agent"）分配 `thread_id`，同一来源的连续
  调用能记住之前说过什么。
- **失败自动重试**：识别网络超时、限流、5xx 这类瞬时故障并指数退避重试，
  鉴权失败这类非瞬时故障不会做无意义的重试。
- **每次调用留痕**：完整 trace（输入、输出、耗时、token 用量、调用了
  哪些工具、调用来源）默认落盘，是评估看板"真实运行记录"的数据源。
- **接入 OpenClaw**：以 skill 的形式挂进 OpenClaw 的共享 skills 目录，
  你现有的任意一个 OpenClaw agent 都能调用这个通用 agent。

## 项目结构

```
agent/
├── config.py              # 默认模型配置（DEFAULT_MODEL）
├── models.py               # 跨厂商模型初始化 + 已验证模型的注意事项
├── agent.py                 # create_agent 组装：模型 + 四个工具 + middleware
├── core.py                  # 唯一入口 run_agent()：调用、记忆、重试、落盘
├── tools/
│   ├── web_search.py         # Brave Search
│   ├── code_exec.py           # 自建 Docker 沙箱
│   ├── internal_retrieval.py  # 占位，待接入真实数据源
│   └── third_party_api.py     # 占位，待接入具体第三方服务
└── middleware/
    └── tracing.py             # trace 采集：耗时、token 用量

openclaw-skill/               # 挂到 OpenClaw 的 skill 定义
├── SKILL.md
├── scripts/run.sh
└── README.md                  # 安装/验证步骤

scripts/
├── openclaw_cli.py            # CLI 包装，OpenClaw 的 exec 工具调这个
└── smoke_test.py               # 本地最小可运行验证脚本

eval/
├── harness-checklist.md        # Agent harness 六要素检查清单（含现状）
├── runner/
│   ├── trace_store/            # 真实运行记录（gitignored，本地生成）
│   └── conversation_memory.sqlite  # 对话记忆数据库（gitignored，本地生成）
└── dashboard/
    ├── index.html               # 评估看板（六维指标示例数据 + 真实运行记录）
    └── build.py                  # 把 trace_store/ 的真实数据注入看板

requirements.txt
.env.example                   # 环境变量模板
```

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，至少配置一个模型 provider 的 key（Anthropic/OpenAI/Google/
# NVIDIA/MiniMax 任选其一），网络搜索用的 BRAVE_SEARCH_API_KEY 也需要配置。
# 代码执行工具需要本机 Docker（或 OrbStack）装好并且在运行，不需要 key。

python scripts/smoke_test.py
```

## 已验证可用的模型

详见 `agent/models.py` 里的注释，简要结论：

- `nvidia:meta/llama-3.1-8b-instruct` —— 真实 tool-calling 正常，响应快，
  但一轮只能调一个工具（同时要求调两个工具会报错）
- `minimax:MiniMax-M3` —— 真实 tool-calling 正常，会把推理过程内联成
  `<think>` 标签，`core.py` 已经自动过滤掉，当前默认模型
- `nvidia:meta/llama-3.2-3b-instruct` —— 不支持真正的 tool-calling，
  不要用于需要工具的场景
- `nvidia:meta/llama-3.3-70b-instruct` —— 在当前配额层级下持续超时

MiniMax 国内站（minimaxi.com）和国际站（minimax.io）是两套独立账号
体系，key 不能混用，详见 `agent/models.py` 里的说明。

## 接入 OpenClaw

见 `openclaw-skill/README.md`。核心是软链到 OpenClaw 的共享 skills 目录：

```bash
ln -s "$(pwd)/openclaw-skill" ~/.openclaw/skills/our-general-agent
```

## 评估看板

```bash
python eval/dashboard/build.py   # 把 eval/runner/trace_store/ 的真实数据注入看板
```

生成的 `eval/dashboard/index.html` 是一个自包含的静态页面，可以直接用
浏览器打开。六维指标趋势图目前还是示例数据（真实的评估系统 Phase 0-4
还没跑起来），"真实运行记录"表格是唯一的真实数据。**每次改动 agent
核心逻辑或者产生了新的真实调用之后，记得重新跑一遍 `build.py`。**

## 已知限制

详见 `eval/harness-checklist.md`——按"上下文管理 / 工具调用 / 执行编排 /
状态与记忆 / 评估与观测 / 约束与恢复"六项原则逐条记录了现状，包括：

- 内部检索、第三方 API 两个工具还是占位实现
- 没有多 agent 协同编排，是单体架构
- 没有真正的评分/评测逻辑（六维图是示例数据）
- 没有人工审核门槛（高风险操作无确认机制）
- 长对话没有上下文压缩/裁剪保护

## 版本历史

- **V0.01**（本次）—— 初始封闭版本：多厂商模型层、四个工具（两个真实
  两个占位）、跨调用对话记忆、失败重试、trace 落盘、OpenClaw skill 集成、
  评估看板雏形。
