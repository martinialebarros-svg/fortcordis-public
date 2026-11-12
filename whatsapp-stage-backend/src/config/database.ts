import type { PoolConfig } from "pg";

const ALLOWED_BOOLEAN_VALUES = new Set(["true", "false"]);

export function buildPostgresConfig(
  databaseUrl: string,
  rejectUnauthorizedSetting = process.env.DATABASE_SSL_REJECT_UNAUTHORIZED,
  poolMaxSetting = process.env.WHATSAPP_DATABASE_POOL_MAX
): PoolConfig {
  const normalizedPoolMax = poolMaxSetting?.trim();
  const poolLimits: Pick<PoolConfig, "max"> = {};
  if (normalizedPoolMax) {
    const poolMax = Number(normalizedPoolMax);
    if (!/^\d+$/.test(normalizedPoolMax) || !Number.isInteger(poolMax) || poolMax < 1 || poolMax > 10) {
      throw new Error("WHATSAPP_DATABASE_POOL_MAX must be an integer between 1 and 10");
    }
    poolLimits.max = poolMax;
  }

  const normalizedSetting = rejectUnauthorizedSetting?.trim().toLowerCase();

  if (!normalizedSetting) {
    return { connectionString: databaseUrl, ...poolLimits };
  }

  if (!ALLOWED_BOOLEAN_VALUES.has(normalizedSetting)) {
    throw new Error("DATABASE_SSL_REJECT_UNAUTHORIZED must be true or false");
  }

  if (normalizedSetting === "true") {
    return { connectionString: databaseUrl, ...poolLimits };
  }

  const parsedUrl = new URL(databaseUrl);
  if (!new Set(["postgres:", "postgresql:"]).has(parsedUrl.protocol)) {
    throw new Error("DATABASE_URL must use the postgres or postgresql protocol");
  }

  const sslMode = parsedUrl.searchParams.get("sslmode")?.toLowerCase();
  if (sslMode !== "require") {
    throw new Error(
      "DATABASE_SSL_REJECT_UNAUTHORIZED=false requires DATABASE_URL with sslmode=require"
    );
  }

  for (const certificateParameter of ["sslcert", "sslkey", "sslrootcert"]) {
    if (parsedUrl.searchParams.has(certificateParameter)) {
      throw new Error(
        "DATABASE_SSL_REJECT_UNAUTHORIZED=false cannot override explicit database certificates"
      );
    }
  }

  // node-postgres lets sslmode from the URL replace an explicit ssl object.
  // Remove only that parser option and keep TLS enabled with a scoped policy.
  parsedUrl.searchParams.delete("sslmode");
  parsedUrl.searchParams.delete("uselibpqcompat");

  return {
    connectionString: parsedUrl.toString(),
    ssl: { rejectUnauthorized: false },
    ...poolLimits
  };
}
