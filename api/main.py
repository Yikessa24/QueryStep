"""HTTP API for the versioned practice and tutoring workflow."""

from contextlib import asynccontextmanager
import asyncio
import json
import logging
import os
from pathlib import Path
from pickle import UnpicklingError
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

from api.catalog import Catalog, DEFAULT_CATALOG, GOAL
from api.db import Database
from api.practice import Practice
from api.recommend import CalibratedScorer, Recommender
from kt.pykt_source import ROOT
from tutor.agent import TutorAgent
from tutor.provider import ChatModel

COOKIE = "querystep_session"
logger = logging.getLogger(__name__)


class Submission(BaseModel):
    option: int = Field(ge=0, le=20, strict=True)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class TutorMessage(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DiagnosisRequest(TutorMessage):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class ExperimentRequest(BaseModel):
    query_id: Literal["having_gt", "having_gte", "join_where"]
    min_count: int | None = Field(default=None, strict=True, ge=0, le=50)
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")

    @model_validator(mode="after")
    def validate_parameters(self):
        if self.query_id.startswith("having_") != (self.min_count is not None):
            raise ValueError("A threshold is required for HAVING queries only.")
        return self


class TransferAnswer(BaseModel):
    option: int = Field(strict=True, ge=0, le=3)


MemorySummary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class ConfirmationRequest(BaseModel):
    proposal_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    action: Literal["confirm", "edit", "skip"]
    summary: MemorySummary | None = None
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")

    @model_validator(mode="after")
    def validate_edit(self):
        if (self.action == "edit") != (self.summary is not None):
            raise ValueError("Provide a summary exactly when editing a proposal.")
        return self


class MemoryEdit(BaseModel):
    summary: MemorySummary
    version: int = Field(strict=True, ge=1)


def create_app(database_url=None, catalog=None, recommender=None, tutor=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        url = database_url or os.environ.get("QUERYSTEP_DATABASE_URL")
        if not url:
            (ROOT / "artifacts").mkdir(mode=0o700, exist_ok=True)
            path = ROOT / "artifacts/querystep.sqlite3"
            try:
                handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(handle)
            url = f"sqlite:///{path}"
        database = Database(url)
        database.initialize()
        configured_catalog = catalog or Catalog.load(
            Path(os.environ.get("QUERYSTEP_CATALOG", DEFAULT_CATALOG))
        )
        scoring = None
        recommendation = recommender
        if not recommendation:
            reason = "model_unconfigured"
            run = os.environ.get("QUERYSTEP_EPIKT_RUN")
            if run:
                try:
                    scoring = CalibratedScorer(Path(run))
                    reason = "unmapped_catalog_or_history"
                except (OSError, ValueError, KeyError, RuntimeError, ImportError,
                        TypeError, UnpicklingError) as error:
                    reason = "model_unavailable"
                    logger.warning("EpiKT initialization failed (%s)", type(error).__name__)
            recommendation = Recommender(scoring, reason)

        chat = None
        tutoring = tutor
        if not tutoring:
            base = os.environ.get("QUERYSTEP_LLM_BASE_URL")
            model = os.environ.get("QUERYSTEP_LLM_MODEL")
            key = os.environ.get("QUERYSTEP_LLM_API_KEY")
            timeout = 5.0
            unavailable = "llm_unconfigured"
            if base or model or key:
                try:
                    if not base or not model or not model.strip():
                        raise ValueError("Both the model service URL and model ID are required.")
                    timeout = float(os.environ.get("QUERYSTEP_LLM_TIMEOUT_SECONDS", "5"))
                    if not 0.1 <= timeout <= 30:
                        raise ValueError("The tutor timeout must be between 0.1 and 30 seconds.")
                    insecure = os.environ.get("QUERYSTEP_LLM_ALLOW_INSECURE_HTTP") == "1"
                    chat = ChatModel(base, model.strip(), key, allow_insecure_http=insecure)
                    if chat.client.base_url.scheme == "http" and insecure:
                        logger.warning("Tutor uses explicitly enabled unencrypted HTTP")
                except ValueError:
                    unavailable = "llm_invalid_configuration"
                    logger.warning("Tutor configuration rejected; using reviewed hints")
            tutoring = TutorAgent(
                chat, timeout=timeout, unavailable=unavailable,
                allow_mapped_items=os.environ.get("QUERYSTEP_LLM_ALLOW_MAPPED_ITEMS") == "1",
            )
        app.state.practice = Practice(database, configured_catalog, recommendation, tutoring)
        app.state.diagnostics = None
        app.state.diagnostics_reason = "disabled"
        if os.environ.get("QUERYSTEP_DIAGNOSTICS_ENABLED") == "1":
            try:
                from api.diagnostics import Diagnostics

                checkpoint = os.environ.get("QUERYSTEP_DIAGNOSIS_CHECKPOINTS")
                explanation_model = os.environ.get("QUERYSTEP_EXPLANATION_MODEL", "gemini-3-flash").strip()
                diagnostics = Diagnostics(app.state.practice, Path(checkpoint) if checkpoint else None,
                                          explanation_model=explanation_model or None)
                await diagnostics.start()
                app.state.diagnostics = diagnostics
                app.state.diagnostics_reason = None
            except Exception as error:
                app.state.diagnostics_reason = "startup_failed"
                logger.warning("Diagnostics startup failed (%s)", type(error).__name__)
        try:
            yield
        finally:
            if app.state.diagnostics:
                await app.state.diagnostics.close()
            if chat:
                await chat.aclose()
                chat.close()
            if scoring:
                scoring.close()
            database.engine.dispose()

    app = FastAPI(title="QueryStep", version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def prevent_session_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def service(request: Request) -> Practice:
        return request.app.state.practice

    def learner(
        request: Request, querystep_session: Annotated[str | None, Cookie()] = None
    ) -> str:
        return service(request).learner(querystep_session)

    @app.get("/healthz")
    def health(request: Request):
        practice = service(request)
        return {"status": "ok", "service": "querystep",
                "catalog_version": practice.catalog.version,
                "epikt_ready": bool(practice.recommender.scorer) and all(
                    practice.recommender.scorer.supports(item) for item in practice.catalog.items.values()
                ),
                "tutor_ready": bool(practice.tutor.model),
                "tutor_status": "configured" if practice.tutor.model else practice.tutor.unavailable,
                "diagnostics_ready": request.app.state.diagnostics is not None,
                "mcp_ready": request.app.state.diagnostics is not None,
                "diagnostics_reason": request.app.state.diagnostics_reason}

    @app.post("/api/session")
    def start(request: Request, response: Response, restart: bool = False,
              querystep_session: Annotated[str | None, Cookie()] = None):
        token = service(request).start(None if restart else querystep_session)
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                            secure=os.environ.get("QUERYSTEP_SECURE_COOKIE") == "1",
                            max_age=30 * 24 * 60 * 60)
        return {"goal_id": GOAL, "goal": "SQL 基础查询与条件筛选"}

    @app.get("/api/practice/progress")
    def progress(request: Request, user: str = Depends(learner)):
        return service(request).progress(user)

    @app.post("/api/practice/next")
    def next_item(request: Request, user: str = Depends(learner)):
        return service(request).next(user)

    @app.post("/api/practice/{decision_id}/answer")
    def answer(decision_id: str, body: Submission, request: Request, user: str = Depends(learner)):
        return service(request).submit(user, decision_id, body.option, body.idempotency_key)

    @app.get("/api/practice/{decision_id}/replay")
    def replay(decision_id: str, request: Request, user: str = Depends(learner)):
        return service(request).replay(user, decision_id)

    @app.post("/api/practice/{decision_id}/tutor")
    def tutor_turn(decision_id: str, body: TutorMessage, request: Request, user: str = Depends(learner)):
        diagnostics = request.app.state.diagnostics
        return service(request).tutor_turn(user, decision_id, body.message,
                                           memory_lookup=diagnostics.relevant_memories if diagnostics else None)

    def diagnostics_service(request: Request):
        diagnostics = request.app.state.diagnostics
        if diagnostics is None:
            raise HTTPException(503, "SQL 诊断当前不可用。")
        return diagnostics

    @app.get("/api/practice/{decision_id}/diagnosis")
    def latest_diagnosis(decision_id: str, request: Request, user: str = Depends(learner)):
        diagnostics = request.app.state.diagnostics
        if diagnostics is None:
            return {"available": False, "run": None}
        return diagnostics.latest(user, decision_id)

    @app.post("/api/practice/{decision_id}/diagnosis", status_code=202)
    async def start_diagnosis(decision_id: str, body: DiagnosisRequest, request: Request,
                              user: str = Depends(learner)):
        return await diagnostics_service(request).enqueue(user, decision_id, body.message, body.idempotency_key)

    @app.get("/api/diagnosis/{run_id}")
    def diagnosis_status(run_id: str, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).status(user, run_id)

    @app.get("/api/diagnosis/{run_id}/events")
    async def diagnosis_events(run_id: str, request: Request, user: str = Depends(learner),
                               after_seq: Annotated[int, Query(ge=0)] = 0):
        diagnostics = diagnostics_service(request)
        header = request.headers.get("Last-Event-ID", "")
        if header:
            if len(header) > 10 or not header.isascii() or not header.isdecimal():
                raise HTTPException(422, "事件序号无效。")
            after_seq = int(header)
        diagnostics.events(user, run_id, after_seq)

        async def stream():
            sequence = after_seq
            with diagnostics.subscribe(run_id) as signal:
                while not await request.is_disconnected():
                    signal.clear()
                    status, events = diagnostics.events(user, run_id, sequence)
                    for event in events:
                        sequence = event["seq"]
                        yield f"id: {sequence}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if status not in ("queued", "running"):
                        yield "event: settled\ndata: {}\n\n"
                        return
                    try:
                        await asyncio.wait_for(signal.wait(), timeout=0.5)
                    except TimeoutError:
                        continue

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/diagnosis/{run_id}/cancel")
    def cancel_diagnosis(run_id: str, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).cancel(user, run_id)

    @app.post("/api/diagnosis/{run_id}/experiment")
    async def run_experiment(run_id: str, body: ExperimentRequest, request: Request,
                             user: str = Depends(learner)):
        return await diagnostics_service(request).experiment(user, run_id, body.query_id, body.min_count,
                                                             body.idempotency_key)

    @app.post("/api/diagnosis/{run_id}/confirmation")
    async def confirm_diagnosis(run_id: str, body: ConfirmationRequest, request: Request,
                                user: str = Depends(learner)):
        return await diagnostics_service(request).confirm(
            user, run_id, body.proposal_id, body.action, body.summary, body.idempotency_key,
        )

    @app.get("/api/diagnosis/{run_id}/transfer")
    def transfer_status(run_id: str, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).transfer(user, run_id)

    @app.post("/api/diagnosis/{run_id}/transfer")
    def open_transfer(run_id: str, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).transfer(user, run_id, offer=True)

    @app.post("/api/diagnosis/{run_id}/transfer/answer")
    def answer_transfer(run_id: str, body: TransferAnswer, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).transfer(user, run_id, option=body.option)

    @app.get("/api/learning-memories")
    def learning_memories(request: Request, user: str = Depends(learner),
                          topic: Annotated[str | None, Query(max_length=40)] = None,
                          limit: Annotated[int, Query(ge=1, le=50)] = 20,
                          offset: Annotated[int, Query(ge=0)] = 0):
        return diagnostics_service(request).memories(user, topic, limit=limit, offset=offset)

    @app.patch("/api/learning-memories/{memory_id}")
    def edit_memory(memory_id: str, body: MemoryEdit, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).change_memory(user, memory_id, summary=body.summary, version=body.version)

    @app.delete("/api/learning-memories/{memory_id}")
    def delete_memory(memory_id: str, request: Request, user: str = Depends(learner)):
        return diagnostics_service(request).change_memory(user, memory_id)

    return app


app = create_app()
