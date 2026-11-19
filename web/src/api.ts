// Calls to the FastAPI server. The session is an HttpOnly cookie the browser sends itself;
// state-changing requests carry the page's Origin, which the server checks.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export async function loggedIn(): Promise<boolean> {
  try {
    await request("GET", "/api/session");
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return false;
    throw error;
  }
}

export const login = (password: string) => request("POST", "/api/login", { password });
export const logout = () => request("POST", "/api/logout");

// The shapes of the Conversation endpoints (src/agent/web/conversations.py). A transcript is also
// the shape live events update.
export type ConversationRow = { thread_id: string; title: string; updated_at: number };
export type ToolStep = { id: string; name: string; args: unknown; result: string | null; error: boolean };
// `stopped` is the message of a turn that ended by a failure, while this server remembers it.
export type Turn = { question: string; steps: ToolStep[]; answer: string | null; stopped?: string };
export type PendingApproval = {
  interrupt_id: string;
  message: string;
  actions: string;
  tool_call_ids: string[];
  instructions?: string;
};
export type Transcript = { thread_id: string; turns: Turn[]; pending: PendingApproval | null };

export const listConversations = () => request<ConversationRow[]>("GET", "/api/conversations");
export const openConversation = (threadId: string) =>
  request<Transcript>("GET", `/api/conversations/${encodeURIComponent(threadId)}`);

// The login status strip (src/agent/web/logins.py): rechecked at the start of every turn; a change
// arrives as a `login_status` event on every open Conversation's stream.
export type LoginRow = { name: string; alive: boolean; command: string; detail: string | null };
export const loginStatus = () => request<LoginRow[]>("GET", "/api/logins");

export const startConversation = (question: string) =>
  request<{ thread_id: string }>("POST", "/api/conversations", { question });
export const askFollowUp = (threadId: string, question: string) =>
  request<{ ok: boolean }>("POST", `/api/conversations/${encodeURIComponent(threadId)}/turns`, { question });
export type Decision = "approve" | "reject";
// Refused (409) when `interruptId` is no longer the pending one, e.g. another tab answered it.
export const decideApproval = (threadId: string, interruptId: string, decision: Decision) =>
  request<{ ok: boolean }>("POST", `/api/conversations/${encodeURIComponent(threadId)}/approval`,
                           { interrupt_id: interruptId, decision });
export const stopTurn = (threadId: string) =>
  request<{ ok: boolean }>("POST", `/api/conversations/${encodeURIComponent(threadId)}/stop`);

// Live events of one Conversation (src/agent/web/turns.py). Every tab on a thread gets the same
// events; the first is always `state`, the thread's current status and transcript.
export type ThreadStatus = "idle" | "running" | "awaiting_approval";
export type TurnOutcome = "answered" | "approval" | "failed" | "error" | "cancelled";
export type LiveEvent =
  | { name: "state"; data: { status: ThreadStatus; transcript: Transcript } }
  | { name: "turn_started"; data: { question: string } }
  | { name: "step_started"; data: { step: ToolStep } }
  | { name: "step_finished"; data: { step: ToolStep } }
  | { name: "approval_pending"; data: { pending: PendingApproval } }
  | { name: "approval_decided"; data: { interrupt_id: string; decision: Decision } }
  | { name: "answer"; data: { text: string } }
  | { name: "turn_ended"; data: { status: ThreadStatus; outcome: TurnOutcome; message: string | null } }
  | { name: "login_status"; data: { logins: LoginRow[] } };
export const LIVE_EVENT_NAMES: LiveEvent["name"][] = [
  "state", "turn_started", "step_started", "step_finished", "approval_pending", "approval_decided", "answer",
  "turn_ended", "login_status",
];

export type LiveConversation = { status: ThreadStatus; transcript: Transcript };

// The same patch the server applies to its copy (turns.apply_event), so every tab agrees.
export function applyEvent(live: LiveConversation | null, event: LiveEvent): LiveConversation | null {
  if (event.name === "state") return event.data;
  if (live === null) return null;
  const turns = [...live.transcript.turns];
  const transcript: Transcript = { ...live.transcript, turns };
  const last = turns.length ? { ...turns[turns.length - 1], steps: [...turns[turns.length - 1].steps] } : null;
  if (last) turns[turns.length - 1] = last;
  let status = live.status;
  switch (event.name) {
    case "turn_started":
      turns.push({ question: event.data.question, steps: [], answer: null });
      transcript.pending = null;
      status = "running";
      break;
    case "step_started":
      last?.steps.push(event.data.step);
      break;
    case "step_finished": {
      if (!last) break;
      const at = last.steps.findIndex((s) => s.id === event.data.step.id);
      if (at < 0) last.steps.push(event.data.step);
      else last.steps[at] = event.data.step;
      break;
    }
    case "approval_pending":
      transcript.pending = event.data.pending;
      break;
    case "approval_decided":
      transcript.pending = null;
      status = "running";
      break;
    case "answer":
      if (last) last.answer = event.data.text;
      break;
    case "turn_ended":
      status = event.data.status;
      if (last && event.data.message) last.stopped = event.data.message;
      break;
  }
  return { status, transcript };
}

// Opens the thread's event stream; returns the function that closes it. EventSource reconnects by
// itself after a drop, and the server then starts again with `state`.
export function conversationEvents(threadId: string, onEvent: (event: LiveEvent) => void,
                                   onError: () => void): () => void {
  const source = new EventSource(`/api/conversations/${encodeURIComponent(threadId)}/events`);
  for (const name of LIVE_EVENT_NAMES) {
    source.addEventListener(name, (message) => {
      onEvent({ name, data: JSON.parse((message as MessageEvent).data) } as LiveEvent);
    });
  }
  source.onerror = onError;
  return () => source.close();
}
