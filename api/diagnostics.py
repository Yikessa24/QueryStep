"""Persist and serve diagnostic runs without touching the grading ledger."""

import asyncio
from contextlib import AsyncExitStack, contextmanager, suppress
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, ForeignKey, JSON, MetaData, String, Table, UniqueConstraint, inspect, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Attempt, Base, Decision
from api.learning_memory import (LearningMemory, active_memories, confirmation_graph,
                                 resume_confirmation, view, wait_for_confirmation)
from course_content.sql_fixtures import FIXTURES, GROUPING_FIXTURE, JOIN_FIXTURE
from course_content.transfer import EVENTS, LOANS, TRANSFER_ITEMS
from sql_lab.client import open_lab
from sql_lab.contracts import TRANSFER_SCOPE, TRANSFER_TOOL
from sql_lab.executor import LabError
from sql_lab.transfer import template_for
from tutor.diagnosis import Diagnosis, EXPLANATIONS
from tutor.diagnosis_explanation import EXPLANATION_TIMEOUT, MAX_EXPLANATIONS, explain


logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running", "waiting_confirmation")
TRANSFER_UNAVAILABLE = {"available": False, "exercise": None, "feedback": None}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DiagnosisRun(Base):
    __tablename__ = "diagnosis_runs"
    __table_args__ = (UniqueConstraint("learner_id", "request_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"), index=True)
    history_version: Mapped[int]
    catalog_revision: Mapped[str] = mapped_column(String(80))
    fixture_id: Mapped[str] = mapped_column(String(80))
    request_key: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(25), index=True)
    branches: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_token: Mapped[str | None] = mapped_column(String(32))
    proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class DiagnosisEvent(Base):
    __tablename__ = "diagnosis_events"

    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class DiagnosisExperiment(Base):
    __tablename__ = "diagnosis_experiments"

    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)


class TransferAttempt(Base):
    __tablename__ = "diagnosis_transfer_attempts"

    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("diagnosis_runs.id"))
    item_id: Mapped[str] = mapped_column(String(80))
    offered_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    option: Mapped[int | None]
    correct: Mapped[bool | None]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)


class PracticeTransfer(Base):
    __tablename__ = "practice_transfers"

    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"), primary_key=True)
    item: Mapped[dict] = mapped_column(JSON)
    offered_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    option: Mapped[int | None]
    correct: Mapped[bool | None]
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)


