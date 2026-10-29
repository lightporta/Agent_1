"""Bounded conversation orchestration, separate from models, UI and game state."""

import json
import re
from copy import deepcopy

from game_npc.config import Settings, load_prompt


class ConversationError(RuntimeError):
    """An incomplete turn; do not append a fabricated assistant message."""


def _schema(name, description, properties=None):
    properties = properties or {}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


STRING = {"type": "string", "minLength": 1, "maxLength": 500}
READ_TOOLS = [
    _schema("get_player_info", "读取当前绑定玩家的本地演示信息与余额。"),
    _schema("get_player_task", "读取当前玩家的演示任务、真实存储的进度与领奖状态。"),
    _schema("search_knowledge", "检索 NPC 规则与设定，返回带来源的参考片段。", {"query": STRING}),
]
WRITE_TOOLS = [
    _schema(
        "update_player_task",
        "更新当前玩家任务状态；必须已达目标才能完成。",
        {
            "task_id": STRING,
            "task_status": {"type": "string", "enum": ["进行中", "已完成", "已失败", "已放弃"]},
        },
    ),
    _schema(
        "grant_task_reward",
        "领取当前玩家已完成任务的演示奖励；重复领取不会重复发放。",
        {
            "task_id": STRING,
        },
    ),
]


class ToolRegistry:
    def __init__(self, game, knowledge, readonly=False):
        self.game = game
        self.knowledge = knowledge
        self.schemas = deepcopy(READ_TOOLS + ([] if readonly else WRITE_TOOLS))
        self.handlers = {
            "get_player_info": game.player_info,
            "get_player_task": game.player_tasks,
            "search_knowledge": knowledge.search,
        }
        if not readonly:
            self.handlers.update(
                {
                    "update_player_task": game.update_task,
                    "grant_task_reward": game.grant_reward,
                }
            )

    def execute(self, name, raw_arguments):
        if name not in self.handlers:
            return {"error": "未知工具，或当前报告模式禁止写入"}
        try:
            if not isinstance(raw_arguments, str) or len(raw_arguments) > 4096:
                raise ValueError("工具参数格式错误或过长")
            arguments = json.loads(raw_arguments)
            schema = next(
                s["function"]["parameters"] for s in self.schemas if s["function"]["name"] == name
            )
            if not isinstance(arguments, dict) or set(arguments) != set(schema["properties"]):
                raise ValueError("工具参数名称不符合定义")
            for key, rule in schema["properties"].items():
                value = arguments[key]
                if not isinstance(value, str) or not value.strip() or len(value) > 500:
                    raise ValueError("工具参数必须是 1 到 500 字的非空字符串")
                if "enum" in rule and value not in rule["enum"]:
                    raise ValueError("任务状态不在允许范围内")
            return {"result": self.handlers[name](**arguments)}
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}
        except Exception:
            return {"error": "工具暂时不可用，请检查配置或知识索引"}


