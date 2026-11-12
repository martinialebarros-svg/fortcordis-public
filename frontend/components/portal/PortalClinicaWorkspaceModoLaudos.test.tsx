import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import PortalClinicaWorkspace from "./PortalClinicaWorkspace";
import { portalSessionHasClinicRead, type PortalSessionResponse } from "@/lib/portal-api";

const sessaoBase: PortalSessionResponse = {
  access_token: "token",
  token_type: "bearer",
  expires_at: "2026-12-31T23:59:00",
  actor_type: "clinica",
  actor_id: 8,
  clinica_id: 8,
  paciente_id: null,
  account_id: null,
  auth_method: "device_trust",
  trusted_session_expires_at: "2026-11-17T15:02:00",
  scope: ["exam:read", "exam:download"],
  message: null,
};

const sessaoComSenha: PortalSessionResponse = {
  ...sessaoBase,
  auth_method: "password",
  account_id: 3,
  scope: ["clinic:read", "exam:read", "exam:download"],
};

const listaVazia = {
  items: [],
  total: 0,
  operational_summary: null,
  operational_pendentes: [],
  operational_recentes: [],
};

const json = (data: unknown) =>
  new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function montar(session: PortalSessionResponse, onPedirLoginPorSenha?: () => void) {
  vi.stubGlobal("fetch", vi.fn(async () => json(listaVazia)));
  return render(
    <PortalClinicaWorkspace
      mode="standalone"
      initialSession={session}
      onPedirLoginPorSenha={onPedirLoginPorSenha}
    />,
  );
}

describe("portal da clinica em modo laudos", () => {
  it("esconde agenda e financeiro na sessao sem clinic:read", async () => {
    montar(sessaoBase);

    expect(await screen.findByRole("tab", { name: "Laudos" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Visão geral" })).toBeInTheDocument();
    // Ausentes por completo, e nao desabilitadas: desabilitado sugeriria que
    // basta insistir.
    expect(screen.queryByRole("tab", { name: "Agenda" })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Financeiro" })).not.toBeInTheDocument();
  });

  it("mostra todas as abas na sessao com senha", async () => {
    montar(sessaoComSenha);

    expect(await screen.findByRole("tab", { name: "Agenda" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Financeiro" })).toBeInTheDocument();
  });

  it("identifica o modo laudos no cabecalho e oferece sair do computador", async () => {
    montar(sessaoBase);

    expect(await screen.findByText("Conectado neste computador")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sair deste computador/i })).toBeInTheDocument();
  });

  it("nao oferece sair do computador na sessao com senha", async () => {
    montar(sessaoComSenha);

    expect(await screen.findByText("Sessão ativa")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sair deste computador/i })).not.toBeInTheDocument();
  });

  it("oferece entrar com senha sem passar por sair do computador (RF-019)", async () => {
    const pedir = vi.fn();
    montar(sessaoBase, pedir);

    const entrar = await screen.findByRole("button", {
      name: /entrar com senha para ver financeiro e agenda/i,
    });
    fireEvent.click(entrar);

    // O caminho para o financeiro nao pode passar por encerrar a confianca: isso
    // tiraria a recepcao do ar so porque o gestor quis ver um numero.
    expect(pedir).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /sair deste computador/i })).toBeInTheDocument();
  });

  it("nao promete o login por senha quando nao ha para onde levar", async () => {
    montar(sessaoBase);

    expect(await screen.findByText("Conectado neste computador")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /entrar com senha para ver financeiro e agenda/i }),
    ).not.toBeInTheDocument();
  });

  it("nao oferece entrar com senha em quem ja entrou com senha", async () => {
    montar(sessaoComSenha, vi.fn());

    expect(await screen.findByText("Sessão ativa")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /entrar com senha para ver financeiro e agenda/i }),
    ).not.toBeInTheDocument();
  });

  it("portalSessionHasClinicRead distingue os dois modos", () => {
    expect(portalSessionHasClinicRead(sessaoComSenha)).toBe(true);
    expect(portalSessionHasClinicRead(sessaoBase)).toBe(false);
    expect(portalSessionHasClinicRead(null)).toBe(false);
  });
});
