import { FormEvent, useEffect, useRef, useState } from "react";

type Request = <T>(path: string, body?: unknown, method?: string) => Promise<T>;
type Cell = string | number | null;
type Table = { name: string; columns: string[]; types?: string[]; rows: Cell[][] };
type TaskSummary = { id: string; title: string; topic: string; concepts: string[] };
type Recommendation = {
  available: boolean;
  source: "epikt" | "history_fallback" | "none";
  task_id?: string;
  task_title?: string;
  topic?: string;
  guidance_tier?: "foundation" | "boundary" | "transfer";
  scaffolding_level?: string;
  priority_scenarios?: string[];
  mean_predicted_probability?: number | null;
  candidate_count?: number;
  model_version?: string | null;
  reason?: string;
};
type Task = TaskSummary & { prompt: string; starter_sql: string; dialect: "sqlite"; version: number; tables: Table[]; ordered: boolean };
type Draft = { sql: string; version: number };
type QueryResult = { status: "ok" | "rejected" | "error" | "timeout"; columns: string[]; rows: Cell[][]; row_count: number; error: string | null; elapsed_ms: number; fingerprint: string; scenario: string; seed: number };
type CheckResult = { status: "passed" | "mismatch" | "rejected" | "error" | "timeout"; passed: boolean; checked: number; total: number; message: string; query_result: QueryResult | null; counterexample: null | { scenario: string; seed: number; tables: Table[]; actual: QueryResult; expected: QueryResult } };
type Action = "run" | "check" | "coach";
type Run = { id: string; task_id: string; sql: string; action: Action; message?: string; status: "queued" | "running" | "completed" | "failed" | "cancelled" | "interrupted"; events: { seq: number; type: string; tool?: string; data?: unknown; elapsed_ms?: number }[]; result: null | { kind: Action; query?: QueryResult; check?: CheckResult; text?: string; question?: string | null; evidence?: unknown[]; citations?: { id: string; title: string; url: string; text?: string }[]; learning_context?: unknown; metrics?: unknown; mode?: string }; created_at: string };
type Detail = { task: Task; draft: Draft; runs: Run[] };
type Attempt = { sql: string; action: Action; message?: string; key: string; signature: string; messageRevision: number };
type Entry = {
  task: Task; sql: string; version: number; savedSql: string; saveState: "saved" | "dirty" | "saving" | "error" | "conflict"; saveError: string;
  savePromise?: Promise<boolean>; remote?: Draft; remoteBusy?: boolean; backupSql?: string;
  runs: Run[]; selectedId: string | null; message: string; messageRevision: number;
  attempt?: Attempt; submitting?: Attempt; failedAttempt?: Attempt; requestError: string;
  runErrors: Record<string, string>; controlBusy?: string; controlError: string;
};
const actionNames: Record<Action, string> = { run: "运行 SQL", check: "提交验证", coach: "请教实验教练" };
const statusNames: Record<Run["status"], string> = { queued: "排队中", running: "执行中", completed: "已完成", failed: "执行失败", cancelled: "已取消", interrupted: "已中断" };
const activeRun = (run: Run) => run.status === "queued" || run.status === "running";
const errorText = (error: unknown) => error instanceof Error ? error.message : "请求失败，请重试。";
const isConflict = (error: unknown) => typeof error === "object" && error !== null && "status" in error && error.status === 409;
const taskPath = (id: string) => `/api/sql/tasks/${encodeURIComponent(id)}`;
const runPath = (id: string) => `/api/sql/runs/${encodeURIComponent(id)}`;
const record = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
const isQuery = (value: unknown): value is QueryResult => { const item = record(value); return !!item && typeof item.status === "string" && Array.isArray(item.columns) && Array.isArray(item.rows) && typeof item.row_count === "number"; };
const isCheck = (value: unknown): value is CheckResult => { const item = record(value); return !!item && typeof item.passed === "boolean" && typeof item.checked === "number" && typeof item.total === "number"; };
const bounded = (value: unknown, limit = 400) => typeof value === "string" ? value.length > limit ? `${value.slice(0, limit)}…` : value : "";
const named = (names: Record<string, string>, value: unknown) => typeof value === "string" && Object.hasOwn(names, value) ? names[value] : bounded(value);
const engineErrors: Record<string, string> = {
  invalid_sql: "SQL 内容无效，请检查输入。", single_select_required: "只允许一条 SELECT 查询。", unsupported_sql: "暂不支持此 SQL 写法。",
  unknown_column: "找不到所用列，请核对表结构。", unknown_table: "找不到所用表，请核对表名。", ambiguous_column: "列名有歧义，请补充表名或别名。",
  syntax_error: "SQL 语法错误，请检查语句。", invalid_aggregate: "聚合用法无效，请检查分组与聚合表达式。", query_error: "查询执行失败，请检查语句。",
  query_too_complex: "查询过于复杂，请简化后重试。", query_not_allowed: "此查询操作不被允许，仅支持只读查询。", table_not_allowed: "只能查询当前任务允许的表。",
  query_timeout: "查询超过执行时限，请简化后重试。", query_cancelled: "查询已取消，输入仍保留。", sql_too_large: "SQL 超过长度限制，请缩短后重试。",
  result_limit_exceeded: "结果超过大小限制，请减少返回内容。", memory_limit_exceeded: "查询超过内存限制，请简化后重试。", worker_error: "查询执行进程异常，请重试。",
  sandbox_unavailable: "安全执行环境暂不可用，请稍后重试。", sql_parser_unavailable: "SQL 解析服务暂不可用，请稍后重试。",
};
const engineMessage = (value: unknown) => named(engineErrors, value);
const toolNames: Record<string, string> = { run: "运行样例查询", check: "验证多组数据", inspect_student_sql: "检查 SQL 有效性", run_student_sql: "运行场景查询", check_student_sql: "核对场景与边界", search_course: "检索课程依据", search_course_knowledge: "检索课程依据" };
const topicNames: Record<string, string> = { select: "投影查询", where: "条件筛选", filter: "条件筛选", join: "表连接", aggregate: "分组聚合", null: "空值处理", distinct: "去重", subquery: "子查询", union: "集合合并", order: "结果排序" };
const tierNames: Record<string, string> = { foundation: "基础概念澄清", boundary: "边界条件验证", transfer: "迁移与举一反三" };
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const numberText = (value: unknown, suffix = "") => finite(value) ? `${value}${suffix}` : "未知";
const versionText = (value: unknown) => bounded(value, 120) || (finite(value) ? String(value) : "未知");
const records = (value: unknown, limit: number) => Array.isArray(value) ? value.slice(0, limit).map(record).filter((item): item is Record<string, unknown> => item !== null) : [];
function safeURL(value: string) {
  if (value.length > 2000) return undefined;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined; } catch { return undefined; }
}