class Diagnostics:
    def __init__(self, practice, checkpoint_path=None, *, explanation_model=None):
        self.practice = practice
        self.db = practice.db
        self.engine = Diagnosis(practice.tutor.model)
        self.explanation_model = explanation_model if callable(getattr(practice.tutor.model, "reply_json", None)) else None
        self.explanations: set[asyncio.Task] = set()
        self.worker: asyncio.Task | None = None
        self.wake = asyncio.Event()
        self.event_listeners: dict[str, set[asyncio.Event]] = {}
        self.stack = AsyncExitStack()
        database_path = self.db.engine.url.database
        self.checkpoint_path = checkpoint_path or (
            Path(database_path).with_suffix(".diagnosis-checkpoints.sqlite3")
            if self.db.engine.dialect.name == "sqlite" and database_path not in (None, ":memory:")
            else Path("artifacts/diagnosis-checkpoints.sqlite3")
        )
        self.graph = None
        self.confirm_lock = asyncio.Lock()

    async def start(self):
        try:
            async with open_lab(GROUPING_FIXTURE):
                pass
            migrate(self.db.engine)
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self.checkpoint_path.touch(mode=0o600, exist_ok=True)
            self.graph = await self.stack.enter_async_context(confirmation_graph(self.checkpoint_path))
            await self.graph.checkpointer.setup()
            self.worker = asyncio.create_task(self._run_queue())
        except BaseException:
            await self.stack.aclose()
            raise

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
            except Exception as error:
                logger.warning("Diagnosis worker stopped (%s)", type(error).__name__)
        tasks = tuple(self.explanations)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.stack.aclose()

    def _owned(self, db, learner_id, run_id) -> DiagnosisRun:
        run = db.get(DiagnosisRun, run_id)
        if not run or run.learner_id != learner_id:
            raise HTTPException(404, "诊断记录不存在。")
        return run

    def _current(self, db, run: DiagnosisRun) -> bool:
        if run.catalog_revision != self.practice.catalog.revision:
            return False
        try:
            return self.practice._tutoring_attempt(db, run.learner_id, run.decision_id).event_seq == run.history_version
        except HTTPException:
            return False

    @staticmethod
    def _view(run: DiagnosisRun) -> dict:
        status = run.status
        if status == "waiting_confirmation" and not Diagnostics._proposal_fresh(run):
            status = "stale"
        pending = None
        if status == "waiting_confirmation" and run.confirmation:
            choice = run.confirmation["choice"]
            pending = {"action": choice["action"], "summary": choice["summary"]}
        result = run.result
        explanation = (result or {}).get("explanation")
        if explanation and explanation["status"] == "pending" and datetime.fromisoformat(explanation["expires_at"]) <= now():
            result = {**result, "explanation": {"status": "fallback", "reason": "interrupted"}}
        return {"run_id": run.id, "status": status, "branches": run.branches, "topic": FIXTURES[run.fixture_id].topic,
                "result": result, "proposal": run.proposal if status == "waiting_confirmation" else None,
                "pending_confirmation": pending}

    @staticmethod
    def _event(db, run_id, event_type, **payload):
        last = db.scalar(select(DiagnosisEvent.seq).where(DiagnosisEvent.run_id == run_id)
                         .order_by(DiagnosisEvent.seq.desc()).limit(1))
        db.add(DiagnosisEvent(run_id=run_id, seq=(last or 0) + 1, event_type=event_type, payload=payload))

    def events(self, learner_id, run_id, after):
        with self.db.transaction() as db:
            run = self._owned(db, learner_id, run_id)
            rows = db.scalars(select(DiagnosisEvent).where(
                DiagnosisEvent.run_id == run_id, DiagnosisEvent.seq > after,
            ).order_by(DiagnosisEvent.seq).limit(100))
            return self._view(run)["status"], [
                {"run_id": run_id, "seq": row.seq, "type": row.event_type, "time": row.created_at.isoformat() + "Z",
                 **row.payload} for row in rows
            ]

    @contextmanager
    def subscribe(self, run_id):
        """Wake local SSE listeners after commit. The database remains the replay source."""
        signal = asyncio.Event()
        listeners = self.event_listeners.setdefault(run_id, set())
        listeners.add(signal)
        try:
            yield signal
        finally:
            listeners.remove(signal)
            if not listeners:
                del self.event_listeners[run_id]

    def _notify(self, run_id):
        for signal in self.event_listeners.get(run_id, ()):
            signal.set()

    def latest(self, learner_id, decision_id) -> dict:
        with self.db.transaction() as db:
            decision = self.practice._owned_decision(db, learner_id, decision_id)
            fixture_id = self._fixture(decision)
            if not fixture_id:
                return {"available": False, "run": None}
            run = db.scalar(select(DiagnosisRun).where(
                DiagnosisRun.learner_id == learner_id, DiagnosisRun.decision_id == decision_id,
            ).order_by(DiagnosisRun.created_at.desc(), DiagnosisRun.id.desc()).limit(1))
            if run and run.status in ACTIVE and not self._current(db, run):
                return {"available": True, "topic": FIXTURES[fixture_id].topic,
                        "run": {**self._view(run), "status": "stale", "proposal": None, "pending_confirmation": None}}
            return {"available": True, "topic": FIXTURES[fixture_id].topic, "run": self._view(run) if run else None}

    def _fixture(self, decision: Decision) -> str | None:
        item = self.practice.catalog.items.get(decision.item_id)
        if item and self.practice.tutor.allow_mapped_items:
            fixture_id = {75: GROUPING_FIXTURE, 81: JOIN_FIXTURE}.get(item.source_question_id)
            if fixture_id and FIXTURES[fixture_id].topic == item.topic:
                return fixture_id
        return None

    async def enqueue(self, learner_id, decision_id, message, request_key) -> dict:
        digest = sha256(f"{decision_id}\n{message}".encode()).hexdigest()
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            prior = db.scalar(select(DiagnosisRun).where(
                DiagnosisRun.learner_id == learner_id, DiagnosisRun.request_key == request_key,
            ))
            if prior:
                if prior.request_hash != digest:
                    raise HTTPException(409, "该提交编号已用于另一条诊断。")
                return self._view(prior)
            attempt = self.practice._tutoring_attempt(db, learner_id, decision_id)
            fixture_id = self._fixture(db.get(Decision, decision_id))
            if fixture_id is None:
                raise HTTPException(409, "当前错题还没有可用的 SQL 实验。")
            active = db.scalar(select(DiagnosisRun).where(
                DiagnosisRun.decision_id == decision_id, DiagnosisRun.status.in_(ACTIVE),
            ).limit(1))
            if active and active.status == "waiting_confirmation" and not self._proposal_fresh(active):
                active.status = "stale"
                self._event(db, active.id, "run_finished", status=active.status)
            elif active:
                raise HTTPException(409, "已有诊断正在运行。")
            run = DiagnosisRun(id=uuid4().hex, learner_id=learner_id, decision_id=decision_id,
                               history_version=attempt.event_seq, catalog_revision=self.practice.catalog.revision,
                               request_key=request_key, request_hash=digest, message=message, fixture_id=fixture_id,
                               status="queued", branches={})
            db.add(run)
            response = self._view(run)
        self.wake.set()
        return response

    def status(self, learner_id, run_id) -> dict:
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            run = self._owned(db, learner_id, run_id)
            if run.status in ACTIVE and (not self._current(db, run)
                    or (run.status == "waiting_confirmation" and not self._proposal_fresh(run))):
                run.status = "stale"
                self._event(db, run.id, "run_finished", status=run.status)
            return self._view(run)

    def cancel(self, learner_id, run_id) -> dict:
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            run = self._owned(db, learner_id, run_id)
            if run.status in ACTIVE:
                run.status = "cancelled"
                self._event(db, run.id, "run_finished", status=run.status)
            return self._view(run)

    @staticmethod
    def _experiment_result(db, run_id, request_key, digest):
        saved = db.get(DiagnosisExperiment, (run_id, request_key))
        if saved is not None:
            if saved.request_hash != digest:
                raise HTTPException(409, "该提交编号已用于另一条实验。")
            return saved.result
        return None

    async def experiment(self, learner_id, run_id, query_id, min_count, request_key) -> dict:
        digest = sha256(f"{query_id}\n{min_count}".encode()).hexdigest()
        with self.db.transaction() as db:
            run = self._owned(db, learner_id, run_id)
            if run.status not in ("completed", "waiting_confirmation") or not self._current(db, run):
                raise HTTPException(409, "当前诊断不可用于实验。")
            saved = self._experiment_result(db, run_id, request_key, digest)
            if saved is not None:
                return saved
            fixture_id = run.fixture_id
        if query_id not in FIXTURES[fixture_id].queries:
            raise HTTPException(422, "此实验不支持该查询。")
        baseline_query = "group_counts" if FIXTURES[fixture_id].topic == "aggregate" else "join_on"
        try:
            async with open_lab(fixture_id) as lab:
                baseline = await lab.call("experiment", "run_example_query", {
                    "fixture_id": fixture_id, "query_id": baseline_query,
                })
                observation = await lab.call("experiment", "run_example_query", {
                    "fixture_id": fixture_id, "query_id": query_id,
                    "parameters": {"min_count": min_count} if min_count is not None else {},
                })
                comparison = await lab.call("experiment", "compare_example_results", {
                    "before_id": baseline["observation_id"], "after_id": observation["observation_id"],
                })
        except Exception as error:
            logger.warning("SQL experiment failed (%s)", type(error).__name__)
            raise HTTPException(503, "SQL 实验暂时不可用，请重试。") from error
        result = {"observations": [baseline, observation], "comparison": comparison}
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            run = self._owned(db, learner_id, run_id)
            if run.status not in ("completed", "waiting_confirmation") or not self._current(db, run):
                raise HTTPException(409, "当前练习已更新。")
            saved = self._experiment_result(db, run_id, request_key, digest)
            if saved is not None:
                return saved
            db.add(DiagnosisExperiment(run_id=run_id, request_key=request_key, request_hash=digest, result=result))
            return result

    def transfer(self, learner_id, run_id, *, offer=False, option=None) -> dict:
        with self.db.transaction() as db:
            writing = offer or option is not None
            if writing:
                self.practice._lock_learner(db, learner_id)
            run = self._owned(db, learner_id, run_id)
            attempt = db.get(TransferAttempt, run.decision_id)
            if db.get(PracticeTransfer, run.decision_id) is not None:
                if writing:
                    raise HTTPException(409, "请在错题页打开已有的迁移练习。")
                return TRANSFER_UNAVAILABLE
            current = (run.status in ("completed", "waiting_confirmation") and run.fixture_id == GROUPING_FIXTURE
                       and (run.result or {}).get("mode") == "full" and self._current(db, run))
            if writing and not current:
                raise HTTPException(409, "当前诊断没有可提交的迁移练习。")
            if not current and (attempt is None or attempt.option is None):
                return {"available": False, "exercise": None, "feedback": None}
            if attempt is not None and attempt.run_id != run.id:
                if option is not None:
                    raise HTTPException(409, "请使用最初打开的迁移练习。")
                return {"available": False, "exercise": None, "feedback": None}
            if attempt is None and offer:
                after_id = run.result["comparison"]["after_id"]
                after = next(row for row in run.result["observations"] if row["observation_id"] == after_id)
                item = EVENTS if after["query_id"] == "having_gte" else LOANS
                attempt = TransferAttempt(decision_id=run.decision_id, run_id=run.id, item_id=item.id)
                db.add(attempt)
            if attempt is None:
                if option is not None:
                    raise HTTPException(409, "请先打开迁移练习。")
                return {"available": True, "exercise": None, "feedback": None}
            item = TRANSFER_ITEMS[attempt.item_id]
            if option is not None:
                self._save_transfer_answer(attempt, option, item.correct_option)
            feedback = None if attempt.option is None else {"selected_option": attempt.option, "correct": attempt.correct,
                                                            "correct_option": item.correct_option, "text": item.feedback}
            return {"available": True, "exercise": item.public(), "feedback": feedback}

    @staticmethod
    def _save_transfer_answer(attempt, option, correct_option):
        if not 0 <= option <= 3:
            raise HTTPException(422, "选项超出范围。")
        if attempt.option is None:
            attempt.option, attempt.correct, attempt.submitted_at = option, option == correct_option, now()
        elif attempt.option != option:
            raise HTTPException(409, "本次迁移练习已经提交。")

    def _practice_transfer(self, db, learner_id, decision_id, *, writing=False):
        decision = self.practice._owned_decision(db, learner_id, decision_id)
        self.practice._check_catalog(decision.catalog_version)
        attempt = db.get(Attempt, decision_id)
        if not attempt or attempt.correct:
            if writing:
                raise HTTPException(409, "请先提交原题作答。只有错题提供迁移练习。")
            return None, None
        current = self.practice._is_current_wrong(db, attempt)
        saved = db.get(PracticeTransfer, decision_id) or db.get(TransferAttempt, decision_id)
        if writing and not current:
            raise HTTPException(409, "当前练习已更新。")
        if saved is not None and (current or saved.option is not None):
            return None, saved
        if current:
            item = self.practice.catalog.items[attempt.item_id]
            variant = "inclusive" if item.source_question_id == 75 else "standard"
            if template_for(item.source_question_id, item.source_kcs, variant) is not None:
                return {"question_id": item.source_question_id, "kcs": list(item.source_kcs),
                        "seed": int(sha256(decision_id.encode()).hexdigest()[:15], 16),
                        "variant": variant}, None
        if writing:
            raise HTTPException(409, "本题没有已审核的迁移练习。")
        return None, None

    @staticmethod
    def _practice_transfer_view(saved, available=True):
        if saved is None:
            return {"available": available, "exercise": None, "feedback": None}
        if isinstance(saved, TransferAttempt):
            legacy = TRANSFER_ITEMS[saved.item_id]
            table = "events" if legacy.id == EVENTS.id else "loans"
            item = {**legacy.public(), "tables": [{"name": table, "columns": legacy.columns, "rows": legacy.rows}],
                    "correct_option": legacy.correct_option, "feedback": legacy.feedback}
        else:
            item = saved.item
        feedback = None if saved.option is None else {
            "selected_option": saved.option, "correct": saved.correct, "correct_option": item["correct_option"],
            "text": item["feedback"], "result_columns": item.get("result_columns"), "result_rows": item.get("result_rows"),
        }
        return {"available": True, "exercise": {key: item[key] for key in ("id", "context", "sql", "tables", "options")},
                "feedback": feedback}

    def practice_transfer_status(self, learner_id, decision_id):
        with self.db.transaction() as db:
            arguments, saved = self._practice_transfer(db, learner_id, decision_id)
            return self._practice_transfer_view(saved, available=arguments is not None)

    async def offer_practice_transfer(self, learner_id, decision_id):
        with self.db.transaction() as db:
            arguments, saved = self._practice_transfer(db, learner_id, decision_id, writing=True)
            if saved:
                return self._practice_transfer_view(saved)
        try:
            async with open_lab(TRANSFER_SCOPE) as lab:
                item = await lab.call("transfer", TRANSFER_TOOL, arguments)
        except Exception as error:
            logger.warning("Transfer exercise unavailable (%s)", type(error).__name__)
            raise HTTPException(503, "迁移练习暂时无法生成，请重试。") from error
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            _, saved = self._practice_transfer(db, learner_id, decision_id, writing=True)
            if saved is None:
                saved = PracticeTransfer(decision_id=decision_id, item=item)
                db.add(saved)
            return self._practice_transfer_view(saved)

    def answer_practice_transfer(self, learner_id, decision_id, option):
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            _, saved = self._practice_transfer(db, learner_id, decision_id, writing=True)
            if saved is None:
                raise HTTPException(409, "请先打开迁移练习。")
            correct_option = (TRANSFER_ITEMS[saved.item_id].correct_option if isinstance(saved, TransferAttempt)
                              else saved.item["correct_option"])
            self._save_transfer_answer(saved, option, correct_option)
            return self._practice_transfer_view(saved)

    def memories(self, learner_id, topic=None, *, limit=20, offset=0) -> list[dict]:
        with self.db.transaction() as db:
            query = active_memories(learner_id)
            if topic:
                query = query.where(LearningMemory.topic == topic)
            rows = db.scalars(query.order_by(LearningMemory.updated_at.desc(), LearningMemory.id)
                              .offset(offset).limit(limit))
            return [view(row) for row in rows]

    def relevant_memories(self, learner_id, topic) -> list[dict]:
        return self.memories(learner_id, topic, limit=2)

    async def _explain(self, run_id, learner_id, token, topic, message, result):
        try:
            with self.db.transaction() as db:
                run = self._owned(db, learner_id, run_id)
                if not self._current(db, run) or run.status not in ("completed", "waiting_confirmation"):
                    return
            memories = self.relevant_memories(learner_id, topic)
            detail = await explain(self.practice.tutor.model, self.explanation_model, message, result, memories)
            with self.db.transaction() as db:
                self.practice._lock_learner(db, learner_id)
                run = self._owned(db, learner_id, run_id)
                if (run.execution_token != token or run.status not in ("completed", "waiting_confirmation")
                        or not self._current(db, run)):
                    return
                for record in memories:
                    if record["memory_id"] in detail.get("memory_ids", ()):
                        memory = db.get(LearningMemory, record["memory_id"])
                        if memory is None or memory.deleted_at is not None or memory.version != record["version"]:
                            detail = {"status": "fallback", "reason": "memory_changed", "elapsed_ms": detail["elapsed_ms"]}
                            break
                run.result = {**run.result, "explanation": detail}
                self._event(db, run_id, "explanation_finished", status=detail["status"])
            self._notify(run_id)
        except (HTTPException, SQLAlchemyError) as error:
            logger.warning("Diagnosis explanation not published (%s)", type(error).__name__)

    def change_memory(self, learner_id, memory_id, *, summary=None, version=None) -> dict:
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            memory = db.get(LearningMemory, memory_id)
            if memory is None or memory.learner_id != learner_id:
                raise HTTPException(404, "学习记录不存在。")
            if summary is None:
                memory.deleted_at = memory.deleted_at or now()
                return {"memory_id": memory_id, "deleted": True}
            if memory.deleted_at is not None:
                raise HTTPException(404, "学习记录不存在。")
            if memory.version != version:
                raise HTTPException(409, "学习记录已更新，请刷新后再修改。")
            memory.summary = summary
            memory.version += 1
            memory.updated_at = now()
            return view(memory)

    async def confirm(self, learner_id, run_id, proposal_id, action, summary, key) -> dict:
        async with self.confirm_lock:
            choice = {"proposal_id": proposal_id, "action": action, "summary": summary, "key": key}
            with self.db.transaction() as db:
                self.practice._lock_learner(db, learner_id)
                run = self._owned(db, learner_id, run_id)
                if run.confirmation:
                    saved_choice = run.confirmation["choice"]
                    if any(saved_choice[field] != choice[field] for field in ("proposal_id", "action", "summary")):
                        raise HTTPException(409, "该提案已有不同的确认记录。")
                    choice = saved_choice
                    if "response" in run.confirmation:
                        return run.confirmation["response"]
                if (run.status != "waiting_confirmation" or run.proposal["proposal_id"] != proposal_id
                        or not self._current(db, run) or not self._proposal_fresh(run)):
                    raise HTTPException(409, "该诊断提案已失效。")
                run.confirmation = {"choice": choice}
            try:
                await resume_confirmation(self.graph, run_id, choice)
            except Exception as error:
                logger.warning("Confirmation checkpoint unavailable (%s)", type(error).__name__)
                raise HTTPException(503, "确认暂时未完成，请重试同一次操作。") from error
            with self.db.transaction() as db:
                self.practice._lock_learner(db, learner_id)
                run = self._owned(db, learner_id, run_id)
                if (run.status != "waiting_confirmation" or not self._current(db, run)
                        or not self._proposal_fresh(run)):
                    raise HTTPException(409, "该诊断提案已失效。")
                memory_id = None
                if action != "skip":
                    memory_id = uuid4().hex
                    db.add(LearningMemory(id=memory_id, learner_id=learner_id, proposal_id=proposal_id,
                                          decision_id=run.decision_id, topic=run.proposal["topic"],
                                          summary=summary if action == "edit" else run.proposal["summary"],
                                          evidence_refs=run.proposal["evidence_refs"],
                                          created_at=now(), updated_at=now()))
                response = {"status": "completed", "memory_id": memory_id, "action": action}
                run.confirmation = {"choice": choice, "response": response}
                run.status = "completed"
                self._event(db, run.id, "run_finished", status=run.status)
                return response

    @staticmethod
    def _proposal_fresh(run):
        return datetime.fromisoformat(run.proposal["expires_at"]) > now()

    def _claim(self):
        with self.db.transaction() as db:
            cutoff = now()
            queued = db.scalar(select(DiagnosisRun.id).where(DiagnosisRun.status == "queued")
                               .order_by(DiagnosisRun.created_at, DiagnosisRun.id).limit(1))
            has_expired = db.scalar(select(DiagnosisRun.id).where(
                DiagnosisRun.status == "running", DiagnosisRun.lease_until < cutoff,
            ).limit(1))
            if not queued and not has_expired:
                return None
            if has_expired:
                expired = db.execute(update(DiagnosisRun).where(
                    DiagnosisRun.status == "running", DiagnosisRun.lease_until < cutoff,
                ).values(status="failed", result={"fallback_reason": "worker_interrupted"})
                    .returning(DiagnosisRun.id)).scalars().all()
                for run_id in expired:
                    self._event(db, run_id, "run_finished", status="failed")
            if not queued:
                return None
            token = uuid4().hex
            claimed = db.execute(update(DiagnosisRun).where(
                DiagnosisRun.id == queued, DiagnosisRun.status == "queued",
            ).values(status="running", execution_token=token, lease_until=now() + timedelta(seconds=50))
                .returning(DiagnosisRun.id, DiagnosisRun.learner_id, DiagnosisRun.message, DiagnosisRun.fixture_id)
            ).one_or_none()
            if claimed is None:
                return None
            self._event(db, claimed.id, "run_started", status="running")
            return claimed.id, claimed.learner_id, token, claimed.message, claimed.fixture_id

    def _publish(self, run_id, learner_id, token, *, branch=None, branch_status=None, result=None, proposal=None):
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner_id)
            run = db.get(DiagnosisRun, run_id)
            if (run is None or run.status != "running" or run.execution_token != token
                    or run.lease_until is None or run.lease_until <= now()):
                return False
            if not self._current(db, run):
                run.status = "stale"
                self._event(db, run.id, "run_finished", status=run.status)
                return False
            if branch:
                run.branches = {**run.branches, branch: branch_status}
                self._event(db, run.id, "branch_started" if branch_status == "running" else "branch_finished",
                            branch=branch, status=branch_status)
            if result is not None:
                run.result = result
                run.proposal = proposal
                run.status = "waiting_confirmation" if proposal else "completed"
                if result.get("sources") or result.get("comparison"):
                    self._event(db, run.id, "evidence_verified", mode=result["mode"])
                self._event(db, run.id, "waiting_for_confirmation" if proposal else "run_finished", status=run.status)
            return True

    async def _run_queue(self):
        while True:
            self.wake.clear()
            try:
                claim = self._claim()
            except SQLAlchemyError as error:
                logger.warning("Diagnosis queue unavailable (%s)", type(error).__name__)
                await asyncio.sleep(1)
                continue
            if claim is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.wake.wait(), timeout=1)
                continue
            run_id, learner_id, token, message, fixture_id = claim
            self._notify(run_id)
            topic = FIXTURES[fixture_id].topic
            try:
                if not self._publish(run_id, learner_id, token):
                    continue
            except SQLAlchemyError as error:
                logger.warning("Diagnosis start unavailable (%s)", type(error).__name__)
                continue

            async def progress(branch, status):
                if not self._publish(run_id, learner_id, token, branch=branch, branch_status=status):
                    raise LabError("inactive_run")
                self._notify(run_id)

            try:
                result = await self.engine.run(message, progress=progress, fixture_id=fixture_id,
                                               strategy="evidence_first")
            except Exception as error:
                logger.warning("SQL diagnosis failed (%s)", type(error).__name__)
                result = {"mode": "reviewed_hint", "summary": EXPLANATIONS[
                    "group_then_filter" if topic == "aggregate" else "join_on_where"],
                          "sources": [], "observations": [], "comparison": None,
                          "fallback_reason": "diagnosis_unavailable"}
            proposal = None
            if result["mode"] == "full":
                proposal = {"proposal_id": uuid4().hex, "topic": topic,
                            "summary": ("复习 GROUP BY 得到分组后，怎样用 HAVING 筛选各组。" if topic == "aggregate"
                                        else "复习 LEFT JOIN 中 ON 与 WHERE 对未匹配行的影响。"),
                            "evidence_refs": [result["comparison"]["comparison_id"],
                                              *[card["id"] for card in result["sources"]]],
                            "expires_at": (now() + timedelta(hours=24)).isoformat()}
                try:
                    await wait_for_confirmation(self.graph, run_id, proposal)
                except Exception as error:
                    logger.warning("Memory proposal checkpoint failed (%s)", type(error).__name__)
                    proposal = None
            try:
                if result["mode"] == "full" and self.explanation_model:
                    detail = ({"status": "pending", "expires_at": (now() + timedelta(seconds=EXPLANATION_TIMEOUT + 1)).isoformat()}
                              if len(self.explanations) < MAX_EXPLANATIONS else {"status": "fallback", "reason": "busy"})
                    result = {**result, "explanation": detail}
                published = self._publish(run_id, learner_id, token, result=result, proposal=proposal)
                self._notify(run_id)
                if published and result.get("explanation", {}).get("status") == "pending":
                    task = asyncio.create_task(self._explain(run_id, learner_id, token, topic, message, result))
                    self.explanations.add(task)
                    task.add_done_callback(self.explanations.discard)
            except SQLAlchemyError as error:
                logger.warning("Diagnosis result unavailable (%s)", type(error).__name__)


