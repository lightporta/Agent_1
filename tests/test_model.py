import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from game_npc.config import Settings
from game_npc.model import ModelError, ModelReply, OpenAIModel, ToolCall


def response(content="回答", tool_calls=None, finish_reason="stop", refusal=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, tool_calls=tool_calls, refusal=refusal),
            )
        ]
    )


class FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(mode="live", api_key="secret-test-key")

    def test_injected_client_requires_no_sdk_and_omits_empty_tools(self):
        client = FakeClient(response())
        with patch.dict(sys.modules, {"openai": None}):
            model = OpenAIModel(self.settings, client=client)
            reply = model.complete([{"role": "user", "content": "你好"}], [])
        self.assertEqual(reply, ModelReply("回答"))
        self.assertNotIn("tools", client.calls[0])
        self.assertIs(client.calls[0]["stream"], False)
        self.assertEqual(client.calls[0]["model"], "qwen3-max")

    def test_tool_arguments_are_returned_without_execution_or_json_parsing(self):
        raw = '{"task_id": "T002"}'
        tools = [{"type": "function", "function": {"name": "grant_task_reward"}}]
        call = SimpleNamespace(
            id="call_1",
            type="function",
            function=SimpleNamespace(name="grant_task_reward", arguments=raw),
        )
        client = FakeClient(response(None, [call], "tool_calls"))
        reply = OpenAIModel(self.settings, client).complete([], tools)
        self.assertEqual(reply.tool_calls, [ToolCall("call_1", "grant_task_reward", raw)])
        self.assertEqual(reply.text, "")
        self.assertEqual(client.calls[0]["tools"], tools)

    def test_text_content_blocks_are_joined_and_nontext_blocks_are_ignored(self):
        blocks = [{"type": "text", "text": "你好"}, {"type": "image", "url": "ignored"}]
        blocks.append(SimpleNamespace(type="text", text="，冒险者！"))
        reply = OpenAIModel(self.settings, FakeClient(response(blocks))).complete([], [])
        self.assertEqual(reply.text, "你好，冒险者！")

    def test_dict_style_compatible_response(self):
        result = {"choices": [{"finish_reason": "stop", "message": {"content": " 好的 "}}]}
        self.assertEqual(
            OpenAIModel(self.settings, FakeClient(result)).complete([], []).text, "好的"
        )

    def test_empty_response_and_empty_answer_are_errors(self):
        for result in [SimpleNamespace(choices=[]), {}, response("   ")]:
            with self.subTest(result=result), self.assertRaises(ModelError):
                OpenAIModel(self.settings, FakeClient(result)).complete([], [])

    def test_truncated_filtered_and_refused_responses_are_errors(self):
        for result in [
            response("partial", finish_reason="length"),
            response("", finish_reason="content_filter"),
            response("", refusal="refused"),
            response([{"type": "refusal", "refusal": "refused"}]),
        ]:
            with self.subTest(result=result), self.assertRaises(ModelError):
                OpenAIModel(self.settings, FakeClient(result)).complete([], [])

    def test_bad_content_and_tool_call_types_are_errors(self):
        for result in [
            response(123),
            response([{"type": "text", "text": {"value": "wrong format"}}]),
            response(None, {"not": "a list"}),
            response(None, [{"id": "call_1", "function": {"name": "x", "arguments": {}}}]),
        ]:
            with self.subTest(result=result), self.assertRaises(ModelError):
                OpenAIModel(self.settings, FakeClient(result)).complete([], [])

    def test_transport_error_does_not_expose_key(self):
        failure = RuntimeError("bad authorization secret-test-key")
        with self.assertRaises(ModelError) as error:
            OpenAIModel(self.settings, FakeClient(failure)).complete([], [])
        self.assertNotIn(self.settings.api_key, str(error.exception))
        self.assertNotIn("authorization", str(error.exception))
        self.assertIs(error.exception.__cause__, failure)

    def test_key_is_required_even_for_injected_client(self):
        with self.assertRaisesRegex(ValueError, "DASHSCOPE_API_KEY"):
            OpenAIModel(Settings(), FakeClient(response()))

    def test_missing_sdk_has_install_instruction(self):
        with patch.dict(sys.modules, {"openai": None}), self.assertRaisesRegex(ModelError, "live"):
            OpenAIModel(self.settings)

    def test_sdk_configuration_is_explicit(self):
        client = FakeClient(response())
        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return client

        with patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=factory)}):
            OpenAIModel(self.settings).complete([], [])
        self.assertEqual(
            factory_calls,
            [
                {
                    "api_key": self.settings.api_key,
                    "base_url": self.settings.base_url,
                    "timeout": 45,
                    "max_retries": 0,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