function DataTable({ table, differences = [] }: { table: Table; differences?: boolean[] }) {
  return <div className="sql-wb-table" tabIndex={0} role="region" aria-label={`${table.name} 数据表`}>
    <table><caption>{table.name}</caption><thead><tr>{table.columns.map((column, index) => <th scope="col" key={index}>{column}{table.types?.[index] && <small>{table.types[index]}</small>}</th>)}</tr></thead>
      <tbody>{table.rows.slice(0, 100).map((row, index) => <tr className={differences[index] ? "sql-wb-different" : undefined} key={index}>{row.map((cell, col) => <td key={col}>{cell === null ? <span className="sql-wb-null">NULL</span> : String(cell)}</td>)}</tr>)}</tbody></table>
    {!table.rows.length && <p className="sql-wb-muted">没有返回行</p>}{table.rows.length > 100 && <p className="sql-wb-muted">仅展示前 100 行</p>}
  </div>;
}
function QueryView({ query, label = "查询结果", differences }: { query: QueryResult; label?: string; differences?: boolean[] }) {
  return <section className="sql-wb-query" aria-label={label}>
    <div className="sql-wb-row"><h3>{label}</h3><span className="sql-wb-muted">{query.status === "ok" ? `${query.row_count} 行 · ${query.elapsed_ms} ms` : ({ rejected: "查询被拒绝", error: "SQL 执行错误", timeout: "执行超时" }[query.status])}</span></div>
    {query.error && <p className="sql-wb-warning">{engineMessage(query.error)}</p>}
    {query.status === "ok" && <DataTable table={{ name: label, columns: query.columns, rows: query.rows }} differences={differences} />}
  </section>;
}
function differingRows(rows: Cell[][], other: Cell[][], ordered: boolean) {
  if (ordered) return rows.map((row, index) => JSON.stringify(row) !== JSON.stringify(other[index]));
  const remaining = new Map<string, number>();
  other.forEach((row) => { const key = JSON.stringify(row); remaining.set(key, (remaining.get(key) ?? 0) + 1); });
  return rows.map((row) => { const key = JSON.stringify(row); const count = remaining.get(key) ?? 0; if (count) remaining.set(key, count - 1); return !count; });
}
function CheckView({ check, ordered }: { check: CheckResult; ordered: boolean }) {
  const example = check.counterexample;
  return <section className="sql-wb-check" aria-label="验证结果">
    <div className={`sql-wb-verdict${check.passed ? " passed" : ""}`}><strong>{check.passed ? "通过当前测试" : check.status === "mismatch" ? "发现结果差异" : "本次未完成验证"}</strong><span>已检查 {check.checked} / {check.total} 组数据</span></div>
    <p className="sql-wb-prose">{engineMessage(check.message)}</p>
    <p className="sql-wb-muted">只说明当前测试数据上的结果，不是所有数据上的等价性证明。</p>
    {example ? <details className="sql-wb-counterexample" open><summary>查看反例与结果差异</summary>
      <p className="sql-wb-muted">场景 {example.scenario} · seed {example.seed} · {ordered ? "按行顺序比较" : "忽略行顺序，保留重复行"}；列值按位置比较，忽略列名与别名；底色标出未匹配的行。</p>
      <div className="sql-wb-tables">{example.tables.map((table, index) => <DataTable table={table} key={index} />)}</div>
      {example.actual.columns.length !== example.expected.columns.length && <p className="sql-wb-warning">结果列数不同：你的结果 {example.actual.columns.length} 列，预期 {example.expected.columns.length} 列。</p>}
      <div className="sql-wb-comparison"><QueryView query={example.actual} label="你的结果" differences={differingRows(example.actual.rows, example.expected.rows, ordered)} /><QueryView query={example.expected} label="预期结果" differences={differingRows(example.expected.rows, example.actual.rows, ordered)} /></div>
    </details> : check.query_result && <QueryView query={check.query_result} />}
  </section>;
}
function CourseCard({ card }: { card: Record<string, unknown> }) {
  const url = typeof card.url === "string" ? safeURL(card.url) : undefined;
  return <div className="sql-wb-course"><strong>{url ? <a href={url} target="_blank" rel="noreferrer">{bounded(card.title, 160) || "课程依据"}</a> : bounded(card.title, 160) || "课程依据"}</strong>
    <p className="sql-wb-prose">{bounded(card.text, 2000)}</p>{typeof card.citation_id === "string" && <small>引用 {bounded(card.citation_id, 80)}</small>}</div>;
}
function Evidence({ value, ordered }: { value: unknown; ordered: boolean }) {
  const item = record(value); if (!item) return null;
  const data = record(item.data) ?? item;
  // Only recognized observation types cross this boundary; never dump arbitrary state.
  if (item.tool === "inspect_student_sql" && typeof data.valid === "boolean") return <section className="sql-wb-query" aria-label="SQL 有效性检查"><h3>SQL 有效性检查</h3><p className={data.valid ? "sql-wb-muted" : "sql-wb-warning"}>{data.valid ? "当前 SQL 通过有效性检查；不代表结果符合任务。" : `当前 SQL 未通过有效性检查：${engineMessage(data.error) || "原因未知"}`}</p></section>;
  if (item.tool === "search_course" && Array.isArray(data.cards)) return <div className="sql-wb-citations" aria-label="检索课程依据">{records(data.cards, 10).map((card, index) => <CourseCard card={card} key={index} />)}{!data.cards.length && <p className="sql-wb-muted">未检索到课程依据。</p>}</div>;
  if (item.tool === "check_student_sql" || item.kind === "check") { const check = [data.check, data].find(isCheck); if (check) return <CheckView check={check} ordered={ordered} />; }
  if (item.tool === "run_student_sql" || item.kind === "query") { const query = [data.query, data.query_result, data].find(isQuery); if (query) return <QueryView query={query} label="查询证据" />; }
  if (item.kind === "course" && typeof data.text === "string") return <CourseCard card={data} />;
  return null;
}
function Metrics({ value, mode }: { value: unknown; mode?: string }) {
  const data = record(value); if (!data) return null;
  const usage = record(data.usage); const attemptUsage = record(data.usage_this_attempt);
  const tokens = (item: Record<string, unknown> | null) => `输入 ${numberText(item?.prompt_tokens)} / 输出 ${numberText(item?.completion_tokens)} / 合计 ${numberText(item?.total_tokens)}`;
  return <details className="sql-wb-info sql-wb-metrics"><summary>运行指标</summary><dl>
    {mode && <><dt>教练模式</dt><dd>{mode === "agent" ? "代理教练" : mode === "evidence_only" ? "仅保留证据（降级）" : "未知"}</dd></>}
    <dt>模型</dt><dd>{versionText(data.model)}</dd><dt>工作流版本</dt><dd>{versionText(data.workflow_version)}</dd>
    <dt>提示版本</dt><dd>{versionText(data.prompt_version)}</dd><dt>工具版本</dt><dd>{versionText(data.tool_version)}</dd>
    <dt>任务版本</dt><dd>{versionText(data.task_version)}</dd><dt>服务版本</dt><dd>{versionText(data.service_version)}</dd>
    <dt>本次执行耗时</dt><dd>{numberText(data.attempt_elapsed_ms, " ms")}</dd><dt>教练累计耗时</dt><dd>{numberText(data.elapsed_ms, " ms")}</dd>
    <dt>累计模型 / 工具调用</dt><dd>{numberText(data.model_calls)} / {numberText(data.tool_calls)}</dd>
    <dt>本次提供方调用</dt><dd>{numberText(data.provider_calls_this_attempt)}</dd>
    <dt>累计 tokens</dt><dd>{tokens(usage)}</dd><dt>本次 tokens</dt><dd>{tokens(attemptUsage)}</dd>
    <dt>费用</dt><dd>{numberText(data.cost)}</dd>
  </dl><p className="sql-wb-muted">未知表示未提供或未计量，不按 0 估算；本次执行与可恢复教练的累计值分开记录。</p></details>;
}
function LearningContext({ value }: { value: unknown }) {
  const data = record(value); if (!data) return null;
  const attempts = records(data.recent_independent_attempts, 12); const epikt = record(data.epikt);
  const candidates = records(epikt?.candidates, 8); const notes = records(data.confirmed_notes, 4); const activity = records(data.practice_activity, 4);
  const reasons: Record<string, string> = { no_prediction: "暂无预测快照", cold_start: "独立作答记录不足", model_unconfigured: "模型未配置", model_unavailable: "模型不可用", no_candidates: "暂无候选正式题" };
  const stale = finite(epikt?.snapshot_history_version) && finite(epikt?.current_history_version) && epikt.snapshot_history_version !== epikt.current_history_version;
  return <details className="sql-wb-info sql-wb-learning"><summary>学习上下文</summary>
    <h3>近期正式首次独立作答</h3>{attempts.length ? <ul>{attempts.map((item, index) => <li key={index}>{named(topicNames, item.topic) || "主题未知"} · {item.correct === true ? "答对" : item.correct === false ? "答错" : "结果未知"}</li>)}</ul> : <p className="sql-wb-muted">暂无独立作答记录。</p>}
    <h3>正式题预测正确率（EpiKT）</h3><p className="sql-wb-muted">仅适用于已有映射的正式题，不代表掌握程度，也不是生成任务或 SQL 实作的准确率。</p>
    {epikt?.available === true ? <>{candidates.length ? <ul>{candidates.map((item, index) => <li key={index}>正式题候选 {index + 1} · {named(topicNames, item.topic) || "主题未知"} · {finite(item.predicted_correct_probability) && item.predicted_correct_probability <= 1 ? `${(item.predicted_correct_probability * 100).toFixed(1)}%` : "预测未知"}</li>)}</ul> : <p className="sql-wb-muted">当前任务主题暂无候选正式题预测。</p>}</> : <p className="sql-wb-muted">预测模型不可用或暂无预测：{named(reasons, epikt?.reason) || "原因未知"}。</p>}
    <p className="sql-wb-muted">预测模型版本：{versionText(epikt?.model_version)}；快照历史版本：{versionText(epikt?.snapshot_history_version)}；采集时历史版本：{versionText(epikt?.current_history_version)}。</p>
    <p className={stale ? "sql-wb-warning" : "sql-wb-muted"}>{stale ? "快照已过时：与采集时的学习历史版本不同，不能视为当前预测。" : "上下文是本次提交时的快照，不会随之后的练习自动更新。"}</p>
    <h3>已确认学习笔记</h3>{notes.length ? <ul>{notes.map((item, index) => <li key={index}>版本 {versionText(item.version)} · {bounded(item.summary, 1000) || "暂无摘要"}</li>)}</ul> : <p className="sql-wb-muted">暂无已确认笔记。</p>}
    <h3>近期实作活动</h3>{activity.length ? <ul>{activity.map((item, index) => <li key={index}>{named(actionNames, item.action) || "实作"} · {named({ passed: "通过当前测试", mismatch: "发现结果差异", rejected: "查询被拒绝", error: "执行错误", timeout: "执行超时" }, item.status) || "无验证结论"} · {item.assisted === true ? "有教练辅助" : item.assisted === false ? "无教练辅助" : "辅助状态未知"}</li>)}</ul> : <p className="sql-wb-muted">暂无已完成实作活动。</p>}
    <p className="sql-wb-muted">实作与提示后的活动单独记录，不计入正式已答题数。</p>
  </details>;
}
function ResultView({ run, ordered }: { run: Run; ordered: boolean }) {
  const result = run.result;
  if (!result) return <p className="sql-wb-muted">{activeRun(run) ? "正在执行，结果会自动更新。" : "本次没有可展示的结果。草稿仍保留在编辑器中。"}</p>;
  return <div className="sql-wb-result">
    {result.text && result.text !== result.check?.message && <p className="sql-wb-prose">{Object.hasOwn(engineErrors, result.text) ? engineMessage(result.text) : bounded(result.text, 6000)}</p>}
    {result.question && <p className="sql-wb-question">{result.question}</p>}
    {result.query && <QueryView query={result.query} />}
    {result.check && <CheckView check={result.check} ordered={ordered} />}
    {!!result.citations?.length && <div className="sql-wb-citations" aria-label="课程引用">{result.citations.map((citation, index) => <div key={`${citation.id}-${index}`}>
      {safeURL(citation.url) ? <a href={safeURL(citation.url)} target="_blank" rel="noreferrer">{citation.title}</a> : <span>{citation.title}</span>}
      {citation.text && <p className="sql-wb-prose">{citation.text}</p>}
    </div>)}</div>}
    {!!result.evidence?.length && <details><summary>查看实验依据</summary>{result.evidence.slice(0, 12).map((value, index) => <Evidence key={index} value={value} ordered={ordered} />)}</details>}
    <Metrics value={result.metrics} mode={result.mode} /><LearningContext value={result.learning_context} />
  </div>;
}
function Events({ run }: { run: Run }) {
  const names: Record<string, string> = { queued: "进入队列", started: "开始执行", running: "执行中", completed: "执行完成", failed: "执行失败", cancelled: "已取消", interrupted: "执行中断", resumed: "继续执行", tool_start: "调用工具", tool_result: "收到工具结果", tool_end: "工具完成", tool_started: "开始调用工具", tool_completed: "工具执行完成", observation: "汇总实验观察", plan: "规划验证步骤", retrieval_version: "记录课程版本", error: "遇到错误" };
  return <details className="sql-wb-events"><summary>执行轨迹 · {run.events.length} 个事件</summary><ol>{[...run.events].sort((a, b) => a.seq - b.seq).map((event) => <li key={event.seq}><span>{event.seq}. {Object.hasOwn(names, event.type) ? names[event.type] : "状态更新"}</span>{event.tool && <small>{named(toolNames, event.tool)}</small>}{event.type === "retrieval_version" && <small className="sql-wb-prose">{bounded(record(event.data)?.mode, 30) || "未知检索方式"} · 课程版本 {versionText(record(event.data)?.corpus)}</small>}{typeof event.elapsed_ms === "number" && <small>{event.elapsed_ms} ms</small>}</li>)}</ol>{!run.events.length && <p className="sql-wb-muted">尚无执行事件。</p>}</details>;
}

