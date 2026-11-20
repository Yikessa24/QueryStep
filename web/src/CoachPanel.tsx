import { FormEvent, MouseEvent, useEffect, useRef, useState } from "react";

type Request = <T>(path: string, body?: unknown) => Promise<T>;
type Rows = { sql: string; parameters: Record<string, number>; columns: string[];
  rows: (number | string | null)[][]; row_count: number };
type Evidence = { id: string } & (
  { kind: "course"; data: { id?: string; title: string; text: string; source_url: string; source_section: string; dialect: string } } |
  { kind: "experiment"; data: { scenario: string; before: Rows; after: Rows; same: boolean; removed_keys: string[] } }
);
type Coverage = { goal: string; title: string; card_id: string | null };
type Run = { id: string; message: string; status: string;
  events: { type: string; evidence?: Evidence; round?: number; coverage?: Coverage[]; retried?: boolean }[];
  result: { status: string; text: string; question: string | null; citations: string[] } | null };
type View = { available: boolean; can_submit?: boolean; runs: Run[] };

function Results({ result, label }: { result: Rows; label: string }) {
  return <div className="transfer-table">
    <h4 className="section-heading">{label} · {result.row_count} 行</h4>
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
    return <li className="tool-step" id={anchor} tabIndex={-1}><a href={entry.data.source_url} target="_blank" rel="noreferrer">
      {entry.data.title}</a> <small>{entry.data.dialect.toUpperCase()} · {entry.data.source_section}</small>
      <p>{entry.data.text}</p></li>;
  }
  const sample = entry.data.scenario === "boundary" ? "含边界数据的样例" : "常规样例";
  return <li className="tool-step" id={anchor} tabIndex={-1}>
    <p><strong>{sample}</strong> · {entry.data.same ? "两次查询结果相同。" : "两次查询结果不同。"}
      {entry.data.removed_keys.length > 0 && ` 第二条查询移除了 ${entry.data.removed_keys.join("、")}。`}</p>
    <div className="diagnosis-results">
      <Results result={entry.data.before} label="第一条查询" />
      <Results result={entry.data.after} label="第二条查询" />
    </div>
  </li>;
}

function CoachRun({ run, readOnly }: { run: Run; readOnly: boolean }) {
  const evidenceRef = useRef<HTMLDetailsElement>(null);
  const evidenceCount = run.events.filter((event) => event.evidence).length;
  const plans = run.events.filter((event) => event.type === "plan");
  const latestPlan = plans[plans.length - 1];

  function revealEvidence(event: MouseEvent<HTMLAnchorElement>, id: string) {
    event.preventDefault();
    if (evidenceRef.current) evidenceRef.current.open = true;
    const target = document.getElementById(`coach-${run.id}-${id}`);
    const viewport = target?.closest(".coach-content");
    if (target && viewport) {
      viewport.scrollTo({ top: viewport.scrollTop + target.getBoundingClientRect().top - viewport.getBoundingClientRect().top - 12 });
      target.focus({ preventScroll: true });
    }
  }

  return <article className="turn coach-turn">
    <p className="coach-message"><b>你</b> {run.message}</p>
    <div className="tool-run">
      <p role="status">{run.status === "running" ? "正在查找依据或验证结果…"
        : run.status === "interrupted" ? (readOnly ? "本轮辅导已中断。" : "本轮辅导中断，可以重新提问。")
          : run.status === "stale" ? "已切换到下一题。"
            : run.result ? "本轮辅导已完成" : "等待本轮辅导结果"}</p>
      <p className="helper-text">{Number(latestPlan?.round) > 1
        ? "根据已有证据检查下一步" : "查找课程依据 · 验证查询结果"}
        {` · 已取得 ${evidenceCount} 条证据`}</p>
    </div>
    {run.result && <div className="tool-summary">
      <h4 className="section-heading">本轮结论</h4>
      <p>{run.result.text}</p>
      {run.result.question && <p>{run.result.question}</p>}
      <div className="coach-citations">{run.result.citations.map((id, index) => <a key={id}
        className="coach-citation" href={`#coach-${run.id}-${id}`} onClick={(event) => revealEvidence(event, id)}>
        依据 {index + 1}
      </a>)}</div>
      {run.result.status === "transfer" && <p className="helper-text">可以用「迁移练习」检查自己的理解。</p>}
      {run.result.status === "fallback" && <p className="helper-text">{readOnly
        ? "本轮保留了已取得的证据与提示。" : "可继续补充疑问，或在 SQL 实验区使用「运行诊断」。"}</p>}
    </div>}
    <details className="tool-evidence" ref={evidenceRef} open={run.status === "running"}>
      <summary>查看工具观察与证据 · {evidenceCount} 条</summary>
      {run.events.length === 0 && <p className="helper-text">尚无工具观察。</p>}
      <ul>{run.events.map((event, index) => event.evidence
        ? <Observation key={index} runId={run.id} entry={event.evidence} />
        : event.type === "plan"
          ? <li className="tool-step" key={index}>{Number(event.round) > 1
            ? "已根据取得的证据检查下一步。" : "计划：查找课程依据并验证查询结果。"}</li>
          : event.coverage
            ? <li className="tool-step" key={index}>
              <strong>课程依据</strong>{event.retried && " · 已补查缺失考点"}
              <ul>{event.coverage.map((goal) => {
                const item = run.events.find(({ evidence }) =>
                  evidence?.kind === "course" && evidence.data.id === goal.card_id)?.evidence;
                return <li key={goal.goal}>{goal.title} · {item
                  ? <a href={`#coach-${run.id}-${item.id}`} onClick={(event) => revealEvidence(event, item.id)}>查看依据</a>
                  : goal.card_id ? "已找到" : "暂未找到课程依据"}</li>;
              })}</ul>
            </li>
            : null)}</ul>
    </details>
  </article>;
}

