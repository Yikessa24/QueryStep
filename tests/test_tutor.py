import asyncio
import json
from dataclasses import replace
import sqlite3
import unittest

import httpx

from api.catalog import Catalog, DEFAULT_CATALOG
from course_content.knowledge_index import search_lessons
from tutor.agent import TutorAgent
from tutor.check_provider import choose_gemini, probe
from tutor.provider import ChatModel, measure_calls


def tool(name, arguments=None):
    return {"tool_calls": [{"id": "call-course", "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments if arguments is not None else {})}}]}


def action(name, text, sources):
    return {"content": json.dumps({"action": name, "text": text, "source_ids": sources})}


class TutorTest(unittest.TestCase):
    def test_provider_usage_meter_records_only_supported_counts(self):
        def handle(request):
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5, "other": "ignored"}})

        model = ChatModel("https://example.invalid/v1", "test", None, transport=httpx.MockTransport(handle))
        self.addCleanup(model.close)
        usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
        with measure_calls() as outer:
            self.assertEqual(model.reply([], [], 1), {"content": "ok"})
            with measure_calls() as inner:
                model.reply([], [], 1)
                with measure_calls() as nested:
                    model.reply([], [], 1)
            self.assertEqual(nested, [usage])
            self.assertEqual(inner, [usage, usage])
            self.assertEqual(outer, [usage, usage, usage])
            self.assertIs(outer[1], inner[0])
            self.assertIs(outer[2], nested[0])
            model.reply([], [], 1)
        model.reply([], [], 1)  # Leaving the scope restores the unmetered context.
        self.assertEqual(len(outer), 4)
        self.assertEqual(len(inner), 2)

    def test_provider_nested_failure_restores_outer_and_keeps_usage_unknown(self):
        responses = iter([
            httpx.Response(503),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "5"}}),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ])
        model = ChatModel("https://example.invalid/v1", "test", None,
                          transport=httpx.MockTransport(lambda request: next(responses)))
        self.addCleanup(model.close)
        with measure_calls() as outer:
            with self.assertRaises(httpx.HTTPStatusError):
                with measure_calls() as inner:
                    with measure_calls() as nested:
                        model.reply([], [], 1)
            self.assertEqual(outer, [{"error": "http_error", "http_status": 503}])
            self.assertIs(outer[0], nested[0])
            self.assertIs(inner[0], nested[0])
            model.reply([], [], 1)
            model.reply([], [], 1)
        failure = {"error": "http_error", "http_status": 503}
        self.assertEqual(outer, [failure, {}, {}])
        self.assertEqual(inner, [failure])

    def test_provider_failure_diagnostics_exclude_sensitive_details(self):
        async def check():
            for asynchronous in (False, True):
                for response, expected in (
                    (httpx.Response(429, json={"error": "SECRET"}), {"error": "http_error", "http_status": 429}),
                    (httpx.Response(200, content="SECRET"), {"error": "invalid_response"}),
                    (httpx.Response(200, json=[]), {"error": "invalid_response"}),
                    (httpx.ReadTimeout("SECRET"), {"error": "transport_timeout"}),
                    (httpx.ConnectError("SECRET"), {"error": "transport_error"}),
                ):
                    with self.subTest(asynchronous=asynchronous, expected=expected):
                        def handle(request):
                            if isinstance(response, Exception):
                                raise response
                            return response
                        model = ChatModel("https://example.invalid/v1", "test", "SECRET",
                                          transport=httpx.MockTransport(handle))
                        model._async_client = httpx.AsyncClient(base_url=model.client.base_url,
                                                               transport=httpx.MockTransport(handle))
                        try:
                            with measure_calls() as calls:
                                with self.assertRaises((httpx.HTTPError, ValueError, AttributeError)):
                                    if asynchronous:
                                        await model.reply_json([], 1, model="test")
                                    else:
                                        model.reply([], [], 1)
                            self.assertEqual(calls, [expected])
                            self.assertNotIn("SECRET", json.dumps(calls))
                        finally:
                            model.close()
                            await model.aclose()
        asyncio.run(check())

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

    def test_latest_five_turns_and_first_turn_recall_use_distinct_contexts(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        prior = [
            {"message": f"旧问题 {number}", "source": "llm", "action": "show_example",
             "text": f"旧例子 {number}，联系地址 learner@example.test。"}
            for number in range(1, 8)
        ]
        replies = iter([
            action("show_example", "回顾旧例子 3。", ["history-turn-3"]),
            tool("retrieve_tutor_history", {"turn_number": 1}),
            action("show_example", "回顾旧例子 1。", ["history-turn-1"]),
        ])
        requests = []

        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": next(replies)}]})

        model = ChatModel("https://example.invalid/v1", "test", None, transport=httpx.MockTransport(handle))
        self.addCleanup(model.close)
        agent = TutorAgent(model)
        recent = agent.respond(item, "回看第 3 轮的例子。", prior)
        recalled = agent.respond(item, "回到第一轮的例子。", prior)

        self.assertEqual(recent["trace"], [])
        self.assertEqual(recent["citations"][0]["id"], "history-turn-3")
        messages = requests[0]["messages"]
        self.assertEqual([entry["content"] for entry in messages[2:-1:2]],
                         [f"旧问题 {number}" for number in range(3, 8)])
        self.assertEqual(json.loads(messages[1]["content"])["course_context"]["recent_turn_numbers"], [3, 4, 5, 6, 7])
        self.assertNotIn("tool_choice", requests[0])
        self.assertNotIn("旧例子 1", str(requests[1]["messages"]))
        self.assertEqual(requests[1]["tool_choice"]["function"]["name"], "retrieve_tutor_history")
        observation = requests[2]["messages"][-1]
        self.assertEqual((observation["role"], observation["tool_call_id"]), ("tool", "call-course"))
        recalled_turn = json.loads(observation["content"])
        self.assertEqual(recalled_turn["text"][0]["content"], "旧问题 1")
        self.assertIn("旧例子 1", recalled_turn["text"][1]["content"])
        self.assertNotIn("learner@example.test", str(requests))
        self.assertEqual(recalled["trace"],
                         [{"tool": "retrieve_tutor_history", "source_id": "history-turn-1", "turn_number": 1}])
        self.assertEqual(recalled["citations"],
                         [{"id": "history-turn-1", "title": "本题第 1 轮对话", "turn_number": 1}])

    def test_history_tool_rejects_invalid_or_unrequested_turn(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        prior = [{"message": "早期问题", "source": "llm", "text": "早期回答。"}] * 7
        for args in ({"turn_number": True}, {"turn_number": 1.0}, {"turn_number": "1"},
                     {"turn_number": 2}, {"turn_number": 1, "decision_id": "another-exercise"}):
            with self.subTest(args=args):
                class FakeModel:
                    def reply(self, messages, tools, timeout, **kwargs):
                        return tool("retrieve_tutor_history", args)

                agent = TutorAgent(FakeModel())
                for message in ("请回到第 1 轮。", "之前的例子是哪个？"):
                    result = agent.respond(item, message, prior)
                    self.assertEqual(result["fallback_reason"], "invalid_tool_call")
                    self.assertEqual(result["trace"], [])

        unavailable = TutorAgent(object()).respond(item, "请回到第 9 轮。", prior)
        self.assertEqual((unavailable["action"], unavailable["fallback_reason"]),
                         ("ask_clarifying", "history_turn_unavailable"))
        self.assertIn("7 轮问答", unavailable["text"])

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

    def test_course_tool_searches_for_follow_up_and_only_exposes_returned_citations(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        query = "LOWER 遇到大小写不一样的名称时怎么比较？"

        class FakeModel:
            def __init__(self, final_source):
                self.final_source = final_source

            def reply(self, messages, tools, timeout):
                if messages[-1]["role"] == "user":
                    schema = tools[0]["function"]["parameters"]
                    self_search.assertIn("query", schema["properties"])
                    return tool("retrieve_course_notes", {"query": query})
                payload = json.loads(messages[-1]["content"])
                self_search.assertFalse(payload["used_reviewed_note"])
                self_search.assertTrue(any(card["id"] == "text-case/lower-ascii" and "ASCII" in card["text"]
                                           for card in payload["cards"]))
                return action("give_hint", "先把字母转成小写，再和筛选条件比较。", [self.final_source])

        self_search = self
        for source in ("text-case/lower-ascii", "invented/source"):
            result = TutorAgent(FakeModel(source), course_search=search_lessons).respond(item, "那大小写呢？", [])
            self.assertIn("text-case/lower-ascii", result["trace"][0]["retrieved_ids"])
            self.assertEqual(result["trace"][0]["retrieval_mode"], "reviewed_cards")
            if source == "invented/source":
                self.assertEqual(result["fallback_reason"], "invalid_citation")
            else:
                self.assertEqual(result["citations"], [{"id": source, "title": "LOWER 将 ASCII 字母转为小写",
                                                       "url": "https://www.sqlite.org/lang_corefunc.html#lower"}])

    def test_course_tool_uses_reviewed_note_on_empty_search_or_error(self):
        item = Catalog.load(DEFAULT_CATALOG).items[2]
        query = "MySQL 中如何用 JSON_TABLE 展开数组？"

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError()

        class FakeModel:
            def reply(self, messages, tools, timeout):
                if messages[-1]["role"] == "user":
                    return tool("retrieve_course_notes")
                payload = json.loads(messages[-1]["content"])
                self_search.assertTrue(payload["used_reviewed_note"])
                self_search.assertEqual([card["id"] for card in payload["cards"]], ["note-where"])
                return action("give_hint", "课程里可以先判断每一行是否满足条件。", ["note-where"])

        self_search = self
        for search, mode in ((search_lessons, "reviewed_cards"), (unavailable, "reviewed_note")):
            with self.subTest(mode=mode):
                result = TutorAgent(FakeModel(), course_search=search).respond(item, query, [])
                self.assertEqual(result["trace"][0]["retrieval_mode"], mode)
                self.assertEqual(result["trace"][0]["retrieved_ids"], [])
                self.assertEqual(result["citations"][0]["id"], "note-where")

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
