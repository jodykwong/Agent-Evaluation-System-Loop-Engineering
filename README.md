# Agent-Evaluation-System-Loop-Engineering

**版本：V0.02**（封闭版本；后续手动推送到 GitHub）

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
    ├── index.html               # 评估看板（全部真实数据，无示例/占位数据）
    └── build.py                  # 把 trace_store/ + harness-checklist.md 的
                                    # 真实数据注入看板

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
python eval/dashboard/build.py
```

生成的 `eval/dashboard/index.html` 是一个自包含的静态页面，可以直接用
浏览器打开。**页面上不存在任何手工构造的示例/占位数据**，`build.py`
注入两类真实数据：

- **六维 harness 原则达成度**（雷达图 + 逐维明细）—— 不是 pass@1／成本
  那类模型效果评分，而是核对这个 agent 有没有按 `eval/harness-checklist.md`
  里的 AI 系統工程六項設計原則（上下文管理／工具调用／执行编排／状态与
  记忆／评估与观测／约束与恢复）落地。每一维的分值就是该维已勾选项数 /
  总检查项数，直接解析 checklist 的 `[x]/[ ]` 得出。**每次改完 agent
  核心逻辑，先去 `harness-checklist.md` 把对应勾选状态更新了，再跑
  `build.py`，雷达图才会跟着变。**
- **调用侧可观测指标**（延迟/token 趋势、成功率、工具与来源分布、逐条
  运行记录）—— 来自 `eval/runner/trace_store/` 的真实调用。看板顶部标题
  会显示当前主要被评测的 agent（平台 + agent 名，从 trace 的调用来源反
  推）和默认模型（读 `agent/config.py` 的 `DEFAULT_MODEL`）。**每次产生
  新的真实调用后，重新跑一遍 `build.py` 刷新。**

## 已知限制

详见 `eval/harness-checklist.md`——按"上下文管理 / 工具调用 / 执行编排 /
状态与记忆 / 评估与观测 / 约束与恢复"六项原则逐条记录了现状，包括：

- 内部检索、第三方 API 两个工具还是占位实现
- 没有多 agent 协同编排，是单体架构
- 没有 pass@1／成本这类模型效果打分逻辑——黄金数据集（Phase 2）、
  grader（Phase 3）、runner（Phase 4）还没跑起来；harness 六维达成度
  雷达图是真实数据，但衡量的是"有没有按六项原则落地"，不是"回答得好不好"
- 没有人工审核门槛（高风险操作无确认机制）
- 长对话没有上下文压缩/裁剪保护

## 版本历史

- **V0.02**（本次）—— code review 修复 + 评估看板重做：
  - `core.py`：重试不再往带记忆的 checkpointer 线程里重复追加用户消息
    （用 resume 语义代替重发）；最终答案提取兼容 Anthropic 等返回内容块
    列表的 provider，不会在换模型厂商时崩溃；trace 落盘失败改成兜底
    `Exception` 而不是只兜 `OSError`，避免序列化异常掩盖真实报错；瞬时
    故障判定里的 HTTP 状态码改成词边界匹配，不再被"1500 行""15000ms"
    这类无关数字误判；"本地直接调用"默认改成每次独立的记忆线程，避免
    所有匿名本地调用挤进同一条无限增长、互相串味的记忆线程。
  - `middleware/tracing.py`：provider 只给 input/output token、不给
    total 时用分项兜底，看板不再出现"分项非零、合计为零"的矛盾数字。
  - `openclaw-skill/`：修正 `run.sh` 和 README 里路径大小写不一致的问题。
  - `eval/dashboard/`：删掉手工构造的 `SAMPLE_DATA` 示例数据，`build.py`
    改为解析 `eval/harness-checklist.md` 注入真实的六维 harness 原则
    达成度（雷达图 + 逐维明细），并解析 trace 的调用来源/`agent/config.py`
    的默认模型，让看板标题动态显示"当前评估的是哪个 agent"；调用侧图表
    （延迟/token 趋势、成功率、工具与来源分布）也全部改用 trace_store
    真实数据重新绘制，页面不再有任何示例/占位内容。

- **V0.01** —— 初始封闭版本：多厂商模型层、四个工具（两个真实
  两个占位）、跨调用对话记忆、失败重试、trace 落盘、OpenClaw skill 集成、
  评估看板雏形。
