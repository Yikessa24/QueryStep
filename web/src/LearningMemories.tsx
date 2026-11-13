import { FormEvent, useCallback, useEffect, useState } from "react";

type Memory = { memory_id: string; topic: string; summary: string; version: number; updated_at: string };
type Request = <T>(path: string, body?: unknown, method?: string) => Promise<T>;

export default function LearningMemories({ request, revision }: { request: Request; revision: number }) {
  const [records, setRecords] = useState<Memory[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let active = true;
    request<{ diagnostics_ready: boolean }>("/healthz").then((health) => {
      if (active) setEnabled(health.diagnostics_ready);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [request]);

  const load = useCallback(async () => {
    setError("");
    try {
      setRecords(await request<Memory[]>("/api/learning-memories"));
    } catch {
      setError("暂时无法读取学习记录。");
    }
  }, [request]);

  useEffect(() => {
    if (open) void load();
  }, [open, revision, load]);

  async function change(record: Memory, method: "PATCH" | "DELETE", event?: FormEvent) {
    event?.preventDefault();
    setError("");
    setBusy(true);
    try {
      await request(`/api/learning-memories/${record.memory_id}`,
        method === "PATCH" ? { summary: summary.trim(), version: record.version } : undefined, method);
      setEditing(null);
      await load();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "更新未完成。");
    } finally {
      setBusy(false);
    }
  }

  if (!enabled) return null;
  return <details className="learning-memories" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>已确认的学习记录</summary>
    {error && <p role="alert">{error}</p>}
    {records?.length === 0 && <p>还没有已确认的记录。</p>}
    {records?.map((record) => <div className="turn" key={record.memory_id}>
      {editing === record.memory_id ? <form onSubmit={(event) => void change(record, "PATCH", event)}>
        <textarea aria-label="修改复习要点" value={summary} maxLength={300} required
          onChange={(event) => setSummary(event.target.value)} />
        <button disabled={busy || !summary.trim()}>保存</button>
      </form> : <>
        <p>{record.summary}</p>
        <div className="actions"><button className="secondary" disabled={busy} onClick={() => {
          setSummary(record.summary);
          setEditing(record.memory_id);
        }}>修改</button>
        <button className="secondary" disabled={busy} onClick={() => void change(record, "DELETE")}>删除</button></div>
      </>}
    </div>)}
  </details>;
}
