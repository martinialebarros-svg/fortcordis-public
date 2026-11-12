import { CanceledError, type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

export type MapsBudget = { calls: number | null; estimated_brl: number | null };
export type MapsPeriods = { action?: MapsBudget; day?: MapsBudget; month?: MapsBudget };
export type MapsOperationMode = "paid_budget" | "cache_only" | "temporary_open" | "cache_first";
export const MAPS_SKU_LABELS: Record<string, string> = {
  routes_essentials: "Routes Essentials", routes_pro: "Routes Pro",
  distance_matrix_essentials: "Distance Matrix Essentials", distance_matrix_pro: "Distance Matrix Advanced",
  geocoding: "Geocoding",
};
export type MapsQuote = {
  confirmation_mode?: "per_action" | "server_recorded";
  operation_mode?: MapsOperationMode;
  budget_policy?: "agenda_monitor" | "enforced";
  financial_limit_enforced?: boolean;
  alerts?: string[];
  route_estimate?: {
    estimate_basis: "request_route_graph";
    cached_directions: number; missing_directions: number;
    first_departure_routes: number; geocoding_units: number;
    max_attempts_per_direction: number; search_start: string; search_end: string;
  } | null;
  pricing_review_due?: boolean;
  pricing_reference_valid_until?: string | null;
  required: boolean;
  blocked: boolean;
  reason?: string;
  message?: string;
  quote_id?: string;
  action: string;
  service: string;
  services?: string[];
  max_calls: number | null;
  estimated_cost_min_brl: number | null;
  estimated_cost_max_brl: number | null;
  uncertainty?: string[];
  consumption?: MapsPeriods;
  remaining?: MapsPeriods;
  limits?: MapsPeriods;
  expires_at?: string;
};

type Signal = InternalAxiosRequestConfig["signal"];
type MapsRequestConfig = InternalAxiosRequestConfig & { mapsConsentReplay?: boolean; mapsCacheFirst?: boolean };
type Confirmation = { id: number; quote: MapsQuote; resolve: (confirmed: boolean) => void };
type Snapshot = { queue: Confirmation[]; notice: string | null; noticeKind?: "warning" | "error" };
let snapshot: Snapshot = { queue: [], notice: null };
let sequence = 0;
const subscribers = new Set<() => void>();
const publish = (next: Snapshot) => {
  snapshot = next;
  subscribers.forEach((listener) => listener());
};

export const mapsConfirmationStore = {
  subscribe(listener: () => void) {
    subscribers.add(listener);
    return () => { subscribers.delete(listener); };
  },
  getSnapshot: () => snapshot,
  respond(id: number, confirmed: boolean) {
    const item = snapshot.queue.find((pending) => pending.id === id);
    if (!item) return;
    publish({ ...snapshot, queue: snapshot.queue.filter((pending) => pending.id !== id) });
    item.resolve(confirmed);
  },
  cancelAll() {
    const pending = snapshot.queue;
    publish({ ...snapshot, queue: [] });
    pending.forEach((item) => item.resolve(false));
  },
  dismissNotice() { publish({ ...snapshot, notice: null }); },
  notify(message: string, noticeKind: "warning" | "error" = "error") { publish({ ...snapshot, notice: message, noticeKind }); },
};

export function requestMapsConfirmation(quote: MapsQuote, signal?: Signal): Promise<boolean> {
  if (signal?.aborted || typeof window === "undefined") return Promise.resolve(false);
  return new Promise((resolve) => {
    const id = ++sequence;
    const onAbort = () => mapsConfirmationStore.respond(id, false);
    const done = (confirmed: boolean) => {
      signal?.removeEventListener?.("abort", onAbort);
      resolve(confirmed && !signal?.aborted);
    };
    signal?.addEventListener?.("abort", onAbort, { once: true });
    publish({ ...snapshot, queue: [...snapshot.queue, { id, quote, resolve: done }] });
  });
}

// The server remains authoritative and rejects unregistered/direct paid calls.
// This list exists only to obtain a quote before dispatching the user action.
export function needsMapsPreflight(method: string, path: string): boolean {
  const relative = path.replace(/^\/api\/v1/, "").replace(/\/$/, "");
  const verb = method.toUpperCase();
  if (verb === "GET") return relative === "/logistica/deslocamento";
  if (verb === "POST") {
    return [
      "/logistica/recalcular", "/clinicas/geocode-endereco", "/tutores/geocode-endereco",
      "/agenda", "/agenda/geocode-endereco-tutor", "/agenda/sugestao-proximidade",
      "/agenda/sugestoes-horario", "/agenda/assistente/ofertas", "/agenda/assistente/validar-oferta",
      "/assistente-ia/chat",
    ].includes(relative) || /^\/agenda\/\d+\/reabilitar-reserva$/.test(relative) ||
      /^\/assistente-ia\/acoes\/[a-zA-Z0-9-]+\/decisao$/.test(relative);
  }
  return (verb === "PUT" && /^\/agenda\/\d+$/.test(relative)) ||
    (verb === "PATCH" && /^\/agenda\/\d+\/status$/.test(relative));
}

function stopMapsRequest(message: string): Error {
  mapsConfirmationStore.notify(message);
  // Preserve the existing pages' response.data.detail error handling.
  return Object.assign(new Error(message), {
    code: "GOOGLE_MAPS_ACTION_BLOCKED", userMessage: message,
    response: { status: 409, data: { detail: message } },
  });
}

export async function prepareMapsAction(
  api: AxiosInstance,
  config: InternalAxiosRequestConfig,
  confirm: typeof requestMapsConfirmation = requestMapsConfirmation,
): Promise<InternalAxiosRequestConfig> {
  const url = new URL(api.getUri(config), "https://fortcordis.invalid");
  const method = (config.method || "get").toUpperCase();
  const mapsConfig = config as MapsRequestConfig;
  if (!needsMapsPreflight(method, url.pathname)) return config;
  // A config copied from a prior attempt must never reuse its authorization.
  config.headers.delete("X-Google-Maps-Action");
  if (config.signal?.aborted) throw new CanceledError("Ação cancelada antes de consultar o Google.");
  let body = config.data ?? null;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { throw stopMapsRequest("Não foi possível verificar esta ação. Nenhuma consulta ao Google foi autorizada."); }
  }
  let quote: MapsQuote;
  try {
    const response = await api.post<MapsQuote>("/google-maps-control/preview", {
      method, path: url.pathname, query: url.search.slice(1), body,
      ...(mapsConfig.mapsConsentReplay ? { paid_call_required: true } : {}),
    }, { signal: config.signal, timeout: !mapsConfig.mapsConsentReplay && /^\/api\/v1\/agenda(?:\/|$)/.test(url.pathname) ? 3_000 : 15_000 });
    quote = response.data;
  } catch (error) {
    if (config.signal?.aborted) throw new CanceledError("Ação cancelada.");
    // Losing the preview endpoint must not take down the entire Agenda. The
    // server can perform local validation/cache reads without a paid grant;
    // its provider boundary still blocks every unauthorized Google attempt.
    if (!mapsConfig.mapsConsentReplay && /^\/api\/v1\/agenda(?:\/|$)/.test(url.pathname)) {
      mapsConfig.mapsCacheFirst = true;
      return config;
    }
    throw stopMapsRequest("Não foi possível verificar o limite do Google Maps. A ação foi suspensa antes do envio.");
  }
  if (quote.blocked) throw stopMapsRequest(quote.message || "Consulta ao Google Maps bloqueada pelo limite configurado.");
  if (!quote.required) {
    mapsConfig.mapsCacheFirst = quote.operation_mode === "cache_first";
    return config;
  }
  if (!quote.quote_id || !Number.isFinite(quote.max_calls) || !Number.isFinite(quote.estimated_cost_max_brl)) {
    throw stopMapsRequest("Estimativa do Google Maps indisponível. A ação foi suspensa antes do envio.");
  }
  if (!(await confirm(quote, config.signal)) || config.signal?.aborted) {
    throw Object.assign(new CanceledError("Ação cancelada. Nenhuma chamada paga foi enviada."), {
      response: { data: { detail: "Ação cancelada. Nenhuma chamada paga foi enviada." } },
    });
  }
  try {
    const response = await api.post<{ token: string }>("/google-maps-control/confirm", {
      quote_id: quote.quote_id,
    }, { signal: config.signal, timeout: 15_000 });
    if (config.signal?.aborted) throw new CanceledError("Ação cancelada.");
    if (!response.data.token) throw new Error("Autorização ausente.");
    config.headers.set("X-Google-Maps-Action", response.data.token);
    if (quote.budget_policy === "agenda_monitor" && quote.alerts?.length) mapsConfirmationStore.notify(quote.alerts.join(" "), "warning");
    return config;
  } catch (error) {
    if (config.signal?.aborted) throw new CanceledError("Ação cancelada.");
    throw stopMapsRequest("Não foi possível confirmar esta ação do Google Maps. O limite pode ter mudado; consulte uma nova estimativa.");
  }
}

