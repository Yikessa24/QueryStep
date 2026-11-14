"""The practice service owns decisions, grading, and the versioned history."""

from hashlib import sha256
import secrets
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update

from api.catalog import Catalog
from api.db import Attempt, Database, Decision, Learner, TutorTurn
from api.recommend import Recommender
from course_content.lessons import reviewed_hint


class Practice:
    def __init__(self, database: Database, catalog: Catalog, recommender: Recommender, tutor):
        self.db = database
        self.catalog = catalog
        self.recommender = recommender
        self.tutor = tutor

    @staticmethod
    def learner_id(token: str) -> str:
        return sha256(token.encode()).hexdigest()

    def start(self, existing: str | None) -> str:
        if existing:
            with self.db.transaction() as db:
                if db.get(Learner, self.learner_id(existing)):
                    return existing
        token = secrets.token_urlsafe(32)
        with self.db.transaction() as db:
            db.add(Learner(id=self.learner_id(token)))
        return token

    def learner(self, token: str | None) -> str:
        if not token or len(token) > 64:
            raise HTTPException(401, "请先开始练习。")
        learner_id = self.learner_id(token)
        with self.db.transaction() as db:
            if not db.get(Learner, learner_id):
                raise HTTPException(401, "练习会话已失效。")
        return learner_id

    @staticmethod
    def _lock_learner(db, learner_id: str, version: int | None = None) -> bool:
        query = update(Learner).where(Learner.id == learner_id)
        if version is not None:
            query = query.where(Learner.history_version == version)
        return db.execute(query.values(history_version=Learner.history_version)).rowcount == 1

    @staticmethod
    def _decision(db, learner_id: str, version: int) -> Decision | None:
        return db.scalar(select(Decision).where(
            Decision.learner_id == learner_id, Decision.history_version == version
        ))

    def _present(self, decision: Decision) -> dict:
        self._check_catalog(decision.catalog_version)
        return {"status": "ready", "decision_id": decision.id,
                "item": self.catalog.items[decision.item_id].public(),
                "source": decision.source, "reason": decision.reason}

    def _check_catalog(self, revision: str) -> None:
        if revision != self.catalog.revision:
            raise HTTPException(409, {
                "code": "catalog_changed", "message": "题库已更新，此会话需要重新开始。",
            })

    @staticmethod
    def _history(db, learner_id: str, version: int) -> list[Attempt]:
        return list(db.scalars(select(Attempt).where(
            Attempt.learner_id == learner_id, Attempt.event_seq <= version
        ).order_by(Attempt.event_seq)))

    def next(self, learner_id: str) -> dict:
        for _ in range(2):
            with self.db.transaction() as db:
                version = db.get(Learner, learner_id).history_version
                existing = self._decision(db, learner_id, version)
                if existing:
                    return self._present(existing)
                previous = db.scalar(select(Decision.catalog_version).where(
                    Decision.learner_id == learner_id
                ).limit(1))
                if previous:
                    self._check_catalog(previous)
                history = [(self.catalog.items[row.item_id], row.correct)
                           for row in self._history(db, learner_id, version)]

            selected = self.recommender.decide(self.catalog.items, history)
            with self.db.transaction() as db:
                if not self._lock_learner(db, learner_id, version):
                    continue
                existing = self._decision(db, learner_id, version)
                if existing:
                    return self._present(existing)
                if not selected:
                    remaining = len(self.catalog.items) - len(history)
                    return {"status": "blocked" if remaining else "complete", "remaining": remaining}
                decision = Decision(id=uuid4().hex, learner_id=learner_id,
                                    history_version=version, catalog_version=self.catalog.revision,
                                    **selected)
                db.add(decision)
                return self._present(decision)
        raise HTTPException(409, "作答历史刚刚更新，请重试。")

    def _owned_decision(self, db, learner_id: str, decision_id: str) -> Decision:
        row = db.get(Decision, decision_id)
        if not row or row.learner_id != learner_id:
            raise HTTPException(404, "练习记录不存在。")
        return row

    def submit(self, learner_id: str, decision_id: str, option: int, key: str) -> dict:
        with self.db.transaction() as db:
            self._lock_learner(db, learner_id)
            decision = self._owned_decision(db, learner_id, decision_id)
            self._present(decision)
            existing = db.get(Attempt, decision_id)
            if existing:
                if existing.idempotency_key != key or existing.option != option:
                    raise HTTPException(409, "这道题已经提交。")
                return self._feedback(existing)
            learner = db.get(Learner, learner_id)
            if decision.history_version != learner.history_version:
                raise HTTPException(409, "当前练习已更新。")
            used = db.scalar(select(Attempt).where(
                Attempt.learner_id == learner_id, Attempt.idempotency_key == key
            ))
            if used:
                raise HTTPException(409, "此提交编号已使用。")
            item = self.catalog.items[decision.item_id]
            if not 0 <= option < len(item.options):
                raise HTTPException(422, "选项超出范围。")
            learner.history_version += 1
            attempt = Attempt(decision_id=decision_id, learner_id=learner_id,
                              event_seq=learner.history_version, item_id=item.id,
                              option=option, correct=option == item.correct_option,
                              idempotency_key=key)
            db.add(attempt)
            return self._feedback(attempt)

    def _feedback(self, attempt: Attempt) -> dict:
        item = self.catalog.items[attempt.item_id]
        return {"decision_id": attempt.decision_id, "event_seq": attempt.event_seq,
                "correct": attempt.correct, "selected_option": attempt.option,
                "template_hint": reviewed_hint(item.topic, item.prompt, item.hint) if not attempt.correct else None}

    def progress(self, learner_id: str) -> dict:
        with self.db.transaction() as db:
            version = db.get(Learner, learner_id).history_version
            attempts = self._history(db, learner_id, version)
            pending = self._decision(db, learner_id, version)
            last = attempts[-1] if attempts else None
            last_decision = db.get(Decision, last.decision_id) if last else None
            last_view = None
            if last_decision and not pending:
                last_view = self._review(db, last_decision, last)
            return {"total": len(attempts), "correct": sum(row.correct for row in attempts),
                    "pending": self._present(pending) if pending else None, "last": last_view}

    def _review(self, db, decision: Decision, attempt: Attempt) -> dict:
        return {"presentation": self._present(decision), "feedback": self._feedback(attempt),
                "turns": self._turns(db, decision.id)}

    def review(self, learner_id: str, event_seq: int) -> dict:
        with self.db.transaction() as db:
            attempt = db.scalar(select(Attempt).where(Attempt.learner_id == learner_id, Attempt.event_seq == event_seq))
            if attempt is None:
                raise HTTPException(404, "找不到这道已提交的练习。")
            return self._review(db, self._owned_decision(db, learner_id, attempt.decision_id), attempt)

    def replay(self, learner_id: str, decision_id: str) -> dict:
        with self.db.transaction() as db:
            decision = self._owned_decision(db, learner_id, decision_id)
            return {"decision_id": decision.id, "chosen_item_id": decision.item_id,
                    "history_version": decision.history_version, "source": decision.source,
                    "reason": decision.reason, "comparison": decision.trace}

    @staticmethod
    def _turns(db, decision_id: str) -> list[dict]:
        turns = db.scalars(select(TutorTurn).where(
            TutorTurn.decision_id == decision_id
        ).order_by(TutorTurn.ordinal)).all()
        return [{"message": row.message, **row.result} for row in turns]

    def _tutoring_attempt(self, db, learner_id: str, decision_id: str) -> Attempt:
        decision = self._owned_decision(db, learner_id, decision_id)
        self._present(decision)
        attempt = db.get(Attempt, decision_id)
        if not self._is_current_wrong(db, attempt):
            raise HTTPException(409, "请在当前错题的反馈页使用辅导。")
        return attempt

    def _is_current_wrong(self, db, attempt: Attempt | None) -> bool:
        if attempt is None or attempt.correct:
            return False
        version = db.get(Learner, attempt.learner_id).history_version
        return attempt.event_seq == version and self._decision(db, attempt.learner_id, version) is None

    def tutor_turn(self, learner_id: str, decision_id: str, message: str, *, memory_lookup=None) -> dict:
        with self.db.transaction() as db:
            attempt = self._tutoring_attempt(db, learner_id, decision_id)
            prior = self._turns(db, decision_id)
        if len(prior) >= 8:
            raise HTTPException(409, "已达到本题的辅导轮数，请继续练习。")
        item = self.catalog.items[attempt.item_id]
        started = monotonic()
        memories = memory_lookup(learner_id, item.topic) if memory_lookup else []
        if memories:
            result = self.tutor.respond(item, message, prior, memories=memories)
        else:
            result = self.tutor.respond(item, message, prior)
        result["elapsed_ms"] = round((monotonic() - started) * 1000)
        with self.db.transaction() as db:
            self._lock_learner(db, learner_id, attempt.event_seq)
            self._tutoring_attempt(db, learner_id, decision_id)
            if len(self._turns(db, decision_id)) != len(prior):
                raise HTTPException(409, "另一条辅导消息已提交，请重试。")
            db.add(TutorTurn(id=uuid4().hex, decision_id=decision_id,
                             ordinal=len(prior), message=message, result=result))
        return {"message": message, **result}
