"""Typed requests and results for the SQL lab MCP tools."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SearchRequest(Contract):
    query: str = Field(min_length=1, max_length=200)
    topic: Literal["aggregate", "join"]
    top_k: int = Field(default=3, ge=1, le=3)


class Card(Contract):
    id: str
    version: int
    topic: str
    title: str
    section: str
    url: str
    text: str
    match_score: int


class SearchResult(Contract):
    cards: list[Card] = Field(max_length=3)


class FixtureRequest(Contract):
    fixture_id: str = Field(min_length=1, max_length=80)


class QueryDescription(Contract):
    sql: str
    parameters: dict


class FixtureDescription(Contract):
    fixture_id: str
    version: int
    dialect: Literal["sqlite"]
    tables: dict[str, dict[str, str]]
    queries: dict[str, QueryDescription]


class QueryRequest(FixtureRequest):
    query_id: Literal["group_counts", "having_gt", "having_gte", "join_on", "join_where"]
    parameters: dict[Literal["min_count"], Annotated[int, Field(ge=0, le=50)]] = Field(default_factory=dict)


class Observation(Contract):
    observation_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    fixture_id: str
    query_id: str
    sql: str
    parameters: dict[str, int]
    columns: list[str]
    rows: list[list[str | int | None]] = Field(max_length=50)
    row_count: int = Field(ge=0, le=50)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    elapsed_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_rows(self):
        if self.row_count != len(self.rows) or any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Observation counts and columns must match the rows.")
        return self


class CompareRequest(Contract):
    before_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    after_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Comparison(CompareRequest):
    comparison_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    fixture_id: str
    before_row_count: int
    after_row_count: int
    removed_keys: list[str]
    added_keys: list[str]
    changed_keys: list[str]


class TransferRequest(Contract):
    question_id: int = Field(ge=1)
    kcs: list[int] = Field(min_length=1, max_length=3)
    seed: int = Field(ge=0, le=2**63 - 1)
    variant: Literal["standard", "inclusive"]


class TransferTable(Contract):
    name: str
    columns: list[str] = Field(min_length=1)
    rows: list[list[int | str | None]] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_table(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Table columns must match the rows.")
        return self


class TransferResult(Contract):
    id: str
    concept: str
    context: str
    sql: str
    tables: list[TransferTable] = Field(min_length=1, max_length=2)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option: int = Field(ge=0, le=3)
    feedback: str
    result_columns: list[str] = Field(min_length=1)
    result_rows: list[list[int | str | None]] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_exercise(self):
        if (len(set(self.options)) != len(self.options)
                or any(len(row) != len(self.result_columns) for row in self.result_rows)):
            raise ValueError("Exercise options must be distinct and result columns must match the rows.")
        return self


TRANSFER_SCOPE = "transfer"
TRANSFER_TOOL = "build_transfer_exercise"
TRANSFER_CONTRACT = (TransferRequest, TransferResult, "用审核过的模板生成并验证 SQL 迁移练习。")


class KnowledgeRequest(Contract):
    query: str = Field(min_length=1, max_length=500)
    topic: Literal["select", "where", "conditions", "distinct", "aggregate", "set_ops", "join", "subquery", "null"]
    top_k: int = Field(default=3, ge=1, le=3)
    mode: Literal["hybrid", "keyword", "vector"] = "hybrid"


class KnowledgeCard(Contract):
    id: str
    title: str
    parent: str
    text: str
    keywords: str
    experiment: str | None
    version: int
    topic: str
    dialect: str
    source_url: str
    source_section: str
    reviewed_on: str


class KnowledgeResult(Contract):
    cards: list[KnowledgeCard] = Field(max_length=3)
    mode: Literal["hybrid", "keyword", "vector", "reviewed_cards"]
    corpus: str
    elapsed_ms: float


class CoachExperimentRequest(Contract):
    experiment: Literal["join_filter", "join_count", "having_boundary"]
    scenario: Literal["matching", "boundary"]
    threshold: int | None = Field(default=None, ge=0, le=50)

    @model_validator(mode="after")
    def validate_threshold(self):
        if (self.experiment == "having_boundary") != (self.threshold is not None):
            raise ValueError("A threshold is required for HAVING only.")
        return self


class ExperimentRows(Contract):
    sql: str
    parameters: dict[str, int]
    columns: list[str]
    rows: list[list[str | int | None]] = Field(max_length=50)
    row_count: int = Field(ge=0, le=50)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.row_count != len(self.rows) or any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Experiment counts and columns must match the rows.")
        return self


class CoachExperimentResult(CoachExperimentRequest):
    fixture: str
    before: ExperimentRows
    after: ExperimentRows
    same: bool
    removed_keys: list[str]
    added_keys: list[str]
    changed_keys: list[str]


COACH_SCOPE = "coach"
KNOWLEDGE_TOOL = "search_course_knowledge"
COACH_EXPERIMENT_TOOL = "run_coach_experiment"
COACH_CONTRACTS = {
    KNOWLEDGE_TOOL: (KnowledgeRequest, KnowledgeResult, "检索审核过的课程片段和来源。"),
    COACH_EXPERIMENT_TOOL: (CoachExperimentRequest, CoachExperimentResult, "执行审核过的两条 SQL 并比较。"),
}


TOOL_CONTRACTS = {
    "search_course_notes": (SearchRequest, SearchResult, "检索审核过的 SQL 课程资料。"),
    "describe_fixture": (FixtureRequest, FixtureDescription, "读取合成数据的表结构与查询模板。"),
    "run_example_query": (QueryRequest, Observation, "在合成数据上执行一条预审查询。"),
    "compare_example_results": (CompareRequest, Comparison, "比较当前诊断中的两个查询观察。"),
}
ROLE_TOOLS = {
    "course": frozenset({"search_course_notes"}),
    "experiment": frozenset({"describe_fixture", "run_example_query", "compare_example_results"}),
    "transfer": frozenset({TRANSFER_TOOL}),
    "coach": frozenset(COACH_CONTRACTS),
}


def contracts_for(scope):
    if scope == TRANSFER_SCOPE:
        return {TRANSFER_TOOL: TRANSFER_CONTRACT}
    if scope == COACH_SCOPE:
        return COACH_CONTRACTS
    return TOOL_CONTRACTS
