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
    track_coverage: bool = False


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


class EvidenceCoverage(Contract):
    goal: str
    title: str
    card_id: str | None


class SearchPass(Contract):
    query: str
    topic: str
    limit: int
    goal: str | None
    retry: bool
    ids: list[str]


class KnowledgeResult(Contract):
    cards: list[KnowledgeCard] = Field(max_length=3)
    mode: Literal["hybrid", "keyword", "vector", "reviewed_cards"]
    corpus: str
    elapsed_ms: float
    coverage: list[EvidenceCoverage] = Field(default_factory=list, max_length=2)
    passes: list[SearchPass] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_coverage(self):
        available = {card.id for card in self.cards}
        goals = {entry.goal for entry in self.coverage}
        if (len(goals) != len(self.coverage) or any(entry.card_id not in available
                for entry in self.coverage if entry.card_id is not None)):
            raise ValueError("Course coverage must refer to returned cards and unique goals.")
        return self


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


WORKBENCH_SCOPE = "workbench"
DESCRIBE_SQL_TASK_TOOL = "describe_sql_task"
INSPECT_STUDENT_SQL_TOOL = "inspect_student_sql"
RUN_STUDENT_SQL_TOOL = "run_student_sql"
CHECK_STUDENT_SQL_TOOL = "check_student_sql"

TaskId = Literal["filter_paid", "null_contacts", "distinct_cities", "group_counts", "having_totals",
                 "inner_join_orders", "left_join_counts", "left_join_filter", "sum_totals", "order_top"]
Scenario = Literal["sample", "boundary", "empty", "duplicates"]
WORKBENCH_SCENARIOS = ("sample", "boundary", "empty", "duplicates")
SQLDigest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Seed = Annotated[int, Field(ge=0, le=1_000_000)]
SQLValue = str | int | Annotated[float, Field(allow_inf_nan=False)] | None


class SQLTaskRequest(Contract):
    task_id: TaskId


class InspectStudentSQLRequest(SQLTaskRequest):
    sql: str = Field(min_length=1, max_length=6000)


class RunStudentSQLRequest(InspectStudentSQLRequest):
    scenario: Scenario = "sample"
    seed: Seed = 0


class CheckStudentSQLRequest(InspectStudentSQLRequest):
    scenarios: list[Scenario] = Field(default_factory=lambda: list(WORKBENCH_SCENARIOS),
                                      min_length=1, max_length=4)
    seed: Seed = 0

    @model_validator(mode="after")
    def validate_scenarios(self):
        if len(set(self.scenarios)) != len(self.scenarios):
            raise ValueError("Scenarios must be distinct.")
        return self


class SQLTaskTable(Contract):
    name: str
    columns: list[str] = Field(min_length=1)
    types: list[str] = Field(min_length=1)
    rows: list[list[SQLValue]]

    @model_validator(mode="after")
    def validate_shape(self):
        if (len(self.types) != len(self.columns) or len(set(self.columns)) != len(self.columns)
                or any(len(row) != len(self.columns) for row in self.rows)):
            raise ValueError("Table types, columns and rows must match.")
        return self


class SQLTaskDescription(SQLTaskRequest):
    id: TaskId
    title: str
    prompt: str
    topic: str
    concepts: list[str]
    starter_sql: str
    dialect: Literal["sqlite"]
    version: int = Field(ge=1)
    tables: list[SQLTaskTable] = Field(min_length=1)
    ordered: bool

    @model_validator(mode="after")
    def validate_task(self):
        if self.id != self.task_id or len({table.name for table in self.tables}) != len(self.tables):
            raise ValueError("Task identity and table names must be consistent.")
        return self


class StudentSQLIdentity(SQLTaskRequest):
    sql_digest: SQLDigest


class InspectStudentSQLResult(StudentSQLIdentity):
    valid: bool
    error: str | None

    @model_validator(mode="after")
    def validate_status(self):
        if self.valid != (self.error is None):
            raise ValueError("Inspection status and error must agree.")
        return self


class StudentQueryResult(Contract):
    status: Literal["ok", "rejected", "error", "timeout"]
    columns: list[str]
    rows: list[list[SQLValue]]
    row_count: int = Field(ge=0)
    error: str | None
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)
    fingerprint: str
    scenario: Scenario
    seed: Seed

    @model_validator(mode="after")
    def validate_rows(self):
        if self.row_count != len(self.rows) or any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Query counts and columns must match the rows.")
        if (self.status == "ok") != (self.error is None):
            raise ValueError("Query status and error must agree.")
        return self


class RunStudentSQLResult(StudentQueryResult, StudentSQLIdentity):
    pass


class SQLCounterexample(Contract):
    scenario: Scenario
    seed: Seed
    tables: list[SQLTaskTable] = Field(min_length=1)
    actual: StudentQueryResult
    expected: StudentQueryResult

    @model_validator(mode="after")
    def validate_context(self):
        if any(result.scenario != self.scenario or result.seed != self.seed
               for result in (self.actual, self.expected)):
            raise ValueError("Counterexample query context must match its dataset.")
        return self


class CheckStudentSQLResult(StudentSQLIdentity):
    scenarios: list[Scenario] = Field(min_length=1, max_length=4)
    seed: Seed
    status: Literal["passed", "mismatch", "rejected", "error", "timeout"]
    passed: bool
    checked: int = Field(ge=0, le=4)
    total: int = Field(ge=1, le=4)
    counterexample: SQLCounterexample | None
    message: str
    query_result: StudentQueryResult | None

    @model_validator(mode="after")
    def validate_evaluation(self):
        if (len(set(self.scenarios)) != len(self.scenarios) or self.total != len(self.scenarios)
                or self.checked > self.total or self.passed != (self.status == "passed")
                or (self.passed and (self.checked != self.total or self.counterexample is not None))
                or (self.status == "mismatch" and self.counterexample is None)):
            raise ValueError("Evaluation status and counts must be consistent.")
        for evidence in (self.counterexample, self.query_result):
            if evidence is not None and (evidence.scenario not in self.scenarios or evidence.seed != self.seed):
                raise ValueError("Evaluation evidence must match the requested scenarios and seed.")
        return self


WORKBENCH_CONTRACTS = {
    DESCRIBE_SQL_TASK_TOOL: (SQLTaskRequest, SQLTaskDescription, "读取 SQL 任务公开题面、表结构和样本，不返回参考 SQL。"),
    INSPECT_STUDENT_SQL_TOOL: (InspectStudentSQLRequest, InspectStudentSQLResult, "检查学生 SQL 是否符合受限只读规则。"),
    RUN_STUDENT_SQL_TOOL: (RunStudentSQLRequest, RunStudentSQLResult, "在指定合成场景中执行受限学生 SQL。"),
    CHECK_STUDENT_SQL_TOOL: (CheckStudentSQLRequest, CheckStudentSQLResult, "在指定有限场景中验证学生 SQL 并返回反例。"),
    KNOWLEDGE_TOOL: COACH_CONTRACTS[KNOWLEDGE_TOOL],
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
    "workbench": frozenset(WORKBENCH_CONTRACTS),
}


def contracts_for(scope):
    if scope == TRANSFER_SCOPE:
        return {TRANSFER_TOOL: TRANSFER_CONTRACT}
    if scope == COACH_SCOPE:
        return COACH_CONTRACTS
    if scope == WORKBENCH_SCOPE:
        return WORKBENCH_CONTRACTS
    return TOOL_CONTRACTS
