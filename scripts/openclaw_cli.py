"""
OpenClaw skill 的调用入口 —— 给 OpenClaw agent 通过 exec 工具调用的 CLI 包装。

默认输入输出都是纯文本：传入用户的问题作为位置参数，输出最终回答到 stdout。
加 --json 则输出完整的结构化结果（含 messages、trace_events），方便以后需要
把这次调用记录下来做评估时用。

用法：
    python scripts/openclaw_cli.py "帮我查一下今天的天气"
    python scripts/openclaw_cli.py "计算 37*428" --model openai:gpt-4.1
    python scripts/openclaw_cli.py "..." --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.core import run_agent


def main():
    parser = argparse.ArgumentParser(description="通过 CLI 调用咱们的通用 agent")
    parser.add_argument("message", help="用户的问题/指令")
    parser.add_argument(
        "--model", default=None, help="provider:model_name（如 openai:gpt-4.1），不传则用默认模型"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="输出完整结构化结果（含 trace），而不是只输出最终回答文本",
    )
    args = parser.parse_args()

    try:
        result = run_agent(args.message, model=args.model)
    except Exception as e:
        # exec 调用失败时把错误打到 stderr、返回非零退出码，
        # 让 OpenClaw agent 能感知到"调用失败"，而不是把报错内容当成正常回答转述给用户
        print(f"Agent 调用失败：{e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(
            json.dumps(
                {
                    "trial_id": result.trial_id,
                    "model": result.model,
                    "final_answer": result.final_answer,
                    "messages": result.messages,
                    "trace_events": result.trace_events,
                    "latency_seconds": result.latency_seconds,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(result.final_answer)


if __name__ == "__main__":
    main()
