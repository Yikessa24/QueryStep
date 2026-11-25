import { FormEvent, useEffect, useRef } from "react";

export type Turn = {
  message: string; text: string; source: "llm" | "template"; action: string;
  fallback_reason?: string | null; memory_ids?: string[];
  citations: { id: string; title: string; url?: string }[];
};

type Props = {
  turns: Turn[]; message: string; pendingMessage: string; pending: boolean; busy: boolean;
  enabled: boolean; readOnly: boolean; hasQuestion: boolean; correct: boolean;
  error: string; focusVersion: number; decisionId?: string;
  onMessage: (message: string) => void; onSubmit: (event: FormEvent) => void;
};

export function RichText({ text }: { text: string }) {
  return <>{text.split(/(`[^`\n]+`)/).map((part, index) =>
    index % 2 === 0 ? part : <code key={index}>{part.slice(1, -1)}</code>)}</>;
}

function fallbackLabel(reason?: string | null) {
  if (reason === "llm_timeout") return "助教响应超时，先为你提供课程提示。你可以重新提问。";
  if (reason === "llm_busy") return "助教暂时繁忙，先为你提供课程提示。";
  if (reason === "history_turn_unavailable") return "可回查的范围是本题已保存的问答。";
  if (reason === "history_lookup_required" || reason === "missing_history_reference") return "本次未能引用指定轮次，先为你提供课程提示。";
  return "本次使用预置课程提示，并非实时生成的回答。";
}

export default function TutorPanel(props: Props) {
  const input = useRef<HTMLTextAreaElement>(null);
  const conversation = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const composing = useRef(false);
  useEffect(() => {
    if (props.focusVersion && props.enabled) input.current?.focus();
  }, [props.focusVersion, props.enabled]);
  useEffect(() => {
    follow.current = true;
    conversation.current?.scrollTo({ top: 0 });
  }, [props.decisionId]);
  useEffect(() => {
    if (conversation.current && (follow.current || props.pending)) {
      conversation.current.scrollTop = conversation.current.scrollHeight;
    }
  }, [props.turns.length, props.pending, props.pendingMessage, props.error]);

  const prompt = !props.hasQuestion ? "先开始一道练习" : props.correct ? "这一题已经答对了" : "先独立思考，再一起探索";
  return <section className="tutor-panel" aria-label="课程辅导">
    <div className="conversation" ref={conversation} onScroll={(event) => {
      const node = event.currentTarget;
      follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    }}>
      {props.turns.length === 0 && <div className="assistant-welcome">
        <div className="assistant-orbit" aria-hidden="true"><span>Q</span><i /><i /></div>
        <p className="eyebrow">YOUR LEARNING COMPANION</p>
        <h2>{props.readOnly ? "这道题还没有辅导记录" : props.enabled ? "一起把这道题弄明白" : prompt}</h2>
        <p>{props.readOnly ? "这里仅展示当时保存的对话，返回当前进度后可以继续学习。" : props.enabled
          ? "说说你的思路，我会用提示和例子帮你梳理，而不是直接给出答案。"
          : props.correct ? "做得不错，继续挑战下一题吧。遇到错题时，我会在这里帮你梳理思路。"
          : "提交答案后，如果遇到不理解的地方，可以在这里追问，不用离开题目。"}</p>
        {props.enabled && <div className="suggested-prompts" aria-label="提问建议">
          {["先给我一点提示，不要直接告诉我答案", "用一个简单例子解释这道题的考点", "我应该怎样检查自己的思路？"].map((text) =>
            <button className="prompt-button" type="button" key={text} disabled={props.busy} onClick={() => {
              props.onMessage(text); input.current?.focus();
            }}>{text}<span aria-hidden="true">↗</span></button>)}
        </div>}
      </div>}
      {props.turns.map((turn, index) => <article className="chat-turn" key={index}>
        <div className="user-message"><span className="sr-only">你：</span>{turn.message}</div>
        <div className="assistant-message">
          <div className="message-author"><span className="mini-avatar" aria-hidden="true">Q</span>
            <b>{turn.source === "llm" ? "LLM 助教" : "课程提示"}</b>
            {turn.source === "template" && <span className="fallback-badge">备用回复</span>}
          </div>
          {turn.source === "template" && <p className="fallback-explanation">{fallbackLabel(turn.fallback_reason)}</p>}
          <p className="message-text"><RichText text={turn.text} /></p>
          {!!turn.memory_ids?.length && <p className="memory-reference">本轮辅导读取了已确认的学习记录</p>}
          {turn.citations.length > 0 && <div className="message-sources">{turn.citations.map((source) => source.url
            ? <a key={source.id} href={source.url} target="_blank" rel="noreferrer">{source.title} <span aria-hidden="true">↗</span></a>
            : <span key={source.id} className="citation">{source.title === "审核例题" ? "课程例题" : source.title}</span>)}</div>}
        </div>
      </article>)}
      {props.pending && <div className="chat-turn">
        <div className="user-message">{props.pendingMessage}</div>
        <div className="tutor-thinking" role="status"><span className="tutor-thinking-dots" aria-hidden="true"><span /><span /><span /></span>助教正在思考…</div>
      </div>}
      {props.error && <p className="error" role="alert">{props.error} 你的问题已保留，可以重试。</p>}
    </div>
    {props.readOnly ? <div className="composer-readonly">历史对话 · 仅供回看</div> : <form className="chat-composer" onSubmit={props.onSubmit}>
      <label className="sr-only" htmlFor="tutor-question">你的问题</label>
      <textarea id="tutor-question" ref={input} placeholder={props.enabled ? "说说你的思路，或提出一个问题…" : "完成作答后，错题辅导将在这里开启"}
        rows={3} maxLength={500} disabled={!props.enabled} readOnly={props.pending} value={props.message}
        onChange={(event) => props.onMessage(event.target.value)}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !composing.current && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
            event.preventDefault();
            if (!props.busy && props.message.trim()) event.currentTarget.form?.requestSubmit();
          }
        }} />
      <div className="composer-footer"><span>{props.message.length > 400 ? `${props.message.length}/500` : "Enter 发送 · Shift + Enter 换行"}</span>
        <button type="submit" className="send-button" disabled={!props.enabled || props.busy || !props.message.trim()}>
          <span>{props.pending ? "思考中" : "发送"}</span><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 19V5m-6 6 6-6 6 6" /></svg>
        </button>
      </div>
      <p className="composer-disclaimer">AI 回答仅作学习参考，请结合课程依据核对。</p>
    </form>}
  </section>;
}
