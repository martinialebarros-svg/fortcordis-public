import axios from 'axios';
import { extractApiErrorMessage } from './api-error';
import { invalidateStableCatalogForMutation } from './stable-catalog-cache';
import { refreshBrowserSession } from './auth-session';
import { isMapsControlError, mapsConfirmationStore, prepareMapsAction, retryMapsActionWithConsent } from './google-maps-control';

const SAFE_METHODS = new Set(['get', 'head', 'options', 'trace']);
const BINARY_RESPONSE_TYPES = new Set(['arraybuffer', 'blob', 'stream']);

export const DEFAULT_SAFE_REQUEST_TIMEOUT_MS = 15_000;

export function shouldApplyDefaultSafeRequestTimeout(config: {
  method?: string;
  responseType?: string;
  timeout?: number;
}): boolean {
  const method = String(config.method || 'get').toLowerCase();
  const responseType = String(config.responseType || 'json').toLowerCase();
  const hasExplicitTimeout = typeof config.timeout === 'number' && config.timeout > 0;

  return SAFE_METHODS.has(method) && !BINARY_RESPONSE_TYPES.has(responseType) && !hasExplicitTimeout;
}

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') {
    return null;
  }

  const encodedName = `${encodeURIComponent(name)}=`;
  const parts = document.cookie.split(';');
  for (const part of parts) {
    const trimmed = part.trim();
    if (trimmed.startsWith(encodedName)) {
      return decodeURIComponent(trimmed.slice(encodedName.length));
    }
  }
  return null;
}

const api = axios.create({
  baseURL: '/api/v1',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Se for FormData, remove Content-Type para o browser enviar boundary correto.
api.interceptors.request.use(
  async (config) => {
    const method = String(config.method || 'get').toLowerCase();
    if (shouldApplyDefaultSafeRequestTimeout(config)) {
      config.timeout = DEFAULT_SAFE_REQUEST_TIMEOUT_MS;
    }

    if (!SAFE_METHODS.has(method)) {
      const csrfToken = getCookie('fortcordis_csrf');
      if (csrfToken) {
        config.headers['x-csrf-token'] = csrfToken;
      }
    }

    if (config.data instanceof FormData) {
      delete config.headers['Content-Type'];
    }

    return prepareMapsAction(api, config);
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor para tratamento de erros de autenticação
api.interceptors.response.use(
  (response) => {
    invalidateStableCatalogForMutation(response.config.method, response.config.url);
    return response;
  },
  async (error) => {
    const mapsRetry = retryMapsActionWithConsent(api, error);
    if (mapsRetry) return mapsRetry;
    const normalizedMessage = await extractApiErrorMessage(error, "Erro de comunicacao com o servidor.");
    if (error && typeof error === "object") {
      (error as { userMessage?: string }).userMessage = normalizedMessage;
    }
    if (isMapsControlError(error)) mapsConfirmationStore.notify(normalizedMessage);

    if (error.response?.status === 401) {
      const config = error.config;
      if (typeof window !== 'undefined' && config && !config._authRetried
        && !String(config.url || '').startsWith('/auth/')
        && localStorage.getItem('auth_provider') === 'supabase') {
        config._authRetried = true;
        try {
          const session = await refreshBrowserSession();
          if (config.headers?.Authorization) config.headers.Authorization = `Bearer ${session.access_token}`;
          return api.request(config);
        } catch (refreshError) {
          // Preserve the browser session during an Auth service outage.
          if (!axios.isAxiosError(refreshError) || ![401, 403].includes(refreshError.response?.status || 0)) {
            return Promise.reject(refreshError);
          }
        }
      }
      // Sessao expirada/invalidada.
      if (typeof window !== 'undefined') {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        localStorage.removeItem('auth_provider');
        window.location.href = `/?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
      }
    }
    return Promise.reject(error);
  }
);

export default api;
