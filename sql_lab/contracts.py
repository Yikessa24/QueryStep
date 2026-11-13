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


TOOL_CONTRACTS = {
    "search_course_notes": (SearchRequest, SearchResult, "检索审核过的 SQL 课程资料。"),
    "describe_fixture": (FixtureRequest, FixtureDescription, "读取合成数据的表结构与查询模板。"),
    "run_example_query": (QueryRequest, Observation, "在合成数据上执行一条预审查询。"),
    "compare_example_results": (CompareRequest, Comparison, "比较当前诊断中的两个查询观察。"),
}
ROLE_TOOLS = {
    "course": frozenset({"search_course_notes"}),
    "experiment": frozenset({"describe_fixture", "run_example_query", "compare_example_results"}),
}
