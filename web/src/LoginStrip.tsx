import { useCallback, useEffect, useState } from "react";
import { LoginRow, loginStatus } from "./api";

// The strip's rows: loaded on mount and by `refresh` (after a turn); `set` takes a `login_status`
// event's rows.
export function useLoginStatus(): [LoginRow[], (rows: LoginRow[]) => void, () => void] {
  const [rows, setRows] = useState<LoginRow[]>([]);
  const refresh = useCallback(() => {
    loginStatus().then(setRows).catch(() => {});
  }, []);
  useEffect(refresh, [refresh]);
  return [rows, setRows, refresh];
}

// Each integration alive or dead; a dead one names the command that logs in again.
export function LoginStrip({ logins }: { logins: LoginRow[] }) {
  if (!logins.length) return null;
  return (
    <ul className="login-strip" aria-label="Logins">
      {logins.map((row) => (
        <li key={row.name} className={row.alive ? "alive" : "dead"} title={row.detail ?? undefined}>
          <span className="dot" aria-hidden="true" />
          {row.name}: {row.alive ? "alive" : <>dead, run <code>{row.command}</code></>}
        </li>
      ))}
    </ul>
  );
}