export default function SQLWorkbench({ active, preferredTopic, request, ensureSession, onPractice, onAssistant }: { active: boolean; preferredTopic?: string | null; request: Request; ensureSession: () => Promise<void>; onPractice: () => void; onAssistant: () => void }) {
  // Per-task entries retain local edits while switching tasks or hiding this workbench.
  // Saves are serialized per task; response bodies never replace newer editor input.
  const entries = useRef<Record<string, Entry>>({});
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const epochs = useRef<Record<string, number>>({});
  const readingRuns = useRef(new Set<string>());
  const mounted = useRef(true);
  const booted = useRef(false);
  const initializing = useRef(false);
  const currentId = useRef("");
  const composing = useRef(false);
  const [, redraw] = useState(0);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [taskId, setTaskId] = useState("");
  const [loading, setLoading] = useState(true);
  const [initError, setInitError] = useState("");
  const [coachUnavailable, setCoachUnavailable] = useState("");
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({});
  const loadingTasks = useRef(new Set<string>());
  const notify = () => { if (mounted.current) redraw((value) => value + 1); };
  const entry = entries.current[taskId];
  const selected = entry?.runs.find((run) => run.id === entry.selectedId);
  const running = entry?.runs.some(activeRun) ?? false;
  const busy = !!entry?.submitting || !!entry?.controlBusy || running;
  const validSQL = !!entry?.sql.trim() && entry.sql.length <= 6000;

  async function loadTask(id: string) {
    if (entries.current[id] || loadingTasks.current.has(id)) return;
    loadingTasks.current.add(id); setLoadErrors((previous) => ({ ...previous, [id]: "" }));
    try {
      const detail = await request<Detail>(taskPath(id));
      if (!mounted.current) return;
      const runs = [...detail.runs].sort((a, b) => b.created_at.localeCompare(a.created_at));
      entries.current[id] = { task: detail.task, sql: detail.draft.sql, version: detail.draft.version, savedSql: detail.draft.sql, saveState: "saved", saveError: "", runs, selectedId: runs[0]?.id ?? null, message: "", messageRevision: 0, requestError: "", runErrors: {}, controlError: "" };
    } catch (error) { if (mounted.current) setLoadErrors((previous) => ({ ...previous, [id]: errorText(error) })); }
    finally { loadingTasks.current.delete(id); notify(); }
  }
  async function initialize() {
    if (initializing.current) return;
    initializing.current = true; setLoading(true); setInitError("");
    try {
      await ensureSession();
      const data = await request<{ available: boolean; tasks: TaskSummary[]; coach_available?: boolean; coach_reason?: string; recommendation?: Recommendation }>("/api/sql/tasks");
      if (!mounted.current) return;
      if (!data.available || !data.tasks.length) throw new Error("SQL 实作暂不可用，请稍后重试。");
      setCoachUnavailable(data.coach_available === false ? (data.coach_reason === "model_unavailable" ? "实验教练未配置模型；仍可运行 SQL 和提交验证。" : "实验教练依赖暂不可用；仍可运行 SQL 和提交验证。") : "");
      setTasks(data.tasks);
      setRecommendation(data.recommendation ?? null);
      const preferred = preferredTopic ? data.tasks.find((task) => task.topic === preferredTopic)?.id : undefined;
      const recommended = data.recommendation?.available && data.recommendation.task_id
        ? data.tasks.find((task) => task.id === data.recommendation?.task_id)?.id
        : undefined;
      const id = currentId.current || preferred || recommended || data.tasks.find((task) => task.id === "left_join_counts")?.id || data.tasks[0].id;
      currentId.current = id; setTaskId(id); void loadTask(id);
    } catch (error) { if (mounted.current) setInitError(errorText(error)); }
    finally { initializing.current = false; if (mounted.current) setLoading(false); }
  }
  function saveDraft(id: string): Promise<boolean> {
    const item = entries.current[id];
    clearTimeout(timers.current[id]);
    if (!item) return Promise.resolve(true);
    if (item.savePromise) return item.savePromise;
    if (item.saveState === "conflict") return Promise.resolve(false);
    if (item.sql === item.savedSql) { item.saveState = "saved"; notify(); return Promise.resolve(true); }
    item.saveState = "saving"; item.saveError = ""; notify();
    item.savePromise = (async () => {
      try {
        while (item.sql !== item.savedSql) {
          const sql = item.sql;
          const draft = await request<Draft>(`${taskPath(id)}/draft`, { sql, version: item.version }, "PUT");
          if (!mounted.current) return false;
          item.version = draft.version; item.savedSql = sql;
        }
        item.saveState = "saved"; return true;
      } catch (error) {
        item.saveState = isConflict(error) ? "conflict" : "error";
        item.saveError = isConflict(error) ? "另一端已更新草稿；未覆盖远端，也未丢弃你的输入。" : errorText(error);
        return false;
      } finally { item.savePromise = undefined; notify(); }
    })();
    return item.savePromise;
  }
  function editSQL(id: string, sql: string) {
    const item = entries.current[id];
    if (!item || sql === item.sql) return;
    item.sql = sql; item.attempt = undefined; item.failedAttempt = undefined; item.requestError = "";
    clearTimeout(timers.current[id]);
    if (item.saveState !== "conflict") {
      item.saveState = item.savePromise ? "saving" : item.sql === item.savedSql ? "saved" : "dirty";
      timers.current[id] = setTimeout(() => { void saveDraft(id); }, 600);
    }
    notify();
  }
  function chooseTask(id: string) {
    if (currentId.current) void saveDraft(currentId.current);
    currentId.current = id; setTaskId(id); void loadTask(id);
  }
  async function readRemote(id: string) {
    const item = entries.current[id]; if (!item || item.remoteBusy) return;
    item.remoteBusy = true; notify();
    try { item.remote = (await request<Detail>(taskPath(id))).draft; item.saveError = "已读取远端版本。本地输入仍保留，请比较后选择。"; }
    catch (error) { item.saveError = errorText(error); }
    finally { item.remoteBusy = false; notify(); }
  }
  function adoptRemote(id: string) {
    const item = entries.current[id]; if (!item?.remote) return;
    item.backupSql = item.sql; item.sql = item.remote.sql; item.savedSql = item.remote.sql; item.version = item.remote.version;
    item.remote = undefined; item.saveState = "saved"; item.saveError = ""; item.attempt = undefined; item.failedAttempt = undefined; item.requestError = ""; notify();
  }
  function mergeRun(item: Entry, run: Run, force = false) {
    const previous = item.runs.find((value) => value.id === run.id);
    if (!force && previous && ((!activeRun(previous) && activeRun(run)) || (previous.events.at(-1)?.seq ?? 0) > (run.events.at(-1)?.seq ?? 0))) return;
    item.runs = [run, ...item.runs.filter((value) => value.id !== run.id)].sort((a, b) => b.created_at.localeCompare(a.created_at));
  }
  async function refreshRun(item: Entry, id: string) {
    if (readingRuns.current.has(id) || item.controlBusy === id) return;
    readingRuns.current.add(id);
    const epoch = epochs.current[id] ?? 0;
    try {
      const run = await request<Run>(runPath(id));
      if (mounted.current && epoch === (epochs.current[id] ?? 0)) { mergeRun(item, run); delete item.runErrors[id]; }
    } catch (error) { if (epoch === (epochs.current[id] ?? 0)) item.runErrors[id] = errorText(error); }
    finally { readingRuns.current.delete(id); notify(); }
  }
  async function controlRun(item: Entry, run: Run, action: "cancel" | "resume") {
    if (item.controlBusy || item.submitting || (action === "resume" && item.runs.some(activeRun))) return;
    item.controlBusy = run.id; item.controlError = "";
    epochs.current[run.id] = (epochs.current[run.id] ?? 0) + 1; notify();
    try { mergeRun(item, await request<Run>(`${runPath(run.id)}/${action}`, {}), true); delete item.runErrors[run.id]; }
    catch (error) { item.controlError = errorText(error); }
    finally { item.controlBusy = undefined; notify(); }
  }
  async function submitRun(action: Action) {
    const item = entries.current[currentId.current];
    if (!item || item.submitting || item.controlBusy || item.runs.some(activeRun) || !item.sql.trim() || item.sql.length > 6000 || (action === "coach" && (coachUnavailable || !item.message.trim() || item.message.length > 500))) return;
    const sql = item.sql; const message = action === "coach" ? item.message.trim() : undefined;
    const signature = JSON.stringify([sql, action, message]);
    const attempt = item.attempt?.signature === signature ? item.attempt : { sql, action, message, signature, key: crypto.randomUUID(), messageRevision: item.messageRevision };
    item.attempt = attempt; item.submitting = attempt; item.requestError = ""; item.failedAttempt = undefined; item.controlError = ""; notify();
    void saveDraft(item.task.id);
    if (action === "coach") onAssistant();
    try {
      const run = await request<Run>(`${taskPath(item.task.id)}/runs`, { sql, action, ...(message === undefined ? {} : { message }), idempotency_key: attempt.key });
      if (!mounted.current) return;
      mergeRun(item, run, true); item.selectedId = run.id;
      if (item.attempt === attempt) item.attempt = undefined;
      if (action === "coach" && item.messageRevision === attempt.messageRevision) { item.message = ""; item.messageRevision += 1; }
    } catch (error) {
      item.requestError = errorText(error);
      if (item.attempt === attempt) item.failedAttempt = attempt;
    } finally { item.submitting = undefined; notify(); }
  }
  function ask(event: FormEvent) { event.preventDefault(); if (!composing.current) void submitRun("coach"); }

  useEffect(() => {
    if (active && !booted.current) { booted.current = true; void initialize(); }
    if (!active) Object.keys(entries.current).forEach((id) => { void saveDraft(id); });
  }, [active]);
  useEffect(() => {
    if (!active || !preferredTopic || !tasks.length) return;
    const match = tasks.find((task) => task.topic === preferredTopic);
    if (match && match.id !== currentId.current) chooseTask(match.id);
  }, [active, preferredTopic, tasks]);
  useEffect(() => {
    mounted.current = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await Promise.all(Object.values(entries.current).flatMap((item) => item.runs.filter((run) => activeRun(run) && !item.runErrors[run.id]).map((run) => refreshRun(item, run.id))));
      if (mounted.current) timer = setTimeout(poll, 800);
    }
    timer = setTimeout(poll, 800);
    function warnUnsaved(event: BeforeUnloadEvent) {
      if (Object.values(entries.current).some((item) => item.sql !== item.savedSql || item.saveState === "conflict")) { event.preventDefault(); event.returnValue = ""; }
    }
    window.addEventListener("beforeunload", warnUnsaved);
    return () => { mounted.current = false; clearTimeout(timer); Object.values(timers.current).forEach(clearTimeout); window.removeEventListener("beforeunload", warnUnsaved); };
  }, []);

  const saveLabels = { saved: "草稿已保存", dirty: "有未保存的修改", saving: "正在保存草稿…", error: "保存失败 · 本地输入已保留", conflict: "草稿版本冲突 · 本地输入已保留" };
  const requestFailure = entry?.requestError && <div className="sql-wb-warning" role="alert"><p>{entry.requestError}</p>{entry.failedAttempt ? <button className="secondary" disabled={busy} onClick={() => void submitRun(entry.failedAttempt!.action)}>重试{actionNames[entry.failedAttempt.action]}</button> : <p>输入已更新，请按当前内容重新提交。</p>}</div>;
  const unresolved = Object.entries(entries.current).filter(([id, item]) => id !== taskId && ["error", "conflict"].includes(item.saveState));
  return <>
    <main id="sql-workspace" className="workspace-scroll sql-wb" hidden={!active} tabIndex={-1}>
      <div className="workspace-inner sql-wb-inner">
        <div className="workspace-heading"><div><p className="eyebrow">WRITE. RUN. UNDERSTAND.</p><h1>SQL 实作</h1></div><span className="sql-wb-badge">SQLite</span></div>
        <p className="sql-wb-intro">亲手写查询，用结果检验思路。这里的实验不计入正式已答题数。</p>
        {loading ? <p className="loading-card" role="status">正在准备 SQL 实作…</p> : initError ? <div className="sql-wb-warning" role="alert"><p>{initError}</p><button className="secondary" onClick={() => void initialize()}>重试加载任务列表</button></div> : <>
          {recommendation?.available && recommendation.task_id && <section className="sql-wb-recommendation" aria-label="自适应实作推荐">
            <div className="sql-wb-row">
              <strong>{recommendation.source === "epikt" ? "EpiKT 薄弱主题推荐实作" : "基于近期错题推荐实作"}：{recommendation.task_title}</strong>
              {recommendation.guidance_tier && <span className="sql-wb-badge">{named(tierNames, recommendation.guidance_tier)}</span>}
            </div>
            <p className="sql-wb-muted">
              主题 {named(topicNames, recommendation.topic) || "SQL"}
              {typeof recommendation.mean_predicted_probability === "number" ? ` · 同主题正式题校准预测均值 ${(recommendation.mean_predicted_probability * 100).toFixed(1)}%（不等于掌握度）` : ""}
              {recommendation.priority_scenarios?.length ? ` · 优先核验：${recommendation.priority_scenarios.join(" → ")}` : ""}
            </p>
            {recommendation.task_id !== taskId && <button className="secondary" onClick={() => chooseTask(recommendation.task_id!)}>切换到推荐任务</button>}
          </section>}
          <label className="sql-wb-task-picker">选择实作任务<select value={taskId} onChange={(event) => chooseTask(event.target.value)}>{tasks.map((task, index) => <option key={task.id} value={task.id}>{String(index + 1).padStart(2, "0")} · {task.title}{recommendation?.available && recommendation.task_id === task.id ? "（推荐）" : ""}</option>)}</select></label>
          {!!unresolved.length && <div className="sql-wb-warning"><p>其他任务仍有未保存的输入：</p>{unresolved.map(([id, item]) => <button className="text-button" key={id} onClick={() => chooseTask(id)}>{item.task.title} · 返回处理</button>)}</div>}
          {loadErrors[taskId] ? <div className="sql-wb-warning" role="alert"><p>{loadErrors[taskId]}</p><button className="secondary" onClick={() => void loadTask(taskId)}>重试加载此任务</button></div> : !entry ? <p className="loading-card" role="status">正在读取任务与草稿…</p> : <>
            <section className="sql-wb-card" aria-label="实作需求"><div className="sql-wb-tags">{entry.task.concepts.map((concept) => <span key={concept}>{concept}</span>)}</div><h2>{entry.task.title}</h2><p className="sql-wb-prose">{entry.task.prompt}</p><p className="sql-wb-muted">{entry.task.ordered ? "结果需要符合指定顺序。" : "验证时忽略行顺序，保留重复行。"}</p>
              <details className="sql-wb-schema" open><summary>表结构与样例数据 · {entry.task.tables.length} 张表</summary><div className="sql-wb-tables">{entry.task.tables.map((table, index) => <DataTable key={index} table={table} />)}</div></details>
            </section>
            <section className="sql-wb-card sql-wb-editor-card" aria-label="SQL 编辑区"><div className="sql-wb-row"><label htmlFor="sql-wb-editor">你的 SQL</label><span className="sql-wb-muted">SQLite · 只读查询</span></div>
              <textarea id="sql-wb-editor" className="sql-wb-editor" value={entry.sql} maxLength={6000} spellCheck={false} autoCapitalize="off" autoCorrect="off" placeholder={entry.task.starter_sql || "SELECT ..."} onChange={(event) => editSQL(taskId, event.target.value)} onBlur={() => { void saveDraft(taskId); }} />
              <div className="sql-wb-row sql-wb-save-row"><span role="status" className={`sql-wb-save ${entry.saveState}`}>{saveLabels[entry.saveState]}</span><span className="sql-wb-muted">{entry.sql.length} / 6000</span></div>
              {entry.sql.length > 6000 && <p className="sql-wb-warning">SQL 超过 6000 字符，请缩短后再提交。</p>}
              {entry.saveState === "error" && <div className="sql-wb-warning" role="alert"><p>{entry.saveError}</p><button className="secondary" onClick={() => void saveDraft(taskId)}>重试保存草稿</button></div>}
              {entry.saveState === "conflict" && <div className="sql-wb-warning" role="alert"><p>{entry.saveError}</p><p>不会自动覆盖另一端。先查看远端草稿；如选择使用远端版本，会另行保留当前本地 SQL 供复制。</p><button className="secondary" disabled={entry.remoteBusy} onClick={() => void readRemote(taskId)}>{entry.remoteBusy ? "正在读取…" : "读取远端草稿"}</button>
                {entry.remote && <><details open><summary>远端草稿 · 版本 {entry.remote.version}</summary><pre>{entry.remote.sql || "（空草稿）"}</pre></details><button className="secondary" onClick={() => adoptRemote(taskId)}>使用远端草稿（替换编辑器）</button></>}
              </div>}
              {entry.backupSql !== undefined && <details><summary>冲突前的本地 SQL（可复制）</summary><textarea className="sql-wb-backup" aria-label="冲突前的本地 SQL" readOnly value={entry.backupSql} /></details>}
              <div className="sql-wb-actions"><button className="secondary" disabled={!validSQL || busy} onClick={() => void submitRun("run")}>运行 SQL</button><button disabled={!validSQL || busy} onClick={() => void submitRun("check")}>提交验证</button></div>
              <p className="sql-wb-muted">运行：查看样例数据上的结果。验证：检查多组数据，寻找反例。两者均不会清空草稿。</p>
              {entry.submitting && <p role="status" className="sql-wb-muted">正在提交{actionNames[entry.submitting.action]}…</p>}
              {entry.failedAttempt?.action !== "coach" && requestFailure}
            </section>
            {selected && selected.action !== "coach" && <section className="sql-wb-card" aria-label="当前实验结果"><div className="sql-wb-row"><h2>{actionNames[selected.action]}</h2><span className={`sql-wb-status ${selected.status}`}>{statusNames[selected.status]}</span></div><ResultView key={selected.id} run={selected} ordered={entry.task.ordered} /><button className="text-button" onClick={onAssistant}>查看执行轨迹与历史 →</button></section>}
          </>}
        </>}
        <p className="workspace-footnote">正式练习与 SQL 实作独立记录 · 草稿在当前学习会话内保存</p>
      </div>
    </main>
    <aside className="assistant-sidebar sql-wb sql-wb-coach" aria-label="实验教练" hidden={!active}>
      <div className="assistant-header"><div className="assistant-title"><span className="assistant-symbol sql-wb-symbol" aria-hidden="true">SQL</span><div><h2>实验教练</h2><p>带着你的查询，用证据找原因。</p></div></div><button className="icon-button mobile-close" aria-label="返回实作练习" onClick={onPractice}>×</button><span className="ai-label">AI</span></div>
      <div className="assistant-context"><span>当前任务</span><strong>{entry?.task.title ?? "等待选择任务"}</strong></div>
      <div className="sql-wb-coach-scroll">
        {!entry ? <p className="sql-wb-muted">选一个任务，写下 SQL，再告诉教练你的疑问。</p> : <>
          <p className="sql-wb-muted">教练会围绕当前 SQL 查找依据、运行实验并给出提示；不是一次正式作答。</p>
          <section className="sql-wb-history" aria-label="最近实验"><h3>最近实验 <small>最多展示 8 次</small></h3>{!entry.runs.length ? <div className="sql-wb-empty"><span aria-hidden="true">&gt;_</span><p>第一条查询，就是起点。</p><p className="sql-wb-muted">运行、验证或向教练提问后，过程会留在这里。</p></div> : <div className="sql-wb-history-list">{entry.runs.slice(0, 8).map((run) => <button className={`sql-wb-history-item${selected?.id === run.id ? " selected" : ""}`} key={run.id} aria-pressed={selected?.id === run.id} onClick={() => { entry.selectedId = run.id; entry.controlError = ""; notify(); }}><span>{actionNames[run.action]}<small>{new Date(run.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small></span><span className={`sql-wb-status ${run.status}`}>{statusNames[run.status]}</span></button>)}</div>}</section>
          {selected && <article className="sql-wb-selected" aria-label="选定实验" data-run-id={selected.id}><div className="sql-wb-row"><h3>{actionNames[selected.action]}</h3><span className={`sql-wb-status ${selected.status}`} role="status">{statusNames[selected.status]}</span></div>
            {selected.message && <p className="sql-wb-user-message">{selected.message}</p>}
            {selected.action === "coach" ? <ResultView key={selected.id} run={selected} ordered={entry.task.ordered} /> : <p className="sql-wb-muted">结果显示在练习区。<button className="text-button" onClick={onPractice}>查看结果</button></p>}
            <details><summary>查看本次 SQL</summary><pre>{selected.sql}</pre></details><button className="text-button" onClick={() => { editSQL(taskId, selected.sql); onPractice(); }}>恢复此运行 SQL 到编辑器</button>
            <div className="sql-wb-actions">{activeRun(selected) && <button className="secondary" disabled={!!entry.controlBusy} onClick={() => void controlRun(entry, selected, "cancel")}>取消执行</button>}{["interrupted", "failed"].includes(selected.status) && <button className="secondary" disabled={busy} onClick={() => void controlRun(entry, selected, "resume")}>恢复执行</button>}</div>
            {entry.controlBusy && <p className="sql-wb-muted" role="status">正在更新执行状态…</p>}
            {entry.controlError && <p className="sql-wb-warning" role="alert">{entry.controlError} 可以重试操作，或修改 SQL 后重新提交。</p>}
            {entry.runErrors[selected.id] && <div className="sql-wb-warning" role="alert"><p>读取执行状态失败：{entry.runErrors[selected.id]}。已有结果与输入仍保留。</p><button className="secondary" onClick={() => void refreshRun(entry, selected.id)}>重试读取状态</button></div>}
            <Events key={selected.id} run={selected} />
          </article>}
          {entry.submitting?.action === "coach" && <div role="status"><p className="sql-wb-user-message">{entry.submitting.message}</p><p className="sql-wb-muted">正在提交给实验教练…</p></div>}
          {(entry.failedAttempt?.action === "coach" || (!entry.failedAttempt && entry.requestError)) && requestFailure}
        </>}
      </div>
      <form className="sql-wb-composer" onSubmit={ask}>
        {coachUnavailable && <p className="sql-wb-warning" role="status">{coachUnavailable}</p>}
        <label htmlFor="sql-wb-message">向实验教练提问</label><textarea id="sql-wb-message" maxLength={500} rows={3} value={entry?.message ?? ""} disabled={!entry} placeholder="例如：为什么没有订单的客户也被计为 1？" onChange={(event) => { if (entry) { entry.message = event.target.value; entry.messageRevision += 1; entry.attempt = undefined; entry.failedAttempt = undefined; entry.requestError = ""; notify(); } }} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.nativeEvent.keyCode !== 229) { event.preventDefault(); void submitRun("coach"); } }} />
        <div className="sql-wb-row"><span className="sql-wb-muted">{entry?.message.length ?? 0} / 500 · Shift + Enter 换行</span><button disabled={!validSQL || busy || !!coachUnavailable || !entry?.message.trim() || entry.message.length > 500}>请教实验教练</button></div>
        <p className="sql-wb-muted">{validSQL ? "将发送当前编辑器中的 SQL 与疑问。" : "先在练习区输入 SQL，再向教练提问。"}</p>
      </form>
    </aside>
  </>;
}
