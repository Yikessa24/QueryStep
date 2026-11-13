"""Confirmed cross-session learning records and an interruptible confirmation graph."""

from contextlib import asynccontextmanager
from datetime import datetime

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context
from sqlalchemy import DateTime, ForeignKey, JSON, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from typing import TypedDict

from api.db import Base


class LearningMemory(Base):
    __tablename__ = "learning_memories"
    __table_args__ = (UniqueConstraint("learner_id", "proposal_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    proposal_id: Mapped[str] = mapped_column(String(32))
    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"))
    topic: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(String(300))
    evidence_refs: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)


def active_memories(learner_id):
    return select(LearningMemory).where(LearningMemory.learner_id == learner_id,
                                        LearningMemory.deleted_at.is_(None))


def view(memory: LearningMemory) -> dict:
    return {"memory_id": memory.id, "topic": memory.topic, "summary": memory.summary,
            "version": memory.version, "decision_id": memory.decision_id,
            "updated_at": memory.updated_at.isoformat() + "Z"}


class ConfirmationState(TypedDict, total=False):
    proposal: dict
    confirmation: dict


def ask_confirmation(state: ConfirmationState) -> dict:
    return {"confirmation": interrupt(state["proposal"])}


@asynccontextmanager
async def confirmation_graph(path):
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        graph = StateGraph(ConfirmationState)
        graph.add_node("ask_confirmation", ask_confirmation)
        graph.add_edge(START, "ask_confirmation")
        graph.add_edge("ask_confirmation", END)
        yield graph.compile(checkpointer=saver)


async def wait_for_confirmation(graph, run_id: str, proposal: dict) -> None:
    config = {"configurable": {"thread_id": run_id}}
    with tracing_context(enabled=False):
        result = await graph.ainvoke({"proposal": proposal}, config)
    if not result.get("__interrupt__"):
        raise RuntimeError("Expected a persisted confirmation interrupt.")


async def resume_confirmation(graph, run_id: str, confirmation: dict) -> None:
    config = {"configurable": {"thread_id": run_id}}
    state = await graph.aget_state(config)
    previous = state.values.get("confirmation")
    if previous is None:
        with tracing_context(enabled=False):
            result = await graph.ainvoke(Command(resume=confirmation), config)
        previous = result.get("confirmation")
    if previous != confirmation:
        raise RuntimeError("Mismatched confirmation checkpoint.")
