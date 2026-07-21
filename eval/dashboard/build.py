"""
把真实数据注入 dashboard 的 index.html —— 这是个纯静态站点生成脚本，
不需要 web server，也不需要浏览器读本地文件（Artifact 页面的 CSP 也不允许
那么做）。每次有新数据，重新跑一遍这个脚本、把生成的 index.html
重新发布/打开就行。

注入两类**真实**数据，各自对应 index.html 里的一对注释标记：

1. REAL_RUNS —— 扫描 eval/runner/trace_store/ 下的真实运行记录，喂给
   "真实运行记录"表格和调用侧的延迟/token/成功率/工具/来源图表。

2. HARNESS_DIMS —— 解析 eval/harness-checklist.md，把"AI 系統工程六項
   設計原則"（上下文管理/工具调用/执行编排/状态与记忆/评估与观测/
   约束与恢复）每一条的达成度（已勾选项 / 总项）算出来，喂给"六维
   harness 原则达成度"雷达图。六维评测的本意就是核对 agent 有没有按
   这六项原则落地，checklist 里的 [x]/[ ] 就是它的真实数据源。

用法：
    python eval/dashboard/build.py
"""
import json
import re
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASHBOARD_DIR.parent.parent
TRACE_STORE_DIR = DASHBOARD_DIR.parent / "runner" / "trace_store"
HARNESS_CHECKLIST = DASHBOARD_DIR.parent / "harness-checklist.md"
AGENT_CONFIG = REPO_ROOT / "agent" / "config.py"
INDEX_HTML = DASHBOARD_DIR / "index.html"

