import axios from "axios";

export type BrowserSession = {
  id?: number; user_id: number; nome: string; email: string; papeis: unknown[];
  access_token: string; provider: "legacy" | "supabase"; expires_at: number | null;
};

export function rememberSession(session: BrowserSession): BrowserSession {
  // Compatibility for existing bearer consumers. The refresh token is only
  // stored in an HttpOnly server cookie, never in JavaScript or localStorage.
  localStorage.setItem("token", session.access_token);
  localStorage.setItem("auth_provider", session.provider || "legacy");
  localStorage.setItem("user", JSON.stringify({ ...session, access_token: undefined, id: session.id ?? session.user_id }));
  return session;
}

let refreshInFlight: Promise<BrowserSession> | null = null;

export function refreshBrowserSession(): Promise<BrowserSession> {
  if (!refreshInFlight) {
    const csrf = document.cookie.split(";").map((part) => part.trim())
      .find((part) => part.startsWith("fortcordis_csrf="))?.slice("fortcordis_csrf=".length);
    refreshInFlight = axios.post<BrowserSession>("/api/v1/auth/refresh", null, {
      withCredentials: true, timeout: 15000,
      headers: csrf ? { "x-csrf-token": decodeURIComponent(csrf) } : {},
    }).then(({ data }) => rememberSession(data)).finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

export async function restoreBrowserSession(): Promise<BrowserSession> {
  try {
    const { data } = await axios.get<BrowserSession>("/api/v1/auth/session", { withCredentials: true, timeout: 15000 });
    return rememberSession(data);
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 401) return refreshBrowserSession();
    throw error;
  }
}
