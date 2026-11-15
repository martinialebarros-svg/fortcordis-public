const INSTITUTIONAL_HOSTS = new Set([
  "fortcordis.com",
  "www.fortcordis.com",
  "fortcordis.com.br",
  "www.fortcordis.com.br",
  "stage.fortcordis.com.br",
  "www.stage.fortcordis.com.br",
]);

const APP_HOST_BY_INSTITUTIONAL_HOST: Record<string, string> = {
  "fortcordis.com": "app.fortcordis.com.br",
  "www.fortcordis.com": "app.fortcordis.com.br",
  "fortcordis.com.br": "app.fortcordis.com.br",
  "www.fortcordis.com.br": "app.fortcordis.com.br",
  "stage.fortcordis.com.br": "app.stage.fortcordis.com.br",
  "www.stage.fortcordis.com.br": "app.stage.fortcordis.com.br",
};

const APP_ROUTE_PREFIXES = [
  "/assistente-ia",
  "/agenda",
  "/atendimento",
  "/clinicas",
  "/configuracoes",
  "/dashboard",
  "/financeiro",
  "/fiscal",
  "/gestao",
  "/laudos",
  "/logistica",
  "/pacientes",
  "/tutores",
  "/referencias-eco",
  "/relatorios",
  "/servicos",
  "/whatsapp-stage",
  "/ultrassonografia-abdominal",
  "/visualizador-vivid-iq",
];

function normalizeHostValue(hostValue: string | null): string {
  if (!hostValue) return "";

  const firstPart = hostValue.split(",")[0] ?? "";
  return firstPart.toLowerCase().split(":")[0]?.trim() ?? "";
}

function normalizeForwardedHostValue(hostValue: string | null): string {
  if (!hostValue) return "";

  const parts = hostValue
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const candidate = parts[parts.length - 1] ?? "";
  return candidate.toLowerCase().split(":")[0]?.trim() ?? "";
}

export function resolveRequestHost(headers: {
  host: string | null;
  forwardedHost: string | null;
  originalHost: string | null;
}): string {
  const host = normalizeHostValue(headers.host);
  if (host) return host;

  const forwardedHost = normalizeForwardedHostValue(headers.forwardedHost);
  if (forwardedHost) return forwardedHost;

  return normalizeForwardedHostValue(headers.originalHost);
}

export function isInstitutionalHost(host: string): boolean {
  return INSTITUTIONAL_HOSTS.has(host);
}

export function resolveAppHostForInstitutionalHost(host: string): string | null {
  return APP_HOST_BY_INSTITUTIONAL_HOST[host] ?? null;
}

export function isAppRoutePath(pathname: string): boolean {
  return APP_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}