class Conversation:
    def __init__(self, settings: Settings, game, knowledge, model=None):
        self.settings = settings
        self.game = game
        self.knowledge = knowledge
        self.model = model
        self.history = []
        self.last_sources = []
        self.last_tools = []

    def clear(self):
        self.history.clear()
        self.last_sources.clear()
        self.last_tools.clear()

    def reply(self, query: str, mode="dialogue") -> str:
        if mode not in {"dialogue", "report"}:
            raise ValueError("对话模式只能是 dialogue 或 report")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000:
            raise ValueError("请输入 1 到 4000 字的内容")
        query = query.strip()
        self.last_sources = []
        self.last_tools = []
        if self.settings.mode == "demo":
            answer = self._demo(query, mode)
        else:
            answer = self._live(query, mode)
        self.history.extend(
            [{"role": "user", "content": query}, {"role": "assistant", "content": answer}]
        )
        self.history = self.history[-self.settings.history_turns * 2 :]
        return answer

    def _live(self, query, mode):
        if self.model is None:
            from game_npc.model import OpenAIModel

            self.model = OpenAIModel(self.settings)
        registry = ToolRegistry(self.game, self.knowledge, readonly=mode == "report")
        messages = [
            {
                "role": "system",
                "content": load_prompt(mode)
                + f"\n当前绑定玩家 ID：{self.game.player_info()['player_id']}。",
            },
            *deepcopy(self.history),
            {"role": "user", "content": query},
        ]
        used = 0
        # One additional request can produce the final answer after the budget is exhausted.
        for _ in range(self.settings.max_tool_calls + 1):
            schemas = registry.schemas if used < self.settings.max_tool_calls else []
            result = self.model.complete(messages, schemas)
            if not result.tool_calls:
                if not result.text.strip():
                    raise ConversationError("模型没有返回有效回答，请重新提交")
                return result.text.strip()
            if not schemas or len(result.tool_calls) > 20:
                raise ConversationError("模型超过本轮工具调用上限，请缩小问题范围")
            ids = [call.id for call in result.tool_calls]
            if any(not item for item in ids) or len(set(ids)) != len(ids):
                raise ConversationError("模型返回了无效的工具调用标识")
            # Text accompanying tool calls is internal intermediate output, never UI output.
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.arguments,
                            },
                        }
                        for call in result.tool_calls
                    ],
                }
            )
            for call in result.tool_calls:
                if used >= self.settings.max_tool_calls:
                    payload = {"error": "本轮工具调用预算已用尽，请根据已有结果回答"}
                else:
                    used += 1
                    payload = registry.execute(call.name, call.arguments)
                    self.last_tools.append(call.name)
                    if call.name == "search_knowledge" and "result" in payload:
                        self.last_sources.extend(payload["result"])
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                )
        raise ConversationError("本轮工具调用已达上限，未生成最终回答；任务面板可核对操作结果")

    def _demo(self, query, mode):
        """Deterministic smoke/demo path. This is not an LLM or semantic RAG evaluation."""
        player = self.game.player_info()
        if mode == "report":
            lines = [
                "## 玩家交互与任务进展报告",
                "数据来源：本地演示环境。",
                f"玩家：{player['name']}（{player['player_id']}）",
                f"余额：{player['gold']} 金币 / {player['experience']} 经验",
                self._task_summary(),
                "建议：先完成未达标任务，再交付并领取奖励。",
            ]
            return "\n\n".join(lines)
        reward_command = re.fullmatch(r"领取\s*(T\d{3})\s*奖励[。！!]?", query, flags=re.I)
        if reward_command:
            result = self.game.grant_reward(reward_command.group(1).upper())
            return (
                "演示奖励已发放。" if result["granted"] else "这个任务的演示奖励已经领过了。"
            ) + (
                f"当前余额：{result['balances']['gold']} 金币 / "
                f"{result['balances']['experience']} 经验。"
            )
        completion_command = re.fullmatch(r"交付\s*(T\d{3})[。！!]?", query, flags=re.I)
        if completion_command:
            task = self.game.update_task(completion_command.group(1).upper(), "已完成")
            return f"演示任务 {task['task_id']} 已完成，可以领取奖励了。"
        if any(word in query for word in ("任务", "进度", "奖励", "完成", "交付")):
            return self._task_summary() + (
                "\n\n演示命令：领取 T002 奖励 / 交付 T001。T001 需先在演示事件面板累计 3 次采集。"
            )
        if any(
            word in query for word in ("我是谁", "我的信息", "我的名字", "我的等级", "我的金币")
        ):
            return (
                f"你是{player['name']}（{player['player_id']}），{player['level']}级"
                f"{player['profession']}。你有 {player['gold']} 金币。以上为本地演示数据。"
            )
        if query in {"你好", "您好", "嗨"}:
            return f"{player['name']}，欢迎来到新手村！要看看任务，还是了解村里的规矩？"
        self.last_sources = self.knowledge.search(query)
        if not self.last_sources:
            return "暂时没有找到相关设定。你可以查看任务，或换个关键词检索 NPC 规则。"
        evidence = self.last_sources[0]
        return f"本地资料摘录（演示检索）：\n\n{evidence['text']}\n\n来源：{evidence['source']}"

    def _task_summary(self):
        return "\n".join(
            f"- {task['task_id']} {task['name']}：{task['status']}，"
            f"{task['progress']}/{task['target']}，"
            f"{'已领奖' if task['reward_claimed'] else '未领奖'}"
            for task in self.game.player_tasks()
        )
