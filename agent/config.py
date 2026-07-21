"""
全局配置：默认模型、环境变量加载。

换模型只需要改 DEFAULT_MODEL 这一行（provider:model 格式），agent 其余代码不用动。
支持的 provider 前缀取决于安装了哪些 langchain-<provider> 包，常见的有：
  - anthropic:claude-opus-4-8   （需要 ANTHROPIC_API_KEY，目前未配置）
  - openai:gpt-4.1              （需要 OPENAI_API_KEY，目前未配置）
  - google_genai:gemini-2.5-pro （需要 GOOGLE_API_KEY，目前未配置）
  - nvidia:meta/llama-3.1-8b-instruct （已验证可用，见 models.py 注释）
  - minimax:MiniMax-M3          （已验证可用；跟你在 OpenClaw 里配置的几个
                                  agent 用的是同一个模型，默认选它）

默认用 minimax:MiniMax-M3——这是目前唯一一个既有真实 key、又验证过真实
tool-calling、还跟你 OpenClaw 里现有 agent 保持一致的选择。等 Anthropic/
OpenAI 的 key 配上了，随时可以换回来。
"""
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "minimax:MiniMax-M3"
