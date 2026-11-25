"""Offline evaluation tests. No network provider, API keys, or dotenv loading."""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import copy
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import anyio

from evals.workbench import (ARMS, BoundedModel, Oracle, SYNTHETIC_SNAPSHOT, ToolAdapter,
                            arm_budget, assess_result, blinded_annotations, extract_verdict,
                            frozen_input, main, outcome_flags, parse_baseline, run_arm,
                            summarize, usage_summary, validate_counterexample, validate_labels)
from evals.workbench_cases import (CASES, DEV_TASKS, SCENARIOS, SEEDS, TEST_TASKS,
                                 select_cases, suite_hash)
from tutor.provider import ChatModel


class ScriptedModel:
    """Emits authored test JSON; it never constructs a transport or calls a provider."""

    def __init__(self, *responses, metered_usage=None):
        self.responses = list(responses)
        self.messages = []
        self.metered_usage = metered_usage

    async def reply_json(self, messages, timeout, *, model, max_tokens=256):
        self.messages.append(copy.deepcopy(messages))
        if self.metered_usage is not None:
            record = ChatModel._start_call()
            if record is not None:
                record.update(self.metered_usage)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return await response()
        return {"content": response if isinstance(response, str) else json.dumps(response)}


def action(name, **args):
    return {"actions": [{"name": name, "args": args}]}


def finish(identifier="e1"):
    return {"finish": {"kind": "answer", "citations": [{"id": identifier}], "context_use": "none"}}


def baseline_reply(verdict="passed", **extra):
    return {"verdict": verdict, "hint": "请按题面核对边界。", "citations": [], "counterexample": None, **extra}


def check_evidence(identifier, scenarios, seed=0):
    return {"id": identifier, "tool": "check_student_sql", "args": {"scenarios": list(scenarios), "seed": seed},
            "data": {"status": "passed", "passed": True, "checked": len(scenarios), "total": len(scenarios),
                     "counterexample": None}}


class FakeLab:
    def __init__(self, *, check=None):
        self.calls = []
        self.check = check

    async def call(self, role, name, args, *, timeout):
        self.calls.append((role, name, copy.deepcopy(args)))
        if name == "search_course_knowledge":
            return {"mode": "reviewed_cards", "cards": [
                {"id": "course-null", "title": "NULL", "text": "NULL 不是空字符串。",
                 "source_url": "/course/null"}]}
        if name == "inspect_student_sql":
            return {"valid": True, "error": None}
        if name == "check_student_sql":
            return copy.deepcopy(self.check or {"status": "passed", "passed": True,
                                                "checked": len(args["scenarios"]), "total": len(args["scenarios"]),
                                                "counterexample": None, "query_result": None})
        raise AssertionError(name)


def lab_factory(lab, *, grouped=False):
    @asynccontextmanager
    async def opened(scope, *, knowledge_args):
        assert scope == "workbench"
        if grouped:
            # Like MCP, AnyIO wraps exceptions escaping the context body.
            async with anyio.create_task_group():
                yield lab
        else:
            yield lab
    return opened


def metric_row(expected="passed", predicted="passed", *, arm="direct", reason=None, mode="structured"):
    result = {"mode": mode, "metrics": {"finish_reason": reason or "answer"}}
    return {"arm": arm, "expected": expected, "predicted": predicted,
            "false_accusation": expected == "passed" and predicted in {"mismatch", "rejected"},
            "verdict_correct": expected == predicted, "counterexamples": [], "evidence_consistent": None,
            "elapsed_ms": 10, "model_attempts": 1, "tool_attempts": 0, "usage": [{}],
            **outcome_flags(result)}


