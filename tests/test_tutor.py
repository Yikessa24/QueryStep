import json
from dataclasses import replace
import unittest

import httpx

from api.catalog import Catalog, DEFAULT_CATALOG
from tutor.agent import TutorAgent
from tutor.check_provider import choose_gemini, probe
from tutor.provider import ChatModel, measure_calls


def tool(name):
    return {"tool_calls": [{"id": "call-course", "type": "function",
                            "function": {"name": name, "arguments": "{}"}}]}


def action(name, text, sources):
    return {"content": json.dumps({"action": name, "text": text, "source_ids": sources})}


class TutorTest(unittest.TestCase):
    def test_provider_usage_meter_records_only_supported_counts(self):
        def handle(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "other": "ignored"}})

        model = ChatModel("https://example.invalid/v1", "test", None, transport=httpx.MockTransport(handle))
        self.addCleanup(model.close)
        with measure_calls() as outer:
            self.assertEqual(model.reply([], [], 1), {"content": "ok"})
            with measure_calls() as inner:
                model.reply([], [], 1)
            self.assertEqual(inner, outer)
            self.assertEqual(outer, [{"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}])

    def test_two_turns_adapt_and_use_returned_tools(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        replies = iter([
            tool("retrieve_course_notes"),
            action("ask_clarifying", "刚好等于边界值的行应该被保留吗？", ["note-where"]),
            tool("get_worked_example"),
            action("show_example", "气温为 12、18、20，严格低于 18 时只有 12 被保留。", ["example-where"]),
        ])
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": next(replies)}]})

        model = ChatModel("https://example.invalid/v1", "test", None)
        self.addCleanup(model.close)
        model.client.close()
        model.client = httpx.Client(base_url="https://example.invalid/v1/",
                                    transport=httpx.MockTransport(handle))
        agent = TutorAgent(model)
        first = agent.respond(item, "不明白边界", [])
        second = agent.respond(item, "我还是分不清", [{"message": "不明白边界", **first}])
        self.assertEqual((first["action"], second["action"]), ("ask_clarifying", "show_example"))
        self.assertEqual(first["trace"][0]["tool"], "retrieve_course_notes")
        self.assertEqual(second["trace"][0]["tool"], "get_worked_example")
        self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
        self.assertIn(first["text"], [message["content"] for message in requests[2]["messages"]])
        self.assertNotIn("correct_option", str(requests))

    def test_invalid_citation_and_answer_leak_fall_back(self):
        class FakeModel:
            def __init__(self, response):
                self.response = response

            def reply(self, messages, tools, timeout):
                return self.response

        item = Catalog.load(DEFAULT_CATALOG).items[2]
        for response, expected in [
            (action("give_hint", "请检查边界", ["unknown"]), "invalid_citation"),
            (action("give_hint", "正确答案是 B。", []), "answer_leak_check"),
            (action("give_hint", "正确答案是 Ｂ选项。", []), "answer_leak_check"),
            (action("give_hint", "请检查边界。", []), "missing_hint_reference"),
            (action("invite_practice", "继续做下一题吧。", []), "invalid_tutor_stage"),
            (tool("execute_sql"), "invalid_tool_call"),
        ]:
            with self.subTest(expected=expected):
                result = TutorAgent(FakeModel(response)).respond(item, "帮我看一下", [])
                self.assertEqual(result["source"], "template")
                self.assertEqual(result["fallback_reason"], expected)

    def test_mapped_item_does_not_contact_provider_by_default(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        item = replace(item, source_question_id=99, source_kcs=(10,))
        result = TutorAgent(object()).respond(item, "我想把题目贴给你。", [])
        self.assertEqual(result["fallback_reason"], "mapped_item_llm_disabled")

    def test_select_row_count_uses_targeted_material_without_sharing_mapped_question(self):
        item = replace(Catalog.load(DEFAULT_CATALOG).items[1], source_question_id=99,
                       source_kcs=(10,), prompt="How many rows will SELECT title FROM private_table return?")
        replies = iter([
            tool("retrieve_course_notes"),
            action("give_hint", "先检查来源表的行是否会被过滤。", ["note-select-row-count"]),
            tool("get_worked_example"),
            action("show_example", "水果表选一列之后仍然有三行。", ["example-select-row-count"]),
        ])
        requests = []

        class FakeModel:
            def reply(self, messages, tools, timeout):
                requests.append(tuple(messages))
                return next(replies)

        agent = TutorAgent(FakeModel(), allow_mapped_items=True)
        first = agent.respond(item, "请给个提示。", [])
        second = agent.respond(item, "请举个例子。", [{"message": "请给个提示。", **first}])
        self.assertEqual([first["source"], second["source"]], ["llm", "llm"])
        self.assertIn("多少行", str(requests[0]))
        self.assertIn("一列、三行", requests[-1][-1]["content"])
        self.assertNotIn("private_table", str(requests))
        self.assertIn("结果行和结果列", TutorAgent().respond(item, "请给个提示。", [])["text"])

    def test_provider_rejects_remote_http_without_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "requires HTTPS"):
            ChatModel("http://example.invalid/v1", "test", "test-key")
        with self.assertRaisesRegex(ValueError, "without credentials"):
            ChatModel("https://test-key@example.invalid/v1", "test", None)

    def test_provider_probe_and_model_selection_with_mock_transport(self):
        models = ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-image"]
        structured = action("ask_clarifying", "你在比较哪个值？", [])
        replies = iter([
            {"content": "WHERE 过滤行。"}, tool("retrieve_course_notes"),
            {"content": "```json\n" + structured["content"] + "\n```"}, structured,
            tool("retrieve_course_notes"),
            action("ask_clarifying", "边界值恰好相等时你会保留吗？", ["note-where"]),
            tool("get_worked_example"),
            action("show_example", "气温严格低于 18 时，12 符合要求。", ["example-where"]),
        ])
        bodies = []

        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer dummy-test-key")
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": model} for model in models]})
            self.assertEqual(request.url.path, "/v1/chat/completions")
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": next(replies)}]})

        model = ChatModel("https://example.invalid/v1", "", "dummy-test-key",
                          transport=httpx.MockTransport(handle))
        self.addCleanup(model.close)
        model.model = choose_gemini(model.list_models())
        self.assertEqual(model.model, "gemini-2.5-flash")
        report = probe(model, 5)
        self.assertTrue(report["tool_calling"])
        self.assertTrue(report["native_json_mode"])
        self.assertEqual(bodies[1]["tool_choice"]["function"]["name"], "retrieve_course_notes")
        self.assertEqual(bodies[3]["response_format"], {"type": "json_object"})
        self.assertEqual([turn["source"] for turn in report["tutor_rounds"]], ["llm", "llm"])

    def test_tutor_capacity_falls_back_without_calling_provider(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        agent = TutorAgent(object(), max_inflight=1)
        self.assertTrue(agent.capacity.acquire(blocking=False))
        self.addCleanup(agent.capacity.release)
        result = agent.respond(item, "请给个例子。", [])
        self.assertEqual(result["fallback_reason"], "llm_busy")

    def test_provider_timeout_uses_reviewed_hint(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]

        def fail(request):
            raise httpx.ReadTimeout("test timeout", request=request)

        model = ChatModel("https://example.invalid/v1", "mock", None, transport=httpx.MockTransport(fail))
        self.addCleanup(model.close)
        result = TutorAgent(model).respond(item, "请给个提示。", [])
        self.assertEqual((result["source"], result["text"], result["fallback_reason"]),
                         ("template", item.hint, "llm_timeout"))
