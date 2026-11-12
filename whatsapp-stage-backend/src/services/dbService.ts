import { Pool, PoolClient, QueryResult, QueryResultRow } from "pg";
import { buildPostgresConfig } from "../config/database";
import { logger } from "../utils/logger";

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required");
}

export const pool = new Pool(buildPostgresConfig(databaseUrl));

pool.on("error", (err: Error) => {
  logger.error("Unexpected PostgreSQL pool error", { message: err.message });
});

export function extractDbErrorDetails(error: unknown): Record<string, unknown> {
  const err = error as Error & {
    code?: string;
    detail?: string;
    hint?: string;
    errors?: unknown[];
  };

  return {
    name: err?.name,
    message: err?.message,
    code: err?.code,
    detail: err?.detail,
    hint: err?.hint,
    inner_errors: Array.isArray(err?.errors)
      ? err.errors.map((inner) => {
          if (inner instanceof Error) {
            return {
              name: inner.name,
              message: inner.message
            };
          }

          return { value: String(inner) };
        })
      : undefined
  };
}

export async function query<T extends QueryResultRow = QueryResultRow>(
  text: string,
  params: unknown[] = []
): Promise<QueryResult<T>> {
  try {
    return await pool.query<T>(text, params);
  } catch (error) {
    logger.error("PostgreSQL query failed", {
      sql: text,
      details: extractDbErrorDetails(error)
    });
    throw error;
  }
}

export async function queryWithClient<T extends QueryResultRow = QueryResultRow>(
  client: PoolClient | undefined | null,
  text: string,
  params: unknown[] = []
): Promise<QueryResult<T>> {
  if (!client) {
    return query<T>(text, params);
  }

  try {
    return await client.query<T>(text, params);
  } catch (error) {
    logger.error("PostgreSQL client query failed", {
      sql: text,
      details: extractDbErrorDetails(error)
    });
    throw error;
  }
}

export async function withClient<T>(callback: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    return await callback(client);
  } finally {
    client.release();
  }
}

export async function withTransaction<T>(callback: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();

  try {
    await client.query("BEGIN");
    const result = await callback(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK");
    logger.error("PostgreSQL transaction failed", extractDbErrorDetails(error));
    throw error;
  } finally {
    client.release();
  }
}

export async function ensureDbConnection(): Promise<void> {
  try {
    await query("SELECT 1");
    logger.info("PostgreSQL connection is ready");
  } catch (error) {
    const details = extractDbErrorDetails(error);
    const message = typeof details.message === "string" ? details.message : "unknown PostgreSQL connection error";
    throw new Error(`Could not connect to PostgreSQL (${message})`);
  }
}

export async function closeDbPool(): Promise<void> {
  await pool.end();
}
