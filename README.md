# NPC 对话实验室 · Agent_1

中文游戏 NPC Agent 示例：角色对话、任务进度、幂等奖励、带来源的知识检索。Python 3.11+，建议使用 Python 3.12。

默认是**无需密钥、无需模型服务的本地演示**。演示使用规则回复和中文 BM25 检索，适合验证安装与任务流程。在线模式使用通义千问的 OpenAI 兼容工具调用；可选 Chroma 语义检索。玩家与金币始终来自本地演示数据库，尚未接入真实游戏服务器。

## 安装与启动

```bash
git clone https://github.com/lightporta/Agent_1.git
cd Agent_1
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ui,pdf]"
game-npc --state-dir .runtime ingest
game-npc --state-dir .runtime ui
```

Windows PowerShell 的前两步环境命令为：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

界面默认监听本机 `127.0.0.1:8501`，也可执行 `streamlit run app.py`。未激活环境时可直接调用 `.venv/bin/game-npc`；Windows 使用 `.venv\Scripts\game-npc.exe`。

第一次使用先构建索引，也可点击界面左侧“构建 / 同步知识库”。修改、新增、删除资料后再次构建，旧分片会同步清理。仓库中的 4 份 NPC 资料均打入安装包，默认索引包含 42 个分片。

不需要界面时：

```bash
python -m pip install -e ".[pdf]"
game-npc --state-dir .runtime doctor
game-npc --state-dir .runtime ingest
game-npc --state-dir .runtime chat "NPC 对话规范"
game-npc --state-dir .runtime chat
```

终端交互支持 `/clear` 清空聊天和 `/quit` 退出。`doctor` 只检查本地配置与索引，不调用模型，也不会创建数据库。

## 任务演示

- 玩家 `1001`、`1002` 的状态相互独立，重新启动后保留。
- `T001` 为采集任务，初始 `0/3`。界面“演示事件”中点击三次“模拟采集一次”，再输入 `交付 T001`，最后输入 `领取 T001 奖励`。
- `T002` 初始已完成，可直接输入 `领取 T002 奖励`。再次领取不会重复增加金币或经验。
- 演示写操作仅接受上述明确命令。询问“奖励是多少”或“不要领取奖励”不会改变状态。
- 打开“只读进展报告”后，只能查看当前玩家状态，不能修改或发奖。
- “清空对话”不会清空任务。需要全新演示时使用新的 `--state-dir` 目录。

进度只接受可信游戏事件，模型工具没有修改进度或指定其他玩家身份的权限。这里的 SQLite 服务用于本地示例；真实部署应由游戏服务器认证玩家并校验事件，不能把演示玩家选择器当作登录系统。

## 在线千问

```bash
python -m pip install -e ".[ui,live,pdf]"
export DASHSCOPE_API_KEY="你的密钥"
export GAME_NPC_MODE=live
game-npc --state-dir .runtime doctor
game-npc --state-dir .runtime ui
```

PowerShell 设置环境变量使用 `$env:DASHSCOPE_API_KEY="你的密钥"`、`$env:GAME_NPC_MODE="live"`。`.env.example` 是配置示例，程序不会自动加载 `.env` 文件。

默认聊天模型保持为原项目的 `qwen3-max`，默认接口为 `https://dashscope.aliyuncs.com/compatible-mode/v1`。具体可用模型、密钥地域与账户权限以你的通义千问服务配置为准。切换服务地域时需要同时配置接口地址与对应密钥。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `GAME_NPC_MODE` | `demo`；在线时设为 `live` |
| `GAME_NPC_RETRIEVAL` | `local`；可选 `vector` |
| `GAME_NPC_MODEL` | `qwen3-max` |
| `GAME_NPC_EMBEDDING_MODEL` | `text-embedding-v4` |
| `GAME_NPC_BASE_URL` | 通义千问兼容接口地址，必须为 HTTPS |
| `DASHSCOPE_API_KEY` | 仅在线聊天或向量模式需要 |
| `GAME_NPC_STATE_DIR` | 默认 `~/.game-npc`，存放演示状态和索引 |
| `GAME_NPC_DATA_DIR` | 默认安装包内的 NPC 资料目录；可设置为自己的绝对路径 |

CLI 的 `--state-dir` 优先于环境变量。显式使用相同绝对路径即可从任意工作目录访问同一状态。不要把生成的 SQLite、Chroma 数据、密钥或运行日志提交到 Git。

## 可选语义检索

```bash
python -m pip install -e ".[vector,pdf]"
export DASHSCOPE_API_KEY="你的密钥"
export GAME_NPC_RETRIEVAL=vector
game-npc --state-dir .runtime ingest
```

`vector` 使用 Chroma 与在线 embeddings。首次构建和资料变动后会请求嵌入服务并产生相应费用；重建成功才切换新 collection，失败保留原索引。当前实现为小型示例知识库重建完整向量集合，不适合大规模频繁更新。无需在线语义检索时保持 `local`，本地索引与对话不产生模型费用。

文本支持 UTF-8 `.txt`、`.md`，PDF 需要 `[pdf]`，扫描 PDF 需先自行 OCR。对纯文本自定义知识库，核心 CLI 可以零第三方依赖安装。

## 结构与设计

```text
src/game_npc/
  config.py       环境配置校验与安装包资源定位
  bootstrap.py    显式组装服务，无导入时模型初始化
  domain.py       玩家绑定、任务规则、SQLite 事务与奖励去重
  knowledge.py    文件同步、中文 BM25、可选 Chroma、资料来源
  model.py        延迟加载的 OpenAI 兼容模型适配器
  agent.py        对话历史、参数验证、工具预算、报告只读
  cli.py / ui.py  终端入口与 Streamlit 界面
  assets/         NPC 资料与提示词，随 wheel 分发
tests/            离线回归与可选 Streamlit 集成测试
docs/REFACTOR.md  原问题证据、改造取舍、验证边界
```

重构移除了原先重复的 LangChain 包装和失效中间件，以小型显式工具循环统一状态与调用预算。检索返回原文及来源，由 Agent 统一生成答复。在线每轮最多执行 5 次工具调用，保留最近 12 轮成功对话，报告工具集在代码层禁止写入。

在线输出先完成工具循环，再一次展示最终答复；本版不提供 token 流式显示。不会将用户消息、工具原文、工具前置思考当作助手回答逐帧展示。失败请求不会写入成功聊天历史，已完成的任务操作可在面板核对，程序不会自动重试发奖。

## 开发、锁定安装与构建

```bash
uv sync --locked --python 3.12 --extra ui --extra live --extra pdf --extra dev
uv run --no-sync python -m unittest discover -s tests -v
uv run --no-sync ruff check src tests app.py
uv run --no-sync ruff format --check src tests app.py
uv build
```

`uv.lock` 锁定所有可选依赖的解析结果，日常离线演示无需安装 `[live]` 或 `[vector]`。不用 uv 时也可以使用上面的 pip 命令，再安装 `.[dev]` 并执行 `python -m build`。

GitHub Actions 配置包含 Linux Python 3.11–3.14、macOS/Windows Python 3.12，以及 Streamlit 测试。配置存在不代表远端已运行；本轮的实际验证记录见 [重构报告](docs/REFACTOR.md)。真实模型、真实嵌入服务和真实游戏后端需要使用对应凭据单独验收。
