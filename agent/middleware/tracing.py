"""
Trace 采集 middleware —— 给后续的评估系统（eval/）提供可追溯的运行记录。

利用 LangChain create_agent 的 before_model / after_model 钩子，在每次
模型调用前后记录时间戳、消息数、耗时、token 用量。跑完一次 agent 后，
通过 tracing.events / tracing.total_tokens 拿到完整的事件列表和聚合的
token 消耗，交给 core.run_agent() 统一落盘——这既是评估系统 Phase 1
要求的"每次运行必须落盘可追溯的 trace"，也是 harness engineering 里
"context" 这一项（上下文/token 用量有没有失控）目前唯一的可观测数据源。
"""
import time
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langgraph.runtime import Runtime


class TracingMiddleware(AgentMiddleware):
    def __init__(self):
        super().__init__()
        self.events: list[dict[str, Any]] = []
        self._call_start_ts: float | None = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        self._call_start_ts = time.time()
        self.events.append(
            {
                "type": "before_model",
                "timestamp": self._call_start_ts,
                "message_count": len(state["messages"]),
            }
        )
        return None

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        now = time.time()
        latency = now - self._call_start_ts if self._call_start_ts else None
        last_message = state["messages"][-1]

        # 不是所有模型/provider 都会填充 usage_metadata（比如某些走 OpenAI
        # 兼容层的第三方 provider 可能缺字段），拿不到就跳过，不让 trace
        # 采集本身成为一个新的失败点。
        usage = getattr(last_message, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if isinstance(input_tokens, int):
            self.total_input_tokens += input_tokens
        if isinstance(output_tokens, int):
            self.total_output_tokens += output_tokens
        if isinstance(usage.get("total_tokens"), int):
            self.total_tokens += usage["total_tokens"]

        self.events.append(
            {
                "type": "after_model",
                "timestamp": now,
                "latency_seconds": latency,
                "message_type": last_message.__class__.__name__,
                "content_preview": str(getattr(last_message, "content", ""))[:500],
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": usage.get("total_tokens"),
                    "cache_read": (usage.get("input_token_details") or {}).get("cache_read"),
                },
            }
        )
        return None

    def reset(self) -> None:
        """复用同一个 agent 实例做多次独立运行前，先清空上一次的 trace。"""
        self.events = []
        self._call_start_ts = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0
