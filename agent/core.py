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
# 纯文本关键词用子串匹配即可；HTTP 状态码单独用词边界匹配，避免裸子串
# "500" 命中 "1500"/"15000ms" 这类无关数字导致误判为瞬时故障。
_TRANSIENT_TEXT_MARKERS = (
    "timeout", "timed out", "rate_limit", "rate limit", "too many requests",
    "connection", "temporarily unavailable", "overloaded",
)
_TRANSIENT_STATUS_RE = re.compile(r"\b(?:429|500|502|503|504)\b")


def _is_transient_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _TRANSIENT_TEXT_MARKERS):
        return True
    return bool(_TRANSIENT_STATUS_RE.search(text))


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


def _normalize_content(content: Any) -> str:
    """把不同 provider 的 message.content 归一化成纯文本字符串。

    OpenAI / MiniMax 返回的是 str；但 Anthropic 等在带 thinking / tool_use
    块时，content 是内容块列表（list[dict]），直接对 list 做正则会抛
    TypeError。项目的卖点就是"改一个配置字符串就能换厂商"，所以这里必须
    兼容 list 形态，把其中的文本块拼起来，保证换到 Anthropic 时最终答案
    提取不会崩。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content) if content is not None else ""


def _strip_thinking(text: Any) -> str:
    """有些模型（比如 MiniMax-M3、DeepSeek 系列）把推理过程内联在 <think>
    标签里，而不是走独立的结构化 thinking 字段。这里把这部分从最终展示
    给用户的回答里去掉，只保留真正的答案；完整内容（含 think 标签）
    还是原样保留在 messages/trace 里，方便调试。"""
    return _THINK_TAG_RE.sub("", _normalize_content(text)).strip()


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
    except Exception as e:
        # 落盘失败绝不能影响本次调用结果。这里兜底 Exception 而不只是 OSError：
        # json.dump 遇到不可序列化的 message content / tool_calls 会抛 TypeError，
        # 而 _persist_result 是在 run_agent 的 finally 里调的——如果这个 TypeError
        # 逃出去，在错误路径上会顶替掉正在向上传播的真实异常，让调用方看到
        # 一个跟根因无关的报错。所以这里全部吞掉、只打日志。
        print(f"[warn] trace 落盘失败（不影响本次调用结果）：{e}")


def _next_invoke_input(agent, config: dict, user_input: str) -> dict:
    """决定这一次 invoke 往图里塞什么消息，避免重试时把用户输入重复追加到
    带记忆的 checkpointer 线程上。

    带 checkpointer 时 LangGraph 会逐步把图状态落盘：如果上一次 invoke 在
    "用户消息已写入、但模型那步失败"的位置抛错，这条用户消息其实已经留在
    thread 里了。此时若重试再传一遍 user_input，同一条用户消息就会在线程里
    出现两次，污染后续调用读到的对话历史。

    这里先看线程当前状态的最后一条消息：如果它正好是我们要发的这条用户
    消息（说明上次失败前已写入），就传空 messages 让图基于已有状态继续
    （resume），不重复追加；否则正常把用户消息塞进去。首次调用、以及上次
    在写入用户消息之前就失败的情况，都会落到"正常塞入"这一支，不会漏掉输入。"""
    try:
        snapshot = agent.get_state(config)
        existing = list(snapshot.values.get("messages", [])) if snapshot else []
    except Exception:
        # 拿不到状态（比如没挂 checkpointer）时，退化成一律塞入用户消息，
        # 这也是无记忆场景下本来就正确的行为。
        existing = []
    if existing:
        last = existing[-1]
        if getattr(last, "type", "") == "human" and getattr(last, "content", None) == user_input:
            return {"messages": []}
    return {"messages": [{"role": "user", "content": user_input}]}


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
        session_id: 可选，跨调用的对话记忆用哪个 thread_id 延续。
                    不传时：认得出的 OpenClaw 来源用 source 当 thread_id，
                    同一个 agent 的连续调用会自动记得之前说过什么；认不出的
                    "本地直接调用"则每次用独立线程（不串记忆），避免所有匿名
                    本地调用挤进同一条无限增长的记忆线程。需要在本地也延续
                    记忆、或在某个来源下开一个全新对话时，显式传 session_id 即可。
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
    # 记忆线程的选取：
    #   - 显式传了 session_id：完全听调用方的。
    #   - 认得出的 OpenClaw 来源：用 source 当 thread_id，让同一个 agent 的
    #     连续调用自然延续上下文。
    #   - 认不出的"本地直接调用"：每次用独立线程。否则所有匿名本地调用
    #     （smoke_test、随手试的无关问题……）会挤进同一条永远增长、还会
    #     互相串味的记忆线程，长对话又没有裁剪，早晚撑爆上下文。需要本地
    #     也延续记忆时，显式传 session_id 即可。
    if session_id:
        thread_id = session_id
    elif source == "本地直接调用":
        thread_id = f"local:{trial_id}"
    else:
        thread_id = source

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
                        _next_invoke_input(agent, invoke_config, user_input),
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