class SuiteDefinitionTest(unittest.TestCase):
    def test_exactly_100_unique_executable_programs(self):
        self.assertEqual(len(CASES), 100)
        self.assertEqual(len({case.id for case in CASES}), 100)
        normalized = {" ".join(case.sql.lower().split()) for case in CASES}
        self.assertEqual(len(normalized), 100)
        self.assertTrue(all(case.sql.startswith("SELECT ") for case in CASES))
        self.assertEqual(set(Counter(case.task_id for case in CASES).values()), {10})
        self.assertTrue(all(case.family and case.rationale for case in CASES))
        self.assertEqual(Counter(case.expected for case in CASES),
                         {"passed": 30, "mismatch": 67, "rejected": 3})
        self.assertGreaterEqual(sum(case.sample_passes_boundary_fails for case in CASES), 20)
        for task_id in (*DEV_TASKS, *TEST_TASKS):
            self.assertEqual(sum(c.task_id == task_id and c.expected == "passed" for c in CASES), 3)

    def test_task_disjoint_fixed_splits(self):
        self.assertEqual(len(DEV_TASKS), 6)
        self.assertEqual(len(TEST_TASKS), 4)
        self.assertFalse(set(DEV_TASKS) & set(TEST_TASKS))
        self.assertEqual(set(DEV_TASKS) | set(TEST_TASKS), {case.task_id for case in CASES})
        self.assertEqual(len(select_cases("dev")), 60)
        self.assertEqual(len(select_cases("test")), 40)
        self.assertFalse({c.task_id for c in select_cases("dev")} & {c.task_id for c in select_cases("test")})
        with self.assertRaises(ValueError):
            select_cases("test", [CASES[0].id])
        with self.assertRaises(ValueError):
            select_cases("all", ["not-a-case"])
        with self.assertRaises(ValueError):
            select_cases("all", limit=0)
        self.assertEqual(select_cases("all", limit=2), list(CASES[:2]))

    def test_version_hash_is_frozen(self):
        self.assertEqual(suite_hash(), "9032de048dacf46e08e4da2047e0682685337cae36262744efd6ab599d58f938")

    def test_public_input_excludes_answer_and_case_labels(self):
        with patch("evals.workbench.task_view", return_value={
            "id": "filter_paid", "prompt": "public", "topic": "where", "tables": [],
            "reference_sql": "PRIVATE_SENTINEL", "solution": "PRIVATE_SENTINEL",
        }):
            serialized = json.dumps(frozen_input(CASES[0]))
        self.assertNotIn("PRIVATE_SENTINEL", serialized)
        self.assertNotIn("reference_sql", serialized)
        self.assertNotIn("rationale", serialized)
        self.assertNotIn('"expected"', serialized)

    def test_label_validation_never_rewrites_labels_or_short_circuits_scenarios(self):
        class FakeOracle:
            def __init__(self):
                self.calls = []

            def check(self, task_id, sql, scenarios, seed):
                self.calls.append((scenarios, seed))
                return {"status": "mismatch"}

        oracle = FakeOracle()
        original = CASES[0]
        validation = validate_labels([original], oracle=oracle, concurrency=1)
        self.assertFalse(validation["passed"])
        self.assertFalse(validation["labels_changed"])
        self.assertEqual(original.expected, "passed")
        self.assertEqual(len(oracle.calls), len(SCENARIOS) * len(SEEDS))
        self.assertEqual(validation["runs"][0]["expected"], "passed")

    def test_validate_labels_cli_never_constructs_chatmodel(self):
        with patch("evals.workbench.ChatModel", side_effect=AssertionError("provider must not load")), \
                patch("evals.workbench.validate_labels", return_value={
                    "passed": True, "cases": 1, "failures": []}), \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(main(["--validate-labels", "--split", "dev", "--limit", "1"]), 0)

    def test_refuses_overwrite_before_any_provider_or_engine_work(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("preserve", encoding="utf-8")
            with patch("evals.workbench.ChatModel", side_effect=AssertionError), \
                    patch("evals.workbench.validate_labels", side_effect=AssertionError), \
                    patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                main(["--output", str(output)])
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve")

    def test_concurrency_cannot_exceed_three(self):
        with patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
            main(["--validate-labels", "--concurrency", "4"])
        with self.assertRaises(ValueError):
            validate_labels([], concurrency=4)


class MetricsTest(unittest.TestCase):
    def test_false_accusation_denominator_is_all_correct_queries(self):
        rows = [metric_row("passed", "mismatch"), metric_row("passed", "unknown"),
                metric_row("passed", "rejected"), metric_row("mismatch", "mismatch"),
                metric_row("rejected", "rejected"), metric_row("mismatch", "passed")]
        summary = summarize(rows)["direct"]
        self.assertEqual(summary["correct_query_denominator"], 3)
        self.assertEqual(summary["false_accusations"], 2)
        self.assertEqual(summary["false_accusation_rate"], 2 / 3)
        self.assertEqual(summary["diagnosis_verdict_accuracy"], 2 / 6)
        self.assertEqual(summary["abstentions"], 1)
        self.assertIsNone(summarize([metric_row("mismatch", "mismatch")])["direct"]["false_accusation_rate"])

    def test_missing_and_partial_usage_remains_null_not_zero(self):
        self.assertIsNone(usage_summary([])["tokens"]["total_tokens"])
        unknown = usage_summary([{}, {}])
        self.assertEqual(unknown["provider_calls"], 2)
        self.assertIsNone(unknown["tokens"]["total_tokens"])
        self.assertIsNone(unknown["cost"])
        partial = usage_summary([{"total_tokens": 12, "prompt_tokens": 8}, {"prompt_tokens": 2}])
        self.assertIsNone(partial["tokens"]["total_tokens"])
        self.assertEqual(partial["tokens"]["prompt_tokens"], 10)
        self.assertEqual(partial["reported_partial_tokens"]["total_tokens"], 12)
        self.assertEqual(partial["calls_reporting_tokens"]["total_tokens"], 1)
        measured = usage_summary([{"total_tokens": 0}, {"total_tokens": 4}])
        self.assertEqual(measured["tokens"]["total_tokens"], 4)
        self.assertIsNone(usage_summary([{"total_tokens": True}])["tokens"]["total_tokens"])

    def test_timeout_and_fallback_counts_are_not_successes(self):
        rows = [metric_row("passed", "unknown", reason="model_timeout", mode="evidence_only"),
                metric_row("mismatch", "unknown", reason="invalid_plan", mode="evidence_only"),
                metric_row("passed", "unknown", reason="clarify"),
                metric_row("mismatch", "unknown", reason="budget_exhausted", mode="evidence_only")]
        summary = summarize(rows)["direct"]
        self.assertEqual(summary["fallback_count"], 3)
        self.assertEqual(summary["timeout_count"], 2)
        self.assertEqual(summary["false_accusations"], 0)
        self.assertEqual(summary["diagnosis_verdict_accuracy"], 0)
        self.assertIsNone(summary["usage"]["tokens"]["total_tokens"])
        self.assertIsNone(summary["evidence_consistency_rate"])
        self.assertIsNone(summary["teaching_quality"])
        self.assertIsNone(summary["learning_gains"])
        flags = outcome_flags({"mode": "agent", "metrics": {"finish_reason": "answer"}},
                              audit=[{"data": {"status": "timeout"}}])
        self.assertEqual(flags["timeout_reasons"], ["sql_timeout"])
        inspection = outcome_flags({"mode": "agent", "metrics": {"finish_reason": "invalid_sql"}},
                                   audit=[{"data": {"valid": False, "error": "query_timeout"}}])
        self.assertEqual(inspection["timeout_reasons"], ["sql_timeout"])

    def test_current_passed_status_requires_cited_full_check(self):
        entry = {"id": "e1", "tool": "check_student_sql", "args": {"scenarios": list(SCENARIOS)},
                 "data": {"status": "passed", "passed": True, "checked": 4, "total": 4,
                          "counterexample": None}}
        result = {"evidence": [entry], "citations": [{"id": "e1"}]}
        self.assertEqual(extract_verdict(result, "agent"), ("passed", "cited_full_finite_check"))
        entry["args"]["scenarios"] = ["sample"]
        entry["data"].update(checked=1, total=1)
        self.assertEqual(extract_verdict(result, "agent")[0], "unknown")
        entry["data"].update(status="error", passed=False)
        self.assertEqual(extract_verdict(result, "agent")[0], "unknown")

    def test_cited_completed_checks_union_coverage_at_one_seed(self):
        for arm in ("agent", "agent_without_context"):
            for first, second in ((SCENARIOS[:2], SCENARIOS[2:]), (SCENARIOS[:1], SCENARIOS[1:]),
                                  (SCENARIOS[:3], SCENARIOS[2:])):
                with self.subTest(arm=arm, first=first, second=second):
                    result = {"evidence": [check_evidence("e1", first, 7), check_evidence("e2", second, 7)],
                              "citations": [{"id": "e1"}, {"id": "e2"}]}
                    self.assertEqual(extract_verdict(result, arm), ("passed", "cited_full_finite_check"))
        # The coach's omitted seed defaults to zero; explicit zero is the same fixture.
        result["evidence"][0]["args"].pop("seed")
        result["evidence"][1]["args"]["seed"] = 0
        self.assertEqual(extract_verdict(result, "agent")[0], "passed")

    def test_partial_uncited_errored_or_cross_seed_checks_do_not_complete_coverage(self):
        for problem in ("partial", "uncited", "entry_error", "status_error", "not_passed", "incomplete",
                        "wrong_total", "different_seed", "invalid_seed", "duplicate_coverage", "extra_scenario"):
            with self.subTest(problem=problem):
                first, second = check_evidence("e1", SCENARIOS[:2]), check_evidence("e2", SCENARIOS[2:])
                result = {"evidence": [first, second], "citations": [{"id": "e1"}, {"id": "e2"}]}
                if problem == "partial":
                    result["evidence"].pop()
                elif problem == "uncited":
                    result["citations"].pop()
                elif problem == "entry_error":
                    second["error"] = "tool_error"
                elif problem == "status_error":
                    second["data"]["status"] = "error"
                elif problem == "not_passed":
                    second["data"]["passed"] = False
                elif problem == "incomplete":
                    second["data"]["checked"] = 1
                elif problem == "wrong_total":
                    second["data"].update(checked=4, total=4)
                elif problem == "different_seed":
                    second["args"]["seed"] = 1
                elif problem == "invalid_seed":
                    second["args"]["seed"] = False
                elif problem == "duplicate_coverage":
                    second["args"]["scenarios"] = first["args"]["scenarios"]
                else:
                    second["args"]["scenarios"].append("unregistered")
                    second["data"].update(checked=3, total=3)
                self.assertEqual(extract_verdict(result, "agent"), ("unknown", "no_decisive_exposed_evidence"))

    def test_decisive_uncited_evidence_precedes_full_union_coverage(self):
        for decisive, expected in (
            ({"tool": "inspect_student_sql", "data": {"valid": False}}, ("rejected", "exposed_inspection")),
            ({"tool": "check_student_sql", "data": {"status": "rejected"}}, ("rejected", "exposed_check_rejection")),
            ({"tool": "check_student_sql", "data": {"status": "mismatch", "counterexample": {"scenario": "boundary"}}},
             ("mismatch", "exposed_counterexample")),
        ):
            with self.subTest(expected=expected):
                result = {"evidence": [check_evidence("e1", SCENARIOS[:2]), check_evidence("e2", SCENARIOS[2:]),
                                       decisive], "citations": [{"id": "e1"}, {"id": "e2"}]}
                self.assertEqual(extract_verdict(result, "agent"), expected)
                decisive["error"] = "tool_error"
                self.assertEqual(extract_verdict(result, "agent")[0], "passed")

    def test_check_rejection_is_distinct_from_execution_failure(self):
        entry = {"id": "e1", "tool": "check_student_sql", "data": {"status": "rejected"}}
        result = {"evidence": [entry], "citations": []}
        self.assertEqual(extract_verdict(result, "agent"), ("rejected", "exposed_check_rejection"))
        entry["data"]["status"] = "error"
        self.assertEqual(extract_verdict(result, "agent")[0], "unknown")

    def test_baseline_cannot_supply_labels_or_out_of_contract_verdicts(self):
        for reply in (baseline_reply("error"), {**baseline_reply(), "expected": "passed"},
                      baseline_reply(citations=[{"id": "fake"}]), ["passed"], "not json"):
            with self.subTest(reply=reply), self.assertRaises((ValueError, TypeError)):
                parse_baseline({"content": json.dumps(reply)})
        self.assertEqual(parse_baseline({"content": json.dumps(baseline_reply())})["verdict"], "passed")

    def test_baseline_accepts_only_bounded_enclosing_json_fence(self):
        body = json.dumps(baseline_reply())
        expected = parse_baseline({"content": body})
        for content in (f"```json\n{body}\n```", f" \n```json\n{body}\n```\t", f"```\n{body}\n```"):
            with self.subTest(content=content):
                self.assertEqual(parse_baseline({"content": content}), expected)
        for content in (f"Explanation\n```json\n{body}\n```", f"```json\n{body}\n```\nExplanation",
                        f"```json\n{body}\n```\n```json\n{body}\n```", f"```json\n```json\n{body}\n```\n```",
                        f"```python\n{body}\n```", f"```JSON\n{body}\n```", f"```json\n{body}",
                        f"```json\n{body}\n{body}\n```", " " * 24000 + f"```json\n{body}\n```"):
            with self.subTest(content=content[:100]), self.assertRaises(ValueError):
                parse_baseline({"content": content})

    def test_fences_do_not_relax_baseline_schema(self):
        for reply in (baseline_reply("error"), baseline_reply(expected="passed"), baseline_reply(hint=" "),
                      baseline_reply(hint="x" * 1601), baseline_reply(citations=[{"id": "fake"}]),
                      baseline_reply(counterexample=[]), baseline_reply(counterexample={"seed": float("nan")}),
                      baseline_reply(counterexample={"seed": float("inf")}), ["passed"]):
            for fence in ("json", ""):
                with self.subTest(reply=reply, fence=fence), self.assertRaises((ValueError, TypeError)):
                    parse_baseline({"content": f"```{fence}\n{json.dumps(reply)}\n```"})
        for reply in (None, [], {}, {"content": None}, {"content": baseline_reply()}):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                parse_baseline(reply)

    def test_evidence_integrity_and_quote_validation(self):
        data = {"cards": [{"id": "c", "citation_id": "r1.c1", "title": "NULL", "text": "NULL is unknown.", "url": "/null"}]}
        entry = {"id": "r1", "tool": "search_course", "args": {"query": "NULL"}, "data": data}
        report = {"verdict": "passed", "evidence": [entry], "citations": [{"id": "r1.c1", "quote": "NULL is unknown."}]}
        audit = [{"tool": "search_course", "args": {"query": "NULL"}, "data": copy.deepcopy(data)}]
        self.assertTrue(assess_result(CASES[0], "rag", report, audit, Oracle())["evidence_consistent"])
        report["citations"][0]["quote"] = "NULL equals zero."
        self.assertFalse(assess_result(CASES[0], "rag", report, audit, Oracle())["evidence_consistent"])
        report["citations"] = []
        report["evidence"][0]["data"]["cards"][0]["text"] = "fabricated"
        self.assertFalse(assess_result(CASES[0], "rag", report, audit, Oracle())["evidence_consistent"])
        self.assertIsNone(assess_result(CASES[0], "direct", baseline_reply(), [], Oracle())["evidence_consistent"])

    def test_budget_differences_are_explicit(self):
        direct, rag, agent = (arm_budget(arm) for arm in ARMS[:3])
        self.assertEqual((direct["model_call_limit"], rag["model_call_limit"], agent["model_call_limit"]), (1, 1, 5))
        self.assertEqual((direct["tool_call_limit"], rag["tool_call_limit"], agent["tool_call_limit"]), (0, 1, 6))
        self.assertEqual(agent["total_requested_output_token_limit"], 3840)
        self.assertIsNone(agent["input_token_limit"])
        self.assertEqual(agent, arm_budget("agent_without_context"))

    def test_blinding_removes_explicit_arm_model_and_gold(self):
        row = {"case_id": "private-case-id", "arm": "agent_without_context", "expected": "passed",
               "model": "private-model", "input": frozen_input(CASES[0]),
               "result": {"text": "一个提示", "question": None, "evidence": [], "citations": [],
                          "metrics": {"model": "private-model"}}}
        annotations, key = blinded_annotations([row])
        serialized = json.dumps(annotations)
        for token in ("private-case-id", "agent_without_context", "private-model", '"expected"'):
            self.assertNotIn(token, serialized)
        self.assertEqual(len(key), 1)
        self.assertTrue(all(value is None for value in annotations["items"][0]["manual_review"].values()))
        self.assertEqual(row["arm"], "agent_without_context")


class ExecutionTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_binding_and_same_audited_retrieval(self):
        public, lab = frozen_input(CASES[0]), FakeLab()
        adapter = ToolAdapter(lab, public, arm_budget("agent"))
        await adapter("search_course", {"query": "边界"})
        self.assertEqual(lab.calls[0], ("workbench", "search_course_knowledge",
                                      {"query": "边界", "topic": public["task"]["topic"], "top_k": 3}))
        await adapter("inspect_student_sql", {})
        self.assertEqual(lab.calls[1][2], {"task_id": CASES[0].task_id, "sql": CASES[0].sql})
        for name, args in (("inspect_student_sql", {"sql": "SELECT secret"}),
                           ("run_student_sql", {"task_id": "other"}), ("get_reference_sql", {})):
            with self.assertRaises(ValueError):
                await adapter(name, args)
        self.assertEqual(len(lab.calls), 2)

    async def test_output_and_input_budgets_prevent_extra_calls(self):
        model = ScriptedModel(baseline_reply())
        bounded = BoundedModel(model, arm_budget("direct"))
        await bounded.reply_json([], 1, model="offline", max_tokens=99999)
        self.assertEqual(bounded.requested_output_tokens, [512])
        with self.assertRaises(ValueError):
            await bounded.reply_json([], 1, model="offline")
        self.assertEqual(len(model.messages), 1)
        other = BoundedModel(ScriptedModel(), arm_budget("direct"))
        with self.assertRaises(ValueError):
            await other.reply_json([{"content": "x" * 70000}], 1, model="offline")
        self.assertEqual(other.attempts, 0)
        self.assertEqual(other.last_failure, "input_budget")

    async def test_direct_uses_meter_not_invented_coach_usage(self):
        model = ScriptedModel(baseline_reply(), metered_usage={"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12})
        row = await run_arm(CASES[0], "direct", model, "offline", frozen_input(CASES[0]))
        self.assertEqual(row["usage_summary"]["tokens"]["total_tokens"], 12)
        self.assertEqual(row["usage_summary"]["provider_calls"], 1)
        self.assertIsNone(row["usage_summary"]["cost"])
        self.assertTrue(row["verdict_correct"])
        self.assertEqual(row["tool_attempts"], 0)
        self.assertNotIn("reference_sql", json.dumps(model.messages))

    async def test_rag_uses_same_input_and_records_retrieval(self):
        public = frozen_input(CASES[0])
        model = ScriptedModel(baseline_reply(citations=[{"id": "r1.c1", "quote": "NULL 不是空字符串。"}]))
        lab = FakeLab()
        row = await run_arm(CASES[0], "rag", model, "offline", public, lab_factory=lab_factory(lab))
        payload = json.loads(model.messages[0][-1]["content"])
        self.assertEqual({key: payload[key] for key in public}, public)
        self.assertTrue(row["evidence_consistent"])
        self.assertEqual(row["tool_attempts"], 1)
        self.assertIsNone(row["usage_summary"]["tokens"]["total_tokens"])
        self.assertEqual(lab.calls[0][1], "search_course_knowledge")

    async def test_baseline_validation_is_classified_before_anyio_context_unwinds(self):
        for arm in ("direct", "rag"):
            for response in ("PRIVATE_SECRET broken JSON", baseline_reply(hint="PRIVATE_SECRET", expected="passed"),
                             baseline_reply(verdict=[])):
                with self.subTest(arm=arm, response=response):
                    model, lab = ScriptedModel(response), FakeLab()
                    row = await run_arm(CASES[0], arm, model, "offline", frozen_input(CASES[0]),
                                        lab_factory=lab_factory(lab, grouped=True))
                    self.assertEqual(row["fallback_reason"], "invalid_response")
                    self.assertEqual(row["result"]["metrics"]["finish_reason"], "invalid_response")
                    self.assertEqual(row["result"]["mode"], "error")
                    self.assertEqual(row["predicted"], "unknown")
                    self.assertFalse(row["timeout"])
                    self.assertFalse(row["false_accusation"])
                    self.assertEqual(row["model_attempts"], 1)
                    self.assertEqual(row["tool_attempts"], int(arm == "rag"))
                    self.assertEqual(row["result"]["citations"], [])
                    self.assertNotIn("PRIVATE_SECRET", json.dumps(row))
                    if arm == "rag":
                        payload = json.loads(model.messages[0][-1]["content"])
                        self.assertEqual(row["result"]["evidence"], payload["evidence"])
                        self.assertEqual(row["result"]["evidence"][0]["data"]["cards"][0]["citation_id"], "r1.c1")
                        self.assertEqual(row["tool_audit"][0]["data"]["cards"][0]["text"], "NULL 不是空字符串。")
                        self.assertTrue(row["evidence_consistent"])
                    else:
                        self.assertEqual(row["result"]["evidence"], [])
                        self.assertIsNone(row["evidence_consistent"])

    async def test_baseline_infrastructure_failures_are_not_response_validation(self):
        for grouped in (False, True):
            for phase in ("setup", "retrieval", "cleanup"):
                with self.subTest(grouped=grouped, phase=phase):
                    lab = FakeLab()

                    @asynccontextmanager
                    async def failing_lab(scope, *, knowledge_args):
                        async with lab_factory(lab, grouped=grouped)(scope, knowledge_args=knowledge_args):
                            if phase == "setup":
                                raise ValueError("PRIVATE_SECRET")
                            yield lab
                            if phase == "cleanup":
                                raise TypeError("PRIVATE_SECRET")

                    model = ScriptedModel("PRIVATE_SECRET invalid JSON")
                    if phase == "retrieval":
                        with patch.object(lab, "call", side_effect=KeyError("PRIVATE_SECRET")):
                            row = await run_arm(CASES[0], "rag", model, "offline", frozen_input(CASES[0]),
                                                lab_factory=failing_lab)
                        self.assertEqual(row["tool_audit"][0]["error"], "tool_error")
                    else:
                        row = await run_arm(CASES[0], "rag", model, "offline", frozen_input(CASES[0]),
                                            lab_factory=failing_lab)
                    self.assertEqual(row["fallback_reason"], "lab_or_coach_error")
                    self.assertEqual(row["model_attempts"], int(phase == "cleanup"))
                    self.assertFalse(row["timeout"])
                    self.assertNotIn("PRIVATE_SECRET", json.dumps(row))
                    if phase == "cleanup":
                        self.assertTrue(row["evidence_consistent"])
                        self.assertEqual(len(row["result"]["evidence"]), 1)

    async def test_rag_model_failures_keep_their_failure_classification(self):
        for error, reason in ((ValueError("PRIVATE_SECRET"), "model_error"), (httpx_timeout(), "model_timeout")):
            with self.subTest(reason=reason):
                row = await run_arm(CASES[0], "rag", ScriptedModel(error), "offline", frozen_input(CASES[0]),
                                    lab_factory=lab_factory(FakeLab(), grouped=True))
                self.assertEqual(row["fallback_reason"], reason)
                self.assertEqual(row["tool_attempts"], 1)
                self.assertNotIn("PRIVATE_SECRET", json.dumps(row))

    async def test_baseline_cancellation_propagates(self):
        for arm in ("direct", "rag"):
            with self.subTest(arm=arm):
                entered = asyncio.Event()

                async def blocked():
                    entered.set()
                    await asyncio.Event().wait()

                task = asyncio.create_task(run_arm(
                    CASES[0], arm, ScriptedModel(blocked), "offline", frozen_input(CASES[0]),
                    lab_factory=lab_factory(FakeLab(), grouped=True),
                ))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=5)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)

    async def test_agent_context_ablation_preserves_frozen_input(self):
        inputs, contexts = [], []
        for arm in ("agent", "agent_without_context"):
            model = ScriptedModel(action("check_student_sql", scenarios=list(SCENARIOS), seed=0), finish())
            row = await run_arm(CASES[0], arm, model, "offline", frozen_input(CASES[0]),
                                context=SYNTHETIC_SNAPSHOT, lab_factory=lab_factory(FakeLab()))
            payload = json.loads(model.messages[0][-1]["content"])
            inputs.append((payload["task"], payload["student_sql"], payload["message"], row["input_hash"]))
            contexts.append(payload["learning_context"])
            self.assertTrue(row["verdict_correct"])
            self.assertTrue(row["evidence_consistent"])
            self.assertEqual(row["model_attempts"], 2)
        self.assertEqual(inputs[0], inputs[1])
        self.assertEqual(contexts[0], SYNTHETIC_SNAPSHOT)
        self.assertEqual(contexts[1], {})
        self.assertFalse(contexts[0]["provenance"]["actual_epikt_inference"])

    async def test_agent_model_timeout_preserves_evidence_and_counts_fallback(self):
        model = ScriptedModel(action("inspect_student_sql"), httpx_timeout())
        row = await run_arm(CASES[0], "agent", model, "offline", frozen_input(CASES[0]),
                            lab_factory=lab_factory(FakeLab()))
        self.assertTrue(row["timeout"])
        self.assertEqual(row["fallback_reason"], "model_timeout")
        self.assertEqual(row["model_attempts"], 2)
        self.assertEqual(len(row["result"]["evidence"]), 1)
        self.assertEqual(row["predicted"], "unknown")
        self.assertNotIn("PRIVATE_SECRET", json.dumps(row))

    async def test_real_async_deadline_and_invalid_json_accounting(self):
        async def blocked():
            await asyncio.Event().wait()

        row = await run_arm(CASES[0], "direct", ScriptedModel(blocked), "offline", frozen_input(CASES[0]),
                            budget_seconds=0.02)
        self.assertTrue(row["timeout"])
        self.assertEqual(row["fallback_reason"], "active_timeout")
        row = await run_arm(CASES[0], "direct", ScriptedModel("broken JSON"), "offline", frozen_input(CASES[0]))
        self.assertEqual(row["fallback_reason"], "invalid_response")
        self.assertFalse(row["timeout"])
        self.assertEqual(row["predicted"], "unknown")
        self.assertFalse(row["false_accusation"])

    async def test_real_mcp_adapter_and_engine_with_scripted_nonprovider_model(self):
        case = next(case for case in CASES if case.id == "left_join_filter.04")
        model = ScriptedModel(action("check_student_sql", scenarios=["sample"], seed=0),
                              action("check_student_sql", scenarios=["boundary"], seed=0), finish("e2"))
        row = await run_arm(case, "agent", model, "offline-scripted", frozen_input(case))
        self.assertEqual(row["predicted"], "mismatch")
        self.assertTrue(row["verdict_correct"])
        self.assertTrue(row["evidence_consistent"])
        self.assertTrue(row["counterexamples"][0]["valid"])
        self.assertTrue(row["counterexamples"][0]["payload_verified"])
        self.assertEqual(row["model_attempts"], 3)
        self.assertEqual(row["tool_attempts"], 2)
        self.assertEqual(row["usage_summary"]["provider_calls"], 0)
        self.assertIsNone(row["fallback_reason"])

    async def test_real_mcp_split_checks_count_as_full_finite_coverage(self):
        model = ScriptedModel(
            action("check_student_sql", scenarios=list(SCENARIOS[:2]), seed=0),
            action("check_student_sql", scenarios=list(SCENARIOS[2:]), seed=0),
            {"finish": {"kind": "answer", "citations": [{"id": "e1"}, {"id": "e2"}], "context_use": "none"}},
        )
        row = await run_arm(CASES[0], "agent", model, "offline-scripted", frozen_input(CASES[0]))
        self.assertEqual((row["predicted"], row["verdict_basis"]), ("passed", "cited_full_finite_check"))
        self.assertTrue(row["evidence_consistent"])
        self.assertEqual(row["model_attempts"], 3)
        self.assertEqual(row["tool_attempts"], 2)
        self.assertEqual([entry["data"]["checked"] for entry in row["result"]["evidence"]], [2, 2])
        self.assertEqual(row["usage_summary"]["provider_calls"], 0)
        self.assertIsNone(row["fallback_reason"])

    async def test_real_mcp_rag_invalid_response_retains_retrieved_evidence(self):
        model = ScriptedModel("PRIVATE_SECRET invalid JSON")
        row = await run_arm(CASES[0], "rag", model, "offline-scripted", frozen_input(CASES[0]))
        payload = json.loads(model.messages[0][-1]["content"])
        self.assertEqual(row["fallback_reason"], "invalid_response")
        self.assertEqual(row["predicted"], "unknown")
        self.assertEqual(row["result"]["evidence"], payload["evidence"])
        self.assertEqual(len(row["result"]["evidence"]), 1)
        self.assertTrue(row["evidence_consistent"])
        self.assertEqual(row["tool_attempts"], 1)
        self.assertEqual(row["usage_summary"]["provider_calls"], 0)
        self.assertFalse(row["timeout"])
        self.assertNotIn("PRIVATE_SECRET", json.dumps(row))

    async def test_provider_error_does_not_leak_secret(self):
        row = await run_arm(CASES[0], "direct", ScriptedModel(RuntimeError("PRIVATE_SECRET")),
                            "offline", frozen_input(CASES[0]))
        self.assertEqual(row["fallback_reason"], "model_error")
        self.assertNotIn("PRIVATE_SECRET", json.dumps(row))

    async def test_warm_shared_lab_reuses_mcp_session_without_cold_launch(self):
        lab = FakeLab()
        model = ScriptedModel(action("check_student_sql", scenarios=list(SCENARIOS), seed=0), finish())
        row = await run_arm(CASES[0], "agent", model, "offline", frozen_input(CASES[0]),
                            lab_factory=lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not cold start")),
                            shared_lab=lab)
        self.assertTrue(row["verdict_correct"])
        self.assertEqual(row["tool_attempts"], 1)
        self.assertEqual(len(lab.calls), 1)


def httpx_timeout():
    import httpx
    return httpx.ReadTimeout("PRIVATE_SECRET")


class TrustedEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oracle = Oracle()
        cls.validation = validate_labels(CASES, oracle=cls.oracle, concurrency=3)

    def test_all_100_authored_labels_match_real_engine_at_all_fixed_seeds(self):
        self.assertTrue(self.validation["passed"], self.validation["failures"])
        self.assertEqual(self.validation["scenario_seed_checks"], 1200)
        self.assertFalse(self.validation["labels_changed"])

    def test_sample_passing_boundary_failures_are_executed_not_prompt_paraphrases(self):
        by_id = {row["case_id"]: row for row in self.validation["runs"]}
        for case in CASES:
            if case.sample_passes_boundary_fails:
                statuses = {(item["seed"], item["scenario"]): item["status"]
                            for item in by_id[case.id]["observations"]}
                for seed in SEEDS:
                    self.assertEqual(statuses[(seed, "sample")], "passed", case.id)
                    self.assertEqual(statuses[(seed, "boundary")], "mismatch", case.id)

    def test_counterexample_replay_accepts_real_fixture_and_rejects_fabricated_rows(self):
        case = next(case for case in CASES if case.id == "filter_paid.04")
        trusted = self.oracle.check(case.task_id, case.sql, ("boundary",), 0)["counterexample"]
        full = validate_counterexample(case, trusted, self.oracle)
        self.assertTrue(full["valid"])
        self.assertTrue(full["payload_verified"])
        self.assertEqual(full["kind"], "complete_payload")
        locator = validate_counterexample(case, {"scenario": "boundary", "seed": 0}, self.oracle)
        self.assertTrue(locator["valid"])
        self.assertFalse(locator["payload_verified"])
        self.assertEqual(locator["kind"], "replayed_locator")
        fake = copy.deepcopy(trusted)
        fake["actual"]["rows"] = [[-1, -1]]
        self.assertFalse(validate_counterexample(case, fake, self.oracle)["valid"])
        fake = copy.deepcopy(trusted)
        fake["actual"]["row_count"] = 999
        self.assertFalse(validate_counterexample(case, fake, self.oracle)["valid"])
        fake = copy.deepcopy(trusted)
        fake["tables"][0]["rows"] = []
        self.assertFalse(validate_counterexample(case, fake, self.oracle)["valid"])
        self.assertFalse(validate_counterexample(case, {"scenario": "sample", "seed": 0}, self.oracle)["valid"])
        self.assertFalse(validate_counterexample(CASES[0], {"scenario": "boundary", "seed": 0}, self.oracle)["valid"])
        self.assertFalse(validate_counterexample(case, {"scenario": "boundary", "seed": True}, self.oracle)["valid"])
        self.assertFalse(validate_counterexample(case, {"scenario": "boundary", "seed": 0, "sql": "SELECT 1"}, self.oracle)["valid"])

    def test_semantic_label_error_fails_instead_of_relabelling(self):
        incorrect = replace(CASES[0], expected="mismatch")
        result = validate_labels([incorrect], oracle=self.oracle, concurrency=1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["runs"][0]["expected"], "mismatch")
        self.assertFalse(result["labels_changed"])


if __name__ == "__main__":
    unittest.main()
