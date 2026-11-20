import asyncio
from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from importlib.util import find_spec
import json
import logging
from threading import Event
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, func, inspect, select, update
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Attempt, Base, Decision, Learner
from tutor.provider import measure_calls


logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")
MAX_ACTIVE = 2
LEASE_SECONDS = 45
SERVICE_VERSION = "sql-workbench-v1"


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SQLDraft(Base):
    __tablename__ = "sql_drafts"
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sql: Mapped[str] = mapped_column(String(6000))
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class SQLRun(Base):
    __tablename__ = "sql_runs"
    __table_args__ = (UniqueConstraint("learner_id", "request_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    task_id: Mapped[str] = mapped_column(String(80))
    task_version: Mapped[str] = mapped_column(String(80))
    request_key: Mapped[str] = mapped_column(String(80))
    digest: Mapped[str] = mapped_column(String(64))
    sql: Mapped[str] = mapped_column(String(6000))
    action: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), index=True)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    events: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(max_length=6000)
    version: int = Field(ge=0, strict=True)


class SQLRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=6000)]
    action: Literal["run", "check", "coach"]
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class Workbench:
    def __init__(self, practice, *, model_id="gemini-3-flash", knowledge_args=()):
        self.practice = practice
        self.db = practice.db
        self.model_id = model_id
        self.knowledge_args = knowledge_args
        self.tasks = {}
        self.wake = asyncio.Event()
        self.dispatcher = None
        self.closed = False
        self.memories_enabled = False
        self.lab_task = None
        self.lab_ready = None
        self.coach_reason = ("model_unavailable" if practice.tutor.model is None else
                             "dependencies_unavailable" if any(find_spec(name) is None for name in
                                                                ("mcp", "langgraph", "langsmith")) else None)

    async def start(self):
        from course_content.sql_tasks import public_tasks
        from sql_lab.workbench import inspect_sql

        self.catalog = public_tasks()
        self.inspect_sql = inspect_sql
        SQLDraft.__table__.create(self.db.engine, checkfirst=True)
        SQLRun.__table__.create(self.db.engine, checkfirst=True)
        self.memories_enabled = inspect(self.db.engine).has_table("learning_memories")
        self.dispatcher = asyncio.create_task(self._dispatch())
        self.wake.set()

    async def close(self):
        self.closed = True
        if self.dispatcher:
            self.dispatcher.cancel()
            with suppress(asyncio.CancelledError):
                await self.dispatcher
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.lab_task:
            self.lab_task.cancel()
            await asyncio.gather(self.lab_task, return_exceptions=True)

    async def _get_lab(self):
        if self.lab_task is None or self.lab_task.done():
            self.lab_ready = asyncio.get_running_loop().create_future()
            self.lab_task = asyncio.create_task(self._serve_lab(self.lab_ready))
        return await asyncio.shield(self.lab_ready)

    async def _serve_lab(self, ready):
        from sql_lab.client import open_lab
        from sql_lab.contracts import WORKBENCH_SCOPE

        try:
            async with open_lab(WORKBENCH_SCOPE, knowledge_args=self.knowledge_args) as lab:
                ready.set_result(lab)
                await asyncio.Future()
        except BaseException as error:
            if not ready.done():
                if isinstance(error, asyncio.CancelledError):
                    ready.cancel()
                else:
                    ready.set_exception(RuntimeError("SQL tool service could not start."))
            if isinstance(error, asyncio.CancelledError):
                raise
            logger.warning("SQL tool service stopped (%s)", type(error).__name__)

    @staticmethod
    def task(task_id):
        from course_content.sql_tasks import task_view

        try:
            return task_view(task_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "SQL 实作任务不存在。") from None

    @staticmethod
    def _owned(db, learner, identifier):
        run = db.get(SQLRun, identifier)
        if run is None or run.learner_id != learner:
            raise HTTPException(404, "实作记录不存在。")
        return run

    @staticmethod
    def _view(run):
        return {"id": run.id, "task_id": run.task_id, "sql": run.sql, "action": run.action,
                "message": run.message, "status": run.status, "events": run.events,
                "result": run.result, "created_at": run.created_at.isoformat() + "Z"}

    def detail(self, learner, task_id):
        task = self.task(task_id)
        with self.db.transaction() as db:
            draft = db.get(SQLDraft, (learner, task_id))
            runs = db.scalars(select(SQLRun).where(SQLRun.learner_id == learner, SQLRun.task_id == task_id)
                              .order_by(SQLRun.created_at.desc(), SQLRun.id.desc()).limit(20)).all()
            return {"task": task, "draft": {"sql": draft.sql if draft else task["starter_sql"],
                                            "version": draft.version if draft else 0},
                    "runs": [self._view(run) for run in reversed(runs)]}

    def save_draft(self, learner, task_id, body):
        self.task(task_id)
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner)
            draft = db.get(SQLDraft, (learner, task_id))
            if (draft.version if draft else 0) != body.version:
                raise HTTPException(409, "草稿已在另一窗口更新；当前输入仍保留，请先核对已保存版本。")
            if draft is None:
                draft = SQLDraft(learner_id=learner, task_id=task_id, sql=body.sql, version=1)
                db.add(draft)
            else:
                draft.sql = body.sql
                draft.version += 1
            return {"sql": draft.sql, "version": draft.version}

    def learning_context(self, db, learner, task):
        record = db.get(Learner, learner)
        history = db.scalars(select(Attempt).where(Attempt.learner_id == learner)
                             .order_by(Attempt.event_seq.desc()).limit(12)).all()
        recent = []
        for row in reversed(history):
            item = self.practice.catalog.items.get(row.item_id)
            if item:
                recent.append({"sequence": row.event_seq, "topic": item.topic, "correct": row.correct})
        snapshot = db.scalar(select(Decision).where(Decision.learner_id == learner)
                             .order_by(Decision.history_version.desc()).limit(1))
        epikt = {"available": False, "reason": "no_prediction"}
        if snapshot:
            epikt = {"available": snapshot.source == "epikt", "reason": snapshot.reason,
                     "snapshot_history_version": snapshot.history_version,
                     "current_history_version": record.history_version,
                     "model_version": snapshot.trace.get("model_version"), "candidates": []}
            if epikt["available"]:
                for item_id, probability in snapshot.trace.get("epikt_scores", {}).items():
                    item = self.practice.catalog.items.get(int(item_id))
                    if item and item.topic == task["topic"]:
                        epikt["candidates"].append({"item_id": item.id, "topic": item.topic,
                                                     "predicted_correct_probability": probability})
        notes = []
        if self.memories_enabled:
            from api.learning_memory import LearningMemory, active_memories

            for memory in db.scalars(active_memories(learner).where(LearningMemory.topic == task["topic"])
                                     .order_by(LearningMemory.updated_at.desc()).limit(4)):
                notes.append({"id": memory.id, "version": memory.version, "summary": memory.summary})
        prior = db.scalars(select(SQLRun).where(SQLRun.learner_id == learner, SQLRun.task_id == task["id"],
                                                SQLRun.status == "completed")
                           .order_by(SQLRun.created_at.desc()).limit(4)).all()
        return {"captured_at": now().isoformat() + "Z", "recent_independent_attempts": recent,
                "epikt": epikt, "confirmed_notes": notes,
                "practice_activity": [{"action": row.action,
                                        "status": (row.result or {}).get("check", {}).get("status"),
                                        "assisted": row.action == "coach"} for row in reversed(prior)],
                "constraints": ["预测仅适用于已有映射的正式题，不是实作题掌握概率。",
                                "实作、提示后作答和正式首次独立作答分开记录。",
                                "没有学习证据时先澄清，不推断学生的具体误解。"]}

    async def submit(self, learner, task_id, body):
        task = self.task(task_id)
        digest = sha256(json.dumps({"task": task_id, "sql": body.sql, "action": body.action,
                                    "message": body.message}, sort_keys=True).encode()).hexdigest()
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner)
            duplicate = db.scalar(select(SQLRun).where(SQLRun.learner_id == learner,
                                                        SQLRun.request_key == body.idempotency_key))
            if duplicate:
                if duplicate.digest != digest:
                    raise HTTPException(409, "此提交编号已用于不同内容。")
                return self._view(duplicate)
            active = db.scalar(select(SQLRun.id).where(SQLRun.learner_id == learner,
                                                       SQLRun.status.in_(ACTIVE)).limit(1))
            if active:
                raise HTTPException(409, "还有实作任务正在运行，请等待或取消后再试。")
            recent = db.scalar(select(func.count()).select_from(SQLRun).where(
                SQLRun.learner_id == learner, SQLRun.created_at >= now() - timedelta(minutes=1)))
            if recent >= 20:
                raise HTTPException(429, "提交较频繁，请稍后继续；草稿已保留。")
            queued = db.scalar(select(func.count()).select_from(SQLRun).where(SQLRun.status.in_(ACTIVE)))
            if queued >= 24:
                raise HTTPException(503, "实作服务正在处理较多请求，请稍后重试。")
            run = SQLRun(id=uuid4().hex, learner_id=learner, task_id=task_id,
                         task_version=str(task["version"]), request_key=body.idempotency_key, digest=digest,
                         sql=body.sql, action=body.action, message=body.message, status="queued", state={},
                         context=self.learning_context(db, learner, task), events=[], result=None, created_at=now())
            db.add(run)
            result = self._view(run)
        self.wake.set()
        return result

    def status(self, learner, identifier):
        with self.db.transaction() as db:
            return self._view(self._owned(db, learner, identifier))

    async def cancel(self, learner, identifier):
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner)
            run = self._owned(db, learner, identifier)
            if run.status in ACTIVE or run.status == "interrupted":
                run.status = "cancelled"
                run.owner = None
                run.lease_until = None
                run.events = [*run.events, {"seq": len(run.events) + 1, "type": "cancelled"}]
            result = self._view(run)
        worker = self.tasks.get(identifier)
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        self.wake.set()
        return result

    def _check_context(self, db, run):
        if run.task_version != str(self.task(run.task_id)["version"]):
            raise HTTPException(409, "任务版本已更新，请重新提交；旧结果仍保留。")
        notes = run.context.get("confirmed_notes", [])
        if notes:
            from api.learning_memory import LearningMemory, active_memories

            current = {note.id: note.version for note in db.scalars(active_memories(run.learner_id).where(
                LearningMemory.id.in_([note["id"] for note in notes])))}
            if any(current.get(note["id"]) != note["version"] for note in notes):
                raise HTTPException(409, "学习记忆已修改或删除，请重新提交以使用最新内容；旧证据仍保留。")

    async def resume(self, learner, identifier):
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner)
            run = self._owned(db, learner, identifier)
            if run.status in ACTIVE:
                return self._view(run)
            if run.status not in {"interrupted", "failed"}:
                raise HTTPException(409, "此任务无需恢复，可修改 SQL 后重新提交。")
            self._check_context(db, run)
            if db.scalar(select(SQLRun.id).where(SQLRun.learner_id == learner, SQLRun.status.in_(ACTIVE)).limit(1)):
                raise HTTPException(409, "请先等待或取消正在运行的任务。")
            if len([event for event in run.events if event["type"] == "resumed"]) >= 3:
                raise HTTPException(409, "此任务已恢复三次，请修改内容后重新提交。")
            run.status = "queued"
            run.owner = None
            run.lease_until = None
            run.events = [*run.events, {"seq": len(run.events) + 1, "type": "resumed"}]
            result = self._view(run)
        self.wake.set()
        return result

    async def _dispatch(self):
        while not self.closed:
            self.wake.clear()
            try:
                with self.db.transaction() as db:
                    db.execute(update(SQLRun).where(SQLRun.status == "running", SQLRun.lease_until < now())
                               .values(status="interrupted", owner=None, lease_until=None))
                    identifiers = list(db.scalars(select(SQLRun.id).where(SQLRun.status == "queued")
                                                  .order_by(SQLRun.created_at).limit(MAX_ACTIVE - len(self.tasks))))
                for identifier in identifiers:
                    token = uuid4().hex
                    with self.db.transaction() as db:
                        claimed = db.execute(update(SQLRun).where(SQLRun.id == identifier, SQLRun.status == "queued")
                                             .values(status="running", owner=token,
                                                     lease_until=now() + timedelta(seconds=LEASE_SECONDS))).rowcount
                    if claimed:
                        task = asyncio.create_task(self._execute(identifier, token))
                        self.tasks[identifier] = task
                        task.add_done_callback(lambda _, identifier=identifier: self._settled(identifier))
            except Exception as error:
                logger.warning("SQL dispatcher unavailable (%s)", type(error).__name__)
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except TimeoutError:
                pass

    def _settled(self, identifier):
        self.tasks.pop(identifier, None)
        self.wake.set()

    def _save(self, identifier, token, *, state=None, event=None, result=None, status=None):
        with self.db.transaction() as db:
            run = db.get(SQLRun, identifier)
            if run.owner != token or run.status != "running":
                raise asyncio.CancelledError
            values = {}
            if state is not None:
                self._check_context(db, run)
                values["state"] = deepcopy(state)
            if event is not None:
                values["events"] = [*run.events, {**deepcopy(event), "seq": len(run.events) + 1}]
            if result is not None:
                values["result"] = result
            if status:
                values.update(status=status, owner=None, lease_until=None)
            else:
                values["lease_until"] = now() + timedelta(seconds=LEASE_SECONDS)
            changed = db.execute(update(SQLRun).where(SQLRun.id == identifier, SQLRun.owner == token,
                                                       SQLRun.status == "running").values(**values)).rowcount
            if not changed:
                raise asyncio.CancelledError

    async def _execute(self, identifier, token):
        started = monotonic()
        with self.db.transaction() as db:
            run = db.get(SQLRun, identifier)
            task_id, sql, action, message = run.task_id, run.sql, run.action, run.message
            context, state = deepcopy(run.context), deepcopy(run.state)
        async def checkpoint(value):
            self._save(identifier, token, state=value)
        async def publish(event):
            self._save(identifier, token, event=event)
        try:
            with self.db.transaction() as db:
                self._check_context(db, db.get(SQLRun, identifier))
            with measure_calls() as calls:
                if action == "coach":
                    result = await self._coach(task_id, sql, message, context, state, checkpoint, publish)
                else:
                    from sql_lab.workbench import evaluate, run_query

                    await publish({"type": "tool_started", "tool": action})
                    cancel_event = Event()
                    try:
                        if action == "run":
                            query = await asyncio.to_thread(run_query, task_id, sql, cancel_event=cancel_event)
                            result = {"kind": "run", "query": query}
                        else:
                            check = await asyncio.to_thread(evaluate, task_id, sql, cancel_event=cancel_event)
                            result = {"kind": "check", "check": check, "text": check["message"]}
                    finally:
                        cancel_event.set()
                    await publish({"type": "tool_completed", "tool": action,
                                   "elapsed_ms": round((monotonic() - started) * 1000, 2)})
            prior_metrics = result.get("metrics", {})
            usage = {name: sum(call[name] for call in calls) if calls and all(name in call for call in calls) else None
                     for name in ("prompt_tokens", "completion_tokens", "total_tokens")}
            result["metrics"] = {**prior_metrics, "service_version": SERVICE_VERSION,
                                 "task_version": str(self.task(task_id)["version"]),
                                 "attempt_elapsed_ms": round((monotonic() - started) * 1000, 2),
                                 "provider_calls_this_attempt": len(calls), "usage_this_attempt": usage,
                                 "cost": None}
            self._save(identifier, token, result=result, status="completed")
        except asyncio.CancelledError:
            with suppress(asyncio.CancelledError):
                self._save(identifier, token, status="interrupted")
            raise
        except Exception as error:
            logger.warning("SQL run interrupted (%s)", type(error).__name__)
            with suppress(asyncio.CancelledError):
                self._save(identifier, token, event={"type": "failed", "code": type(error).__name__},
                           result={"kind": action, "text": "本轮暂未完成，输入和已取得的证据已保留，可重试恢复。"},
                           status="failed")

    async def _coach(self, task_id, sql, message, context, state, checkpoint, publish):
        if self.coach_reason:
            return {"kind": "coach", "mode": "evidence_only", "evidence": [], "citations": [],
                    "text": "实验教练当前不可用；请先使用运行 SQL 与提交验证，输入仍保留。",
                    "learning_context": context, "metrics": {"finish_reason": self.coach_reason,
                    "model": self.model_id, "model_calls": 0, "tool_calls": 0}}
        from langsmith import tracing_context
        from sql_lab.contracts import KNOWLEDGE_TOOL
        from sql_lab.executor import LabError
        from tutor.workbench_coach import WorkbenchCoach

        task = self.task(task_id)
        async def tool(name, arguments):
            lab = await self._get_lab()
            try:
                if name == "search_course":
                    response = await lab.call("workbench", KNOWLEDGE_TOOL, {
                        "query": arguments["query"], "topic": task["topic"], "top_k": 3,
                    }, timeout=5)
                    await publish({"type": "retrieval_version", "tool": "search_course",
                                   "data": {"mode": response["mode"], "corpus": response["corpus"]}})
                    return {**response, "cards": [{**card, "url": card.get("source_url", card.get("url", ""))}
                                                  for card in response["cards"]]}
                return await lab.call("workbench", name, {"task_id": task_id, "sql": sql, **arguments}, timeout=8)
            except LabError as error:
                if str(error) == "mcp_request_failed" and self.lab_task:
                    self.lab_task.cancel()
                    await asyncio.gather(self.lab_task, return_exceptions=True)
                raise
        if self.practice.tutor.model is not None:
            await self._get_lab()
        with tracing_context(enabled=False):
            return await WorkbenchCoach(self.practice.tutor.model, self.model_id).run(
                task, sql, message, context, tool=tool, state=state or None,
                checkpoint=checkpoint, publish=publish,
            )


