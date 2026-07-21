"""
统一的模型层封装。

用 langchain 的 init_chat_model 做跨厂商模型初始化：模型字符串是
"provider:model_name" 的格式，切换底层模型提供商时只改这个字符串，
agent 的工具定义、middleware、调用方式完全不用变——这是实现"不锁定在
某一家模型"的关键点。

已验证过的 NVIDIA 模型（nvidia:<model_id>），供参考：
  - meta/llama-3.1-8b-instruct   —— 能正常走真实 tool-calling（不是把
    工具调用当文本回复），响应快（约2秒），推荐用这个测试 agent 的工具能力。
    但注意：这个模型只支持"一轮一个工具调用"，如果一句话里同时要求
    调两个工具（比如"算个数再搜个东西"），NVIDIA 那边会报 500
    "This model only supports single tool-calls at once"——把复合请求
    拆成单个工具的请求就没问题，agent 本身多轮调用不同工具是没问题的。
  - meta/llama-3.2-3b-instruct   —— 响应快，但不支持真正的 tool-calling，
    会把工具调用格式当成普通文本输出，不要用来测试需要调工具的场景
  - meta/llama-3.3-70b-instruct  —— 在免费/试用额度下持续超时（60-120秒
    都没返回），可能是这个模型在该配额层级下排队严重，暂不建议用
  - meta/llama3-70b-instruct（无版本号）—— 已废弃，NVIDIA 目前返回 404
完整模型列表可以调 GET https://integrate.api.nvidia.com/v1/models 查询。

特殊说明——MiniMax：init_chat_model 原生不认识 "minimax" 这个 provider，
但 MiniMax 提供了 OpenAI 兼容接口。这里用 "minimax:<model_name>" 的写法时
（比如 "minimax:MiniMax-M3"），内部会转换成走 openai provider + 自定义
base_url 的方式，调用方不需要关心这个细节，跟其他 provider 用法保持一致。
需要配置 MINIMAX_API_KEY。

⚠️ 注意国内站/国际站是两个完全不同的账号体系，key 不能混用：
  - 国内站（minimaxi.com 账号）：https://api.minimaxi.com/v1
  - 国际站（minimax.io 账号）：   https://api.minimax.io/v1
用错 base_url 会报 401 "invalid api key (2049)"，看起来像 key 错了，
其实是 key 对应的账号体系跟请求打的域名不匹配。这里默认按国内站
（minimaxi.com）配置，如果你用的是国际站账号，把下面的 MINIMAX_BASE_URL
换成 minimax.io 那个即可。

已验证——minimax:MiniMax-M3：真实 tool-calling 正常工作（结构化 tool_call，
不是文本模仿），响应约2-8秒。这个模型会把推理过程内联写成 <think>...</think>
标签混在正文里，而不是走独立的 thinking 字段——core.run_agent() 已经在
final_answer 里自动去掉这部分，只保留真正的回答；如果需要看完整推理过程
排查问题，去 messages/trace_events 里看原始内容（没有被过滤）。
"""
import os

from langchain.chat_models import init_chat_model

from agent.config import DEFAULT_MODEL

MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"  # 国内站；国际站换成 api.minimax.io/v1


def get_model(model: str | None = None, **kwargs):
    """
    Args:
        model: "provider:model_name" 格式的字符串，例如 "openai:gpt-4.1"、
               "nvidia:meta/llama3-70b-instruct"、"minimax:MiniMax-M3"。
               不传则使用 config.DEFAULT_MODEL。
        **kwargs: 透传给 init_chat_model 的其他参数（如 temperature）。
    """
    model = model or DEFAULT_MODEL

    if model.startswith("minimax:"):
        model_name = model.split(":", 1)[1]
        return init_chat_model(
            model_name,
            model_provider="openai",
            base_url=MINIMAX_BASE_URL,
            api_key=os.environ.get("MINIMAX_API_KEY"),
            **kwargs,
        )

    return init_chat_model(model, **kwargs)
