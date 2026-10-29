# 多模型接入（OpenAI 兼容）

版本：0.4.0。English: [PROVIDERS.en.md](PROVIDERS.en.md)

在线对话统一走 **Chat Completions + function calling**。只要提供商暴露 OpenAI 兼容 HTTPS 接口，即可接入 DeepSeek、Kimi、ChatGPT、Grok、GLM、Claude 网关、通义千问等。

## 快速切换

```bash
export GAME_NPC_MODE=live
export GAME_NPC_PROVIDER=deepseek   # kimi | openai | grok | glm | openrouter | claude | qwen | custom
export GAME_NPC_API_KEY="你的密钥"
# 可选覆盖：
# export GAME_NPC_MODEL=...
# export GAME_NPC_BASE_URL=https://...
game-npc providers
game-npc doctor
```

| Provider | 默认模型 | 默认 Base URL | 常用密钥环境变量 |
| --- | --- | --- | --- |
| `qwen` | `qwen3-max` | DashScope compatible-mode | `DASHSCOPE_API_KEY` |
| `deepseek` | `deepseek-chat` | `https://api.deepseek.com/v1` | `DEEPSEEK_API_KEY` |
| `kimi` | `moonshot-v1-auto` | `https://api.moonshot.cn/v1` | `MOONSHOT_API_KEY` |
| `openai` | `gpt-4o-mini` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `grok` | `grok-3-mini` | `https://api.x.ai/v1` | `XAI_API_KEY` |
| `glm` | `glm-4-plus` | 智谱 paas/v4 | `ZHIPUAI_API_KEY` |
| `openrouter` | `anthropic/claude-sonnet-4` | OpenRouter | `OPENROUTER_API_KEY` |
| `claude` | 同上（经兼容网关） | OpenRouter | `OPENROUTER_API_KEY` |
| `custom` | 必填 | 必填 HTTPS | `GAME_NPC_API_KEY` |

密钥解析顺序：`GAME_NPC_API_KEY` → 提供商专用变量 → 兼容回退（如旧的 `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`）。

## Claude 说明

本仓库**不**直接调用 Anthropic Messages API。`claude` / `openrouter` 预设指向 OpenAI 兼容网关。也可：

```bash
export GAME_NPC_PROVIDER=custom
export GAME_NPC_BASE_URL="https://你的兼容网关/v1"
export GAME_NPC_MODEL="claude-sonnet-4"
export GAME_NPC_API_KEY="..."
```

## 与思维链的关系

提供商只影响**表达与工具调用语言**。策略选择仍由 `CognitiveEngine` 在请求模型前完成。换模型不会合并或抹掉各 NPC 的 `thinking_order`。

## 向量检索

`GAME_NPC_RETRIEVAL=vector` 时，嵌入模型与 `base_url` 需支持 embeddings。部分聊天提供商没有嵌入接口，请单独配置嵌入兼容端点，或保持 `local` BM25。

## 安全

- Base URL 必须是不含内嵌凭据的 HTTPS。  
- 错误信息不会回显 API Key。  
- `.env.example` 仅作示例；程序不会自动加载 `.env`。  