REAL_RUNS_RE = re.compile(
    r"/\*REAL_RUNS_JSON_START\*/.*?/\*REAL_RUNS_JSON_END\*/",
    re.DOTALL,
)
HARNESS_RE = re.compile(
    r"/\*HARNESS_DIMS_JSON_START\*/.*?/\*HARNESS_DIMS_JSON_END\*/",
    re.DOTALL,
)
AGENT_INFO_RE = re.compile(
    r"/\*AGENT_INFO_JSON_START\*/.*?/\*AGENT_INFO_JSON_END\*/",
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


# 解析 harness-checklist.md 里的六项设计原则 -----------------------------------
_HEAD_RE = re.compile(r"^##\s+([①②③④⑤⑥])\s+(.+?)\s*$")
_ITEM_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s*(.+?)\s*$")
_NAME_SPLIT_RE = re.compile(r"^([^\x00-\x7f].*?)\s+([A-Za-z].*)$")


def _clean(s: str) -> str:
    """去掉 markdown 的反引号/加粗标记，便于在页面上直接当纯文本显示。"""
    return re.sub(r"[`*]", "", s).strip()


def load_harness_dims() -> list[dict]:
    """把六项设计原则解析成结构化的达成度数据。

    每一维产出：编号、中文名、英文名、一句话定义（来自 > 引用行）、
    已完成项数 done、总项数 total、逐条 items（含完成状态和简短描述）。
    只统计以 `- [x]` / `- [ ]` 开头的条目；碰到非六原则的二级标题
    （比如"五阶段推进路径对照"）就停止归集，避免把无关内容算进最后一维。
    """
    dims: list[dict] = []
    if not HARNESS_CHECKLIST.exists():
        print(f"[warn] 找不到 {HARNESS_CHECKLIST}，六维雷达图将为空")
        return dims

    cur: dict | None = None
    for line in HARNESS_CHECKLIST.read_text(encoding="utf-8").splitlines():
        mh = _HEAD_RE.match(line)
        if mh:
            if cur:
                dims.append(cur)
            title = mh.group(2).strip()
            m2 = _NAME_SPLIT_RE.match(title)
            name, en = (m2.group(1).strip(), m2.group(2).strip()) if m2 else (title, "")
            cur = {"id": mh.group(1), "name": name, "en": en,
                   "definition": "", "done": 0, "total": 0, "items": []}
            continue
        if line.startswith("## "):
            # 非六原则的二级标题 —— 停止归集
            if cur:
                dims.append(cur)
                cur = None
            continue
        if cur is None:
            continue
        mq = _QUOTE_RE.match(line)
        if mq and not cur["definition"]:
            cur["definition"] = _clean(mq.group(1))
            continue
        mi = _ITEM_RE.match(line)
        if mi:
            done = mi.group(1).lower() == "x"
            cur["total"] += 1
            if done:
                cur["done"] += 1
            cur["items"].append({"done": done, "text": _clean(mi.group(2))[:90]})
    if cur:
        dims.append(cur)
    return dims


# 解析"当前评估对象" ---------------------------------------------------------
_DEFAULT_MODEL_RE = re.compile(r'^DEFAULT_MODEL\s*=\s*["\']([^"\']+)["\']', re.M)


def _parse_source(s: str | None) -> dict:
    """把 trace 的 source 字段拆成 平台 + agent 名 + 展示标签。

    core.resolve_source 产出的格式：
      - "openclaw:openclaw-business-analysis" → 平台 openclaw，agent 名就是冒号后半段
      - "本地直接调用"                          → 本地开发自测，无平台
    """
    if not s or s == "本地直接调用":
        return {"source": "本地直接调用", "platform": "local",
                "agent": "本地直接调用", "label": "本地直接调用"}
    if ":" in s:
        platform, agent = s.split(":", 1)
        return {"source": s, "platform": platform, "agent": agent, "label": agent}
    return {"source": s, "platform": "", "agent": s, "label": s}


def load_agent_info(runs: list[dict]) -> dict:
    """汇总"这个看板当前评估的是哪个 agent"。

    agent 的定义性特征就是它跑在哪个模型上（整个项目的卖点是跨模型通用），
    所以这里取 agent/config.py 里的 DEFAULT_MODEL 作为"默认模型"，再从真实
    运行记录里统计这批样本实际涉及了哪些模型（trace 里的 "default" 表示调用
    时没显式指定、走的就是 DEFAULT_MODEL，这里解析回真实模型名）。
    """
    default_model = ""
    if AGENT_CONFIG.exists():
        m = _DEFAULT_MODEL_RE.search(AGENT_CONFIG.read_text(encoding="utf-8"))
        if m:
            default_model = m.group(1)

    seen: list[str] = []
    for r in runs:
        mdl = (r.get("model") or "").strip()
        eff = default_model if mdl in ("", "default") else mdl
        if eff and eff not in seen:
            seen.append(eff)

    # 统计这个看板到底在评测"谁的" agent —— 来源就是 trace 里的 source
    # 字段（core.resolve_source 反推出来的：openclaw:<agent名> / 本地直接调用）。
    counts: dict[str, int] = {}
    for r in runs:
        s = r.get("source") or "本地直接调用"
        counts[s] = counts.get(s, 0) + 1
    sources = [dict(count=c, **_parse_source(s))
               for s, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    # 主评测对象：优先取真实平台 agent（非"本地直接调用"）里调用最多的那个；
    # 全是本地调用时才回退到"本地直接调用"。本地调用通常是开发自测，真正
    # 想在看板上标出来的是那个挂在平台上、被真实触发的 agent。
    def _is_local(s: str) -> bool:
        return s == "本地直接调用"
    primary_src = min(
        counts.items(),
        key=lambda kv: (_is_local(kv[0]), -kv[1]),
        default=(None, 0),
    )[0]
    primary = dict(count=counts.get(primary_src, 0), **_parse_source(primary_src)) if primary_src else None

    last_run = max((r.get("timestamp") or "" for r in runs), default="")
    return {
        "default_model": default_model,
        "models_seen": seen,
        "run_count": len(runs),
        "last_run": last_run,
        "sources": sources,
        "source_count": len(counts),
        "primary": primary,
    }


def _inject(html: str, marker_re: re.Pattern, start: str, end: str,
            payload: str, label: str) -> str:
    replacement = f"{start}{payload}{end}"
    # repl 必须传函数，不能传字符串：真实内容里经常有 \n 这类被 JSON 转义出来
    # 的反斜杠序列，re.sub 对字符串形式的 repl 会把反斜杠当反向引用（\1、\n）
    # 解析，导致注入内容被悄悄改坏。传函数就绕过了模板展开。
    new_html, count = marker_re.subn(lambda _m: replacement, html)
    if count != 1:
        raise RuntimeError(
            f"期望在 index.html 里找到 1 处 {label} 标记，实际找到 {count} 处——"
            "可能是 index.html 结构被改动过，检查一下标记还在不在。"
        )
    return new_html


def main() -> None:
    runs = load_runs()
    dims = load_harness_dims()
    agent_info = load_agent_info(runs)

    html = INDEX_HTML.read_text(encoding="utf-8")
    html = _inject(
        html, REAL_RUNS_RE,
        "/*REAL_RUNS_JSON_START*/", "/*REAL_RUNS_JSON_END*/",
        json.dumps(runs, ensure_ascii=False), "REAL_RUNS_JSON",
    )
    html = _inject(
        html, HARNESS_RE,
        "/*HARNESS_DIMS_JSON_START*/", "/*HARNESS_DIMS_JSON_END*/",
        json.dumps(dims, ensure_ascii=False), "HARNESS_DIMS_JSON",
    )
    html = _inject(
        html, AGENT_INFO_RE,
        "/*AGENT_INFO_JSON_START*/", "/*AGENT_INFO_JSON_END*/",
        json.dumps(agent_info, ensure_ascii=False), "AGENT_INFO_JSON",
    )
    INDEX_HTML.write_text(html, encoding="utf-8")

    done = sum(d["done"] for d in dims)
    total = sum(d["total"] for d in dims)
    print(f"已注入 {len(runs)} 条真实运行记录；"
          f"六维原则达成度 {done}/{total} 项（{len(dims)} 维）；"
          f"评估对象默认模型 {agent_info.get('default_model') or '（未解析到）'} → {INDEX_HTML}")


if __name__ == "__main__":
    main()
