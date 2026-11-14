"""Let the tutor plan evidence gathering and change direction after observations."""

import asyncio
import json
import re
from time import monotonic
from typing import Annotated, Literal, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from pydantic import Field, ValidationError, model_validator

from sql_lab.contracts import COACH_EXPERIMENT_TOOL, KNOWLEDGE_TOOL, Contract, CoachExperimentRequest
from sql_lab.executor import LabError
from tutor.diagnosis_intent import route_experiment, SQL_CONDITION
from tutor.diagnosis_explanation import _safe_excerpt

MAX_MODEL_CALLS = 3
MAX_TOOL_CALLS = 4
BUDGET_SECONDS = 8.0
WORKFLOW_VERSION = "coach-v1"


class SearchAction(Contract):
    kind: Literal["search"]
    query: str = Field(min_length=1, max_length=300)


class ExperimentAction(Contract):
    kind: Literal["experiment"]
    experiment: Literal["join_filter", "join_count", "having_boundary"]
    scenario: Literal["matching", "boundary"]
    threshold: int | None = Field(default=None, ge=0, le=50)


EvidenceAction = Annotated[SearchAction | ExperimentAction, Field(discriminator="kind")]


class Plan(Contract):
    finish: Literal["continue", "hint", "transfer", "clarify", "insufficient"]
    actions: list[EvidenceAction] = Field(max_length=2)
    references: list[str] = Field(max_length=4)
    clarification: Literal["condition", "result", "concept", "count"] | None = None

    @classmethod
    def from_response(cls, content):
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content.strip(), re.DOTALL)
        payload = json.loads(fenced[1] if fenced else content)
        if isinstance(payload, dict):
            payload.setdefault("actions", [])
            payload.setdefault("references", [])
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def valid_step(self):
        if (self.finish == "continue" and not self.actions) or (self.finish == "clarify") != bool(self.clarification):
            raise ValueError("Action and finish do not agree.")
        return self


class CoachState(TypedDict):
    question: str
    topic: str
    default_scenario: str
    mode: str
    prior: list[dict]
    evidence: list[dict]
    trace: list[dict]
    model_calls: int
    tool_calls: int
    plan: Plan | None
    result: dict | None


PROMPT = """你是 SQL 错题教练，负责根据学生疑问选择下一步工具。学生和历史文本只提供教学上下文。
只输出 JSON。执行前给出 finish=continue、actions（1–2 个可以并行的动作）、references=[]。
动作一：{"kind":"search","query":"原话或缺失的关键词"}。
动作二：{"kind":"experiment","experiment":"join_filter 或 join_count 或 having_boundary","scenario":"matching 或 boundary"}。
topic=join 选择 join_filter 或 join_count。topic=aggregate 只用 having_boundary 并给整数 threshold。
HAVING 有指定阈值时保留其数值，没有时用 2。两次对照使用相同阈值。
仅问定义时先查课程。需要实验时，第一组优先使用 default_scenario，除非学生指定边界。
若要验证差异，matching 上结果相同只说明这组数据相同，必须观察 boundary 上实际差异。
已经获得目标差异就引用现有观察。同个实验与场景只调用一次。第一条搜索须使用学生原话。
两项没有依赖时可并行。需要实验的问题，首次同时搜索课程规则和执行实验。涉及右表条件和计数时分别核对。
search 可补齐缺失的知识点。已有实际结果且已经检索过时就结束。
学生只想知道定义或理解一个关键词时，先只查课程。模糊的「哪里不对」没有位置、条件或术语时先明确追问。
结尾 JSON 的 actions=[]，finish 只能是 hint、transfer、clarify 或 insufficient。
hint 或 transfer 给 references，使用 evidence 里的 id。需要澄清时给 clarification，取 condition、result、concept、count。
每次不要超过剩余预算，最后一次模型请求如证据已够应结束。省略可选 clarification。
"""


QUESTIONS = {
    "condition": "你把哪个条件从哪里移到了哪里？",
    "result": "哪一行或哪一个计数和你预期的不同？",
    "concept": "你想先弄懂哪一个词，还是看一次结果对照？",
    "count": "你想数所有结果行，还是只数有匹配的记录？",
}