def migrate(engine):
    """Apply additive diagnosis migrations to an existing practice database."""
    with engine.begin() as connection:
        revisions = Table("query_schema_revisions", MetaData(), Column("id", String(80), primary_key=True))
        revisions.create(connection, checkfirst=True)
        revision = "diagnostics_001"
        if connection.scalar(select(revisions.c.id).where(revisions.c.id == revision)) is None:
            Base.metadata.create_all(connection, tables=[DiagnosisRun.__table__, DiagnosisEvent.__table__,
                                                          LearningMemory.__table__])
            connection.execute(revisions.insert().values(id=revision))
        revision = "diagnostics_002"
        if connection.scalar(select(revisions.c.id).where(revisions.c.id == revision)) is None:
            DiagnosisExperiment.__table__.create(connection, checkfirst=True)
            connection.execute(revisions.insert().values(id=revision))
        revision = "diagnostics_003"
        if connection.scalar(select(revisions.c.id).where(revisions.c.id == revision)) is None:
            TransferAttempt.__table__.create(connection, checkfirst=True)
            connection.execute(revisions.insert().values(id=revision))
        revision = "diagnostics_004"
        if connection.scalar(select(revisions.c.id).where(revisions.c.id == revision)) is None:
            PracticeTransfer.__table__.create(connection, checkfirst=True)
            connection.execute(revisions.insert().values(id=revision))
        for table in (DiagnosisRun.__table__, DiagnosisEvent.__table__, LearningMemory.__table__,
                      DiagnosisExperiment.__table__, TransferAttempt.__table__, PracticeTransfer.__table__):
            actual = {column["name"] for column in inspect(connection).get_columns(table.name)}
            if not set(table.columns.keys()) <= actual:
                raise RuntimeError(f"Database table {table.name} needs a migration.")
