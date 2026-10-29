"""Conversation and tool boundaries with real temporary game state and fake I/O."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from game_npc.agent import Conversation, ConversationError, ToolRegistry
from game_npc.config import Settings
from game_npc.domain import DomainError, GameService
from game_npc.model import ModelReply, ToolCall


class FakeKnowledge:
    def __init__(self):
        self.queries = []
        self.documents = [{"source": "规则.txt", "text": "完成目标才能交付任务。", "score": 1.0}]

    def search(self, query):
        self.queries.append(query)
        return deepcopy(self.documents)


class FakeModel:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append((deepcopy(messages), deepcopy(tools)))
        if not self.replies:
            raise AssertionError("Unexpected model request")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(name, arguments=None, call_id="call_1"):
    return ToolCall(call_id, name, json.dumps(arguments or {}, ensure_ascii=False))


class AgentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / "game.sqlite3"
        self.game = GameService(self.db_path)
        self.knowledge = FakeKnowledge()

    def conversation(self, model=None, **settings):
        return Conversation(
            Settings(mode="live" if model else "demo", api_key="offline-test", **settings),
            self.game,
            self.knowledge,
            model,
        )

    def task(self, task_id):
        return next(task for task in self.game.player_tasks() if task["task_id"] == task_id)

    def test_successful_history_is_passed_to_later_model_turns(self):
        model = FakeModel(ModelReply("你叫旅行者一号。"), ModelReply("你刚才问了名字。"))
        conversation = self.conversation(model)
        conversation.reply("我叫什么？")
        conversation.reply("我刚才问了什么？")
        messages = model.requests[1][0]
        self.assertEqual(
            messages[1:],
            [
                {"role": "user", "content": "我叫什么？"},
                {"role": "assistant", "content": "你叫旅行者一号。"},
                {"role": "user", "content": "我刚才问了什么？"},
            ],
        )
        self.assertIn("1001", messages[0]["content"])

    def test_intermediate_text_and_raw_tool_results_do_not_enter_answer_or_history(self):
        model = FakeModel(
            ModelReply("内部计划：先查询玩家。", [call("get_player_info")]),
            ModelReply("欢迎，冒险者。"),
            ModelReply("我们刚才打过招呼。"),
        )
        conversation = self.conversation(model)
        self.assertEqual(conversation.reply("你好"), "欢迎，冒险者。")
        self.assertEqual(conversation.last_tools, ["get_player_info"])
        # The next request within a turn contains a valid tool protocol pair,
        # but preceding model-planning text is deliberately discarded.
        followup = model.requests[1][0]
        self.assertIsNone(followup[-2]["content"])
        self.assertEqual(followup[-1]["role"], "tool")
        self.assertEqual(json.loads(followup[-1]["content"])["result"]["player_id"], "1001")
        conversation.reply("刚才说了什么")
        self.assertTrue(all(message["role"] != "tool" for message in model.requests[2][0]))
        self.assertNotIn("内部计划", json.dumps(conversation.history, ensure_ascii=False))

    def test_empty_reply_does_not_create_successful_history(self):
        conversation = self.conversation(FakeModel(ModelReply("  ")))
        with self.assertRaises(ConversationError):
            conversation.reply("你好")
        self.assertEqual(conversation.history, [])

    def test_failed_later_turn_preserves_previous_history(self):
        conversation = self.conversation(FakeModel(ModelReply("你好"), ModelReply("")))
        conversation.reply("问候")
        previous = deepcopy(conversation.history)
        with self.assertRaises(ConversationError):
            conversation.reply("第二轮")
        self.assertEqual(conversation.history, previous)

    def test_budget_is_shared_across_model_rounds_and_final_request_has_no_tools(self):
        model = FakeModel(
            ModelReply("", [call("get_player_info", call_id="a")]),
            ModelReply("", [call("get_player_task", call_id="b")]),
            ModelReply("已查询玩家与任务。"),
        )
        conversation = self.conversation(model, max_tool_calls=2)
        self.assertEqual(conversation.reply("任务进度"), "已查询玩家与任务。")
        self.assertEqual(conversation.last_tools, ["get_player_info", "get_player_task"])
        self.assertEqual(model.requests[-1][1], [])

    def test_batch_calls_beyond_budget_are_not_executed(self):
        model = FakeModel(
            ModelReply(
                "",
                [
                    call("grant_task_reward", {"task_id": "T002"}, "a"),
                    call("update_player_task", {"task_id": "T001", "task_status": "已放弃"}, "b"),
                ],
            ),
            ModelReply("已发放完成任务的奖励。"),
        )
        conversation = self.conversation(model, max_tool_calls=1)
        conversation.reply("查看并处理任务")
        self.assertEqual(conversation.last_tools, ["grant_task_reward"])
        self.assertTrue(self.task("T002")["reward_claimed"])
        self.assertEqual(self.task("T001")["status"], "进行中")
        payload = json.loads(model.requests[1][0][-1]["content"])
        self.assertIn("预算", payload["error"])

    def test_model_calling_tools_after_budget_is_rejected(self):
        model = FakeModel(
            ModelReply("", [call("get_player_info", call_id="a")]),
            ModelReply("", [call("grant_task_reward", {"task_id": "T002"}, "b")]),
        )
        conversation = self.conversation(model, max_tool_calls=1)
        with self.assertRaises(ConversationError):
            conversation.reply("查看任务")
        self.assertEqual(conversation.last_tools, ["get_player_info"])
        self.assertFalse(self.task("T002")["reward_claimed"])
        self.assertEqual(conversation.history, [])

    def test_excessive_batch_and_duplicate_ids_execute_nothing(self):
        cases = [
            [call("grant_task_reward", {"task_id": "T002"}, str(i)) for i in range(21)],
            [call("grant_task_reward", {"task_id": "T002"}, "same") for _ in range(2)],
        ]
        for calls in cases:
            conversation = self.conversation(FakeModel(ModelReply("", calls)))
            with self.subTest(count=len(calls)), self.assertRaises(ConversationError):
                conversation.reply("领取奖励")
            self.assertFalse(self.task("T002")["reward_claimed"])
            self.assertEqual(conversation.last_tools, [])

    def test_report_tools_are_readonly_even_if_model_requests_a_write(self):
        model = FakeModel(
            ModelReply("", [call("grant_task_reward", {"task_id": "T002"})]),
            ModelReply("当前任务已经完成，奖励尚未领取。"),
        )
        conversation = self.conversation(model)
        conversation.reply("生成报告并领奖", mode="report")
        names = {tool["function"]["name"] for tool in model.requests[0][1]}
        self.assertNotIn("grant_task_reward", names)
        self.assertNotIn("update_player_task", names)
        payload = json.loads(model.requests[1][0][-1]["content"])
        self.assertIn("禁止写入", payload["error"])
        self.assertFalse(self.task("T002")["reward_claimed"])

    def test_knowledge_sources_are_exposed_separately_from_history(self):
        model = FakeModel(
            ModelReply("", [call("search_knowledge", {"query": "任务完成"})]),
            ModelReply("达成目标后才可交付。"),
        )
        conversation = self.conversation(model)
        conversation.reply("任务怎样完成")
        self.assertEqual(self.knowledge.queries, ["任务完成"])
        self.assertEqual(conversation.last_sources, self.knowledge.documents)
        self.assertNotIn("规则.txt", json.dumps(conversation.history, ensure_ascii=False))

    def test_history_is_bounded_in_complete_turns(self):
        conversation = self.conversation(
            FakeModel(ModelReply("一"), ModelReply("二"), ModelReply("三")), history_turns=2
        )
        for query in ("第一轮", "第二轮", "第三轮"):
            conversation.reply(query)
        self.assertEqual(
            [message["content"] for message in conversation.history],
            ["第二轮", "二", "第三轮", "三"],
        )

    def test_invalid_input_and_mode_never_reach_model(self):
        model = FakeModel()
        conversation = self.conversation(model)
        for query in ("", "   ", None, "字" * 4001):
            with self.subTest(query_type=type(query).__name__), self.assertRaises(ValueError):
                conversation.reply(query)
        with self.assertRaises(ValueError):
            conversation.reply("你好", mode="unknown")
        self.assertEqual(model.requests, [])
        self.assertEqual(conversation.history, [])

    def test_demo_reward_is_persistent_and_duplicate_claim_does_not_add_gold(self):
        conversation = self.conversation()
        self.assertIn("已发放", conversation.reply("领取 T002 奖励"))
        self.assertIn("已经领过", conversation.reply("领取 T002 奖励"))
        self.assertEqual(self.game.player_info()["gold"], 20)
        self.assertTrue(self.task("T002")["reward_claimed"])

    def test_demo_cannot_complete_or_reward_unfinished_task_from_chat_claim(self):
        conversation = self.conversation()
        for query in ("交付 T001", "领取 T001 奖励"):
            with self.subTest(query=query), self.assertRaises(DomainError):
                conversation.reply(query)
        self.assertEqual(self.task("T001")["progress"], 0)
        self.assertEqual(self.task("T001")["status"], "进行中")
        self.assertEqual(conversation.history, [])

    def test_demo_requires_exact_write_command_not_mentions_or_negations(self):
        conversation = self.conversation()
        for query in ("我已完成 T001", "不要领取 T002 奖励", "如何交付 T001"):
            with self.subTest(query=query):
                conversation.reply(query)
        self.assertEqual(self.task("T001")["status"], "进行中")
        self.assertFalse(self.task("T002")["reward_claimed"])

    def test_demo_report_does_not_execute_requested_write(self):
        conversation = self.conversation()
        report = conversation.reply("领取 T002 奖励", mode="report")
        self.assertIn("报告", report)
        self.assertIn("本地演示", report)
        self.assertFalse(self.task("T002")["reward_claimed"])

    def test_clear_resets_conversation_metadata_without_erasing_game_progress(self):
        conversation = self.conversation()
        conversation.reply("领取 T002 奖励")
        conversation.reply("怎样遵守村里的规矩")
        conversation.last_tools.append("get_player_task")
        self.assertTrue(conversation.history)
        self.assertTrue(conversation.last_sources)
        conversation.clear()
        self.assertEqual(conversation.history, [])
        self.assertEqual(conversation.last_sources, [])
        self.assertEqual(conversation.last_tools, [])
        self.assertTrue(self.task("T002")["reward_claimed"])

    def test_tool_registry_rejects_cross_player_argument_injection(self):
        registry = ToolRegistry(self.game, self.knowledge)
        for name, arguments in [
            ("get_player_info", {"player_id": "1002"}),
            ("get_player_task", {"player_id": "1002"}),
            ("grant_task_reward", {"task_id": "T002", "player_id": "1002"}),
        ]:
            with self.subTest(name=name):
                self.assertIn("error", registry.execute(name, json.dumps(arguments)))
        self.assertFalse(self.task("T002")["reward_claimed"])
        self.assertEqual(GameService(self.db_path, "1002").player_info()["gold"], 0)

    def test_tool_registry_rejects_invalid_json_unknown_tools_and_invalid_status(self):
        registry = ToolRegistry(self.game, self.knowledge)
        cases = [
            ("get_player_info", "not json"),
            ("get_player_info", "[]"),
            ("get_player_info", "null"),
            ("get_player_info", " " * 4097),
            ("get_player_info", {}),
            ("shell", "{}"),
            ("record_progress", '{"task_id":"T001","progress":3}'),
            ("update_player_task", '{"task_id":"T001","task_status":"完成"}'),
            ("update_player_task", '{"task_id":"T001","task_status":42}'),
            ("update_player_task", '{"task_id":"T001"}'),
            ("search_knowledge", '{"query":" "}'),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.assertIn("error", registry.execute(name, arguments))
        self.assertEqual(self.task("T001")["status"], "进行中")
        self.assertEqual(self.knowledge.queries, [])

    def test_tool_registry_uses_stored_progress_before_claiming_success(self):
        registry = ToolRegistry(self.game, self.knowledge)
        result = registry.execute("update_player_task", '{"task_id":"T001","task_status":"已完成"}')
        self.assertIn("error", result)
        self.game.record_progress("T001", 3)
        result = registry.execute("update_player_task", '{"task_id":"T001","task_status":"已完成"}')
        self.assertEqual(result["result"]["status"], "已完成")

    def test_tool_registry_masks_unexpected_infrastructure_failure(self):
        registry = ToolRegistry(self.game, self.knowledge)
        with patch.object(self.knowledge, "search", side_effect=OSError("private file path")):
            # Handlers are bound when the registry is built.
            registry = ToolRegistry(self.game, self.knowledge)
            result = registry.execute("search_knowledge", '{"query":"任务"}')
        self.assertIn("error", result)
        self.assertNotIn("private file path", result["error"])


if __name__ == "__main__":
    unittest.main()