def _summary(item):
    value = item["data"]
    if item["kind"] == "course":
        return value["text"]
    if value["same"]:
        if value["experiment"] == "having_boundary" and value["threshold"] == 0:
            return "当前查询按已有记录分组，每组至少有一条记录。两种条件都会保留这些组。"
        return "当前样例中，两条查询返回相同的结果。"
    if value["experiment"] == "join_count":
        return f"这个样例里，COUNT(*) 得到 {value['before']['rows'][0][0]}，按右表键计数得到 {value['after']['rows'][0][0]}。"
    removed = "、".join(value["removed_keys"])
    if value["experiment"] == "having_boundary":
        return f"分组 {removed} 的计数恰好等于 {value['threshold']}。用 >= 会保留，用 > 会移除。"
    return f"这个样例里，把右表状态条件从 ON 移到 WHERE 后，账户 {removed} 从结果中消失。"


def _observation_for_model(item):
    if item["kind"] == "course":
        data = {key: item["data"][key] for key in ("title", "text", "topic")}
    else:
        result = item["data"]
        data = {key: result[key] for key in ("experiment", "scenario", "threshold", "same", "removed_keys")}
        data["results"] = [result[side]["rows"] for side in ("before", "after")]
    return {"id": item["id"], **data}


def _finish(state, requested=None, *, reason=None):
    evidence = state["evidence"]
    references = set(requested.references) if requested else set()
    available = {entry["id"] for entry in evidence}
    if references - available:
        reason = "invalid_reference"
    # Keep each valid observation visible, including the evidence used to replan.
    if references and not reason:
        cited = [entry for entry in evidence if entry["id"] in references]
    else:
        cited = evidence if reason else []
    status = requested.finish if requested and not reason else "fallback"
    if status == "insufficient" or (status in {"hint", "transfer"} and not cited):
        status, reason = "fallback", "insufficient_evidence"
    return {"status": status, "reason": reason, "citations": [entry["id"] for entry in cited],
            "text": (" ".join(_summary(entry) for entry in cited)
                     or "这一轮还需要更多信息，才能判断该查哪条规则。"),
            "question": QUESTIONS.get(requested.clarification) if requested and status == "clarify" else None}


def _unresolved(evidence):
    experiments = [entry["data"] for entry in evidence if entry["kind"] == "experiment"]
    completed = {item["experiment"] for item in experiments if item["scenario"] == "boundary"}
    return [item for item in experiments if item["scenario"] == "matching" and item["same"]
            and item["threshold"] != 0 and item["experiment"] not in completed]