def router(learner):
    routes = APIRouter(prefix="/api/sql")

    def service(request: Request):
        instance = request.app.state.workbench
        if instance is None:
            raise HTTPException(503, "SQL 实作服务暂不可用，请检查启动状态后重试。")
        return instance

    @routes.get("/tasks")
    def tasks(request: Request, user: str = Depends(learner)):
        instance = service(request)
        return {"available": True, "tasks": instance.catalog, "coach_available": instance.coach_reason is None,
                "coach_reason": instance.coach_reason}

    @routes.get("/tasks/{task_id}")
    def detail(task_id: str, request: Request, user: str = Depends(learner)):
        return service(request).detail(user, task_id)

    @routes.put("/tasks/{task_id}/draft")
    def draft(task_id: str, body: DraftRequest, request: Request, user: str = Depends(learner)):
        return service(request).save_draft(user, task_id, body)

    @routes.post("/tasks/{task_id}/runs", status_code=202)
    async def submit(task_id: str, body: SQLRequest, request: Request, user: str = Depends(learner)):
        return await service(request).submit(user, task_id, body)

    @routes.get("/runs/{identifier}")
    def status(identifier: str, request: Request, user: str = Depends(learner)):
        return service(request).status(user, identifier)

    @routes.post("/runs/{identifier}/cancel")
    async def cancel(identifier: str, request: Request, user: str = Depends(learner)):
        return await service(request).cancel(user, identifier)

    @routes.post("/runs/{identifier}/resume")
    async def resume(identifier: str, request: Request, user: str = Depends(learner)):
        return await service(request).resume(user, identifier)

    return routes
