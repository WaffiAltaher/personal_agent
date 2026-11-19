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
