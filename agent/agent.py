"""
Agent 组装：把模型、四个工具、tracing middleware 拼成一个可运行的 agent。

模型层已经通过 models.get_model() 做到跨厂商无关；工具都是 LangChain
的标准 tool，create_agent 会自动把它们翻译成不同厂商各自的
function-calling 格式，这里不需要关心 Anthropic 的 tool_use 和 OpenAI
的 tool_calls 之间的差异。
"""
from langchain.agents import create_agent

from agent.models import get_model
from agent.tools.web_search import get_web_search_tool
from agent.tools.code_exec import execute_python_code
from agent.tools.internal_retrieval import search_internal_knowledge_base
from agent.tools.third_party_api import call_third_party_api
from agent.middleware.tracing import TracingMiddleware

DEFAULT_SYSTEM_PROMPT = """你是一个通用助手 agent，具备以下能力：
1. 网络搜索：获取最新的公开信息
2. 代码执行：在隔离沙箱中运行 Python 代码，用于计算、数据处理
3. 内部知识库检索：查找公司内部文档和专有数据
4. 第三方业务 API：调用外部业务系统完成具体操作

根据用户的问题判断需要用到哪些工具，按需一步步完成任务；不确定的
信息不要凭空编造，能用工具核实就用工具核实。"""


def build_agent(model: str | None = None, system_prompt: str | None = None, checkpointer=None):
    """
    构建一个 agent 实例。

    Args:
        checkpointer: 可选，LangGraph 的 checkpointer 实例（比如
            core.py 里用的 SqliteSaver）。传了之后 agent 在 .invoke()
            时配合 config={"configurable": {"thread_id": ...}} 就有了
            跨调用的对话记忆——这是 harness 六原则里"状态与记忆"这一条
            的具体实现，见 eval/harness-checklist.md。不传的话每次调用
            还是无状态的（等价于旧行为）。

    Returns:
        (agent, tracing): agent 是可以直接 .invoke()/.stream() 的
        CompiledStateGraph；tracing 是这次构建挂载的 TracingMiddleware
        实例，用于运行结束后取出完整 trace。
    """
    llm = get_model(model)
    tracing = TracingMiddleware()

    tools = [
        get_web_search_tool(),
        execute_python_code,
        search_internal_knowledge_base,
        call_third_party_api,
    ]

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
        middleware=[tracing],
        checkpointer=checkpointer,
    )
    return agent, tracing
