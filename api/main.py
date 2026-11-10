"""HTTP API for the versioned practice and tutoring workflow."""

from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from pickle import UnpicklingError
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, Request, Response
from pydantic import BaseModel, Field, StringConstraints

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
        try:
            yield
        finally:
            if chat:
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
                "tutor_status": "configured" if practice.tutor.model else practice.tutor.unavailable}

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
        return service(request).tutor_turn(user, decision_id, body.message)

    return app


app = create_app()
