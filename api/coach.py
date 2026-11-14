"""Persist bounded coaching runs separately from the practice ledger."""

import asyncio
from contextlib import AsyncExitStack
from hashlib import sha256
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column

from api.db import Attempt, Base
from sql_lab.client import open_lab
from sql_lab.contracts import COACH_SCOPE
from tutor.coach import Coach
from tutor.diagnosis_explanation import _safe_excerpt

logger = logging.getLogger(__name__)
TOPICS = {75: "aggregate", 81: "join"}
MAX_ACTIVE = 3


class CoachRun(Base):
    __tablename__ = "coach_runs"
    __table_args__ = (UniqueConstraint("learner_id", "request_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"), index=True)
    request_key: Mapped[str] = mapped_column(String(80))
    digest: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16))
    events: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ordinal: Mapped[int]


class CoachService:
    def __init__(self, practice, model, index_path=None, embedding_model=None):
        self.practice = practice
        self.db = practice.db
        self.model = model
        self.args = ()
        for flag, path in (("--knowledge-index", index_path), ("--embedding-model", embedding_model)):
            if path:
                self.args += (flag, str(Path(path).resolve()))
        self.stack = AsyncExitStack()
        self.worker: Coach | None = None
        self.tasks = {}

    async def start(self):
        try:
            lab = await self.stack.enter_async_context(open_lab(COACH_SCOPE, knowledge_args=self.args))
            CoachRun.__table__.create(self.db.engine, checkfirst=True)
            with self.db.transaction() as db:
                # The embedded stdio worker is owned by one app process.
                for run in db.scalars(select(CoachRun).where(CoachRun.status == "running")):
                    run.status = "interrupted"
            self.worker = Coach(self.practice.tutor.model, self.model, lab)
        except BaseException:
            await self.stack.aclose()
            raise

    async def close(self):
        tasks = tuple(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.stack.aclose()

    def _topic(self, db, learner, decision):
        selected = self.practice._owned_decision(db, learner, decision)
        self.practice._check_catalog(selected.catalog_version)
        return TOPICS.get(self.practice.catalog.items[selected.item_id].source_question_id)

    @staticmethod
    def _view(run):
        return {"id": run.id, "message": run.message, "status": run.status,
                "events": run.events, "result": run.result}

    def status(self, learner, decision):
        with self.db.transaction() as db:
            topic = self._topic(db, learner, decision)
            attempt = db.get(Attempt, decision)
            if not topic or not attempt or attempt.correct:
                return {"available": False, "runs": []}
            runs = db.scalars(select(CoachRun).where(CoachRun.learner_id == learner, CoachRun.decision_id == decision)
                              .order_by(CoachRun.ordinal)).all()
            current = self.practice._is_current_wrong(db, attempt)
            return {"available": current or bool(runs), "can_submit": current,
                    "runs": [self._view(run) for run in runs]}

    async def submit(self, learner, decision, message, key):
        digest = sha256(f"{decision}\n{message}".encode()).hexdigest()
        message = _safe_excerpt(message, 500)
        with self.db.transaction() as db:
            self.practice._lock_learner(db, learner)
            topic = self._topic(db, learner, decision)
            duplicate = db.scalar(select(CoachRun).where(CoachRun.learner_id == learner, CoachRun.request_key == key))
            if duplicate:
                if duplicate.digest != digest:
                    raise HTTPException(409, "此提交编号已使用。")
                return self._view(duplicate)
            self.practice._tutoring_attempt(db, learner, decision)
            if not topic:
                raise HTTPException(409, "这道题可以使用普通助教或迁移练习。")
            runs = db.scalars(select(CoachRun).where(CoachRun.decision_id == decision).order_by(CoachRun.ordinal)).all()
            if any(run.status == "running" for run in runs):
                raise HTTPException(409, "本题还有一次辅导正在运行。")
            if len(runs) >= 8:
                raise HTTPException(409, "已达到本题的辅导轮数。")
            if len(self.tasks) >= MAX_ACTIVE:
                raise HTTPException(503, "错题教练正忙，请重试或使用快速诊断。")
            prior = [{"message": run.message, "outcome": run.result["text"], "question": run.result["question"]}
                     for run in runs if run.result][-2:]
            run = CoachRun(id=uuid4().hex, learner_id=learner, decision_id=decision, request_key=key, digest=digest,
                           message=message, status="running", events=[], ordinal=len(runs))
            db.add(run)
            view = self._view(run)
        task = asyncio.create_task(self._execute(run.id, learner, decision, message, topic, prior))
        self.tasks[run.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run.id, None))
        return view

    async def _execute(self, identifier, learner, decision, message, topic, prior):
        def update(*, event=None, result=None, status=None):
            with self.db.transaction() as db:
                self.practice._lock_learner(db, learner)
                run = db.get(CoachRun, identifier)
                if not self.practice._is_current_wrong(db, db.get(Attempt, decision)):
                    run.status = "stale"
                    return False
                if event:
                    run.events = [*run.events, event]
                if status:
                    run.status, run.result = status, result
                return True

        async def publish(event):
            if not update(event=event):
                raise StaleRun

        try:
            result = await self.worker.run(message, topic, publish=publish, prior=prior)
            update(result=result, status="complete")
        except StaleRun:
            pass
        except asyncio.CancelledError:
            update(status="interrupted")
            raise
        except Exception as error:
            logger.warning("Coach run failed (%s)", type(error).__name__)
            update(status="interrupted")


class StaleRun(Exception):
    pass
