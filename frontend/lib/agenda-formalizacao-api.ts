import { portalErrorMessageFromBody } from "@/lib/portal-errors";

export type AgendaFormalizacaoContext = {
  clinica_nome: string;
  servico: string;
  data: string;
  hora: string;
  expires_at: string | null;
};

export type AgendaFormalizacaoSubmitResult = {
  agendamento_id: number;
  status: string;
};

async function fetchJson<T>(
  url: string,
  options: RequestInit = {},
  fallback = "Erro ao comunicar com o servidor.",
): Promise<T> {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  if (!headers.has("Content-Type") && method !== "GET") {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(url, { ...options, headers, credentials: "same-origin" });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(portalErrorMessageFromBody(text, fallback));
  }
  return (await response.json()) as T;
}

export async function getAgendaFormalizacaoContext(token: string): Promise<AgendaFormalizacaoContext> {
  return fetchJson<AgendaFormalizacaoContext>(
    `/api/v1/agenda/formalizacao/${encodeURIComponent(token)}`,
    {},
    "Não foi possível consultar este link.",
  );
}

export async function submitAgendaFormalizacao(
  token: string,
  payload: { nome_paciente: string; nome_tutor: string; telefone_tutor: string },
): Promise<AgendaFormalizacaoSubmitResult> {
  return fetchJson<AgendaFormalizacaoSubmitResult>(
    `/api/v1/agenda/formalizacao/${encodeURIComponent(token)}`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    "Não foi possível enviar os dados informados.",
  );
}
