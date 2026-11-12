import axios, { AxiosError } from "axios";
import { NextFunction, Request, Response } from "express";
import { logger } from "../utils/logger";

interface CoreApiRole {
  id?: number;
  nome?: string;
}

interface CoreApiUser {
  id: number;
  email: string;
  nome: string;
  ativo: number;
  papeis?: CoreApiRole[];
}

interface AuthRuntimePolicy {
  environment: string;
  isProduction: boolean;
  authEnabled: boolean;
  enforceAuthInProduction: boolean;
}

function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) {
    return fallback;
  }

  const normalized = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }

  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }

  return fallback;
}

function normalizeEnvironment(value: string | undefined): string {
  return (value || "").trim().toLowerCase();
}

function isProductionEnvironment(env: NodeJS.ProcessEnv): boolean {
  const candidates = [
    normalizeEnvironment(env.NODE_ENV),
    normalizeEnvironment(env.APP_ENV),
    normalizeEnvironment(env.ENVIRONMENT),
    normalizeEnvironment(env.ENV)
  ];
  return candidates.some((item) => item === "production" || item === "prod");
}

export function buildAuthRuntimePolicy(env: NodeJS.ProcessEnv = process.env): AuthRuntimePolicy {
  const isProduction = isProductionEnvironment(env);
  const authEnabled = parseBoolean(env.WHATSAPP_API_AUTH_ENABLED, isProduction);
  const enforceAuthInProduction = parseBoolean(env.WHATSAPP_ENFORCE_AUTH_IN_PRODUCTION, true);
  const environment =
    normalizeEnvironment(env.APP_ENV) ||
    normalizeEnvironment(env.ENVIRONMENT) ||
    normalizeEnvironment(env.ENV) ||
    normalizeEnvironment(env.NODE_ENV) ||
    "development";

  return {
    environment,
    isProduction,
    authEnabled,
    enforceAuthInProduction
  };
}

function parseRoles(value: string | undefined): Set<string> {
  if (!value) {
    return new Set<string>();
  }

  return new Set(
    value
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter((item) => item.length > 0)
  );
}

function extractBearerToken(authorizationHeader: string | undefined): string | null {
  if (!authorizationHeader) {
    return null;
  }

  const [scheme, token] = authorizationHeader.trim().split(/\s+/, 2);
  if (!scheme || !token || scheme.toLowerCase() !== "bearer") {
    return null;
  }

  return token;
}

function toRoleSet(user: CoreApiUser): Set<string> {
  const roles = new Set<string>();
  for (const role of user.papeis ?? []) {
    const normalized = (role?.nome ?? "").trim().toLowerCase();
    if (normalized.length > 0) {
      roles.add(normalized);
    }
  }
  return roles;
}

function isReadOnlyMethod(method: string): boolean {
  const normalized = method.toUpperCase();
  return normalized === "GET" || normalized === "HEAD" || normalized === "OPTIONS";
}

function isAllowedByRoles(userRoles: Set<string>, requiredRoles: Set<string>): boolean {
  if (requiredRoles.size === 0) {
    return true;
  }

  for (const role of userRoles) {
    if (requiredRoles.has(role)) {
      return true;
    }
  }

  return false;
}

const apiBackendUrl = (process.env.API_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const authPolicy = buildAuthRuntimePolicy(process.env);
const authEnabled = authPolicy.authEnabled;
const allowedRoles = parseRoles(process.env.WHATSAPP_ALLOWED_PAPEIS);
const writeAllowedRoles = parseRoles(process.env.WHATSAPP_WRITE_ALLOWED_PAPEIS);
const internalApiToken = (process.env.WHATSAPP_INTERNAL_API_TOKEN || "").trim();
let warnedAuthDisabled = false;

export function assertWhatsAppAuthPolicyOrThrow(env: NodeJS.ProcessEnv = process.env): void {
  const policy = buildAuthRuntimePolicy(env);
  if (policy.isProduction && policy.enforceAuthInProduction && !policy.authEnabled) {
    throw new Error(
      "Unsafe WhatsApp auth policy: WHATSAPP_API_AUTH_ENABLED=false em ambiente de producao."
    );
  }
}

async function fetchCurrentUser(authorizationHeader: string): Promise<CoreApiUser> {
  const response = await axios.get<CoreApiUser>(`${apiBackendUrl}/api/v1/auth/me`, {
    headers: {
      Authorization: authorizationHeader
    },
    timeout: 5000
  });

  return response.data;
}

export async function requireApiAuth(req: Request, res: Response, next: NextFunction): Promise<void> {
  if (!authEnabled) {
    if (!warnedAuthDisabled) {
      warnedAuthDisabled = true;
      logger.warn("WhatsApp API auth is disabled for protected routes", {
        environment: authPolicy.environment
      });
    }

    next();
    return;
  }

  const providedInternalToken = (req.header("x-whatsapp-internal-token") || "").trim();
  if (internalApiToken && providedInternalToken && providedInternalToken === internalApiToken) {
    req.authUser = {
      id: null,
      email: null,
      nome: "internal_automation",
      papeis: ["internal_automation"],
      authSource: "internal_token"
    };
    next();
    return;
  }

  const bearerToken = extractBearerToken(req.header("authorization") || undefined);
  if (!bearerToken) {
    res.status(401).json({ error: "Missing or invalid Authorization Bearer token" });
    return;
  }

  const authorizationHeader = `Bearer ${bearerToken}`;

  try {
    const user = await fetchCurrentUser(authorizationHeader);

    if (user.ativo !== 1) {
      res.status(403).json({ error: "User inactive" });
      return;
    }

    const userRoles = toRoleSet(user);
    const requiredRoles =
      isReadOnlyMethod(req.method) || writeAllowedRoles.size === 0 ? allowedRoles : writeAllowedRoles;

    if (!isAllowedByRoles(userRoles, requiredRoles)) {
      res.status(403).json({
        error: "Forbidden: insufficient role for WhatsApp stage endpoint"
      });
      return;
    }

    req.authUser = {
      id: user.id,
      email: user.email,
      nome: user.nome,
      papeis: [...userRoles],
      authSource: "core_api"
    };

    next();
  } catch (error: unknown) {
    const axiosError = error as AxiosError;
    const status = axiosError.response?.status;

    if (status === 401 || status === 403) {
      res.status(status).json({ error: "Unauthorized token for WhatsApp stage endpoint" });
      return;
    }

    logger.error("Failed to validate auth token against core API", {
      status,
      message: axiosError.message,
      apiBackendUrl
    });
    res.status(503).json({ error: "Auth service unavailable" });
  }
}
