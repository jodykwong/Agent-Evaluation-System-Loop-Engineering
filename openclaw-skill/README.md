# 接入 OpenClaw 的方式

这个文件夹是要挂到 OpenClaw 的 skills 目录下的，OpenClaw 本身不需要知道
咱们 agent 项目的内部实现，只需要能找到这个 `SKILL.md` 和 `scripts/run.sh`。

## 安装（软链，已完成）

```bash
ln -s "/Users/jodykwong/Documents/Claude Code/test/openclaw-skill" \
      ~/.openclaw/skills/our-general-agent
```

注意路径是 `~/.openclaw/skills/`（共享/managed 目录，所有 agent 都能看到），
不是 `~/.openclaw/workspace/skills/`（那个只对 "main" 这一个 agent 生效，
因为 main 的 workspace 恰好就是顶层的 `~/.openclaw/workspace`）。
用软链而不是复制，之后改 SKILL.md 或者 run.sh 不用重新同步。

## 验证

先手动跑一遍，确认脚本本身没问题（这一步不依赖 OpenClaw）：

```bash
"/Users/jodykwong/Documents/Claude Code/test/openclaw-skill/scripts/run.sh" "帮我算一下 12*8 是多少"
```

正常应该会调用代码执行工具，最后输出一句包含 96 的回答。

再确认 OpenClaw 那边加载到了这个技能——按 OpenClaw 文档，默认会自动
监听 skills 目录下的 SKILL.md 变化；如果没生效，开一个新的 session 让
它重新读取技能列表。之后可以用类似 `openclaw agent --message "..."`
的方式在 OpenClaw 里直接测试这个技能有没有被正确调用到。

## 已知限制

- `run.sh` 里的 `PROJECT_DIR` 是写死的绝对路径，多机器部署时要手动改。
- 这一版是同步调用——OpenClaw agent 等这个 exec 命令跑完才能拿到结果，
  如果咱们的 agent 单次调用比较慢（比如触发了好几轮工具调用），
  OpenClaw 那边等待时间会比较长，注意超时设置。
