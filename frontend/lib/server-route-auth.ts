import { NextRequest, NextResponse } from "next/server";

const sessionCookie = process.env.AUTH_COOKIE_NAME || "fortcordis_session";
const refreshCookie = process.env.SUPABASE_REFRESH_COOKIE_NAME || "fortcordis_refresh";
const csrfCookie = process.env.CSRF_COOKIE_NAME || "fortcordis_csrf";

function privateResponse(response: NextResponse): NextResponse {
  response.headers.set("Cache-Control", "private, no-store");
  response.headers.set("Pragma", "no-cache");
  return response;
}

function loginRedirect(request: NextRequest): NextResponse {
  // Next may expose its internal localhost origin behind the reverse proxy.
  // Next requires absolute redirect URLs, so rebuild the public origin from
  // the proxy's Host header and only accept known application/dev hosts.
  try {
    const url = new URL(`http://${request.headers.get("host") || request.nextUrl.host}`);
    const publicHost = ["app.fortcordis.com.br", "app.stage.fortcordis.com.br"].includes(url.hostname);
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if ((!publicHost && !localHost) || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
      throw new Error("Invalid application host");
    }
    url.protocol = publicHost ? "https:" : request.nextUrl.protocol;
    url.searchParams.set("next", `${request.nextUrl.pathname}${request.nextUrl.search}`);
    return privateResponse(NextResponse.redirect(url));
  } catch {
    return privateResponse(new NextResponse("Host de aplicativo invalido.", { status: 503 }));
  }
}

export async function protectRoute(request: NextRequest): Promise<NextResponse> {
  if (!request.cookies.has(sessionCookie) && !request.cookies.has(refreshCookie)) {
    return loginRedirect(request);
  }
  // Use a configured internal upstream, never a user-supplied Host header.
  const backend = process.env.API_BACKEND_URL || "http://127.0.0.1:8000";
  const cookie = [sessionCookie, refreshCookie, csrfCookie]
    .map((name) => request.cookies.get(name))
    .filter((item): item is { name: string; value: string } => Boolean(item))
    .map(({ name, value }) => `${name}=${value}`).join("; ");
  const headers: Record<string, string> = { cookie };
  const csrf = request.cookies.get(csrfCookie)?.value;
  if (csrf) headers[process.env.CSRF_HEADER_NAME || "x-csrf-token"] = csrf;
  try {
    const call = (path: string, method = "GET") => fetch(new URL(`/api/v1/auth/${path}`, backend), {
      method, headers, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(8000),
    });
    let auth = await call("session");
    if (auth.status === 401 && request.cookies.has(refreshCookie)) {
      auth = await call("refresh", "POST");
    }
    if (auth.status === 401) return loginRedirect(request);
    if (auth.status === 403) {
      return privateResponse(new NextResponse("Acesso negado.", { status: 403 }));
    }
    if (!auth.ok) throw new Error("Auth unavailable");
    // Propagate rotations to both this request and the browser. Preserve every
    // Set-Cookie header independently (Expires may contain commas).
    const setCookies = auth.headers.getSetCookie();
    for (const value of setCookies) {
      const pair = value.split(";", 1)[0];
      const index = pair.indexOf("=");
      const name = pair.slice(0, index);
      if (index > 0 && [sessionCookie, refreshCookie, csrfCookie].includes(name)) {
        request.cookies.set(name, pair.slice(index + 1));
      }
    }
    const response = privateResponse(NextResponse.next({ request: { headers: request.headers } }));
    for (const value of setCookies) response.headers.append("Set-Cookie", value);
    return response;
  } catch {
    // An outage must not render a private page or erase a valid session.
    const response = new NextResponse("Nao foi possivel verificar a sessao. Tente novamente.", { status: 503 });
    response.headers.set("Retry-After", "5");
    return privateResponse(response);
  }
}
