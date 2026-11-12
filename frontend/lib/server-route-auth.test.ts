// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { protectRoute } from "./server-route-auth";
import { requiresLogin, safeLoginDestination } from "./auth-routes";
import { middleware } from "../middleware";

afterEach(() => vi.unstubAllGlobals());
const req = (path = "/agenda", cookie = "fortcordis_session=token") => new NextRequest(`https://app.fortcordis.com.br${path}`, { headers: { cookie } });

describe("server authentication boundary", () => {
  it("protects all internal route families and descendants", async () => {
    const paths = ["agenda", "assistente-ia", "atendimento", "clinicas", "configuracoes", "dashboard", "financeiro", "fiscal", "laudos", "logistica", "pacientes", "referencias-eco", "relatorios", "servicos", "ultrassonografia-abdominal", "visualizador-vivid-iq", "whatsapp-stage"];
    for (const path of paths) {
      expect(requiresLogin(`/${path}`)).toBe(true);
      expect(requiresLogin(`/${path}/42`)).toBe(true);
      const response = await middleware(req(`/${path}`, ""));
      expect(response.status).toBe(307);
      expect(new URL(response.headers.get("location")!, "https://app.fortcordis.com.br").searchParams.get("next")).toBe(`/${path}`);
    }
  });

  it("keeps public and token-authenticated flows outside the staff gate", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    for (const path of ["/", "/privacidade", "/termos", "/exclusao-de-dados", "/area-pacientes", "/clinica-parceira/ativar/token", "/veterinario-parceiro", "/laudo/token", "/agenda/formalizar/token", "/api/v1/auth/login", "/agendado"]) {
      expect(requiresLogin(path)).toBe(false);
      expect((await middleware(req(path, ""))).status).toBe(200);
    }
    expect(upstream).not.toHaveBeenCalled();
  });

  it("validates the session rather than trusting cookie presence", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    const response = await protectRoute(req("/laudos/42?aba=medidas"));
    expect(response.status).toBe(307);
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(new URL(response.headers.get("location")!, "https://app.fortcordis.com.br").searchParams.get("next")).toBe("/laudos/42?aba=medidas");
  });

  it("keeps login on the browser origin when Next exposes an internal proxy URL", async () => {
    const request = new NextRequest("http://localhost:3001/fiscal?aba=rotina", {
      headers: { host: "app.stage.fortcordis.com.br", "x-forwarded-proto": "https" },
    });
    const response = await protectRoute(request);
    const location = response.headers.get("location")!;
    expect(location).toBe("https://app.stage.fortcordis.com.br/?next=%2Ffiscal%3Faba%3Drotina");
    expect(new URL(location, "https://app.stage.fortcordis.com.br").origin).toBe("https://app.stage.fortcordis.com.br");
  });

  it("rejects unknown or malformed Host values instead of redirecting off site", async () => {
    for (const host of ["evil.invalid", "app.stage.fortcordis.com.br@evil.invalid", "app.stage.fortcordis.com.br/path"]) {
      const response = await protectRoute(new NextRequest("http://localhost:3001/dashboard", { headers: { host } }));
      expect(response.status).toBe(503);
      expect(response.headers.get("location")).toBeNull();
    }
  });

  it("refreshes expired sessions and forwards all rotated cookies", async () => {
    const headers = new Headers();
    headers.append("set-cookie", "fortcordis_session=new-access; Path=/; HttpOnly; SameSite=Lax");
    headers.append("set-cookie", "fortcordis_refresh=new-refresh; Path=/; HttpOnly; SameSite=Lax");
    headers.append("set-cookie", "fortcordis_csrf=new-csrf; Path=/; SameSite=Lax");
    const upstream = vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response("{}", { headers }));
    vi.stubGlobal("fetch", upstream);
    const response = await protectRoute(req("/agenda", "fortcordis_session=old; fortcordis_refresh=refresh; fortcordis_csrf=csrf"));
    expect(response.status).toBe(200);
    expect(upstream.mock.calls[1][0].pathname).toBe("/api/v1/auth/refresh");
    expect(upstream.mock.calls[1][1].headers["x-csrf-token"]).toBe("csrf");
    expect(response.headers.getSetCookie()).toHaveLength(3);
    expect(response.headers.get("x-middleware-request-cookie")).toContain("fortcordis_session=new-access");
  });

  it("fails closed during upstream errors without clearing cookies", async () => {
    for (const status of [403, 500, 503]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status })));
      const response = await protectRoute(req());
      expect(response.status).toBe(status === 403 ? 403 : 503);
      expect(response.headers.getSetCookie()).toEqual([]);
    }
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("timeout")));
    expect((await protectRoute(req())).status).toBe(503);
  });

  it("preserves institutional host routing before checking application login", async () => {
    const response = await middleware(new NextRequest("https://fortcordis.com.br/fiscal", { headers: { host: "fortcordis.com.br" } }));
    expect(response.headers.get("location")).toBe("https://app.fortcordis.com.br/fiscal");
  });

  it("rejects external or misleading login destinations", () => {
    for (const value of ["https://evil.invalid", "//evil.invalid/agenda", "/\\evil.invalid", "/agenda\r\nLocation:evil", "/laudo/token", "/", "/agendado"]) {
      expect(safeLoginDestination(value)).toBe("/dashboard");
    }
    expect(safeLoginDestination("/laudos/42/editar?aba=medidas")).toBe("/laudos/42/editar?aba=medidas");
  });
});
