import { FormEvent, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import CoachPanel from "./CoachPanel";
import DiagnosisPanel from "./DiagnosisPanel";
import TransferExercise from "./TransferExercise";
import LearningMemories from "./LearningMemories";
import SQLWorkbench from "./SQLWorkbench";
import TutorPanel, { Turn } from "./TutorPanel";
import "./style.css";

type Item = { id: number; title: string; prompt: string; options: string[]; level: number; topic: string };
type Presentation = { status: "ready"; decision_id: string; item: Item; source: "rule" | "epikt"; reason: string };
type Finished = { status: "complete" | "blocked"; remaining: number };
type Feedback = { decision_id: string; event_seq: number; correct: boolean; selected_option: number; template_hint: string | null };
type Review = { presentation: Presentation; feedback: Feedback; turns: Turn[] };
type Progress = { total: number; correct: number; pending: Presentation | null; last: Review | null };
type Replay = { chosen_item_id: number; source: string; comparison: { rule_item_id?: number | null; model_version?: string } };
type PendingRequest = "practice" | "tutor";
type Dialog = "records" | "guide" | "recommendation" | null;

const topicNames: Record<string, string> = {
  select: "数据查询", where: "条件筛选", filter: "条件筛选", aggregate: "分组与聚合", join: "多表连接",
  distinct: "去重查询", set: "集合运算", set_operations: "集合运算", subquery: "子查询", subqueries: "子查询", null: "空值处理",
};
const practiceDirection: Record<number, string> = { 1: "从基础概念开始，稳稳向前。", 2: "巩固这个知识点，再进一步。", 3: "挑战进阶练习，连接你学过的知识。" };
const fallbackReason: Record<string, string> = {
  model_unconfigured: "当前使用课程规则安排练习。", model_unavailable: "本轮评分模型不可用，已切换到课程规则。",
  model_timeout: "本轮评分未及时完成，已切换到课程规则。", model_error: "本轮未得到有效模型评分，已切换到课程规则。",
  unmapped_catalog_or_history: "本轮题目或作答记录未纳入模型评分，已使用课程规则。", model_no_eligible_item: "本轮按课程规则选出了一道符合练习条件的题。",
};

function Icon({ name, size = 20 }: { name: "grid" | "book" | "arrow" | "back" | "chat" | "spark" | "check" | "close" | "help" | "chart" | "chevron"; size?: number }) {
  const paths = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    book: <><path d="M12 5v15M3 4c4-1 6 0 9 2 3-2 5-3 9-2v15c-4-1-6 0-9 2-3-2-5-3-9-2Z" /></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />, back: <path d="M20 12H4m6-6-6 6 6 6" />,
    chat: <path d="M21 11a8 8 0 0 1-8 8H8l-5 3V7a4 4 0 0 1 4-4h6a8 8 0 0 1 8 8Z" />,
    spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z" /><path d="M20 2v4m-2-2h4" /></>,
    check: <path d="m5 12 4 4L19 6" />, close: <path d="m6 6 12 12M6 18 18 6" />,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4m0 3h.01" /></>,
    chart: <><path d="M4 3v17h17M8 15l4-5 4 2 5-7" /></>, chevron: <path d="m9 5 7 7-7 7" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function SqlCode({ text }: { text: string }) {
  return <pre className="sql-code"><code>{text.split(/('[^']*'|\b(?:SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LEFT JOIN|INNER JOIN|JOIN|ON|AS|DISTINCT|COUNT|SUM|MIN|MAX|AVG|EXISTS|NOT|IN|UNION|EXCEPT|AND|OR|IS|NULL)\b)/gi).map((part, index) =>
    index % 2 === 0 ? part : <span className={part.startsWith("'") ? "sql-string" : "sql-keyword"} key={index}>{part}</span>)}</code></pre>;
}

function QuestionContent({ prompt }: { prompt: string }) {
  const [question, ...context] = prompt.split("演示用表数据（合成）");
  const sqlAt = question.search(/^\s*SELECT\b/im);
  const tables = context.join("演示用表数据（合成）").trim().split(/\n\s*\n/).filter(Boolean);
  return <div className="question-content">
    <p className="question" lang="en">{sqlAt < 0 ? question : question.slice(0, sqlAt).trim()}</p>
    {sqlAt >= 0 && <div className="query-block"><div className="code-label"><span>SQL</span><span>阅读查询，判断结果</span></div><SqlCode text={question.slice(sqlAt).trim()} /></div>}
    {tables.length > 0 && <section className="question-data" aria-label="题目数据">
      <div className="section-label"><span>题目数据</span><span className="subtle-badge">合成演示</span></div>
      <div className="context-tables">{tables.map((block, index) => {
        const [name, heading, ...rows] = block.split("\n");
        if (!heading?.includes("|")) return <pre key={index}>{block}</pre>;
        return <div className="context-table" key={index}><table><caption>{name}</caption>
          <thead><tr>{heading.split("|").map((column, col) => <th scope="col" key={col}>{column.trim()}</th>)}</tr></thead>
          <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.split("|").map((cell, col) => <td key={col}>{cell.trim()}</td>)}</tr>)}</tbody>
        </table></div>;
      })}</div>
    </section>}
  </div>;
}

