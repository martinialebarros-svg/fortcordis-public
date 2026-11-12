import { act, fireEvent, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildMessageResendRequest,
  reviewedBotResponseId,
  shouldOfferMessageResend,
} from "@/lib/whatsapp-message-retry";
import WhatsAppStagePage from "./page";

vi.mock("../layout-dashboard", () => ({
  default: ({ children }: PropsWithChildren) => <div>{children}</div>,
}));

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function notFoundDomainContextResponse(): Response {
  return jsonResponse({
    normalized_phone: "558500000000",
    resolution: "not_found",
    match_type: null,
    clinicas: [],
    tutores: [],
    pets: [],
    agendamentos: [],
    ordens_servico: [],
  });
}

describe("WhatsAppStagePage", () => {
  it("não oferece reenvio genérico de uma resposta automática com falha", () => {
    expect(shouldOfferMessageResend({
      type: "text", from_me: true, status: "failed",
      metadata: { source: "bot_auto", origem: "bot", resposta_id: "18" },
    })).toBe(false);
  });
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-14T03:00:00.000Z"));
    window.localStorage.setItem("token", "test-token");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it("preserva o fluxo idempotente ao reenviar rascunho revisado do bot", () => {
    const botMessage = {
      body: "Resposta revisada",
      type: "text",
      from_me: true,
      status: "failed",
      metadata: {
        source: "bot_suggest_reviewed",
        origem: "bot",
        resposta_id: "7",
        idempotency_key: "whatsapp-bot-resposta-7",
      },
    };

    expect(reviewedBotResponseId(botMessage)).toBe("7");
    expect(buildMessageResendRequest(botMessage, "3926")).toEqual({
      url: "/api/v1/whatsapp/bot/respostas/7/enviar",
      body: { texto: "Resposta revisada" },
      botReviewed: true,
    });
    expect(shouldOfferMessageResend(botMessage)).toBe(true);
    expect(shouldOfferMessageResend({
      ...botMessage,
      metadata: { ...botMessage.metadata, superseded_by_message_id: "2437" },
    })).toBe(false);
  });

  const routerComEstadoDoBot = (estadoDoBot: Record<string, unknown> | null, messages?: unknown[]) =>
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
      if (url.startsWith("/whatsapp/conversations?")) {
        return jsonResponse({
          data: [{
            id: "3926", wa_phone_number: "558500000000", wa_psid: "558500000000",
            status: "open", subject: "Cliente de teste", last_agent_id: null,
            last_activity_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z",
            last_message_body: "Oi", last_message_at: "2026-08-14T02:26:00.000Z",
            customer_service_window: {
              last_inbound_at: "2026-08-14T02:26:00.000Z",
              expires_at: "2026-08-15T02:26:00.000Z", is_open: true,
            },
          }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
      }
      if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
      if (url.startsWith("/whatsapp/conversations/3926/messages?")) {
        return jsonResponse({
          data: messages ?? [{
            id: "1", conversation_id: "3926", wa_message_id: "wamid.test",
            from_me: false, body: "Oi", type: "text", status: "received",
            created_at: "2026-08-14T02:26:00.000Z",
          }],
          pagination: { page: 1, limit: 50, total: messages?.length ?? 1 },
          customer_service_window: {
            last_inbound_at: "2026-08-14T02:26:00.000Z",
            expires_at: "2026-08-15T02:26:00.000Z", is_open: true,
          },
        });
      }
      if (url.includes("/whatsapp/bot/conversas/")) {
        return jsonResponse(estadoDoBot ?? {
          wa_identity: "558500000000", modo: "suggest", modo_origem: "institucional",
          pausado: false, pausado_ate: null, handoff_motivo: null,
          rascunho_pendente: null, ultima_recusa: null, ultimo_silencio: null,
        });
      }
      if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
      if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });
      throw new Error(`URL inesperada no teste: ${url}`);
    });

  const abrirConversa = async () => {
    render(<WhatsAppStagePage />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
    // O nome aparece em mais de um lugar (lista e cabecalho); a lista e a
    // primeira ocorrencia e e a clicavel.
    const [item] = screen.queryAllByText("Cliente de teste");
    expect(item).toBeTruthy();
    await act(async () => { fireEvent.click(item); });
    for (let i = 0; i < 6; i += 1) {
      await act(async () => { await Promise.resolve(); });
    }
  };

  it.each([
    [{ source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" }, "Presença registrada na agenda."],
    [{ source: "reservation", action: "confirmar", result: "ja_confirmado", status: "Confirmado" }, "Reserva confirmada na agenda."],
  ] as const)("mostra o resultado persistido da agenda abaixo do botão recebido: %j", async (receipt, label) => {
    vi.stubGlobal("fetch", routerComEstadoDoBot(null, [{
      id: "receipt-1", conversation_id: "3926", wa_message_id: "wamid.receipt",
      from_me: false, body: "Confirmar", type: "button", status: "received",
      created_at: "2026-08-14T02:26:00.000Z", metadata: { agenda_receipt: receipt },
    }]));
    await abrirConversa();
    const badge = screen.getByText(label);
    expect(badge).toHaveClass("fc-wa-bot-badge");
    const bubble = badge.closest("article");
    expect(bubble).toHaveClass("fc-wa-bubble-client");
    expect(bubble?.querySelector("p")?.textContent).toBe("Confirmar");
    expect(bubble?.querySelector("p")?.nextElementSibling).toBe(badge);
    expect(bubble).not.toHaveTextContent("Realizado");
  });

  it("mantém botões sem prova da agenda e recibos inválidos como mensagens normais", async () => {
    const button = {
      conversation_id: "3926", from_me: false, body: "Confirmar", type: "button", status: "received",
      created_at: "2026-08-14T02:26:00.000Z",
    };
    vi.stubGlobal("fetch", routerComEstadoDoBot(null, [
      { ...button, id: "unknown", metadata: { button: { payload: "confirmar:1" } } },
      { ...button, id: "missing-source", metadata: { agenda_receipt: { action: "confirmar", result: "confirmado", status: "Confirmado" } } },
      { ...button, id: "wrong-source", metadata: { agenda_receipt: { source: "appointmentReminder", action: "confirmar", result: "confirmado", status: "Confirmado" } } },
      { ...button, id: "failed", metadata: { agenda_receipt: { source: "reservation", action: "confirmar", result: "erro", status: "Confirmado" } } },
      { ...button, id: "realizado", metadata: { agenda_receipt: { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Realizado" } } },
      { ...button, id: "sent", from_me: true, metadata: { agenda_receipt: { source: "reservation", action: "confirmar", result: "confirmado", status: "Confirmado" } } },
    ]));
    await abrirConversa();
    expect(screen.getAllByText("Confirmar")).toHaveLength(6);
    expect(screen.queryByText("Presença registrada na agenda.")).not.toBeInTheDocument();
    expect(screen.queryByText("Reserva confirmada na agenda.")).not.toBeInTheDocument();
  });

  it("mostra solicitação conferida sem apresentar agendamento confirmado", async () => {
    vi.stubGlobal("fetch", routerComEstadoDoBot({
      wa_identity: "558500000000", modo: "auto", modo_origem: "institucional",
      pausado: true, pausado_ate: null, handoff_motivo: "solicitacao_agendamento",
      rascunho_pendente: null, ultima_recusa: null, ultimo_silencio: null,
      solicitacao_agendamento: { status: "encaminhada", resumo: "Paciente: Rex\nTutor: Maria", preferencia_recebida_em: "2026-09-09T12:00:00Z" },
    }));
    await abrirConversa();
    expect(screen.getByText("Solicitação de agendamento")).toBeInTheDocument();
    expect(screen.getByText("Dados conferidos pelo solicitante — validar agenda")).toBeInTheDocument();
    expect(screen.getByText("Nenhum horário reservado. A equipe confirma o agendamento.")).toBeInTheDocument();
  });

  it("mostra na central quando o bot viu e nao respondeu por pausa", async () => {
    // Medido em producao em 2026-08-25: um envio assistido pausou a conversa e
    // as mensagens seguintes do cliente sumiram sem rastro na tela.
    vi.stubGlobal("fetch", routerComEstadoDoBot({
      wa_identity: "558500000000", modo: "suggest", modo_origem: "institucional",
      pausado: true, pausado_ate: "2026-08-15T02:26:00.000Z", handoff_motivo: null,
      rascunho_pendente: null, ultima_recusa: null,
      ultimo_silencio: { resposta_id: 25, motivo: "pausado", criado_em: "2026-08-14T18:26:00.000Z" },
    }));

    await abrirConversa();

    const aviso = screen.getByText(/O bot viu esta mensagem e não respondeu/i);
    expect(aviso.textContent).toMatch(/atendimento automático desta conversa está pausado/i);
    // E informacao, nao tarefa: nada de acao dentro do aviso.
    const caixa = aviso.closest(".fc-wa-bot-silencio");
    expect(caixa).not.toBeNull();
    expect(caixa?.querySelector("button")).toBeNull();
  });

  it("nao renderiza aviso de silencio quando nao ha silencio", async () => {
    vi.stubGlobal("fetch", routerComEstadoDoBot(null));
    await abrirConversa();
    expect(screen.queryByText(/O bot viu esta mensagem e não respondeu/i)).toBeNull();
  });

  it("explica que a mudança de cadastro aguarda nova mensagem sem oferecer reenvio do texto anterior", async () => {
    vi.stubGlobal("fetch", routerComEstadoDoBot({
      wa_identity: "558500000000", modo: "auto", modo_origem: "conversa",
      pausado: false, pausado_ate: null, handoff_motivo: null,
      rascunho_pendente: null, ultima_recusa: null,
      ultimo_silencio: { resposta_id: 26, motivo: "contexto_alterado", criado_em: "2026-08-14T02:26:00.000Z" },
    }));
    await abrirConversa();
    const aviso = screen.getByText(/O bot viu esta mensagem e não respondeu/i);
    expect(aviso).toHaveTextContent("o cadastro usado pelo bot mudou; aguardando uma nova mensagem do cliente");
    expect(aviso.closest(".fc-wa-bot-silencio")?.querySelector("button")).toBeNull();
    expect(screen.queryByText("Rascunho do copiloto")).not.toBeInTheDocument();
  });

  it("atualiza silenciosamente o status da mensagem selecionada", async () => {
    let messagesRequestCount = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });

        if (url.startsWith("/whatsapp/conversations?")) {
          return jsonResponse({
            data: [
              {
                id: "3926",
                wa_phone_number: "558500000000",
                wa_psid: "558500000000",
                status: "open",
                subject: "Cliente de teste",
                last_agent_id: null,
                last_activity_at: "2026-08-14T02:26:00.000Z",
                created_at: "2026-08-14T02:26:00.000Z",
                updated_at: "2026-08-14T02:26:00.000Z",
                last_message_body: "Teste recebido com sucesso pela Fort Cordis.",
                last_message_at: "2026-08-14T02:26:00.000Z",
                customer_service_window: {
                  last_inbound_at: "2026-08-14T02:26:00.000Z",
                  expires_at: "2026-08-15T02:26:00.000Z",
                  is_open: true,
                },
              },
            ],
            pagination: { page: 1, limit: 20, total: 1 },
          });
        }

        if (url === "/whatsapp/agents") {
          return jsonResponse({ data: [] });
        }

        if (url.startsWith("/whatsapp/conversations/3926/messages?")) {
          messagesRequestCount += 1;
          return jsonResponse({
            data: [
              {
                id: "1",
                conversation_id: "3926",
                wa_message_id: "wamid.test",
                from_me: true,
                body: "Teste recebido com sucesso pela Fort Cordis.",
                type: "text",
                status: messagesRequestCount === 1 ? "sent" : "delivered",
                created_at: "2026-08-14T02:26:00.000Z",
              },
            ],
            pagination: { page: 1, limit: 50, total: 1 },
            customer_service_window: {
              last_inbound_at: "2026-08-14T02:26:00.000Z",
              expires_at: "2026-08-15T02:26:00.000Z",
              is_open: true,
            },
          });
        }

        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();

        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Enviada")).toBeInTheDocument();
    expect(screen.getByText(/Resposta livre disponível até/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Digite sua resposta")).toBeEnabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(screen.getByText("Entregue")).toBeInTheDocument();
    expect(screen.queryByText("Carregando mensagens...")).not.toBeInTheDocument();
  });

  it("bloqueia texto livre quando a janela de 24 horas encerrou", async () => {
    vi.setSystemTime(new Date("2026-08-16T03:00:00.000Z"));

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        const customerServiceWindow = {
          last_inbound_at: "2026-08-14T02:26:00.000Z",
          expires_at: "2026-08-15T02:26:00.000Z",
          is_open: false,
        };

        if (url.startsWith("/whatsapp/conversations?")) {
          return jsonResponse({
            data: [
              {
                id: "3926",
                wa_phone_number: "558500000000",
                wa_psid: "558500000000",
                status: "open",
                subject: "Cliente de teste",
                last_agent_id: null,
                last_activity_at: "2026-08-14T02:26:00.000Z",
                created_at: "2026-08-14T02:26:00.000Z",
                updated_at: "2026-08-14T02:26:00.000Z",
                last_message_body: "Pergunta da clínica.",
                last_message_at: "2026-08-14T02:26:00.000Z",
                customer_service_window: customerServiceWindow,
              },
            ],
            pagination: { page: 1, limit: 20, total: 1 },
          });
        }

        if (url === "/whatsapp/agents") {
          return jsonResponse({ data: [] });
        }

        if (url.startsWith("/whatsapp/conversations/3926/messages?")) {
          return jsonResponse({
            data: [
              {
                id: "1",
                conversation_id: "3926",
                wa_message_id: "wamid.inbound",
                from_me: false,
                body: "Pergunta da clínica.",
                type: "text",
                status: "received",
                created_at: "2026-08-14T02:26:00.000Z",
              },
            ],
            pagination: { page: 1, limit: 50, total: 1 },
            customer_service_window: customerServiceWindow,
          });
        }

        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();

        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText(/Janela encerrada em/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Digite sua resposta")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
  });

  it("preenche a previa de um modelo e copia o texto para revisao", async () => {
    const requestedUrls: string[] = [];
    const customerServiceWindow = {
      last_inbound_at: "2026-08-14T02:26:00.000Z",
      expires_at: "2026-08-15T02:26:00.000Z",
      is_open: true,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        requestedUrls.push(url);

        if (url.startsWith("/whatsapp/conversations?")) {
          return jsonResponse({
            data: [
              {
                id: "3926",
                wa_phone_number: "558500000000",
                wa_psid: "558500000000",
                status: "open",
                subject: "Animal Care",
                last_agent_id: "7",
                assigned_agent_name: "Ana",
                assigned_agent_email: "ana@fortcordis.com",
                last_activity_at: "2026-08-14T02:26:00.000Z",
                last_inbound_at: "2026-08-14T02:26:00.000Z",
                created_at: "2026-08-14T02:26:00.000Z",
                updated_at: "2026-08-14T02:26:00.000Z",
                last_message_body: "Olá",
                last_message_at: "2026-08-14T02:26:00.000Z",
                customer_service_window: customerServiceWindow,
              },
            ],
            pagination: { page: 1, limit: 20, total: 1 },
          });
        }

        if (url === "/whatsapp/agents") {
          return jsonResponse({
            data: [
              {
                id: "7",
                name: "Ana",
                email: "ana@fortcordis.com",
                role: "agent",
                active: true,
                created_at: "2026-08-14T02:00:00.000Z",
              },
            ],
          });
        }

        if (url === "/whatsapp/automation/templates") {
          return jsonResponse({
            data: [
              {
                key: "portalReportAvailable",
                name: "laudo_disponivel_portal",
                meta_id: "1682393009502350",
                language: "pt_BR",
                body: "Olá, {{1}}. O laudo do exame {{2}} de {{3}} está disponível no Portal Fort Cordis.",
                body_parameter_count: 3,
                variable_labels: ["Clínica ou destinatário", "Exame", "Pet"],
                quick_replies: [],
                category: "laudos",
                workflow_label: "Laudo disponível no portal",
                requires_document: false,
                can_copy_as_free_text: true,
                meta_approval_live: null,
              },
            ],
            source: "configured_catalog",
            meta_approval_live: null,
          });
        }

        if (url.startsWith("/whatsapp/conversations/3926/messages?")) {
          return jsonResponse({
            data: [],
            pagination: { page: 1, limit: 50, total: 0 },
            customer_service_window: customerServiceWindow,
          });
        }

        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();

        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("tab", { name: /Modelos configurados/ }));
    expect(screen.getByText(/A aprovação atual na Meta não é consultada/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Exame"), { target: { value: "Ecocardiograma" } });
    fireEvent.change(screen.getByLabelText("Pet"), { target: { value: "Gamora" } });
    const copyButton = screen.getByRole("button", { name: "Copiar texto para resposta" });
    expect(copyButton).toBeEnabled();
    fireEvent.click(copyButton);

    expect(screen.getByPlaceholderText("Digite sua resposta")).toHaveValue(
      "Olá, Animal Care. O laudo do exame Ecocardiograma de Gamora está disponível no Portal Fort Cordis."
    );

    fireEvent.change(screen.getByLabelText("Buscar conversas"), { target: { value: "Animal Care" } });
    fireEvent.submit(screen.getByLabelText("Buscar conversas").closest("form")!);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(requestedUrls.some((url) => url.includes("search=Animal+Care"))).toBe(true);
  });

  it("mostra clinica, tutor, pet, agendamento e OS vinculados pelo telefone", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) {
          return jsonResponse({
            data: [{
              id: "3926", wa_phone_number: "558588281436", wa_psid: "558588281436",
              status: "open", subject: "Animal Care", last_agent_id: null,
              last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
              created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z",
              customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
            }],
            pagination: { page: 1, limit: 20, total: 1 },
          });
        }
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/3926/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return jsonResponse({
          normalized_phone: "558588281436", resolution: "matched", match_type: "clinica",
          clinicas: [{ id: 10, nome: "Animal Care", cidade: "Fortaleza", estado: "CE" }],
          tutores: [{ id: 20, nome: "Maria Oliveira" }],
          pets: [{ id: 30, tutor_id: 20, nome: "Gamora", especie: "Canina", raca: "SRD" }],
          agendamentos: [{ id: 40, inicio: "2026-08-15T12:00:00.000Z", fim: "2026-08-15T12:30:00.000Z", status: "Confirmado",
            clinica_id: 10, clinica_nome: "Animal Care", tutor_id: 20, tutor_nome: "Maria Oliveira", pet_id: 30, pet_nome: "Gamora",
            servico_id: 50, servico_nome: "Ecocardiograma" }],
          ordens_servico: [{ id: 60, numero_os: "OS-0001", agendamento_id: 40, data_atendimento: "2026-08-15T12:00:00.000Z",
            status: "Pendente", valor_final: 250, clinica_id: 10, clinica_nome: "Animal Care", tutor_id: 20, tutor_nome: "Maria Oliveira",
            pet_id: 30, pet_nome: "Gamora", servico_id: 50, servico_nome: "Ecocardiograma" }],
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Vínculo automático por telefone")).toBeInTheDocument();
    expect(screen.getByText("Maria Oliveira")).toBeInTheDocument();
    expect(screen.getByText("Canina · SRD")).toBeInTheDocument();
    expect(screen.getByText(/OS-0001 · Gamora/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Agenda" })).toHaveAttribute("href", "/agenda?agendamento_id=40");
    expect(screen.getByRole("link", { name: "Financeiro" })).toHaveAttribute("href", "/financeiro?os_id=60");
  });

  it("avisa quando o telefone pertence a mais de um cadastro", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "3926", wa_phone_number: "5585999990001", wa_psid: null, status: "open", subject: "Contato compartilhado",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: null,
            created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/3926/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: null, expires_at: null, is_open: false },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return jsonResponse({
          normalized_phone: "5585999990001", resolution: "ambiguous", match_type: null,
          clinicas: [{ id: 10, nome: "Animal Care", cidade: "Fortaleza", estado: "CE" }],
          tutores: [{ id: 20, nome: "Maria Oliveira" }], pets: [], agendamentos: [], ordens_servico: [],
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Número presente em mais de um cadastro")).toBeInTheDocument();
    expect(screen.getByText("Clínica: Animal Care")).toBeInTheDocument();
    expect(screen.getByText("Tutor: Maria Oliveira")).toBeInTheDocument();
    expect(screen.queryByText("Vínculo automático por telefone")).not.toBeInTheDocument();
  });

  it("descarta um contexto atrasado depois da troca de conversa", async () => {
    let resolveFirstContext!: (response: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [
            { id: "1", wa_phone_number: "558511111111", wa_psid: null, status: "open", subject: "Conversa Um", last_agent_id: null,
              last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: null, created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z" },
            { id: "2", wa_phone_number: "558522222222", wa_psid: null, status: "open", subject: "Conversa Dois", last_agent_id: null,
              last_activity_at: "2026-08-14T02:25:00.000Z", last_inbound_at: null, created_at: "2026-08-14T02:25:00.000Z", updated_at: "2026-08-14T02:25:00.000Z" },
          ],
          pagination: { page: 1, limit: 20, total: 2 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.includes("/messages?")) return jsonResponse({ data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: null, expires_at: null, is_open: false } });
        if (url.includes("telefone=558511111111")) {
          return await new Promise<Response>((resolve) => { resolveFirstContext = resolve; });
        }
        if (url.includes("telefone=558522222222")) return jsonResponse({
          normalized_phone: "558522222222", resolution: "matched", match_type: "clinica",
          clinicas: [{ id: 2, nome: "Clínica Dois Vinculada", cidade: "Fortaleza", estado: "CE" }],
          tutores: [], pets: [], agendamentos: [], ordens_servico: [],
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    fireEvent.click(screen.getByRole("button", { name: /Conversa Dois/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Clínica Dois Vinculada")).toBeInTheDocument();

    await act(async () => {
      resolveFirstContext(jsonResponse({
        normalized_phone: "558511111111", resolution: "matched", match_type: "clinica",
        clinicas: [{ id: 1, nome: "Cadastro Antigo", cidade: null, estado: null }],
        tutores: [], pets: [], agendamentos: [], ordens_servico: [],
      }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Clínica Dois Vinculada")).toBeInTheDocument();
    expect(screen.queryByText("Cadastro Antigo")).not.toBeInTheDocument();
  });

  it("edita e desativa um atendente na seção Configurar equipe", async () => {
    let agentsCallCount = 0;
    const requestedCalls: Array<{ url: string; method: string; body: unknown }> = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        const method = init?.method || "GET";
        if (method !== "GET") {
          requestedCalls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
        }

        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({ data: [], pagination: { page: 1, limit: 20, total: 0 } });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });

        if (url === "/whatsapp/agents") {
          agentsCallCount += 1;
          return jsonResponse({
            data: [
              {
                id: "7",
                name: agentsCallCount === 1 ? "Ana" : "Ana Paula",
                email: "ana@fortcordis.com",
                role: agentsCallCount === 1 ? "agent" : "supervisor",
                active: agentsCallCount < 3,
                created_at: "2026-08-14T02:00:00.000Z",
              },
            ],
          });
        }

        if (url === "/whatsapp/agents/7" && method === "PATCH") {
          return jsonResponse({ id: "7", name: "Ana Paula", email: "ana@fortcordis.com", role: "supervisor", active: agentsCallCount < 2, created_at: "2026-08-14T02:00:00.000Z" });
        }

        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByText("Configurar equipe"));
    fireEvent.click(screen.getByRole("button", { name: "Editar Ana" }));

    const nameInput = screen.getByDisplayValue("Ana");
    fireEvent.change(nameInput, { target: { value: "Ana Paula" } });
    const roleSelects = screen.getAllByDisplayValue("Atendente");
    fireEvent.change(roleSelects[roleSelects.length - 1], { target: { value: "supervisor" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(requestedCalls[0]).toEqual({
      url: "/whatsapp/agents/7",
      method: "PATCH",
      body: { name: "Ana Paula", email: "ana@fortcordis.com", role: "supervisor" },
    });
    expect(screen.getByText("Atendente atualizado com sucesso.")).toBeInTheDocument();
    expect(screen.getByText("Ana Paula")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Desativar" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(requestedCalls[1]).toEqual({
      url: "/whatsapp/agents/7",
      method: "PATCH",
      body: { active: false },
    });
    expect(screen.getByText("Atendente desativado.")).toBeInTheDocument();
  });

  it("pré-seleciona o atendente logado pelo email ao assumir uma conversa sem responsável", async () => {
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: 1, email: " Eu@FortCordis.com ", nome: "Eu Mesma", ativo: 1, papeis: [] })
    );

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "3926", wa_phone_number: "558500000000", wa_psid: null, status: "open", subject: "Sem responsável",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: null,
            created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({
          data: [
            { id: "5", name: "Outra Pessoa", email: "outra@fortcordis.com", role: "agent", active: true, created_at: "2026-08-14T02:00:00.000Z" },
            { id: "9", name: "Eu Mesma", email: "eu@fortcordis.com", role: "agent", active: true, created_at: "2026-08-14T02:00:00.000Z" },
          ],
        });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/3926/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: null, expires_at: null, is_open: false },
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByLabelText("Atribuir para")).toHaveValue("9");
  });

  it("usa o primeiro atendente ativo quando o email logado não corresponde a nenhum atendente", async () => {
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: 1, email: "ninguem@fortcordis.com", nome: "Ninguém", ativo: 1, papeis: [] })
    );

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "3926", wa_phone_number: "558500000000", wa_psid: null, status: "open", subject: "Sem responsável",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: null,
            created_at: "2026-08-14T02:26:00.000Z", updated_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({
          data: [
            { id: "3", name: "Inativa Primeiro", email: "inativa@fortcordis.com", role: "agent", active: false, created_at: "2026-08-14T02:00:00.000Z" },
            { id: "5", name: "Ativa Segunda", email: "ativa@fortcordis.com", role: "agent", active: true, created_at: "2026-08-14T02:00:00.000Z" },
          ],
        });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/3926/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: null, expires_at: null, is_open: false },
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T00:00:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByLabelText("Atribuir para")).toHaveValue("5");
  });

  it("mostra indicador de não lida e marca como vista ao abrir a conversa", async () => {
    const patchCalls: string[] = [];

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if ((init?.method || "GET") === "PATCH") patchCalls.push(url);

        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [
            { id: "50", wa_phone_number: "558511110000", wa_psid: null, status: "open", subject: "Já vista",
              last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:20:00.000Z",
              unread: false, created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" },
            { id: "60", wa_phone_number: "558522220000", wa_psid: null, status: "open", subject: "Contato Pendente",
              last_agent_id: null, last_activity_at: "2026-08-14T02:30:00.000Z", last_inbound_at: "2026-08-14T02:29:00.000Z",
              unread: true, created_at: "2026-08-14T02:10:00.000Z", updated_at: "2026-08-14T02:10:00.000Z" },
          ],
          pagination: { page: 1, limit: 20, total: 2 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/50/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 }, last_inbound_at: "2026-08-14T02:20:00.000Z",
          customer_service_window: { last_inbound_at: "2026-08-14T02:20:00.000Z", expires_at: "2026-08-15T02:20:00.000Z", is_open: true },
        });
        if (url.startsWith("/whatsapp/conversations/60/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 }, last_inbound_at: "2026-08-14T02:29:00.000Z",
          customer_service_window: { last_inbound_at: "2026-08-14T02:29:00.000Z", expires_at: "2026-08-15T02:29:00.000Z", is_open: true },
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: url.split("/")[3] ?? "", last_seen_at: "2026-08-14T02:31:00.000Z" } });

        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByLabelText("Não lida")).toBeInTheDocument();
    expect(patchCalls).toContain("/whatsapp/conversations/50/seen");
    expect(patchCalls).not.toContain("/whatsapp/conversations/60/seen");

    fireEvent.click(screen.getByText("Contato Pendente"));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(patchCalls).toContain("/whatsapp/conversations/60/seen");
    expect(screen.queryByLabelText("Não lida")).not.toBeInTheDocument();
  });

  it("carrega e exibe a mídia recebida ao clicar no botão", async () => {
    if (!URL.createObjectURL) {
      // jsdom não implementa isso nativamente; stub mínimo só para este teste.
      URL.createObjectURL = vi.fn(() => "blob:mock-url");
    }
    if (!URL.revokeObjectURL) {
      URL.revokeObjectURL = vi.fn();
    }

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "70", wa_phone_number: "558533330000", wa_psid: null, status: "open", subject: "Foto do exame",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/70/messages?")) return jsonResponse({
          data: [{ id: "500", conversation_id: "70", wa_message_id: "wamid.foto", from_me: false, body: "[image]", type: "image", status: "received", created_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 50, total: 1 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "70", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        if (url === "/whatsapp/conversations/70/messages/500/media") {
          return {
            ok: true,
            status: 200,
            blob: async () => new Blob(["fake-image-bytes"], { type: "image/jpeg" }),
          } as unknown as Response;
        }
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const botao = screen.getByRole("button", { name: "Ver imagem" });
    fireEvent.click(botao);
    await act(async () => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    });

    expect(screen.getByRole("img", { name: "[image]" })).toBeInTheDocument();
  });

  it("oferece baixar o áudio quando o navegador não consegue tocar (ex.: Safari com Opus/OGG)", async () => {
    if (!URL.createObjectURL) URL.createObjectURL = vi.fn(() => "blob:mock-url");
    if (!URL.revokeObjectURL) URL.revokeObjectURL = vi.fn();

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "80", wa_phone_number: "558544440000", wa_psid: null, status: "open", subject: "Áudio recebido",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/80/messages?")) return jsonResponse({
          data: [{ id: "600", conversation_id: "80", wa_message_id: "wamid.audio", from_me: false, body: "[audio]", type: "audio", status: "received", created_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 50, total: 1 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.includes("/seen")) return jsonResponse({ data: { id: "80", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        if (url === "/whatsapp/conversations/80/messages/600/media") {
          return { ok: true, status: 200, blob: async () => new Blob(["fake-audio-bytes"], { type: "audio/ogg" }) } as unknown as Response;
        }
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: "Ouvir áudio" }));
    await act(async () => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    });

    const audioEl = document.querySelector("audio");
    expect(audioEl).not.toBeNull();
    fireEvent.error(audioEl as HTMLAudioElement);

    expect(screen.getByText(/não toca este áudio/)).toBeInTheDocument();
    expect(document.querySelector("audio")).toBeNull();
  });

  it("reenvia uma mensagem com falha", async () => {
    const requestedCalls: Array<{ url: string; method: string; body: unknown }> = [];
    let messagesCallCount = 0;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        const method = init?.method || "GET";
        if (method !== "GET") {
          requestedCalls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
        }

        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "90", wa_phone_number: "558555550000", wa_psid: null, status: "open", subject: "Mensagem com falha",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/90/messages?")) {
          messagesCallCount += 1;
          return jsonResponse({
            data: [{
              id: "800", conversation_id: "90", wa_message_id: null, from_me: true,
              body: "Olá, tudo bem?", type: "text",
              status: messagesCallCount === 1 ? "failed" : "sent",
              created_at: "2026-08-14T02:26:00.000Z",
            }],
            pagination: { page: 1, limit: 50, total: 1 },
            customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
          });
        }
        if (url === "/whatsapp/conversations/90/messages" && method === "POST") {
          return jsonResponse({ id: "801", wa_message_id: "wamid.reenvio", status: "sent" });
        }
        if (url.includes("/seen")) return jsonResponse({ data: { id: "90", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: /Reenviar/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Reenviar/ }));

    await act(async () => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    });

    const postCall = requestedCalls.find((call) => call.method === "POST");
    expect(postCall).toEqual({
      url: "/whatsapp/conversations/90/messages",
      method: "POST",
      body: { body: "Olá, tudo bem?", type: "text" },
    });
    expect(screen.getByText("Mensagem reenviada.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Reenviar/ })).toBeNull();
  });

  it("anexa um PDF e envia como mensagem no WhatsApp", async () => {
    let capturedInit: RequestInit | undefined;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        const method = init?.method || "GET";

        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "120", wa_phone_number: "558566660000", wa_psid: null, status: "open", subject: "Exame para anexar",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/120/messages?")) return jsonResponse({
          data: [],
          pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
        if (url.includes("/seen")) return jsonResponse({ data: { id: "120", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        if (url === "/whatsapp/conversations/120/messages" && method === "POST") {
          capturedInit = init;
          return jsonResponse({ id: "900", wa_message_id: "wamid.anexo", status: "sent" });
        }
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const file = new File(["conteudo-fake-pdf"], "exame.pdf", { type: "application/pdf" });
    const fileInput = screen.getByLabelText("Selecionar arquivo para anexar") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(screen.getByText("exame.pdf")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Digite sua resposta"), { target: { value: "Segue o exame combinado" } });
    fireEvent.click(screen.getByRole("button", { name: /Enviar/ }));

    await act(async () => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    });

    expect(capturedInit).toBeDefined();
    expect(capturedInit?.method).toBe("POST");
    const formData = capturedInit?.body as FormData;
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get("attachment")).toBe(file);
    expect(formData.get("body")).toBe("Segue o exame combinado");
    expect((capturedInit?.headers as Record<string, string> | undefined)?.["Content-Type"]).toBeUndefined();

    expect(screen.getByText("Anexo enviado.")).toBeInTheDocument();
    expect(fileInput.value).toBe("");
    expect(screen.queryByText("exame.pdf")).not.toBeInTheDocument();
  });

  it("rejeita anexo com tipo de arquivo não suportado antes de enviar", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "121", wa_phone_number: "558577770000", wa_psid: null, status: "open", subject: "Anexo invalido",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/121/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
        if (url.includes("/seen")) return jsonResponse({ data: { id: "121", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const file = new File(["conteudo"], "virus.exe", { type: "application/x-msdownload" });
    const fileInput = screen.getByLabelText("Selecionar arquivo para anexar") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });

    expect(screen.getByText(/Tipo de arquivo não suportado/)).toBeInTheDocument();
    expect(screen.queryByText("virus.exe")).not.toBeInTheDocument();
  });

  it("limpa o anexo selecionado ao trocar de conversa", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [
            { id: "200", wa_phone_number: "558511110000", wa_psid: null, status: "open", subject: "Primeira conversa",
              last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
              created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" },
            { id: "201", wa_phone_number: "558522220000", wa_psid: null, status: "open", subject: "Segunda conversa",
              last_agent_id: null, last_activity_at: "2026-08-14T02:20:00.000Z", last_inbound_at: "2026-08-14T02:20:00.000Z",
              created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" },
          ],
          pagination: { page: 1, limit: 20, total: 2 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/200/messages?") || url.startsWith("/whatsapp/conversations/201/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
        if (url.includes("/seen")) return jsonResponse({ data: { id: "0", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const file = new File(["conteudo"], "exame-paciente-a.pdf", { type: "application/pdf" });
    const fileInput = screen.getByLabelText("Selecionar arquivo para anexar") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [file] } });
    expect(screen.getByText("exame-paciente-a.pdf")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Segunda conversa"));
    await act(async () => {
      for (let i = 0; i < 8; i += 1) await Promise.resolve();
    });

    expect(screen.queryByText("exame-paciente-a.pdf")).not.toBeInTheDocument();
    expect(fileInput.value).toBe("");
  });

  it("remove o anexo anterior ao tentar substituí-lo por um arquivo inválido", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "210", wa_phone_number: "558533330001", wa_psid: null, status: "open", subject: "Troca de anexo",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/210/messages?")) return jsonResponse({
          data: [], pagination: { page: 1, limit: 50, total: 0 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
        if (url.includes("/seen")) return jsonResponse({ data: { id: "210", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    const validFile = new File(["conteudo"], "exame-valido.pdf", { type: "application/pdf" });
    const fileInput = screen.getByLabelText("Selecionar arquivo para anexar") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [validFile] } });
    expect(screen.getByText("exame-valido.pdf")).toBeInTheDocument();

    const invalidFile = new File(["conteudo"], "virus.exe", { type: "application/x-msdownload" });
    fireEvent.change(fileInput, { target: { files: [invalidFile] } });

    expect(screen.getByText(/Tipo de arquivo não suportado/)).toBeInTheDocument();
    expect(screen.queryByText("exame-valido.pdf")).not.toBeInTheDocument();
    expect(fileInput.value).toBe("");
  });

  it("não mostra o botão de mídia para um anexo enviado que falhou", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
      if (url === "/whatsapp/quick-replies") return jsonResponse({ data: [] });
        if (url.startsWith("/whatsapp/conversations?")) return jsonResponse({
          data: [{ id: "220", wa_phone_number: "558533330002", wa_psid: null, status: "open", subject: "Anexo com falha",
            last_agent_id: null, last_activity_at: "2026-08-14T02:26:00.000Z", last_inbound_at: "2026-08-14T02:26:00.000Z",
            created_at: "2026-08-14T02:00:00.000Z", updated_at: "2026-08-14T02:00:00.000Z" }],
          pagination: { page: 1, limit: 20, total: 1 },
        });
        if (url === "/whatsapp/agents") return jsonResponse({ data: [] });
        if (url === "/whatsapp/automation/templates") return jsonResponse({ data: [], source: "configured_catalog", meta_approval_live: null });
        if (url.startsWith("/whatsapp/conversations/220/messages?")) return jsonResponse({
          data: [{ id: "900", conversation_id: "220", wa_message_id: null, from_me: true, body: "exame.pdf",
            type: "document", status: "failed", created_at: "2026-08-14T02:26:00.000Z" }],
          pagination: { page: 1, limit: 50, total: 1 },
          customer_service_window: { last_inbound_at: "2026-08-14T02:26:00.000Z", expires_at: "2026-08-15T02:26:00.000Z", is_open: true },
        });
        if (url.startsWith("/api/v1/whatsapp-contexto?")) return notFoundDomainContextResponse();
        if (url.includes("/seen")) return jsonResponse({ data: { id: "220", last_seen_at: "2026-08-14T02:26:00.000Z" } });
        throw new Error(`URL inesperada no teste: ${url}`);
      })
    );

    render(<WhatsAppStagePage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("exame.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Baixar documento" })).not.toBeInTheDocument();
  });
});
