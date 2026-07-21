"""
最小可运行验证：跑通一次 agent 对话，确认四个能力（模型、搜索、代码
执行、trace 采集）都能正常工作。

用法：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --model openai:gpt-4.1   # 换模型跑同一个问题
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.core import run_agent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="provider:model_name，例如 openai:gpt-4.1")
    parser.add_argument(
        "--question",
        default="现在几点了不重要，但请帮我计算 37 * 428 的结果，并搜索一下今天有什么值得关注的科技新闻标题（一条就行）。",
        help="测试用的输入，默认会同时触发代码执行和网络搜索两个工具",
    )
    args = parser.parse_args()

    result = run_agent(args.question, model=args.model)

    print("=" * 60)
    print(f"trial_id: {result.trial_id}")
    print(f"model: {result.model}")
    print(f"latency: {result.latency_seconds:.2f}s")
    print("=" * 60)
    print("最终回答：")
    print(result.final_answer)
    print("=" * 60)
    print(f"trace 事件数：{len(result.trace_events)}")
    print(f"消息数：{len(result.messages)}")

    out_path = Path(__file__).resolve().parent / f"smoke_test_trace_{result.trial_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "trial_id": result.trial_id,
                "model": result.model,
                "user_input": result.user_input,
                "final_answer": result.final_answer,
                "messages": result.messages,
                "trace_events": result.trace_events,
                "latency_seconds": result.latency_seconds,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"完整 trace 已保存到：{out_path}")


if __name__ == "__main__":
    main()
