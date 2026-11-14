import { FormEvent, useEffect, useState } from "react";

type Cell = number | string | null;
type DataTable = { name: string; columns: string[]; rows: Cell[][] };
type Exercise = { id: string; context: string; tables: DataTable[]; sql: string; options: string[] };
type Transfer = { available: boolean; exercise: Exercise | null;
  feedback: { selected_option: number; correct: boolean; correct_option: number; text: string;
    result_columns: string[] | null; result_rows: Cell[][] | null } | null };
type Request = <T>(path: string, body?: unknown) => Promise<T>;

function ExerciseTable({ name, columns, rows }: DataTable) {
  return <div className="transfer-table">
    <table>
      <caption>{name}</caption>
      <thead><tr>{columns.map((column, index) => <th key={index} scope="col">{column}</th>)}</tr></thead>
      <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>
        {row.map((cell, index) => <td key={index}>{cell ?? "NULL"}</td>)}
      </tr>)}</tbody>
    </table>
    {rows.length === 0 && <p>查询没有返回记录。</p>}
  </div>;
}

export default function TransferExercise({ decisionId, request, readOnly }:
  { decisionId: string; request: Request; readOnly: boolean }) {
  const path = `/api/practice/${decisionId}/transfer`;
  const [state, setState] = useState<Transfer | null>(null);
  const [choice, setChoice] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    request<Transfer>(path).then((result) => { if (active) setState(result); })
      .catch(() => { if (active) setError("暂时无法读取迁移练习。"); });
    return () => { active = false; };
  }, [path, request]);

  async function perform(route: string, body: object) {
    setBusy(true);
    setError("");
    try {
      setState(await request<Transfer>(route, body));
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "迁移练习暂时不可用。");
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!readOnly && choice !== null) void perform(`${path}/answer`, { option: choice });
  }

  if (state?.available === false || (!state && !error) || (readOnly && !state?.feedback)) return null;
  const item = state?.exercise;
  const feedback = state?.feedback;
  return <section className="diagnosis" aria-label="迁移练习">
    <h3>迁移练习</h3>
    {error && <p className="error" role="alert">{error}</p>}
    {!item ? <button type="button" className="secondary" disabled={busy} onClick={() => void perform(path, {})}>
      {busy ? "正在生成练习…" : "换一组数据练练"}
    </button> : <>
      {!feedback && <p>先独立判断，再提交查看解析。</p>}
      <p>{item.context}</p>
      <div className="diagnosis-results">
        {item.tables.map((table) => <ExerciseTable key={table.name} {...table} />)}
      </div>
      <pre>{item.sql}</pre>
      <form onSubmit={submit}>
        <fieldset disabled={readOnly || busy || !!feedback}>
          <legend>选择查询结果</legend>
          {item.options.map((option, index) => <label className="option" key={option}>
            <input type="radio" name={`transfer-${item.id}`} checked={(feedback?.selected_option ?? choice) === index}
              onChange={() => setChoice(index)} />{option}
          </label>)}
        </fieldset>
        {!feedback && <button type="submit" disabled={busy || choice === null}>提交迁移题</button>}
      </form>
      {feedback && <p className="feedback" role="status">
        {feedback.correct ? "答对了。" : `正确结果是${item.options[feedback.correct_option]}。`}{feedback.text}
      </p>}
      {feedback?.result_columns && feedback.result_rows && <div className="diagnosis-results">
        <ExerciseTable name="SQLite 查询结果" columns={feedback.result_columns} rows={feedback.result_rows} />
      </div>}
    </>}
  </section>;
}
