import { FormEvent, useEffect, useState } from "react";

type Request = <T>(path: string, body?: unknown) => Promise<T>;
type Rows = { sql: string; parameters: Record<string, number>; columns: string[];
  rows: (number | string | null)[][]; row_count: number };
type Evidence = { id: string } & (
  { kind: "course"; data: { title: string; text: string; source_url: string; source_section: string; dialect: string } } |
  { kind: "experiment"; data: { scenario: string; before: Rows; after: Rows; same: boolean; removed_keys: string[] } }
);
type Run = { id: string; message: string; status: string; events: { type: string; evidence?: Evidence; round?: number }[];
  result: { status: string; text: string; question: string | null; citations: string[] } | null };
type View = { available: boolean; can_submit?: boolean; runs: Run[] };

function Results({ result, label }: { result: Rows; label: string }) {
  return <div className="transfer-table">
    <h3>{label} · {result.row_count} 行</h3>
    <pre>{result.sql}{Object.keys(result.parameters).length > 0 && `\n参数 ${JSON.stringify(result.parameters)}`}</pre>
    <table><thead><tr>{result.columns.map((name, index) => <th key={index} scope="col">{name}</th>)}</tr></thead>
      <tbody>{result.rows.map((row, index) => <tr key={index}>
        {row.map((cell, col) => <td key={col}>{cell ?? "NULL"}</td>)}
      </tr>)}</tbody>
    </table>
  </div>;
}

function Observation({ entry, runId }: { entry: Evidence; runId: string }) {
  const anchor = `coach-${runId}-${entry.id}`;
  if (entry.kind === "course") {
    return <li id={anchor}><a href={entry.data.source_url} target="_blank" rel="noreferrer">
      {entry.data.title}</a> <small>{entry.data.dialect.toUpperCase()} · {entry.data.source_section}</small>
      <p>{entry.data.text}</p></li>;
  }
  const sample = entry.data.scenario === "boundary" ? "含边界数据的样例" : "常规样例";
  return <li id={anchor}>
    <p><strong>{sample}</strong> · {entry.data.same ? "两次查询结果相同。" : "两次查询结果不同。"}
      {entry.data.removed_keys.length > 0 && ` 第二条查询移除了 ${entry.data.removed_keys.join("、")}。`}</p>
    <div className="diagnosis-results">
      <Results result={entry.data.before} label="第一条查询" />
      <Results result={entry.data.after} label="第二条查询" />
    </div>
  </li>;
}

export default function CoachPanel({ decisionId, request, readOnly }:
  { decisionId: string; request: Request; readOnly: boolean }) {
  const path = `/api/practice/${decisionId}/coach`;
  const [view, setView] = useState<View | null>(null);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [updated, setUpdated] = useState(0);
  const [error, setError] = useState("");
  const running = !!view?.runs.some((run) => run.status === "running");

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const next = await request<View>(path);
        if (!active) return;
        setView(next);
        if (next.runs.some((run) => run.status === "running")) timer = setTimeout(load, 350);
      } catch {
        if (active) setError("无法刷新错题教练。");
      }
    }
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [path, request, updated]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending || running || !message.trim()) return;
    setPending(true);
    setError("");
    try {
      const run = await request<Run>(path, { message: message.trim(), idempotency_key: crypto.randomUUID() });
      setView((previous) => previous && ({ ...previous, runs: [...previous.runs.filter((r) => r.id !== run.id), run] }));
      setMessage("");
      setUpdated((value) => value + 1);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "错题教练暂不可用。");
    } finally {
      setPending(false);
    }
  }

  if (!view?.available || (readOnly && !view.runs.length)) return null;
  return <section className="diagnosis coach" aria-label="自主错题教练">
    <h3>自主错题教练</h3>
    {!open && view.runs.length === 0 && <button type="button" className="secondary" onClick={() => setOpen(true)}>
      带我弄懂这题
    </button>}
    {view.runs.map((run) => <article key={run.id} className="turn">
      <p><b>你</b> {run.message}</p>
      <ul>{run.events.map((event, index) => event.evidence
        ? <Observation key={index} runId={run.id} entry={event.evidence} />
        : event.type === "plan" && Number(event.round) > 1
          ? <li key={index}>已根据取得的证据检查下一步。</li>
          : null)}</ul>
      {run.status === "running" && <p role="status">正在查找依据或验证结果…</p>}
      {run.result && <div>
        <p>{run.result.text}</p>
        {run.result.question && <p>{run.result.question}</p>}
        {run.result.citations.map((id, index) => <a key={id} className="coach-citation" href={`#coach-${run.id}-${id}`}>
          依据 {index + 1}
        </a>)}
        {run.result.status === "transfer" && <p>可以用下方「迁移练习」检查自己的理解。</p>}
        {run.result.status === "fallback" && <p>可继续补充疑问，或使用「运行诊断」。</p>}
      </div>}
      {run.status === "interrupted" && <p>本轮辅导中断，可以重新提问。</p>}
      {run.status === "stale" && <p>已切换到下一题。</p>}
    </article>)}
    {error && <p className="error" role="alert">{error} <button type="button" className="secondary"
      onClick={() => { setError(""); setUpdated((value) => value + 1); }}>刷新</button></p>}
    {!readOnly && view.can_submit && (open || view.runs.length > 0) && <form className="tutor-form" onSubmit={submit}>
      <input aria-label="错题教练：你的疑问" placeholder="哪一步的结果和你预期的不一样？" maxLength={500}
        value={message} onChange={(event) => setMessage(event.target.value)} />
      <button disabled={pending || running || !message.trim()}>请教错题教练</button>
    </form>}
  </section>;
}
