import { FormEvent, useEffect, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ApiError, ConversationRow, LiveConversation, LiveEvent, PendingApproval, ToolStep, Transcript, Turn,
  applyEvent, askFollowUp, conversationEvents, listConversations, startConversation,
} from "./api";
import type { LoginRow } from "./api";

// `refreshKey` changes when the list may have changed (a turn started or ended): it loads again.
export function ConversationList({ selected, onSelect, refreshKey = 0 }:
                                 { selected: string | null; onSelect: (id: string) => void; refreshKey?: number }) {
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listConversations().then(setRows).catch((err) => setError(err.message));
  }, [refreshKey]);

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
      {turn.stopped && <p role="alert" className="error">{turn.stopped}</p>}
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

// The live state of one Conversation: its event stream applied to the `state` it starts with.
// `onEvent` sees each event too (the shell refreshes the list when a turn ends).
export function useConversation(threadId: string, onEvent?: (event: LiveEvent) => void) {
  const [live, setLive] = useState<LiveConversation | null>(null);
  const [disconnected, setDisconnected] = useState(false);

  useEffect(() => {
    setLive(null);
    setDisconnected(false);
    return conversationEvents(threadId, (event) => {
      setDisconnected(false);
      setLive((current) => applyEvent(current, event));
      onEvent?.(event);
    }, () => setDisconnected(true));
    // onEvent is a callback from the parent: a new one must not reopen the stream.
  }, [threadId]);

  return { live, disconnected };
}

// The message box. Disabled while it sends; `disabled` (a turn runs) keeps it closed.
export function QuestionBox({ placeholder, disabled = false, onAsk }:
                            { placeholder: string; disabled?: boolean; onAsk: (question: string) => Promise<void> }) {
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setSending(true);
    setError(null);
    try {
      await onAsk(text);
      setQuestion("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="question-box" onSubmit={submit}>
      <textarea aria-label="Question" placeholder={placeholder} value={question} disabled={disabled || sending}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    e.currentTarget.form?.requestSubmit();
                  }
                }} />
      <button type="submit" disabled={disabled || sending || !question.trim()}>Send</button>
      {error && <p role="alert" className="error">{error}</p>}
    </form>
  );
}

export function OpenConversation({ threadId, onTurnEnded, onLoginStatus }:
  { threadId: string; onTurnEnded?: () => void; onLoginStatus?: (logins: LoginRow[]) => void }) {
  const { live, disconnected } = useConversation(threadId, (event) => {
    if (event.name === "turn_ended") onTurnEnded?.();
    if (event.name === "login_status") onLoginStatus?.(event.data.logins);
  });

  if (live === null) return disconnected ? <p role="alert" className="error">Cannot open this Conversation.</p> : null;
  const running = live.status === "running";
  return (
    <div>
      <TranscriptView transcript={live.transcript} />
      {running && <p className="muted" aria-live="polite">Working…</p>}
      {disconnected && <p role="alert" className="error">Connection lost. Reconnecting…</p>}
      <QuestionBox placeholder="Ask a follow-up" disabled={running}
                   onAsk={async (question) => { await askFollowUp(threadId, question); }} />
    </div>
  );
}

// A new Conversation: its first question starts it (a new thread on the server).
export function NewConversation({ onStarted }: { onStarted: (threadId: string) => void }) {
  return (
    <QuestionBox placeholder="Ask a question to start a Conversation"
                 onAsk={async (question) => onStarted((await startConversation(question)).thread_id)} />
  );
}