export function retryMapsActionWithConsent(api: AxiosInstance, error: unknown): Promise<AxiosResponse> | undefined {
  const failure = error as { config?: MapsRequestConfig; response?: { status?: number; data?: { detail?: {
    code?: string; reason?: string; can_retry_with_confirmation?: boolean;
  } } } };
  const config = failure?.config;
  const detail = failure?.response?.data?.detail;
  if (!config?.mapsCacheFirst || config.mapsConsentReplay || config.signal?.aborted ||
      failure.response?.status !== 409 || detail?.code !== "GOOGLE_MAPS_COST_BLOCKED" ||
      detail.reason !== "confirmation_required" || detail.can_retry_with_confirmation !== true) return;
  const url = new URL(api.getUri(config), "https://fortcordis.invalid");
  if (!/^\/api\/v1\/agenda(?:\/|$)/.test(url.pathname) || !needsMapsPreflight(config.method || "get", url.pathname)) return;
  // No general-purpose retry: the server attests that this unpaid attempt
  // stopped before Google/business commit. A second denial never loops.
  return api.request({ ...config, mapsConsentReplay: true } as MapsRequestConfig);
}

export function isMapsControlError(error: unknown): boolean {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (!detail || typeof detail !== "object") return false;
  const code = (detail as { code?: string; codigo?: string }).code || (detail as { codigo?: string }).codigo || "";
  return code.startsWith("GOOGLE_MAPS_");
}

export const formatMapsBrl = (value: number | null | undefined) => value == null
  ? "Não definido" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
