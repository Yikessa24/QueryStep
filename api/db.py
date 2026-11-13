"""Practice ledger. PostgreSQL for deployment and SQLite for local development."""

from contextlib import contextmanager

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class Learner(Base):
    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    history_version: Mapped[int] = mapped_column(Integer, default=0)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (UniqueConstraint("learner_id", "history_version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    history_version: Mapped[int] = mapped_column(Integer)
    catalog_version: Mapped[str] = mapped_column(String(80))
    item_id: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(100))
    trace: Mapped[dict] = mapped_column(JSON)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (
        UniqueConstraint("learner_id", "event_seq"),
        UniqueConstraint("learner_id", "idempotency_key"),
    )

    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), primary_key=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    event_seq: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer)
    option: Mapped[int] = mapped_column(Integer)
    correct: Mapped[bool] = mapped_column(Boolean)
    idempotency_key: Mapped[str] = mapped_column(String(80))


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (UniqueConstraint("decision_id", "ordinal"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("attempts.decision_id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(500))
    result: Mapped[dict] = mapped_column(JSON)


class Database:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            from sqlalchemy import event

            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")

    def initialize(self):
        # Initial schema only. Future incompatible changes require migrations.
        Base.metadata.create_all(self.engine, tables=[Learner.__table__, Decision.__table__,
                                                       Attempt.__table__, TutorTurn.__table__])

    @contextmanager
    def transaction(self):
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            yield session
