export const STABLE_CATALOG_CACHE_TTL_MS = 5 * 60 * 1000;

export type StableCatalogName = "clinicas" | "servicos";

type CatalogCacheEntry = {
  catalog: StableCatalogName;
  session: string;
  generation: number;
  expiresAt: number;
  value: unknown;
};

type InFlightCatalogRequest = {
  catalog: StableCatalogName;
  promise: Promise<unknown>;
};

type LoadStableCatalogOptions<T> = {
  catalog: StableCatalogName;
  variant: string;
  load: () => Promise<T>;
  ttlMs?: number;
};

const cache = new Map<string, CatalogCacheEntry>();
const inFlight = new Map<string, InFlightCatalogRequest>();
const generations = new Map<StableCatalogName, number>();
let activeSession: string | null = null;

function sessionFingerprint(token: string): string {
  let hash = 2_166_136_261;
  for (let index = 0; index < token.length; index += 1) {
    hash ^= token.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return `${token.length}:${hash >>> 0}`;
}

function getCurrentSession(): string | null {
  if (typeof window === "undefined") return null;

  try {
    return sessionFingerprint(window.localStorage.getItem("token") || "");
  } catch {
    return "unavailable";
  }
}

function synchronizeSession(): string | null {
  const currentSession = getCurrentSession();
  if (currentSession === null) return null;

  if (activeSession !== null && activeSession !== currentSession) {
    cache.clear();
    inFlight.clear();
  }
  activeSession = currentSession;
  return currentSession;
}

function cacheKey(session: string, catalog: StableCatalogName, variant: string): string {
  return `${session}:${catalog}:${variant}`;
}

function getGeneration(catalog: StableCatalogName): number {
  return generations.get(catalog) || 0;
}

export function loadStableCatalog<T>({
  catalog,
  variant,
  load,
  ttlMs = STABLE_CATALOG_CACHE_TTL_MS,
}: LoadStableCatalogOptions<T>): Promise<T> {
  const session = synchronizeSession();
  if (session === null) return load();

  const key = cacheKey(session, catalog, variant);
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now && cached.generation === getGeneration(catalog)) {
    return Promise.resolve(cached.value as T);
  }

  const pending = inFlight.get(key);
  if (pending) return pending.promise as Promise<T>;

  const generation = getGeneration(catalog);
  let request: Promise<T>;
  request = Promise.resolve()
    .then(load)
    .then(
      (value) => {
        if (synchronizeSession() === session && getGeneration(catalog) === generation) {
          cache.set(key, {
            catalog,
            session,
            generation,
            expiresAt: Date.now() + ttlMs,
            value,
          });
        }
        if (inFlight.get(key)?.promise === request) inFlight.delete(key);
        return value;
      },
      (error: unknown) => {
        if (inFlight.get(key)?.promise === request) inFlight.delete(key);
        throw error;
      }
    );

  inFlight.set(key, { catalog, promise: request });
  return request;
}

export function invalidateStableCatalog(catalog: StableCatalogName): void {
  generations.set(catalog, getGeneration(catalog) + 1);

  for (const [key, entry] of cache) {
    if (entry.catalog === catalog) cache.delete(key);
  }
  for (const [key, request] of inFlight) {
    if (request.catalog === catalog) inFlight.delete(key);
  }
}

function normalizeMutationPath(url: unknown): string {
  const rawUrl = String(url || "").trim();
  if (!rawUrl) return "";

  try {
    if (/^https?:\/\//i.test(rawUrl)) {
      return new URL(rawUrl).pathname.replace(/^\/api\/v1/, "");
    }
  } catch {
    return "";
  }

  return rawUrl.split(/[?#]/, 1)[0].replace(/^\/api\/v1/, "");
}

export function invalidateStableCatalogForMutation(method: unknown, url: unknown): void {
  const normalizedMethod = String(method || "get").toLowerCase();
  if (!new Set(["post", "put", "patch", "delete"]).has(normalizedMethod)) return;

  const path = normalizeMutationPath(url);
  if (path === "/clinicas" || /^\/clinicas\/\d+(?:\/|$)/.test(path)) {
    invalidateStableCatalog("clinicas");
  }
  if (path === "/servicos" || /^\/servicos\/\d+(?:\/|$)/.test(path)) {
    invalidateStableCatalog("servicos");
  }
}

export function resetStableCatalogCacheForTests(): void {
  cache.clear();
  inFlight.clear();
  generations.clear();
  activeSession = null;
}
