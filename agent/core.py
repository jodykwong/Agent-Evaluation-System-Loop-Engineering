"""
项目唯一入口：run_agent()。

这是整个项目对外暴露的唯一函数——后续搭建的 eval/runner 只需要调用
这一个函数（可以指定不同的 model 字符串来跑不同模型的对比评测，
可以传 trial_id 来支持同一条 case 的多次独立重跑），不需要了解 agent
内部是怎么组装的。

每次调用默认会把结果落盘到 eval/runner/trace_store/ 下——不管是本地
手动跑、smoke_test.py 跑，还是 OpenClaw 那边真实触发的调用，都会留下
一条记录。这是"数据飞轮"和评估看板"真实运行记录"的数据来源；
不想留痕迹的场景（比如反复调参数试错）可以传 persist=False 跳过落盘。
"""
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from agent.agent import build_agent

TRACE_STORE_DIR = Path(__file__).resolve().parent.parent / "eval" / "runner" / "trace_store"
MEMORY_DB_PATH = Path(__file__).resolve().parent.parent / "eval" / "runner" / "conversation_memory.sqlite"

# 判断一次失败是不是"瞬时故障"（网络抖动、限流、对方服务临时不可用），
# 值得原地重试；跟"key 错了""参数不对"这种重试也没用的错误区分开。
# 多厂商环境下每家 SDK 抛的异常类型都不一样（openai 的 RateLimitError、
# requests 的 ReadTimeout、httpx 的 ConnectError……），与其挨个 import
# 每家的异常类型，不如直接从错误信息里找关键词，简单但覆盖面更广。
_TRANSIENT_ERROR_MARKERS = (
    "429", "500", "502", "503", "504",
    "timeout", "timed out", "rate_limit", "rate limit",
    "connection", "temporarily unavailable", "overloaded",
)


def _is_transient_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


def resolve_source(caller_cwd: str | None) -> str:
    """
    把调用方传进来的原始工作目录，翻译成一个人能看懂的"这是谁调的我"标签。

    OpenClaw 的 exec 工具默认在触发这次调用的那个 agent 的 workspace 目录
    下执行命令（每个 agent 有自己的 workspace，比如
    ~/.openclaw/workspace/openclaw-business-analysis）——run.sh 在 cd 到
    咱们项目目录之前会先把这个原始 $PWD 存下来传进来，这里再从路径里
    反推出 agent 名字。直接手动跑脚本、没经过 OpenClaw 时，caller_cwd
    就是你自己终端的路径，认不出 openclaw workspace 特征，归类成"本地直接调用"。
    """
    if not caller_cwd:
        return "本地直接调用"
    marker = "/.openclaw/workspace"
    idx = caller_cwd.find(marker)
    if idx == -1:
        return "本地直接调用"
    remainder = caller_cwd[idx + len(marker):].strip("/")
    if not remainder:
        return "openclaw:main"
    agent_name = remainder.split("/")[0]
    return f"openclaw:{agent_name}"

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """有些模型（比如 MiniMax-M3、DeepSeek 系列）把推理过程内联在 <think>
    标签里，而不是走独立的结构化 thinking 字段。这里把这部分从最终展示
    给用户的回答里去掉，只保留真正的答案；完整内容（含 think 标签）
    还是原样保留在 messages/trace 里，方便调试。"""
    return _THINK_TAG_RE.sub("", text).strip()


@dataclass
class AgentResult:
    trial_id: str
    user_input: str
    model: str
    final_answer: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    trace_events: list[dict[str, Any]] = field(default_factory=list)
    latency_seconds: float = 0.0
    timestamp: str = ""
    error: str | None = None
    source: str = "本地直接调用"
    token_usage: dict[str, int] = field(default_factory=dict)
    retry_count: int = 0


def _extract_tool_names(messages: list[dict[str, Any]]) -> list[str]:
    """从消息历史里提取这一轮实际调用过的工具名，去重但保留顺序。"""
    seen: list[str] = []
    for m in messages:
        for call in m.get("tool_calls") or []:
            name = call.get("name")
            if name and name not in seen:
                seen.append(name)
    return seen


def _persist_result(result: AgentResult) -> None:
    """落盘到 eval/runner/trace_store/，文件名按时间排序方便后续按时间轴读取。
    落盘失败不应该影响正常的 agent 调用结果，所以这里只吞异常、不往上抛。"""
    try:
        TRACE_STORE_DIR.mkdir(parents=True, exist_ok=True)
        safe_ts = result.timestamp.replace(":", "").replace("+00:00", "Z")
        path = TRACE_STORE_DIR / f"{safe_ts}_{result.trial_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "trial_id": result.trial_id,
                    "timestamp": result.timestamp,
                    "user_input": result.user_input,
                    "model": result.model,
                    "final_answer": result.final_answer,
                    "messages": result.messages,
                    "trace_events": result.trace_events,
                    "latency_seconds": result.latency_seconds,
                    "error": result.error,
                    "tools_used": _extract_tool_names(result.messages),
                    "source": result.source,
                    "token_usage": result.token_usage,
                    "retry_count": result.retry_count,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as e:
        print(f"[warn] trace 落盘失败（不影响本次调用结果）：{e}")