export default function CoachPanel({ decisionId, request, readOnly }:
  { decisionId: string; request: Request; readOnly: boolean }) {
  const path = `/api/practice/${decisionId}/coach`;
  const [view, setView] = useState<View | null>(null);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const [pending, setPending] = useState(false);
  const [updated, setUpdated] = useState(0);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [refreshing, setRefreshing] = useState(true);
  const composing = useRef(false);
  const running = !!view?.runs.some((run) => run.status === "running");

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setRefreshing(true);
    setLoadError("");
    async function load() {
      try {
        const next = await request<View>(path);
        if (!active) return;
        setView(next);
        setRefreshing(false);
        setLoadError("");
        if (next.runs.some((run) => run.status === "running")) timer = setTimeout(load, 350);
      } catch {
        if (active) {
          setRefreshing(false);
          setLoadError("暂时无法加载教练状态，请重试。已有记录和输入不会丢失。");
        }
      }
    }
    void load();
    return () => { active = false; clearTimeout(timer); };
  }, [path, request, updated]);

  function retry() {
    setError("");
    setLoadError("");
    setUpdated((value) => value + 1);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (readOnly || !view?.available || !view.can_submit || pending || running || refreshing || !message.trim()) return;
    setPending(true);
    setError("");
    try {
      const run = await request<Run>(path, { message: message.trim(), idempotency_key: requestKey });
      setView((previous) => previous && ({ ...previous, runs: [...previous.runs.filter((r) => r.id !== run.id), run] }));
      setMessage("");
      setRequestKey(crypto.randomUUID());
      setUpdated((value) => value + 1);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "错题教练暂不可用。");
    } finally {
      setPending(false);
    }
  }

  return <section className="coach coach-panel" aria-label="自主错题教练">
    <header className="panel-intro">
      <h3 className="section-heading">自主错题教练</h3>
      <p className="helper-text">{readOnly ? "查看已保存的提问、结论与工具证据。" : "从你的疑问出发，用课程依据和 SQL 实验一起查证。"}</p>
    </header>
    <div className="coach-content">
      {refreshing && <p className="helper-text" role="status">{view ? "正在刷新教练状态…" : "正在加载错题教练…"}</p>}
      {view && !view.available && <div className="empty-state">
        <p>该题暂无实验教练，可切换到普通助教继续提问。</p>
      </div>}
      {view && readOnly && view.runs.length === 0 && <p className="empty-state">本题没有已保存的教练记录。</p>}
      {view?.available && <>
        {!readOnly && view.runs.length === 0 && <div className="empty-state">
          <p>哪一步和你的预期不同？说说你的判断，教练会逐步查证。</p>
          {!open && view.can_submit && <button type="button" className="secondary" onClick={() => setOpen(true)}>
            带我弄懂这题
          </button>}
        </div>}
        {view.runs.map((run) => <CoachRun key={run.id} run={run} readOnly={readOnly} />)}
        {!readOnly && !view.can_submit && <p className="helper-text">本题暂不能继续向教练提问，可查看已有记录或切换到普通助教。</p>}
      </>}
      {(loadError || error) && <div className="error" role="alert">
        <p>{loadError || error}</p>
        {error && <p className="helper-text">你的疑问已保留。可重试加载状态，待教练可用后重新发送。</p>}
        <button type="button" className="secondary" disabled={refreshing || pending} onClick={retry}>重试</button>
      </div>}
    </div>
    {!readOnly && view?.available && view.can_submit && (open || view.runs.length > 0) && <form
      className="coach-composer" onSubmit={submit} aria-busy={pending || running || refreshing}>
      <textarea aria-label="错题教练：你的疑问" placeholder="哪一步的结果和你预期的不一样？" maxLength={500} rows={3}
        value={message} readOnly={pending || running || refreshing} onChange={(event) => {
          setMessage(event.target.value);
          setRequestKey(crypto.randomUUID());
        }}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.shiftKey || composing.current || event.nativeEvent.isComposing
            || event.nativeEvent.keyCode === 229) return;
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }} />
      <div className="composer-footer">
        <span className="helper-text" role="status">{pending ? "正在发送…" : refreshing ? "正在刷新状态…"
          : running ? "教练正在查证，请稍候…" : "Enter 发送 · Shift + Enter 换行"}</span>
        <span className="helper-text">{message.length}/500</span>
        <button disabled={pending || running || refreshing || !message.trim()}>请教错题教练</button>
      </div>
    </form>}
  </section>;
}
