import { FormEvent, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import DiagnosisPanel from "./DiagnosisPanel";
import LearningMemories from "./LearningMemories";
import "./style.css";

type Item = { id: number; title: string; prompt: string; options: string[]; level: number; topic: string };
type Presentation = { status: "ready"; decision_id: string; item: Item; source: "rule" | "epikt"; reason: string };
type Finished = { status: "complete" | "blocked"; remaining: number };
type Feedback = { decision_id: string; correct: boolean; selected_option: number; template_hint: string | null };
type Turn = { message: string; text: string; source: "llm" | "template"; action: string;
  memory_ids?: string[];
  citations: { id: string; title: string; url?: string }[] };
type Progress = { total: number; correct: number; pending: Presentation | null;
  last: { presentation: Presentation; feedback: Feedback; turns: Turn[] } | null };
type Replay = { chosen_item_id: number; source: string; comparison: { rule_item_id?: number | null; model_version?: string } };
type PendingRequest = "practice" | "tutor";

const practiceDirection: Record<number, string> = {
  1: "先练一道基础题",
  2: "用一道题巩固这个知识点",
  3: "试试更高难度的练习",
};
const fallbackReason: Record<string, string> = {
  model_unconfigured: "当前使用课程规则安排练习。",
  model_unavailable: "本轮评分模型不可用，已切换到课程规则。",
  model_timeout: "本轮评分未及时完成，已切换到课程规则。",
  model_error: "本轮未得到有效模型评分，已切换到课程规则。",
  unmapped_catalog_or_history: "本轮题目或作答记录未纳入模型评分，已使用课程规则。",
  model_no_eligible_item: "本轮按课程规则选出了一道符合练习条件的题。",
};

class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(path, {
    method, ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = result.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail :
      (detail?.message ?? "请求失败，请重试。"), detail?.code);
  }
  return result as T;
}

