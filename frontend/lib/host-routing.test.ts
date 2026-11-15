import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";
import { isAppRoutePath } from "./host-routing";

describe.each([
  { label: "Tutores", path: "/tutores", query: "busca=Cristiane", similarPath: "/tutores-outros" },
  { label: "Gestão", path: "/gestao", query: "regiao=Norte", similarPath: "/gestao-empresarial" },
])("roteamento de $label para o domínio do aplicativo", ({ path, query, similarPath }) => {
  it("reconhece a tela e suas rotas descendentes sem capturar nomes semelhantes", () => {
    expect(isAppRoutePath(path)).toBe(true);
    expect(isAppRoutePath(`${path}/`)).toBe(true);
    expect(isAppRoutePath(`${path}/detalhes`)).toBe(true);
    expect(isAppRoutePath(similarPath)).toBe(false);
  });

  it.each([
    ["fortcordis.com.br", "app.fortcordis.com.br"],
    ["www.fortcordis.com", "app.fortcordis.com.br"],
    ["stage.fortcordis.com.br", "app.stage.fortcordis.com.br"],
  ])("redireciona %s preservando caminho e filtros", async (host, appHost) => {
    const request = new NextRequest(`https://${host}${path}?${query}`, { headers: { host } });
    const response = await middleware(request);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`https://${appHost}${path}?${query}`);
  });

  it("exige login no domínio do aplicativo sem entrar em loop com o institucional", async () => {
    const host = "app.fortcordis.com.br";
    const response = await middleware(new NextRequest(`https://${host}${path}`, { headers: { host } }));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`https://${host}/?next=${encodeURIComponent(path)}`);
  });
});