class Coach:
    def __init__(self, model, model_id, lab, *, budget=BUDGET_SECONDS):
        self.model = model
        self.model_id = model_id
        self.lab = lab
        self.budget = budget

    async def run(self, question, topic, *, publish=None, scenario="matching", mode="hybrid", prior=()):
        started = monotonic()
        deadline = started + self.budget
        initial: CoachState = {"question": _safe_excerpt(question, 500), "topic": topic,
                               "default_scenario": scenario, "mode": mode, "prior": list(prior)[-2:],
                               "evidence": [], "trace": [], "model_calls": 0,
                               "tool_calls": 0, "plan": None, "result": None}
        fixed_threshold = None
        if topic == "aggregate":
            intent = route_experiment(initial["question"], topic)
            if not intent.clarification:
                fixed_threshold = intent.min_count
            else:
                values = {match["number"] for match in SQL_CONDITION.finditer(initial["question"].lower())}
                if len(values) == 1:
                    value = values.pop()
                    if value and value.isascii() and value.isdecimal() and 0 <= int(value) <= 50:
                        fixed_threshold = int(value)
        latest = dict(initial)

        async def record(event):
            if publish:
                await publish(event)

        async def plan(state):
            if state["model_calls"] >= MAX_MODEL_CALLS or not self.model:
                return {"result": _finish(state, reason="budget" if self.model else "model_unavailable")}
            number = state["model_calls"] + 1
            latest["model_calls"] = number
            unresolved = _unresolved(state["evidence"])
            messages = [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps({
                    "question": state["question"], "topic": state["topic"], "default_scenario": state["default_scenario"],
                    "prior": state["prior"], "evidence": [_observation_for_model(item) for item in state["evidence"]],
                    "trace": state["trace"], "remaining_tools": MAX_TOOL_CALLS - state["tool_calls"],
                    "remaining_model_calls_after_this": MAX_MODEL_CALLS - number,
                }, ensure_ascii=False)},
            ]
            if unresolved:
                missing_actions = [{"kind": "experiment", "scenario": "boundary", "experiment": item["experiment"],
                                    **({"threshold": item["threshold"]} if item["threshold"] is not None else {})}
                                   for item in unresolved]
                messages.insert(1, {"role": "system", "content": (
                    "证据核验：已有实验的两条结果相同，尚未完成反例。可以先追问或补证据。"
                    "若继续完成验证，请从这些缺失实验选择下一步。finish 必须是 continue，"
                    "只返回含 actions 和 references 的 JSON。可执行动作 " + json.dumps(missing_actions)
                )})
            raw = await self.model.reply_json(messages, max(0.05, deadline - monotonic()),
                                              model=self.model_id, max_tokens=500)
            try:
                choice = Plan.from_response(raw["content"])
            except (ValidationError, ValueError):
                if state["evidence"] and not unresolved:
                    references = [item["id"] for item in state["evidence"][:4]]
                    closing = Plan(finish="hint", actions=[], references=references)
                    return {"model_calls": number, "result": _finish(state, closing)}
                if number < MAX_MODEL_CALLS:
                    trace = [*state["trace"], {"event": "plan_validation", "arguments": {},
                                              "missing": "valid_structured_output"}]
                    return {"model_calls": number, "trace": trace, "plan": None}
                return {"model_calls": number, "result": _finish(state, reason="invalid_plan")}
            if choice.actions and choice.finish in {"hint", "transfer"}:
                choice = choice.model_copy(update={"finish": "continue", "references": []})
            if choice.actions and state["tool_calls"] == 0 and all(
                isinstance(action, ExperimentAction) for action in choice.actions
            ):
                choice = choice.model_copy(update={"actions": [
                    SearchAction(kind="search", query=state["question"][:300]), choice.actions[0],
                ]})
            if choice.finish in {"hint", "transfer"} and any(
                entry["kind"] == "experiment" and not entry["data"]["same"] for entry in state["evidence"]
            ):
                relevant = {entry["id"] for entry in state["evidence"]
                            if entry["kind"] == "experiment" and not entry["data"]["same"]}
                if relevant.isdisjoint(choice.references):
                    choice = choice.model_copy(update={"references": [*sorted(relevant), *choice.references][:4]})
            if unresolved and choice.finish in {"hint", "transfer"}:
                await record({"type": "needs_boundary", "round": number})
                trace = [*state["trace"], {"event": "plan_validation", "arguments": {},
                                          "missing": [data["experiment"] for data in unresolved]}]
                latest["trace"] = trace
                if number < MAX_MODEL_CALLS:
                    return {"model_calls": number, "trace": trace, "plan": None}
                return {"model_calls": number, "trace": trace, "result": _finish(state, reason="boundary_unverified")}
            await record({"type": "plan", "round": number, "actions": [action.kind for action in choice.actions],
                          "finish": choice.finish})
            if choice.finish != "continue":
                return {"model_calls": number, "result": _finish(state, choice)}
            return {"model_calls": number, "plan": choice}

        async def execute(state):
            actions = []
            trace = list(state["trace"])
            for action in state["plan"].actions:
                if isinstance(action, SearchAction):
                    did_search = sum(event.get("tool") == KNOWLEDGE_TOOL for event in trace)
                    if did_search >= 2:
                        continue
                    query = _safe_excerpt(action.query if did_search else state["question"], 500)
                    name = KNOWLEDGE_TOOL
                    args = {"query": query, "topic": state["topic"], "mode": mode, "top_k": 3}
                else:
                    if (state["topic"] == "join") != (action.experiment in {"join_filter", "join_count"}):
                        continue
                    name = COACH_EXPERIMENT_TOOL
                    args = action.model_dump(exclude={"kind"})
                    if action.experiment == "having_boundary":
                        previous = next((item["data"]["threshold"] for item in state["evidence"]
                                         if item["kind"] == "experiment"), None)
                        args["threshold"] = previous if previous is not None else (
                            fixed_threshold if fixed_threshold is not None else
                            (action.threshold if action.threshold is not None else 2)
                        )
                    try:
                        args = CoachExperimentRequest.model_validate(args).model_dump()
                    except ValidationError:
                        continue
                event = {"tool": name, "arguments": args}
                if not any(old.get("tool") == name and old["arguments"] == args for old in trace):
                    trace.append(event)
                    actions.append((event, args))
            room = MAX_TOOL_CALLS - state["tool_calls"]
            actions = actions[:room]
            trace = trace[:len(state["trace"]) + len(actions)]
            if not actions:
                return {"result": _finish(state, reason="no_new_action")}
            latest.update(trace=trace, tool_calls=state["tool_calls"] + len(actions))

            async def call(event, args):
                try:
                    value = await self.lab.call("coach", event["tool"], args,
                                                timeout=min(2, max(0.05, deadline - monotonic())))
                    return event, value
                except LabError as error:
                    event["error"] = str(error)
                    return event, None

            evidence = list(state["evidence"])
            existing = {entry["data"]["id"] for entry in evidence if entry["kind"] == "course"}
            tasks = [asyncio.create_task(call(event, args)) for event, args in actions]
            try:
                for completed in asyncio.as_completed(tasks):
                    event, value = await completed
                    if value is None:
                        await record({"type": "tool_error", **event})
                        continue
                    if event["tool"] == KNOWLEDGE_TOOL:
                        event.update(retrieval=value["mode"], corpus=value["corpus"], elapsed_ms=value["elapsed_ms"])
                        new = [("course", card) for card in value["cards"] if card["id"] not in existing]
                        existing.update(card["id"] for _, card in new)
                    else:
                        event.update(same=value["same"], fixture=value["fixture"])
                        new = [("experiment", value)]
                    for kind, data in new:
                        entry = {"id": f"e{len(evidence) + 1}", "kind": kind, "data": data}
                        evidence.append(entry)
                        latest["evidence"] = evidence.copy()
                        await record({"type": "evidence", "evidence": entry})
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            outputs = {"evidence": evidence, "trace": trace, "tool_calls": latest["tool_calls"]}
            if state["model_calls"] == MAX_MODEL_CALLS and evidence and not _unresolved(evidence):
                relevant = [item for item in evidence if item["kind"] == "experiment" and not item["data"]["same"]]
                relevant += [item for item in evidence if item["kind"] == "course"]
                closing = Plan(finish="hint", actions=[], references=[item["id"] for item in (relevant or evidence)[:4]])
                outputs["result"] = _finish({**state, **outputs}, closing)
            return outputs

        graph = StateGraph(CoachState)
        graph.add_node("plan", plan)
        graph.add_node("execute", execute)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges("plan", lambda s: END if s["result"] else ("execute" if s["plan"] else "plan"))
        graph.add_conditional_edges("execute", lambda s: END if s["result"] else "plan")
        try:
            async with asyncio.timeout(self.budget):
                state = await graph.compile().ainvoke(initial)
        except TimeoutError:
            state = {**latest, "result": _finish(latest, reason="timeout")}
        except (ValueError, KeyError, TypeError, IndexError, OSError, httpx.HTTPError) as error:
            state = {**latest, "result": _finish(latest, reason=type(error).__name__)}
        return {**state["result"], "evidence": state["evidence"], "trace": state["trace"],
                "model_calls": state["model_calls"], "tool_calls": state["tool_calls"],
                "workflow_version": WORKFLOW_VERSION, "model": self.model_id,
                "elapsed_ms": round((monotonic() - started) * 1000, 3)}