function App() {
  const [loaded, setLoaded] = useState(false);
  const [practice, setPractice] = useState<Presentation | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [progress, setProgress] = useState({ total: 0, correct: 0 });
  const [finished, setFinished] = useState<Finished | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const [choice, setChoice] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [replay, setReplay] = useState<Replay | null>(null);
  const [memoryRevision, setMemoryRevision] = useState(0);
  const [pendingRequest, setPendingRequest] = useState<PendingRequest | null>(null);
  const [error, setError] = useState("");
  const busy = pendingRequest !== null;
  const tutorPending = pendingRequest === "tutor";

  useEffect(() => {
    let active = true;
    api<Progress>("/api/practice/progress").then((data) => {
      if (!active) return;
      setProgress(data);
      setPractice(data.pending ?? data.last?.presentation ?? null);
      setFeedback(data.last?.feedback ?? null);
      setTurns(data.last?.turns ?? []);
      setChoice(data.last?.feedback.selected_option ?? null);
    }).catch((problem: unknown) => {
      if (!active || (problem instanceof ApiError && problem.status === 401)) return;
      if (problem instanceof ApiError && problem.code === "catalog_changed") {
        setRestartRequired(true);
        setError(problem.message);
      } else {
        setError("暂时无法恢复练习。");
      }
    }).finally(() => { if (active) setLoaded(true); });
    return () => { active = false; };
  }, []);

  async function perform(work: () => Promise<void>, request: PendingRequest = "practice") {
    if (busy) return;
    setPendingRequest(request);
    setError("");
    try {
      await work();
    } catch (problem) {
      if (problem instanceof ApiError && problem.code === "catalog_changed") {
        setRestartRequired(true);
        setPractice(null);
      }
      setError(problem instanceof Error ? problem.message : "请求失败，请重试。");
    } finally {
      setPendingRequest(null);
    }
  }

  async function nextItem() {
    const data = await api<Presentation | Finished>("/api/practice/next", {});
    setFinished(data.status === "ready" ? null : data);
    setPractice(data.status === "ready" ? data : null);
    setChoice(null);
    setFeedback(null);
    setTurns([]);
    setMessage("");
    setReplay(null);
  }

  function begin(restart = false) {
    return perform(async () => {
      await api("/api/session" + (restart ? "?restart=true" : ""), {});
      if (restart) {
        setProgress({ total: 0, correct: 0 });
        setRestartRequired(false);
        setFinished(null);
      }
      await nextItem();
    });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (choice === null || !practice) return;
    const selected = practice;
    return perform(async () => {
      const result = await api<Feedback>(`/api/practice/${selected.decision_id}/answer`,
        { option: choice, idempotency_key: selected.decision_id });
      setFeedback(result);
      const status = await api<Progress>("/api/practice/progress");
      setProgress(status);
    });
  }

  function ask(event: FormEvent) {
    event.preventDefault();
    if (!practice || !message.trim()) return;
    const id = practice.decision_id;
    const text = message.trim();
    return perform(async () => {
      const result = await api<Turn>(`/api/practice/${id}/tutor`, { message: text });
      setTurns((existing) => [...existing, result]);
      setMessage("");
    }, "tutor");
  }

  return (
    <main className="page">
      <header className="top">
        <div className="brand"><span className="mark">Q</span> QueryStep</div>
        <span className="pill">SQL · 基础查询</span>
      </header>
      <div className="layout">
        <aside className="progress">
          <p className="eyebrow">学习记录</p>
          <h2>每道题都有下一步</h2>
          <p>练习结果会用于后续推荐。你可以关闭页面，下次继续。</p>
          <dl><dt>已作答</dt><dd>{progress.total}</dd><dt>答对</dt><dd>{progress.correct}</dd></dl>
          {(practice || finished) && <LearningMemories key={practice?.decision_id ?? "finished"} request={api}
            revision={memoryRevision} />}
        </aside>
        <section className="workspace">
          {error && <p className="error" role="alert">{error}</p>}
          {!loaded ? <p role="status">正在恢复练习…</p> : !practice ? (
            <>
              <p className="eyebrow">{finished ? "练习结束" : "今日练习"}</p>
              <h1>{finished?.status === "blocked" ? "本轮暂无适合的下一题" :
                finished ? "本轮练习已完成" : "用 SQL 找到你想要的数据"}</h1>
              <p>{finished?.status === "blocked"
                ? `还有 ${finished.remaining} 道题。可以开启新一轮复习基础知识。`
                : "从 SELECT 和 WHERE 起步。做完一道题后，系统会根据本轮作答安排下一步。"}</p>
              <button disabled={busy} onClick={() => begin(restartRequired || !!finished)}>
                {restartRequired || finished ? "重新开始" : "开始练习"}
              </button>
            </>
          ) : (
            <>
              <div className="item-meta"><span>{practice.item.topic}</span><span>{practice.source === "epikt" ? "EpiKT 推荐" : "规则推荐"}</span></div>
              <p>{practice.reason === "cold_start" ? "正在建立练习记录。" :
                `${practiceDirection[practice.item.level]}。`}</p>
              <h1>{practice.item.title}</h1>
              <p className="question">{practice.item.prompt}</p>
              <form onSubmit={submit}>
                <fieldset disabled={!!feedback || busy}>
                  <legend className="sr-only">选择答案</legend>
                  {practice.item.options.map((option, index) => {
                    const selected = choice === index;
                    const incorrect = selected && feedback?.correct === false;
                    return <label className={`option${incorrect ? " incorrect" : selected ? " selected" : ""}`} key={index}>
                      <input type="radio" name="answer" checked={selected} onChange={() => setChoice(index)} />
                      <span className="letter">{String.fromCharCode(65 + index)}</span>
                      <span className="option-text">{option}</span>
                      {incorrect && <span className="incorrect-label">答错</span>}
                    </label>;
                  })}
                </fieldset>
                {!feedback && <button disabled={choice === null || busy}>提交答案</button>}
              </form>
              {feedback && <>
                <p className={feedback.correct ? "notice success" : "notice"} role="status">
                  {feedback.correct ? "回答正确。可以继续练习。" : `回答有误。${feedback.template_hint ?? ""}`}
                </p>
                {!feedback.correct && <section className="tutor" aria-label="课程辅导">
                  <h2>问问助教</h2>
                  {turns.map((turn, index) => <article className="turn" key={index}>
                    <p><b>你</b> {turn.message}</p>
                    <p><b>{turn.source === "llm" ? "LLM 助教" : "审核提示"}</b>{" "}
                      {turn.text.split(/(`[^`\n]+`)/).map((part, index) =>
                        index % 2 === 0 ? part : <code key={index}>{part.slice(1, -1)}</code>)}
                    </p>
                    {!!turn.memory_ids?.length && <p className="citation">本轮辅导读取了已确认的学习记录</p>}
                    {turn.citations.map((source) => source.url
                      ? <a key={source.id} href={source.url} target="_blank" rel="noreferrer">{source.title}</a>
                      : <span key={source.id} className="citation">{source.title}</span>)}
                  </article>)}
                  <div role="status">
                    {tutorPending && <p className="tutor-thinking">
                      <span className="tutor-thinking-dots" aria-hidden="true"><span /><span /><span /></span>
                      助教正在思考…
                    </p>}
                  </div>
                  <form onSubmit={ask} className="tutor-form">
                    <input aria-label="你的问题" placeholder="说说你刚才是怎么想的…" maxLength={500}
                      value={message} readOnly={tutorPending} onChange={(event) => setMessage(event.target.value)} />
                    <button type="submit" disabled={busy || !message.trim()}>发送</button>
                  </form>
                </section>}
                {!feedback.correct && <DiagnosisPanel key={practice.decision_id} decisionId={practice.decision_id} request={api}
                  onMemorySaved={() => setMemoryRevision((value) => value + 1)} />}
                <div className="actions">
                  <button disabled={busy} onClick={() => perform(nextItem)}>下一题</button>
                  <button className="secondary" disabled={busy} onClick={() => perform(async () => {
                    setReplay(await api<Replay>(`/api/practice/${practice.decision_id}/replay`));
                  })}>查看选题记录</button>
                </div>
              </>}
              {replay && <p className="replay">
                {replay.source === "epikt" && typeof replay.comparison.rule_item_id === "number" &&
                  (replay.chosen_item_id === replay.comparison.rule_item_id
                    ? "EpiKT 与规则选了同一道题。" : "EpiKT 与规则选了不同的题。")}
                本轮实际题号 {replay.chosen_item_id}。
                {replay.comparison.rule_item_id === null ? "规则对照未选题。" :
                  replay.comparison.rule_item_id !== undefined && `规则对照题号 ${replay.comparison.rule_item_id}。`}
                {replay.comparison.model_version && `模型版本 ${replay.comparison.model_version}。`}
                {fallbackReason[practice.reason]}
              </p>}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
