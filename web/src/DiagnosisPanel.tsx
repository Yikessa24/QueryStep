import { FormEvent, useEffect, useState } from "react";
import TransferExercise from "./TransferExercise";

type Observation = { observation_id: string; sql: string; parameters: Record<string, number>;
  columns: string[]; rows: (string | number | null)[][]; row_count: number };
type Comparison = { before_id: string; after_id: string; removed_keys: string[]; added_keys: string[];
  changed_keys: string[]; before_row_count: number; after_row_count: number };
type Evidence = { observations: Observation[]; comparison: Comparison | null };
type Explanation = { status: "pending" | "ready" | "fallback"; text?: string; question?: string;
  source_id?: string; memory_ids?: string[] };
type Result = Evidence & { summary: string; mode: string; sources: { id: string; title: string; url: string; text?: string }[];
  memory_ids?: string[];
  explanation?: Explanation;
  trace?: Record<string, { tool: string }[]> };
type ConfirmationAction = "confirm" | "edit" | "skip";
type Run = { run_id: string; status: string; branches: Record<string, string>; result: Result | null;
  proposal: { proposal_id: string; summary: string } | null;
  pending_confirmation: { action: ConfirmationAction; summary: string | null } | null };
type Request = <T>(path: string, body?: unknown) => Promise<T>;

const branchTitles: Record<string, string> = { course: "课程检索", experiment: "SQL 实验" };
const statuses: Record<string, string> = {
  queued: "等待运行", running: "正在诊断…", completed: "诊断完成", failed: "诊断失败，可以重试。",
  waiting_confirmation: "诊断完成，学习记录待确认。",
  cancelled: "诊断已取消。", stale: "练习已更新。", ok: "已找到证据", no_evidence: "未找到足够证据",
  needs_input: "请选择实验条件", failed_branch: "暂时不可用",
};

