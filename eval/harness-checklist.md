# Agent Harness 检查清单

来源：Jody Kwong《酒店 AI 轉型落地框架》文档里的"AI 系統工程六項設計原則"——
六条原则本身是通用的 agent 工程检查标准，跟具体业务领域无关，这里拿来
检查我们自己这个通用 agent（`agent/` 目录）。**每次对 agent 核心逻辑
（`agent/agent.py`、`agent/core.py`、工具、middleware）做改动之后，
过一遍这六条，更新一下下面的状态。**

## ① 上下文管理 Context Management

> 确保 AI 决策时掌握完整业务背景，避免信息缺失导致误判。

- [x] token 用量追踪（input/output/total，`TracingMiddleware` 从
      `usage_metadata` 提取，落盘在 `trace_events` 和 `token_usage` 里）
- [ ] 业务背景注入——agent 目前不知道"自己是谁的助手、服务什么场景"，
      没有类似系统提示词里动态注入业务上下文的机制
- [ ] 长对话的上下文压缩/超限保护——对话变长后没有自动摘要或裁剪

## ② 工具调用 Tools Integration

> 通过 API 打通各系统，使 AI 具备实际执行能力。

- [x] 网络搜索（Brave Search，真实可用）
- [x] 代码执行（自建 Docker 沙箱，真实可用，网络隔离）
- [ ] 内部数据检索——占位实现（`agent/tools/internal_retrieval.py`）
- [ ] 第三方业务 API——占位实现（`agent/tools/third_party_api.py`）
- [ ] 工具级成功/失败结构化标记——目前只能从 ToolMessage 的文本内容里
      猜测有没有出错，没有显式的 `tool_call_success: bool` 字段

## ③ 执行编排 Orchestration

> 多个 AI 任务协同运作，跨部门业务联动响应。

- [x] 单 agent 内的多轮工具调用循环（LangGraph `create_agent` 状态图）
- [ ] 多 agent/多任务协同——目前是单体架构，没有"多个 agent 分工、
      互相联动"这个层次
- [ ] 显式的"这次跑了几轮工具调用"指标，目前只能从 `trace_events` 里
      数 before_model/after_model 配对数量，没有直接暴露成字段

## ④ 状态与记忆 State & Memory

> 宾客偏好与营运知识分层沉淀，服务具备连贯性。

- [x] **跨调用的对话记忆**（本轮加上）——`agent/agent.py` 的
      `build_agent()` 现在接受一个 SQLite checkpointer，`core.py` 的
      `run_agent()` 默认按调用来源（`source`，比如
      `openclaw:openclaw-business-analysis`）分配 `thread_id`，同一个
      来源的连续调用会记得之前说过什么。数据库文件：
      `eval/runner/conversation_memory.sqlite`。
- [ ] 长期知识沉淀（比如学到的偏好、纠正过的错误）——目前只有"这次
      会话记得上一轮"，没有跨会话、跨版本沉淀的长期记忆层
- [ ] 记忆的检索/清理策略——sqlite 文件会无限增长，没有过期/裁剪机制

## ⑤ 评估与观测 Evaluation & Observability

> 以量化指标持续监测 AI 效果，向管理层透明汇报。

- [x] 观测的一半：真实运行记录（`eval/dashboard/` 的"真实运行记录"表，
      来源、耗时、token 用量、成功/失败状态）
- [ ] 量化的一半：真正的评分/评测逻辑——六维图目前是示例数据，
      Phase 0-4 的评估系统（黄金数据集 + grader + runner）还没跑起来，
      现在只有"发生了什么"的日志，没有"这个回答好不好"的判断

## ⑥ 约束与恢复 Constraints & Recovery

> 设定安全边界与人工审核门槛，异常时自动回退，保障营运。

- [x] **失败重试**（本轮加上）——`core.py` 的 `run_agent()` 现在对
      "看起来像瞬时故障"的错误（网络超时、429 限流、5xx）做指数退避
      重试，不再是"一次 Brave 429 就整次调用报废"
- [ ] 人工审核门槛——没有任何"高风险操作需要人确认"的机制（目前四个
      工具里网络搜索/代码执行/占位工具都不算高风险，但以后接了真的
      第三方业务 API、可能有副作用的操作时，这条会变得必要）
- [ ] 迭代次数/资源上限的显式约束——目前依赖 LangGraph 自身的默认
      recursion limit，没有针对我们业务场景显式设置更保守的上限

## 五阶段推进路径对照

按同一份文档的五阶段模型（现状评估 → 沙盒验证 → 蓝图规划 → 边缘试点 →
全量部署），目前项目大致卡在 **Phase 2（沙盒验证）与 Phase 3（蓝图规划）
之间**：技术可行性验证得差不多了（多模型、多工具都跑通过），但还没有
一份按优先级排过的路线图文档，也还没有真正意义上的隔离沙盒环境——
之前测试 OpenClaw 集成时直接用了生产 agent（`openclaw-business-analysis`），
这一点在 harness 六原则之外、但同样值得记录。
