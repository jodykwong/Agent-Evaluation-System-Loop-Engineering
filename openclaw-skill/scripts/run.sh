#!/usr/bin/env bash
set -euo pipefail

# 指向我们自己的 agent 项目目录。
# 如果这个 skill 文件夹被复制/软链到另一台机器，记得改成那台机器上的实际路径。
PROJECT_DIR="/Users/jodykwong/Documents/Claude Code/test"

# 在 cd 之前先记下调用方是从哪个目录发起的——OpenClaw 的 exec 工具默认在
# 触发这次调用的那个 agent 的 workspace 目录下执行命令（比如
# ~/.openclaw/workspace/openclaw-business-analysis），所以这个原始 $PWD
# 能反推出"是哪个 agent 调用的"，写进真实运行记录的"来源"字段里。
export CALLER_CWD="$PWD"

cd "$PROJECT_DIR"
source .venv/bin/activate
python scripts/openclaw_cli.py "$@"
