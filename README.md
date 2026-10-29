# NPC 对话实验室 · Agent_1

中文游戏 NPC Agent：**每个 NPC 保留独特思维链**，游戏世界背景可外接，聊天模型可换成任意 OpenAI 兼容提供商（DeepSeek、Kimi、ChatGPT、Grok、GLM、Claude 网关、通义千问等）。

版本 **0.4.0**。Python 3.11+，建议 3.12。

- 中文文档：[NPC 认知与世界包](docs/NPC_COGNITION.md) · [多模型接入](docs/PROVIDERS.md) · [重构说明](docs/REFACTOR.md)
- English: [README.en.md](README.en.md) · [docs/NPC_COGNITION.en.md](docs/NPC_COGNITION.en.md) · [docs/PROVIDERS.en.md](docs/PROVIDERS.en.md)

## 设计要点

| 层 | 可否外接 | 说明 |
| --- | --- | --- |
| NPC 档案 | 是 | 姓名、性格、职业、区域、`thinking_order`、决策权重 |
| 游戏世界包 | 是 | 王者峡谷 / 提瓦特 / 方块世界 / 大世界等设定框 + 知识目录 |
| 认知引擎 | **否（内核）** | 六阶段决策；换皮不换思维链 |
| 聊天模型 | 是 | OpenAI 兼容 Chat Completions + 工具调用 |
| 演示任务库 | 演示级 | 本地 SQLite；真实玩法需宿主替换领域服务 |

默认 **demo** 模式无需密钥。`live` 模式通过 `GAME_NPC_PROVIDER` 选择提供商。

## 安装与启动

```bash
cd Agent_1
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ui,pdf]"
game-npc --state-dir .runtime ingest
game-npc --state-dir .runtime ui
```

界面默认 `127.0.0.1:8501`。也可 `streamlit run app.py`。

## 多模型在线模式

```bash
python -m pip install -e ".[ui,live,pdf]"
export GAME_NPC_MODE=live
export GAME_NPC_PROVIDER=deepseek          # 或 kimi / openai / grok / glm / openrouter / claude / qwen
export GAME_NPC_API_KEY="你的密钥"
game-npc providers                         # 查看预设
game-npc --state-dir .runtime doctor
game-npc --state-dir .runtime ui
```

| 变量 | 用途 |
| --- | --- |
| `GAME_NPC_PROVIDER` | `qwen`（默认）/ `deepseek` / `kimi` / `openai` / `grok` / `glm` / `openrouter` / `claude` / `custom` |
| `GAME_NPC_API_KEY` | 统一密钥（优先） |
| `GAME_NPC_MODEL` / `GAME_NPC_BASE_URL` | 可选覆盖预设 |
| `DASHSCOPE_API_KEY` 等 | 各厂商专用密钥仍可用作回退 |

Claude 通过 OpenRouter 等 **OpenAI 兼容网关**接入，不走 Anthropic 原生 Messages API。细节见 [docs/PROVIDERS.md](docs/PROVIDERS.md)。

## 游戏世界包（换背景，不换思维链）

内置演示框（原创骨架，非官方文案）：

| 世界 ID | 设定名 | 示例 NPC |
| --- | --- | --- |
| `honor_of_kings` | 王者峡谷风格地图 | 中路小兵 |
| `genshin` | 提瓦特风格大陆 | 街头商贩 |
| `minecraft` | 方块大陆与村庄 | 村庄商人 |
| `open_world` | 无主大世界边境 | 驿站掮客 |
| `demo_valley` | 溪谷村 | 使用默认三角色 |

```bash
game-npc world --list
game-npc --world-pack src/game_npc/assets/worlds/genshin --use-world-npc \
  --state-dir .runtime ingest
game-npc --world-pack src/game_npc/assets/worlds/genshin --use-world-npc \
  --state-dir .runtime chat "你是谁" --explain
```

宿主可把已获授权或自写的资料放入世界包 `knowledge/` 后 `ingest`。**程序不会自动爬网页**；网页内容需宿主自行下载、审阅后导入。

## 任务演示

- 玩家 `1001` / `1002` 状态独立。
- `T001` 采集：演示事件采集三次 → `交付 T001` → `领取 T001 奖励`。
- `T002` 可直接领奖，重复领取幂等。
- 进度只接受可信游戏事件；模型工具不能改进度或冒充其他玩家。

## 结构

```text
src/game_npc/
  providers.py    多模型预设
  world.py        游戏世界包
  persona.py      NPC 档案与实时情境
  cognition.py    独特思维链 / 六阶段决策
  agent.py        对话编排
  config.py       环境配置
  assets/worlds/  内置世界框与示例 NPC
docs/             中英文说明
```

## 开发

```bash
uv sync --locked --python 3.12 --extra ui --extra live --extra pdf --extra dev
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync ruff check src tests app.py
```
