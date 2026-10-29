# NPC Dialogue Lab · Agent_1

A game NPC agent where **each NPC keeps a unique cognition chain**, game settings are swappable world packs, and chat models are any OpenAI-compatible provider (DeepSeek, Kimi, ChatGPT, Grok, GLM, Claude via gateway, Qwen, and custom endpoints).

Version **0.4.0**. Python 3.11+ (3.12 recommended).

- English docs: [NPC cognition & world packs](docs/NPC_COGNITION.en.md) · [Providers](docs/PROVIDERS.en.md)
- 中文：[README.md](README.md) · [docs/NPC_COGNITION.md](docs/NPC_COGNITION.md) · [docs/PROVIDERS.md](docs/PROVIDERS.md)

## Design

| Layer | External? | Role |
| --- | --- | --- |
| NPC profile | Yes | Name, personality, job, region, `thinking_order`, weights |
| World pack | Yes | Setting frame (King's Canyon–style, Teyvat-style, block world, open world) + knowledge dir |
| Cognitive engine | **No (core)** | Six-stage decisions; reskinning must not replace the chain |
| Chat model | Yes | OpenAI-compatible Chat Completions + tools |
| Demo domain | Demo only | Local SQLite; replace for a real game backend |

Default **demo** mode needs no API key. Use `GAME_NPC_PROVIDER` in **live** mode.

## Install

```bash
cd Agent_1
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ui,pdf]"
game-npc --state-dir .runtime ingest
game-npc --state-dir .runtime ui
```

UI listens on `127.0.0.1:8501`.

## Multi-provider live mode

```bash
python -m pip install -e ".[ui,live,pdf]"
export GAME_NPC_MODE=live
export GAME_NPC_PROVIDER=openai    # deepseek | kimi | grok | glm | openrouter | claude | qwen | custom
export GAME_NPC_API_KEY="your-key"
game-npc providers
game-npc --state-dir .runtime doctor
```

Claude is reached through an **OpenAI-compatible gateway** (default preset: OpenRouter), not the native Anthropic Messages API. See [docs/PROVIDERS.en.md](docs/PROVIDERS.en.md).

## World packs (setting skin, cognition stays)

| World ID | Setting | Sample NPC |
| --- | --- | --- |
| `honor_of_kings` | MOBA lane map frame | Lane minion |
| `genshin` | Open-world continent frame | Street vendor |
| `minecraft` | Blocky village frame | Village trader |
| `open_world` | Borderlands / open world | Caravan broker |
| `demo_valley` | Demo village | Built-in elder/guard/merchant |

```bash
game-npc world --list
game-npc --world-pack src/game_npc/assets/worlds/genshin --use-world-npc \
  --state-dir .runtime chat "Who are you?" --explain
```

Hosts supply licensed or original lore under the pack’s `knowledge/` folder, then run `ingest`. **The runtime never scrapes the web**; download and review materials yourself before import.

## What “unique thinking chain” means

Each NPC profile owns `thinking_order` and decision weights. The engine runs:

**perception → motivation → context → selection → expression → feedback**

World packs change *where* the NPC lives and which lore is retrieved. They do not rewrite the scoring machine. `last_decision` is the auditable application summary for that NPC turn.

## Develop

```bash
uv sync --locked --python 3.12 --extra ui --extra live --extra pdf --extra dev
uv run --no-sync python -m unittest discover -s tests -v
```
