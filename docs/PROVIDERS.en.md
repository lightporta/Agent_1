# Multi-provider setup (OpenAI-compatible)

Version: 0.4.0. 中文：[PROVIDERS.md](PROVIDERS.md)

Live chat always uses **Chat Completions + function calling**. Any HTTPS OpenAI-compatible endpoint works: DeepSeek, Kimi, ChatGPT, Grok, GLM, Claude gateways, Qwen, and custom proxies.

## Switch providers

```bash
export GAME_NPC_MODE=live
export GAME_NPC_PROVIDER=openai    # deepseek | kimi | grok | glm | openrouter | claude | qwen | custom
export GAME_NPC_API_KEY="your-key"
game-npc providers
game-npc doctor
```

| Provider | Default model | Notes |
| --- | --- | --- |
| `qwen` | `qwen3-max` | DashScope compatible mode |
| `deepseek` | `deepseek-chat` | Official DeepSeek API |
| `kimi` | `moonshot-v1-auto` | Moonshot / Kimi |
| `openai` | `gpt-4o-mini` | ChatGPT platform |
| `grok` | `grok-3-mini` | xAI |
| `glm` | `glm-4-plus` | Zhipu |
| `openrouter` / `claude` | `anthropic/claude-sonnet-4` | Claude via OpenAI-compatible gateway |
| `custom` | required | You must set `GAME_NPC_BASE_URL` + `GAME_NPC_MODEL` |

Key resolution: `GAME_NPC_API_KEY` → provider-specific env → legacy fallbacks (`DASHSCOPE_API_KEY`, `OPENAI_API_KEY`).

## Claude

This project does **not** call the native Anthropic Messages API. Use OpenRouter (preset) or any OpenAI-compatible Claude gateway via `custom`.

## Cognition stays local

Providers only affect wording and tool-call language. Strategy selection still runs in `CognitiveEngine` before the model is called. Swapping models does not merge NPC thinking orders.

## Embeddings

Vector mode needs an embeddings-capable endpoint. Keep `GAME_NPC_RETRIEVAL=local` if your chat provider has no embeddings API.

## Safety

HTTPS base URLs only, no embedded credentials. Errors never echo API keys. `.env` files are not auto-loaded.
