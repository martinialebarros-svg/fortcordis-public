import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";
import { isAppRoutePath } from "./host-routing";

describe("roteamento de tutores para o domínio do aplicativo", () => {
  it("protege a tela de tutores e redireciona o domínio institucional", async () => {
    expect(isAppRoutePath("/tutores")).toBe(true);
    expect(isAppRoutePath("/tutores-outros")).toBe(false);
    const response = await middleware(new NextRequest("https://fortcordis.com.br/tutores", { headers: { host: "fortcordis.com.br" } }));
    expect(response.headers.get("location")).toBe("https://app.fortcordis.com.br/tutores");
    const login = await middleware(new NextRequest("https://app.fortcordis.com.br/tutores", { headers: { host: "app.fortcordis.com.br" } }));
    expect(login.headers.get("location")).toBe("https://app.fortcordis.com.br/?next=%2Ftutores");
  });
  it("reconhece a tela e suas rotas descendentes sem capturar nomes semelhantes", () => {
    expect(isAppRoutePath("/tutores")).toBe(true);
    expect(isAppRoutePath("/tutores/")).toBe(true);
    expect(isAppRoutePath("/tutores/detalhes")).toBe(true);
    expect(isAppRoutePath("/tutores-outros")).toBe(false);
  });

  it.each([
    ["fortcordis.com.br", "app.fortcordis.com.br"],
    ["www.fortcordis.com", "app.fortcordis.com.br"],
    ["stage.fortcordis.com.br", "app.stage.fortcordis.com.br"],
  ])("redireciona %s preservando caminho e filtros", async (host, appHost) => {
    const request = new NextRequest(`https://${host}/tutores?busca=Cristiane`, { headers: { host } });
    const response = await middleware(request);
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`https://${appHost}/tutores?busca=Cristiane`);
  });

  it("exige login no domínio do aplicativo sem entrar em loop com o institucional", async () => {
    const host = "app.fortcordis.com.br";
    const response = await middleware(new NextRequest(`https://${host}/tutores`, { headers: { host } }));
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(`https://${host}/?next=%2Ftutores`);
  });
});