def run_agent(
    user_input: str,
    model: str | None = None,
    trial_id: str | None = None,
    persist: bool = True,
    caller_cwd: str | None = None,
    session_id: str | None = None,
    max_retries: int = 2,
) -> AgentResult:
    """
    运行一次 agent 对话。

    Args:
        user_input: 用户的输入
        model: 可选，"provider:model_name" 格式（如 "openai:gpt-4.1"），
               不传则用 agent.config.DEFAULT_MODEL
        trial_id: 可选，试验编号；评估系统做 pass@k 多次重跑同一条 case
                  时用来区分每一次独立运行
        persist: 是否把这次运行落盘到 eval/runner/trace_store/，默认落盘。
                 反复调参数试错、不想留痕迹时可以传 False。
        caller_cwd: 可选，调用方（比如 openclaw-skill/scripts/run.sh）
                    在 cd 到本项目之前的原始工作目录，用来反推是本地直接
                    调用还是哪个 OpenClaw agent 触发的（见 resolve_source）。
                    不传的话会尝试读 CALLER_CWD 环境变量。
        session_id: 可选，跨调用的对话记忆用哪个 thread_id 延续。不传的话
                    默认用调用来源（source）当 thread_id——同一个 OpenClaw
                    agent 的连续调用会自动记得之前说过什么；同一个来源
                    下如果需要开一个全新的、不带历史的对话，显式传一个
                    新的 session_id 即可。
        max_retries: 遇到看起来像瞬时故障（网络超时、429、5xx）时的
                     重试次数，指数退避。不是瞬时故障（比如鉴权失败）
                     不会重试，直接抛出。

    Returns:
        AgentResult：包含最终回答、完整消息历史（含 tool 调用）、
        trace 事件、耗时、token 用量、调用来源——默认已经落盘到
        eval/runner/trace_store/ 下，评估看板的"真实运行记录"就是从这里读的。
    """
    trial_id = trial_id or str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    resolved_model = model or "default"
    source = resolve_source(caller_cwd or os.environ.get("CALLER_CWD"))
    thread_id = session_id or source

    MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    error: str | None = None
    retry_count = 0
    # 提前初始化 tracing——万一 build_agent() 都还没跑完就失败了，
    # finally 块里引用它也不会报 NameError。
    tracing = None
    try:
        with SqliteSaver.from_conn_string(str(MEMORY_DB_PATH)) as checkpointer:
            agent, tracing = build_agent(model=model, checkpointer=checkpointer)
            invoke_config = {"configurable": {"thread_id": thread_id}}

            attempt = 0
            while True:
                try:
                    result = agent.invoke(
                        {"messages": [{"role": "user", "content": user_input}]},
                        config=invoke_config,
                    )
                    break
                except Exception as e:
                    if attempt < max_retries and _is_transient_error(e):
                        retry_count += 1
                        time.sleep(2**attempt)  # 1s, 2s, 4s...
                        attempt += 1
                        tracing.reset()  # 重试前清空上一次失败尝试留下的 trace 事件
                        continue
                    raise

            messages = result["messages"]
            final_answer = _strip_thinking(messages[-1].content) if messages else ""
            serialized_messages = [
                {
                    "type": m.__class__.__name__,
                    "content": m.content,
                    "tool_calls": getattr(m, "tool_calls", None),
                }
                for m in messages
            ]
    except Exception as e:
        # 重试用完了还是失败（或者根本不是瞬时故障），也落盘记录下来——
        # 这本身就是评估系统关心的"可靠性"信号，不应该悄悄丢掉。
        error = str(e)
        final_answer = ""
        serialized_messages = []
        raise
    finally:
        latency = time.time() - start
        agent_result = AgentResult(
            trial_id=trial_id,
            user_input=user_input,
            model=resolved_model,
            final_answer=final_answer if error is None else "",
            messages=serialized_messages,
            trace_events=tracing.events if tracing else [],
            latency_seconds=latency,
            timestamp=timestamp,
            error=error,
            source=source,
            token_usage={
                "input_tokens": tracing.total_input_tokens if tracing else 0,
                "output_tokens": tracing.total_output_tokens if tracing else 0,
                "total_tokens": tracing.total_tokens if tracing else 0,
            },
        )
        agent_result.retry_count = retry_count
        if persist:
            _persist_result(agent_result)

    return agent_result