class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string) { super(message); }
}
async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(path, { method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, typeof result.detail === "string" ? result.detail : (result.detail?.message ?? "请求失败，请重试。"), result.detail?.code);
  return result as T;
}

function App() {
  const [loaded, setLoaded] = useState(false);
  const [workbench, setWorkbench] = useState<"practice" | "sql">("practice");
  const [sqlVisited, setSqlVisited] = useState(false);
  const [sqlSessionRevision, setSqlSessionRevision] = useState(0);
  const sessionReady = useRef(false);
  const sessionRequest = useRef<Promise<void> | null>(null);
  const [currentPractice, setPractice] = useState<Presentation | null>(null);
  const [currentFeedback, setFeedback] = useState<Feedback | null>(null);
  const [currentTurns, setTurns] = useState<Turn[]>([]);
  const [review, setReview] = useState<Review | null>(null);
  const [progress, setProgress] = useState({ total: 0, correct: 0 });
  const [finished, setFinished] = useState<Finished | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const [currentChoice, setChoice] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [pendingMessage, setPendingMessage] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [memoryRevision, setMemoryRevision] = useState(0);
  const [pendingRequest, setPendingRequest] = useState<PendingRequest | null>(null);
  const [error, setError] = useState("");
  const [tutorError, setTutorError] = useState("");
  const [assistantTab, setAssistantTab] = useState<"tutor" | "coach">("tutor");
  const [mobilePanel, setMobilePanel] = useState<"practice" | "assistant">("practice");
  const [focusVersion, setFocusVersion] = useState(0);
  const [dialog, setDialog] = useState<Dialog>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const busy = pendingRequest !== null;
  const tutorPending = pendingRequest === "tutor";
  const practice = review?.presentation ?? currentPractice;
  const feedback = review?.feedback ?? currentFeedback;
  const turns = review?.turns ?? currentTurns;
  const choice = review?.feedback.selected_option ?? currentChoice;
  const previousSequence = (feedback?.event_seq ?? progress.total + 1) - 1;
  const topic = practice ? topicNames[practice.item.topic] ?? practice.item.topic.toUpperCase() : "SQL 基础查询";
  const wrong = feedback?.correct === false;
  const experimentsAvailable = !!practice && [75, 81].includes(practice.item.id);

  useEffect(() => {
    let active = true;
    api<Progress>("/api/practice/progress").then((data) => {
      if (!active) return;
      sessionReady.current = true;
      setProgress(data); setPractice(data.pending ?? data.last?.presentation ?? null);
      setFeedback(data.last?.feedback ?? null); setTurns(data.last?.turns ?? []); setChoice(data.last?.feedback.selected_option ?? null);
    }).catch((problem: unknown) => {
      if (!active || (problem instanceof ApiError && problem.status === 401)) return;
      if (problem instanceof ApiError && problem.code === "catalog_changed") { setRestartRequired(true); setError(problem.message); }
      else setError("暂时无法恢复练习，请刷新页面重试。");
    }).finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (dialog) dialogRef.current?.showModal();
    else dialogRef.current?.close();
  }, [dialog]);
  useEffect(() => {
    workspace.current?.scrollTo({ top: 0 });
    setAssistantTab("tutor"); setTutorError("");
  }, [practice?.decision_id]);
  useEffect(() => {
    if (error) workspace.current?.scrollTo({ top: 0 });
  }, [error]);
  useEffect(() => {
    function choose(event: KeyboardEvent) {
      if (workbench !== "practice" || !practice || feedback || busy || review || (mobilePanel === "assistant" && window.innerWidth <= 900) || event.ctrlKey || event.metaKey || event.altKey || dialog) return;
      if ((event.target as HTMLElement).closest("input, textarea, select, button, [contenteditable]")) return;
      const index = Number(event.key) - 1;
      if (/^[1-9]$/.test(event.key) && index < practice.item.options.length) setChoice(index);
    }
    document.addEventListener("keydown", choose);
    return () => document.removeEventListener("keydown", choose);
  }, [practice, feedback, busy, review, mobilePanel, dialog, workbench]);

  function showWorkbench(next: "practice" | "sql") {
    if (next === "sql") setSqlVisited(true);
    setWorkbench(next); setMobilePanel("practice");
  }
  async function ensureSQLSession() {
    if (sessionReady.current) return;
    if (!sessionRequest.current) {
      sessionRequest.current = api("/api/session", {}).then(() => { sessionReady.current = true; })
        .finally(() => { sessionRequest.current = null; });
    }
    await sessionRequest.current;
  }

  async function perform(work: () => Promise<void>, request: PendingRequest = "practice") {
    if (busy) return;
    setPendingRequest(request);
    if (request === "tutor") setTutorError(""); else setError("");
    try { await work(); }
    catch (problem) {
      if (problem instanceof ApiError && problem.code === "catalog_changed") { setRestartRequired(true); setPractice(null); setReview(null); }
      const text = problem instanceof Error ? problem.message : "请求失败，请重试。";
      if (request === "tutor") setTutorError(text); else setError(text);
    } finally { setPendingRequest(null); setPendingMessage(""); }
  }
  async function nextItem() {
    const data = await api<Presentation | Finished>("/api/practice/next", {});
    setFinished(data.status === "ready" ? null : data); setPractice(data.status === "ready" ? data : null);
    setReview(null); setChoice(null); setFeedback(null); setTurns([]); setMessage(""); setReplay(null); setTutorError("");
    setMobilePanel("practice");
  }
  function reviewItem(sequence: number) {
    return perform(async () => {
      setReview(await api<Review>(`/api/practice/history/${sequence}`)); setReplay(null); showWorkbench("practice"); setDialog(null);
    });
  }
  function returnToCurrent() { setReview(null); setReplay(null); setError(""); setMobilePanel("practice"); }
  function begin(restart = false) {
    return perform(async () => {
      await api("/api/session" + (restart ? "?restart=true" : ""), {});
      sessionReady.current = true;
      if (restart) { setProgress({ total: 0, correct: 0 }); setRestartRequired(false); setFinished(null); setSqlSessionRevision((value) => value + 1); }
      await nextItem();
    });
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (review || choice === null || !practice || feedback) return;
    const selected = practice;
    return perform(async () => {
      const result = await api<Feedback>(`/api/practice/${selected.decision_id}/answer`, { option: choice, idempotency_key: selected.decision_id });
      setFeedback(result);
      setProgress(await api<Progress>("/api/practice/progress"));
    });
  }
  function ask(event: FormEvent) {
    event.preventDefault();
    if (review || !practice || !wrong || !message.trim() || busy) return;
    const id = practice.decision_id;
    const text = message.trim();
    setPendingMessage(text);
    return perform(async () => {
      const result = await api<Turn>(`/api/practice/${id}/tutor`, { message: text });
      setTurns((existing) => [...existing, result]); setMessage("");
    }, "tutor");
  }
  function openTutor() { setAssistantTab("tutor"); setMobilePanel("assistant"); setFocusVersion((value) => value + 1); }

  return <div className={`app-shell mobile-${mobilePanel}`}>
    <a className="skip-link" href={workbench === "sql" ? "#sql-workspace" : "#practice-workspace"} onClick={() => setMobilePanel("practice")}>跳到练习区</a>
    <header className="topbar">
      <a className="brand" href="#practice-workspace" onClick={() => showWorkbench("practice")} aria-label="QueryStep 练习工作台"><span className="brand-mark">Q<span /></span><span>QueryStep<span className="brand-dot">.</span></span></a>
      <div className="topbar-center"><span>学习空间</span><Icon name="chevron" size={13} /><strong>{workbench === "sql" ? "SQL 实作" : "SQL 基础查询"}</strong></div>
      <div className="topbar-right"><button className="mobile-workbench-entry secondary" disabled={!loaded} onClick={() => showWorkbench(workbench === "sql" ? "practice" : "sql")}>{workbench === "sql" ? "正式练习" : "SQL 实作"}</button><span className="local-session"><span className="status-dot" />本机学习会话</span><button type="button" className="icon-button" aria-label="使用指南" onClick={() => setDialog("guide")}><Icon name="help" /></button><span className="profile-avatar" aria-label="学习者">L</span></div>
    </header>

    <aside className="sidebar" aria-label="学习导航">
      <div><p className="nav-caption">WORKSPACE</p><nav className="side-nav">
        <button className={`nav-item${workbench === "practice" ? " active" : ""}`} aria-label="练习工作台" title="练习工作台" aria-current={workbench === "practice" ? "page" : undefined} onClick={() => { showWorkbench("practice"); workspace.current?.scrollTo({ top: 0, behavior: "smooth" }); }}><Icon name="grid" />练习工作台{workbench === "practice" && <span className="nav-active-dot" />}</button>
        <button className={`nav-item${workbench === "sql" ? " active" : ""}`} aria-label="SQL 实作" title="SQL 实作" disabled={!loaded} aria-current={workbench === "sql" ? "page" : undefined} onClick={() => showWorkbench("sql")}><span className="sql-nav-icon" aria-hidden="true">SQL</span>SQL 实作{workbench === "sql" && <span className="nav-active-dot" />}</button>
        <button className="nav-item" onClick={() => setDialog("records")}><Icon name="book" />学习记录{progress.total > 0 && <span className="nav-count">{progress.total}</span>}</button>
      </nav></div>
      <div className="sidebar-progress"><p className="nav-caption">你的每一步，都算数</p><div className="progress-numbers"><div><strong>{progress.total.toString().padStart(2, "0")}</strong><span>已作答</span></div><div><strong>{progress.correct.toString().padStart(2, "0")}</strong><span>答对</span></div></div>
        <div className="progress-track" aria-hidden="true"><span style={{ width: progress.total ? `${progress.correct / progress.total * 100}%` : "0%" }} /></div>
        <p>{progress.total ? `本轮正确率 ${Math.round(progress.correct / progress.total * 100)}%` : "从第一道题开始积累"}</p>
      </div>
      <div className="sidebar-bottom"><div className="adaptive-card"><span className="adaptive-icon"><Icon name="spark" size={18} /></span><h3>不是题海，是下一步</h3><p>依据正式作答记录，安排更适合的下一题。</p><button className="text-button" onClick={() => setDialog("recommendation")}>了解选题方式 <Icon name="arrow" size={15} /></button></div><span className="sidebar-footnote">一步一题，循序而进。</span></div>
    </aside>

    <main className="workspace-scroll" id="practice-workspace" ref={workspace} tabIndex={-1} hidden={workbench !== "practice"}>
      <div className="workspace-inner">
        <div className="workspace-heading"><div><p className="eyebrow">LEARN. QUERY. GROW.</p><h1>练习工作台</h1></div><button className="mobile-records icon-button" aria-label="查看学习记录" onClick={() => setDialog("records")}><Icon name="book" /></button><span className="workspace-label"><span />专注当下这一题</span></div>
        {error && <p className="error" role="alert">{error}</p>}
        {!loaded ? <div className="loading-card" role="status"><span className="loading-spinner" />正在恢复你的练习…</div> : !practice ? <section className="welcome-card">
          <div className="welcome-art" aria-hidden="true"><div className="art-grid" /><div className="art-sql"><span>SQL</span><p><b>SELECT</b> next_step<br /><b>FROM</b> your_journey;</p><div><i /><i /><i /></div></div><span className="art-orbit orbit-one" /><span className="art-orbit orbit-two" /></div>
          <p className="eyebrow">{finished ? "每一步练习，都有收获" : "让每一道题，成为进步的一步"}</p>
          <h2>{finished?.status === "blocked" ? "先巩固，再向前" : finished ? "这一轮，完成了" : <>学会的不只是 SQL，<br />还有解决问题的思路。</>}</h2>
          <p className="welcome-description">{finished?.status === "blocked" ? `本轮还有 ${finished.remaining} 道题暂未满足推荐条件，可以开始新一轮复习。` : finished ? `你已经完成 ${progress.total} 道练习，答对 ${progress.correct} 道。可以回看题目，或开启新一轮。` : "从一道查询题开始。独立思考、验证结果，再和助教一起把不理解的地方弄明白。"}</p>
          <div className="welcome-actions"><button disabled={busy} onClick={() => begin(restartRequired || !!finished)}>{busy ? "正在准备题目…" : restartRequired || finished ? "重新开始" : "开始练习"}<Icon name="arrow" size={18} /></button>{finished && progress.total > 0 && <button className="secondary" disabled={busy} onClick={() => reviewItem(progress.total)}>回看上一题</button>}</div>
          <div className="learning-steps"><div><span>01</span><b>独立思考</b><p>从你的真实理解出发</p></div><div><span>02</span><b>弄懂原因</b><p>用提示与 SQL 结果验证</p></div><div><span>03</span><b>巩固迁移</b><p>换一组数据，再练一次</p></div></div>
        </section> : <>
          <div className="practice-navigation"><div className="navigation-left"><button type="button" className="icon-button" aria-label="上一题" title="上一题" disabled={busy || previousSequence < 1} onClick={() => reviewItem(previousSequence)}><Icon name="back" size={18} /></button><span>{review ? "回看" : "练习"} <strong>{String(feedback?.event_seq ?? progress.total + 1).padStart(2, "0")}</strong></span>{review && <button type="button" className="icon-button" aria-label="下一题" title="下一题" disabled={busy} onClick={() => { const nextSequence = review.feedback.event_seq + 1; if (nextSequence < (currentFeedback?.event_seq ?? progress.total + 1)) void reviewItem(nextSequence); else returnToCurrent(); }}><Icon name="arrow" size={18} /></button>}</div>
            {review ? <button className="text-button" disabled={busy} onClick={returnToCurrent}>返回当前进度 <Icon name="arrow" size={15} /></button> : <span className={`recommendation-badge ${practice.source === "epikt" ? "model" : ""}`}><Icon name="spark" size={13} />{practice.source === "epikt" ? "EpiKT 推荐" : practice.reason === "cold_start" ? "起步练习" : "规则推荐"}</span>}
          </div>
          {review && <div className="review-notice"><Icon name="book" size={16} />正在回看第 {review.feedback.event_seq} 题 · 不会改变作答记录</div>}
          <section className="question-card" aria-label="当前题目">
            <div className="question-header"><div className="topic-tags"><span className="topic-tag">{topic}</span><span className="level-tag">{({ 1: "基础", 2: "巩固", 3: "进阶" } as Record<number, string>)[practice.item.level]}</span></div><span className="question-id">{practice.item.title}</span></div>
            <h2>{topic}练习</h2><p className="question-direction">{practice.reason === "cold_start" ? `正在建立练习记录，完成前三道题后尝试个性化推荐。` : practiceDirection[practice.item.level]}</p>
            <QuestionContent prompt={practice.item.prompt} />
            <form onSubmit={submit} className="answer-form"><div className="answer-label"><span>选择你的答案</span>{!feedback && <span className="keyboard-hint">可按 1–{practice.item.options.length} 选择</span>}</div>
              <fieldset disabled={!!feedback || busy}><legend className="sr-only">选择答案</legend>{practice.item.options.map((option, index) => {
                const selected = choice === index; const incorrect = selected && wrong; const correct = selected && feedback?.correct;
                return <label className={`option${selected ? " selected" : ""}${incorrect ? " incorrect" : ""}${correct ? " correct" : ""}`} key={index}>
                  <input type="radio" name="answer" checked={selected} onChange={() => setChoice(index)} /><span className="letter">{String.fromCharCode(65 + index)}</span><span className={`option-text${/^select\b/i.test(option) ? " sql-option" : ""}`}>{option}</span>{incorrect ? <span className="answer-state">答错</span> : correct ? <Icon name="check" size={18} /> : <span className="radio-indicator" />}
                </label>;
              })}</fieldset>
              {!feedback && <div className="answer-footer"><span>{choice === null ? "选择一个选项，再提交答案" : `已选择 ${String.fromCharCode(65 + choice)}`}</span><button disabled={choice === null || busy}>{busy ? "正在提交…" : "提交答案"}<Icon name="arrow" size={17} /></button></div>}
            </form>
            {feedback && <div className={`answer-feedback ${feedback.correct ? "is-correct" : "is-incorrect"}`} role="status"><span className="feedback-icon"><Icon name={feedback.correct ? "check" : "help"} size={19} /></span><div><strong>{feedback.correct ? "回答正确，继续保持" : "还差一步，一起理清思路"}</strong><p>{feedback.correct ? "这道题已计入学习记录，可以继续下一题。" : feedback.template_hint ?? "回答有误，可以向右侧助教提问，或换一组数据再练习。"}</p></div></div>}
          </section>
          {feedback && <div className="practice-action-bar"><div>{wrong && !review && <button className="secondary" onClick={openTutor}><Icon name="chat" size={17} />问问助教</button>}<button className="text-button" disabled={busy} onClick={() => perform(async () => { setReplay(replay ? null : await api<Replay>(`/api/practice/${practice.decision_id}/replay`)); })}><Icon name="chart" size={16} />{replay ? "收起选题记录" : "查看选题记录"}</button></div>{!review && <button disabled={busy} onClick={() => perform(nextItem)}>{pendingRequest === "practice" ? "正在选题…" : "下一题"}<Icon name="arrow" size={18} /></button>}</div>}
          {replay && <section className="replay" aria-label="选题记录"><h3>这道题是如何选出的？</h3><p>{replay.source === "epikt" && typeof replay.comparison.rule_item_id === "number" && (replay.chosen_item_id === replay.comparison.rule_item_id ? "EpiKT 与规则选了同一道题。" : "EpiKT 与规则选了不同的题。")}{`本轮实际题号 ${replay.chosen_item_id}。`}{replay.comparison.rule_item_id === null ? "规则对照未选题。" : replay.comparison.rule_item_id !== undefined && `规则对照题号 ${replay.comparison.rule_item_id}。`}{fallbackReason[practice.reason]}</p>{replay.comparison.model_version && <details><summary>模型版本</summary><code>{replay.comparison.model_version}</code></details>}</section>}
          {wrong && <div className="practice-extensions">
            <TransferExercise key={`transfer-${practice.decision_id}`} decisionId={practice.decision_id} request={api} readOnly={!!review} />
            {experimentsAvailable && <details className="lab-disclosure" key={`lab-${practice.decision_id}`}><summary><span className="extension-icon"><Icon name="grid" size={19} /></span><span><strong>SQL 错题诊断</strong><small>查找课程依据，亲手验证查询结果</small></span><Icon name="chevron" size={17} /></summary><DiagnosisPanel decisionId={practice.decision_id} request={api} readOnly={!!review} onMemorySaved={() => setMemoryRevision((value) => value + 1)} /></details>}
          </div>}
          <p className="workspace-footnote">正式作答用于后续选题 · 辅导与迁移练习不改变原题记录</p>
        </>}
      </div>
    </main>

    <aside className="assistant-sidebar" aria-label="学习助教" hidden={workbench !== "practice"}>
      <div className="assistant-header"><div className="assistant-title"><span className="assistant-symbol"><Icon name="spark" size={19} /></span><div><h2>学习助教</h2><p>思路有人陪，答案自己找。</p></div></div><button className="icon-button mobile-close" aria-label="返回练习" onClick={() => setMobilePanel("practice")}><Icon name="close" /></button><span className="ai-label">AI</span></div>
      <div className="assistant-tabs" role="tablist" aria-label="辅导方式"><button id="tutor-tab" role="tab" aria-controls="tutor-pane" aria-selected={assistantTab === "tutor"} tabIndex={assistantTab === "tutor" ? 0 : -1} onClick={() => setAssistantTab("tutor")} onKeyDown={(event) => { if (event.key === "ArrowRight") { setAssistantTab("coach"); document.getElementById("coach-tab")?.focus(); } }}>对话辅导</button><button id="coach-tab" role="tab" aria-controls="coach-pane" aria-selected={assistantTab === "coach"} tabIndex={assistantTab === "coach" ? 0 : -1} onClick={() => setAssistantTab("coach")} onKeyDown={(event) => { if (event.key === "ArrowLeft") { setAssistantTab("tutor"); document.getElementById("tutor-tab")?.focus(); } }}>错题教练<span>实验验证</span></button></div>
      {practice && <div className="assistant-context"><span>当前{review ? "回看" : "题目"}</span><strong>{practice.item.title} · {topic}</strong>{review && <span className="subtle-badge">只读</span>}</div>}
      <div className="assistant-pane" id="tutor-pane" role="tabpanel" aria-labelledby="tutor-tab" hidden={assistantTab !== "tutor"}><TutorPanel turns={turns} message={message} pendingMessage={pendingMessage} pending={tutorPending} busy={busy} enabled={wrong && !review} readOnly={!!review} hasQuestion={!!practice} correct={feedback?.correct === true} error={tutorError} focusVersion={focusVersion} decisionId={practice?.decision_id} onMessage={setMessage} onSubmit={ask} /></div>
      <div className="assistant-pane" id="coach-pane" role="tabpanel" aria-labelledby="coach-tab" hidden={assistantTab !== "coach"}>{practice && wrong ? <CoachPanel key={practice.decision_id} decisionId={practice.decision_id} request={api} readOnly={!!review} /> : <div className="assistant-welcome coach-introduction"><div className="empty-icon"><Icon name="spark" size={28} /></div><h2>用证据，拆解一个疑问</h2><p>教练会查课程、运行 SQL，并根据结果决定下一步验证。</p><div className="coach-steps"><span>查找依据</span><Icon name="chevron" size={13} /><span>对照实验</span><Icon name="chevron" size={13} /><span>梳理结论</span></div><p className="helper-text">目前支持部分 HAVING 与 LEFT JOIN 错题；提交对应题目后可用，其他错题可使用对话辅导。</p></div>}</div>
    </aside>

    {sqlVisited && <SQLWorkbench key={sqlSessionRevision} active={workbench === "sql"} request={api} ensureSession={ensureSQLSession} onPractice={() => setMobilePanel("practice")} onAssistant={() => setMobilePanel("assistant")} />}

    <nav className="mobile-switch" aria-label="切换学习面板"><button className={mobilePanel === "practice" ? "active" : ""} onClick={() => setMobilePanel("practice")}><Icon name="grid" size={19} />练习</button><button className={mobilePanel === "assistant" ? "active" : ""} onClick={() => setMobilePanel("assistant")}><Icon name="chat" size={19} />助教{tutorPending && <span className="status-dot" />}</button></nav>

    <dialog ref={dialogRef} className="app-dialog" onCancel={() => setDialog(null)} onClose={() => setDialog(null)} onClick={(event) => { if (event.target === event.currentTarget) { const box = event.currentTarget.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) setDialog(null); } }} aria-labelledby="dialog-title">
      <div className="dialog-header"><div><p className="eyebrow">QUERYSTEP</p><h2 id="dialog-title">{dialog === "records" ? "学习记录" : dialog === "guide" ? "从这里开始" : "每道题，都有下一步"}</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setDialog(null)}><Icon name="close" /></button></div>
      <div className="dialog-body">{dialog === "records" ? <><p className="helper-text">本轮完成 {progress.total} 题，答对 {progress.correct} 题。点击序号回看，原始作答不会被修改。</p>{progress.total > 0 ? <div className="history-grid">{Array.from({ length: progress.total }, (_, index) => <button className="secondary" key={index} disabled={busy} onClick={() => reviewItem(index + 1)}>第 {index + 1} 题<Icon name="chevron" size={14} /></button>)}</div> : <div className="empty-records"><Icon name="book" size={30} /><p>还没有作答记录，从第一道练习开始吧。</p></div>}{progress.total > 0 && <LearningMemories request={api} revision={memoryRevision} />}</> : dialog === "guide" ? <ol className="guide-steps"><li><strong>先独立作答</strong><p>在中间阅读题目和数据，选择答案后提交。桌面端也可以按数字键选择。</p></li><li><strong>到右侧问问助教</strong><p>遇到错题，描述你的思路，或选择一个提问建议。Enter 发送，Shift + Enter 换行。</p></li><li><strong>用结果验证理解</strong><p>错题可换一组数据做迁移练习；部分题目还支持 SQL 诊断与自主错题教练。</p></li><li><strong>按自己的节奏继续</strong><p>点「下一题」继续，或用「学习记录」回看。当前浏览器会保留会话；清除 Cookie 后不能自动找回。</p></li></ol> : <><div className="recommendation-explainer"><Icon name="chart" size={30} /><h3>预测，是为了安排下一步</h3></div><p>前三道正式作答用于建立起步记录，使用课程规则选题；之后在模型可用、记录符合条件时，EpiKT 会预测候选题的答对概率，由教学策略选择下一题。</p><p>模型不可用时自动使用规则推荐。每道题的「选题记录」会显示实际采用的方式，以及规则对照结果。</p><p className="helper-text">预测概率不等于掌握度证明。练习结果、辅导对话和迁移题分别记录，不把未经验证的聊天内容写入模型历史。</p></>}</div>
    </dialog>
  </div>;
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
