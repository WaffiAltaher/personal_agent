import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ConversationRow, PendingApproval, ToolStep, Transcript, Turn, listConversations, openConversation,
} from "./api";

export function ConversationList({ selected, onSelect }: { selected: string | null; onSelect: (id: string) => void }) {
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listConversations().then(setRows).catch((err) => setError(err.message));
  }, []);

  if (error) return <p role="alert" className="error">{error}</p>;
  if (rows === null) return null;
  if (rows.length === 0) return <p className="muted">No Conversations yet.</p>;
  return (
    <ul>
      {rows.map((row) => (
        <li key={row.thread_id}>
          <button className={row.thread_id === selected ? "row selected" : "row"}
                  onClick={() => onSelect(row.thread_id)}>
            <span className="title">{row.title}</span>
            <span className="date">{new Date(row.updated_at * 1000).toLocaleString()}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// Raw HTML in the text is never rendered: react-markdown shows it as text unless a plugin allows it.
export function AnswerMarkdown({ text }: { text: string }) {
  return <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>;
}

export function StepView({ step }: { step: ToolStep }) {
  const status = step.result === null ? "running" : step.error ? "failed" : "done";
  return (
    <details className={`step ${status}`}>
      <summary>{step.name} <span className="muted">({status})</span></summary>
      <pre>{JSON.stringify(step.args, null, 2)}</pre>
      {step.result !== null && <pre>{step.result}</pre>}
    </details>
  );
}

export function TurnView({ turn }: { turn: Turn }) {
  return (
    <section className="turn">
      <p className="question">{turn.question}</p>
      {turn.steps.map((step) => <StepView key={step.id} step={step} />)}
      {turn.answer !== null && <div className="answer"><AnswerMarkdown text={turn.answer} /></div>}
    </section>
  );
}

// Read-only for now: ticket 04 adds the Approve and Reject buttons.
export function ApprovalCard({ pending }: { pending: PendingApproval }) {
  return (
    <aside className="approval" aria-label="Approval">
      <p>{pending.message}</p>
      <pre>{pending.actions}</pre>
      {pending.instructions && <p className="muted">{pending.instructions}</p>}
    </aside>
  );
}

export function TranscriptView({ transcript }: { transcript: Transcript }) {
  return (
    <div>
      {transcript.turns.map((turn, index) => <TurnView key={index} turn={turn} />)}
      {transcript.pending && <ApprovalCard pending={transcript.pending} />}
    </div>
  );
}

export function OpenConversation({ threadId }: { threadId: string }) {
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTranscript(null);
    setError(null);
    openConversation(threadId).then(setTranscript).catch((err) => setError(err.message));
  }, [threadId]);

  if (error) return <p role="alert" className="error">{error}</p>;
  if (transcript === null) return null;
  return <TranscriptView transcript={transcript} />;
}
