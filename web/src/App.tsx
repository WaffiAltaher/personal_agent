import { FormEvent, useEffect, useState } from "react";
import { ApiError, loggedIn, login, logout } from "./api";
import { ConversationList, NewConversation, OpenConversation } from "./Conversations";

type View = "loading" | "login" | "shell";

export default function App() {
  const [view, setView] = useState<View>("loading");

  useEffect(() => {
    loggedIn()
      .then((yes) => setView(yes ? "shell" : "login"))
      .catch(() => setView("login"));
  }, []);

  if (view === "loading") return null;
  if (view === "login") return <Login onLoggedIn={() => setView("shell")} />;
  return <Shell onLoggedOut={() => setView("login")} />;
}

function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(password);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit}>
        <h1>Personal agent</h1>
        <label>
          Password
          <input type="password" autoFocus autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" disabled={busy || !password}>Log in</button>
        {error && <p role="alert" className="error">{error}</p>}
      </form>
    </main>
  );
}

function Shell({ onLoggedOut }: { onLoggedOut: () => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [listKey, setListKey] = useState(0);
  const refreshList = () => setListKey((key) => key + 1);

  async function signOut() {
    try {
      await logout();
    } finally {
      onLoggedOut();
    }
  }

  return (
    <div className="shell">
      <header>
        <span>Personal agent</span>
        <button onClick={signOut}>Log out</button>
      </header>
      <div className="body">
        <nav className="conversations" aria-label="Conversations">
          <button className="new" onClick={() => setSelected(null)}>New Conversation</button>
          <ConversationList selected={selected} onSelect={setSelected} refreshKey={listKey} />
        </nav>
        <main className="conversation">
          {selected
            ? <OpenConversation key={selected} threadId={selected} onTurnEnded={refreshList} />
            : <NewConversation onStarted={(threadId) => { setSelected(threadId); refreshList(); }} />}
        </main>
      </div>
    </div>
  );
}