function ExperimentResults({ evidence, join }: { evidence: Evidence; join: boolean }) {
  const comparison = evidence.comparison;
  const observations = comparison
    ? [comparison.before_id, comparison.after_id].map((id) => evidence.observations.find((row) => row.observation_id === id))
    : evidence.observations;
  return <>
    <div className="diagnosis-results">
      {observations.map((result, index) => result && <div key={result.observation_id}>
        <h3>{comparison ? (index === 0 ? (join ? "条件在 ON" : "分组结果") : (join ? "条件在 WHERE" : "筛选结果")) : "实验结果"} · {result.row_count} 行</h3>
        <pre>{result.sql}{Object.keys(result.parameters).length > 0 && `\n参数 ${JSON.stringify(result.parameters)}`}</pre>
        {result.rows.length === 0 ? <p>查询未返回结果。</p> : <table>
          <thead><tr>{result.columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead>
          <tbody>{result.rows.map((row, rowIndex) => <tr key={rowIndex}
            className={index === 0 && comparison?.removed_keys.includes(String(row[0])) ? "removed-row" : undefined}>
            {row.map((value, columnIndex) => <td key={columnIndex}>{value ?? "NULL"}</td>)}
          </tr>)}</tbody>
        </table>}
      </div>)}
    </div>
    {comparison && <p>{comparison.removed_keys.length
      ? `${join ? "被筛除的账户" : "被筛除的分组"}：${comparison.removed_keys.join("、")}` : "两次查询未移除任何结果键。"}</p>}
  </>;
}

export default function DiagnosisPanel({ decisionId, request, onMemorySaved }:
  { decisionId: string; request: Request; onMemorySaved: () => void }) {
  const [available, setAvailable] = useState(false);
  const [topic, setTopic] = useState("aggregate");
  const [run, setRun] = useState<Run | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [operator, setOperator] = useState("having_gte");
  const [threshold, setThreshold] = useState("1");
  const [experiment, setExperiment] = useState<Evidence | null>(null);
  const [experimentKey, setExperimentKey] = useState(() => crypto.randomUUID());
  const [summary, setSummary] = useState("");
  const [confirmationKey, setConfirmationKey] = useState(() => crypto.randomUUID());
  const [confirmationMessage, setConfirmationMessage] = useState("");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const running = run?.status === "queued" || run?.status === "running";
  const runId = run?.run_id;
  const proposal = run?.proposal;
  const pending = run?.pending_confirmation;
  const explanation = run?.result?.explanation;
  const join = topic === "join";

  useEffect(() => {
    if (proposal) {
      setSummary(pending?.summary ?? proposal.summary);
      setConfirmationKey(crypto.randomUUID());
    }
  }, [proposal, pending]);

  useEffect(() => {
    let active = true;
    request<{ available: boolean; topic?: string; run: Run | null }>(`/api/practice/${decisionId}/diagnosis`).then((data) => {
      if (active) {
        setAvailable(data.available);
        if (data.topic) setTopic(data.topic);
        setRun(data.run);
      }
    }).catch(() => undefined);
    return () => { active = false; };
  }, [decisionId, request]);

  useEffect(() => {
    if (!running || !runId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const source = new EventSource(`/api/diagnosis/${runId}/events`);
    source.onmessage = (message) => {
      const event = JSON.parse(message.data) as { branch?: string; status: string };
      if (event.branch) setRun((current) => current && ({
        ...current, branches: { ...current.branches, [event.branch!]: event.status },
      }));
    };
    async function poll() {
      try {
        const result = await request<Run>(`/api/diagnosis/${runId}`);
        if (!active) return;
        setError("");
        setRun(result);
        if (result.status !== "queued" && result.status !== "running") return;
      } catch {
        if (active) setError("暂时无法刷新诊断，正在重试。");
      }
      if (active) timer = setTimeout(poll, 650);
    }
    function switchToPolling() {
      source.close();
      if (active) void poll();
    }
    source.addEventListener("settled", switchToPolling);
    source.onerror = switchToPolling;
    return () => { active = false; source.close(); clearTimeout(timer); };
  }, [running, runId, request]);

  useEffect(() => {
    if (running || !runId || explanation?.status !== "pending") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const deadline = performance.now() + 6500;
    async function checkExplanation() {
      try {
        const refreshed = await request<Run>(`/api/diagnosis/${runId}`);
        if (!active) return;
        if (refreshed.result?.explanation?.status !== "pending") {
          setRun((current) => current && current.run_id === runId && current.result && refreshed.result
            ? { ...current, result: { ...current.result, explanation: refreshed.result.explanation } } : current);
          return;
        }
      } catch { /* The evidence and controls already on screen remain usable. */ }
      if (!active) return;
      if (performance.now() < deadline) timer = setTimeout(checkExplanation, 400);
      else setRun((current) => current && current.run_id === runId && current.result
        ? { ...current, result: { ...current.result, explanation: { status: "fallback" } } } : current);
    }
    timer = setTimeout(checkExplanation, 400);
    return () => { active = false; clearTimeout(timer); };
  }, [running, runId, explanation?.status, request]);

  async function start(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setError("");
    try {
      setRun(await request<Run>(`/api/practice/${decisionId}/diagnosis`, {
        message: message.trim(), idempotency_key: requestKey,
      }));
      setRequestKey(crypto.randomUUID());
      setExperiment(null);
      setConfirmationMessage("");
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "无法启动诊断。");
    } finally {
      setSending(false);
    }
  }

  async function tryExperiment(event: FormEvent) {
    event.preventDefault();
    setSending(true);
    setError("");
    try {
      setExperiment(await request<Evidence>(`/api/diagnosis/${runId}/experiment`, {
        ...(join ? { query_id: "join_where" } : { query_id: operator, min_count: Number(threshold) }),
        idempotency_key: experimentKey,
      }));
      setExperimentKey(crypto.randomUUID());
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "实验未完成。");
    } finally {
      setSending(false);
    }
  }

  async function confirm(action: ConfirmationAction) {
    if (!proposal) return;
    setSending(true);
    setError("");
    try {
      await request(`/api/diagnosis/${runId}/confirmation`, {
        proposal_id: proposal.proposal_id, action, idempotency_key: confirmationKey,
        ...(action === "edit" ? { summary: pending?.summary ?? summary.trim() } : {}),
      });
      setConfirmationMessage(action === "skip" ? "已跳过学习记录。" : "学习记录已保存。");
      if (action !== "skip") onMemorySaved();
      setRun(await request<Run>(`/api/diagnosis/${runId}`));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "无法确认学习记录。");
      try { setRun(await request<Run>(`/api/diagnosis/${runId}`)); } catch { /* Retry keeps the same choice. */ }
    } finally {
      setSending(false);
    }
  }

  if (!available) return null;
  const result = run?.status === "completed" || run?.status === "waiting_confirmation" ? run.result : null;
  return <section className="diagnosis" aria-label="SQL 错题诊断">
    <h2>SQL 错题诊断</h2>
    <p>用独立的合成数据验证你的判断。</p>
    <form className="tutor-form" onSubmit={start}>
      <input aria-label="你的判断" placeholder={join ? "例如：条件移到 WHERE 后，为什么少了行？" : "例如：为什么分组后还会少一行？"} maxLength={500}
        value={message} readOnly={sending || running} onChange={(event) => {
          setMessage(event.target.value);
          setRequestKey(crypto.randomUUID());
        }} />
      <button disabled={sending || running || !!proposal || !message.trim()}>运行诊断</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {run && <div role="status">
      <p>{run.status === "completed" && run.result?.mode === "clarify" ? "请确认实验条件" : statuses[run.status]}</p>
      {Object.entries(run.branches).map(([branch, status]) =>
        <span className="citation" key={branch}>{branchTitles[branch]} · {statuses[status === "failed" ? "failed_branch" : status] ?? status}</span>)}
    </div>}
    {running && <button type="button" className="secondary" onClick={async () => {
      try {
        setRun(await request<Run>(`/api/diagnosis/${runId}/cancel`, {}));
      } catch {
        setError("暂时无法取消诊断。");
      }
    }}>取消诊断</button>}
    {result && <>
      <p>{result.summary}</p>
      {!!result.memory_ids?.length && <p>本轮诊断读取了此前确认的相关学习记录。</p>}
      {result.mode !== "full" && result.mode !== "clarify" && <p>本轮仅展示已取得的证据或课程提示。</p>}
      {result.sources.length > 0 && <ul>{result.sources.map((source) =>
        <li key={source.id}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
          {source.text && <p>{source.text}</p>}</li>)}</ul>}
      {result.observations.length > 0 && <ExperimentResults evidence={result} join={join} />}
      {explanation?.status === "pending" && <p className="tutor-thinking" role="status">
        <span className="tutor-thinking-dots" aria-hidden="true"><span /><span /><span /></span>
        Gemini 正在补充讲解…
      </p>}
      {explanation?.status === "ready" && <section aria-label="Gemini 补充讲解">
        <h3>Gemini 补充讲解 · 本轮诊断</h3>
        <p>{explanation.text}</p>
        <p>{explanation.question}</p>
        {result.sources.filter((source) => source.id === explanation.source_id).map((source) =>
          <a key={source.id} href={source.url} target="_blank" rel="noreferrer">讲解依据 · {source.title}</a>)}
        {!!explanation.memory_ids?.length && <p>本次讲解参考了你确认过的复习要点。</p>}
      </section>}
      {explanation?.status === "fallback" && <p>本轮可根据上方课程依据和 SQL 结果继续练习。</p>}
      <form className="diagnosis-controls" onSubmit={tryExperiment}>
        {!join && <><label>筛选条件 <select value={operator} disabled={sending} onChange={(event) => {
          setOperator(event.target.value);
          setExperimentKey(crypto.randomUUID());
        }}>
          <option value="having_gt">严格大于</option><option value="having_gte">大于等于</option>
        </select></label>
        <label>计数阈值 <input type="number" min={0} max={50} step={1} required value={threshold}
          disabled={sending} onChange={(event) => {
            setThreshold(event.target.value);
            setExperimentKey(crypto.randomUUID());
          }} /></label></>}
        <button disabled={sending}>{join ? "把条件移到 WHERE 并比较" : "比较结果"}</button>
      </form>
      {experiment && <ExperimentResults evidence={experiment} join={join} />}
      {runId && !join && result.mode === "full" && <TransferExercise key={runId} runId={runId} request={request} />}
      {result.trace && <details><summary>查看诊断轨迹</summary>
        {Object.entries(result.trace).map(([branch, steps]) => <p key={branch}>
          {branchTitles[branch]} · {steps.map((step) => step.tool).join(" → ") || "未执行工具"}
        </p>)}
      </details>}
    </>}
    {proposal && <form className="diagnosis-memory" onSubmit={(event) => {
      event.preventDefault();
      void confirm(pending?.action ?? (summary.trim() === proposal.summary ? "confirm" : "edit"));
    }}>
      <h3>保存为学习记录</h3>
      <label>复习要点 <textarea value={summary} maxLength={300} required readOnly={!!pending || sending} onChange={(event) =>
        setSummary(event.target.value)} /></label>
      <div className="actions"><button disabled={sending || !summary.trim()}>{pending ? "重试确认" : "确认保存"}</button>
        {!pending && <button type="button" className="secondary" disabled={sending} onClick={() => void confirm("skip")}>跳过</button>}</div>
    </form>}
    {confirmationMessage && <p role="status">{confirmationMessage}</p>}
  </section>;
}
