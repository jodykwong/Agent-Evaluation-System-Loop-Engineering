"""
把 eval/runner/trace_store/ 下的真实运行记录注入到 dashboard 的 index.html 里，
替换掉 "真实运行记录" 表格用的 REAL_RUNS 数组。这是个纯粹的静态站点生成脚本——
不需要跑 web server，也不需要浏览器读本地文件（Artifact 页面的 CSP 也不允许
那么做），每次有新的运行记录，重新跑一遍这个脚本、把生成的 index.html
重新发布/打开就行。

用法：
    python eval/dashboard/build.py
"""
import json
import re
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
TRACE_STORE_DIR = DASHBOARD_DIR.parent / "runner" / "trace_store"
INDEX_HTML = DASHBOARD_DIR / "index.html"

MARKER_RE = re.compile(
    r"/\*REAL_RUNS_JSON_START\*/.*?/\*REAL_RUNS_JSON_END\*/",
    re.DOTALL,
)


def load_runs() -> list[dict]:
    runs = []
    if not TRACE_STORE_DIR.exists():
        return runs
    for path in sorted(TRACE_STORE_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] 跳过读取失败的文件 {path.name}：{e}")
            continue
        runs.append(
            {
                "trial_id": data.get("trial_id"),
                "timestamp": data.get("timestamp"),
                "user_input": data.get("user_input", ""),
                "final_answer": data.get("final_answer", ""),
                "error": data.get("error"),
                "model": data.get("model", ""),
                "tools_used": data.get("tools_used", []),
                "latency_seconds": data.get("latency_seconds"),
                # 下面几个字段是老版本 trace 文件没有的（陆续加上的），
                # 用 .get 兜底默认值，不让老记录读取失败。
                "source": data.get("source"),
                "token_usage": data.get("token_usage") or {},
                "retry_count": data.get("retry_count", 0),
            }
        )
    return runs


def inject(runs: list[dict]) -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    payload = json.dumps(runs, ensure_ascii=False)
    replacement = f"/*REAL_RUNS_JSON_START*/{payload}/*REAL_RUNS_JSON_END*/"
    # 注意：repl 必须传函数，不能传字符串。真实回答里经常有 \n 这种被 JSON
    # 转义出来的反斜杠序列，re.sub 对字符串形式的 repl 会把反斜杠当成
    # 反向引用语法（\1、\n 等）去解析，导致注入内容被悄悄改坏、
    # 生成的 index.html 里出现语法错误的 JS。传函数就不会有这个问题，
    # 因为 re 只对字符串 repl 做反斜杠模板展开。
    new_html, count = MARKER_RE.subn(lambda _m: replacement, html)
    if count != 1:
        raise RuntimeError(
            f"期望在 index.html 里找到 1 处 REAL_RUNS_JSON 标记，实际找到 {count} 处——"
            "可能是 index.html 结构被改动过，检查一下标记还在不在。"
        )
    INDEX_HTML.write_text(new_html, encoding="utf-8")


def main() -> None:
    runs = load_runs()
    inject(runs)
    print(f"已把 {len(runs)} 条真实运行记录写入 {INDEX_HTML}")


if __name__ == "__main__":
    main()
