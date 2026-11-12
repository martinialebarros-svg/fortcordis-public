import "dotenv/config";
import fs from "fs/promises";
import path from "path";
import { Client } from "pg";
import { buildPostgresConfig } from "../config/database";

async function runMigration(): Promise<void> {
  const databaseUrl = process.env.DATABASE_URL;

  if (!databaseUrl) {
    throw new Error("DATABASE_URL is required");
  }

  const migrationFiles = ["init.sql", "quick-replies.sql"];
  const migrations = await Promise.all(migrationFiles.map((file) =>
    fs.readFile(path.resolve(__dirname, "../../migrations", file), "utf8")
  ));

  const client = new Client(buildPostgresConfig(databaseUrl));

  await client.connect();
  try {
    await client.query("BEGIN");
    for (const sql of migrations) await client.query(sql);
    await client.query("COMMIT");
    console.log("Migration applied successfully.");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    await client.end();
  }
}

void runMigration().catch((error: unknown) => {
  if (error instanceof Error) {
    console.error("Migration failed:", error.message);
    const maybeAggregate = error as Error & { errors?: unknown[] };
    if (Array.isArray(maybeAggregate.errors) && maybeAggregate.errors.length > 0) {
      console.error("Inner errors:");
      for (const inner of maybeAggregate.errors) {
        if (inner instanceof Error) {
          console.error(`- ${inner.name}: ${inner.message}`);
        } else {
          console.error("-", inner);
        }
      }
    }
    if (error.stack) {
      console.error(error.stack);
    }
  } else {
    console.error("Migration failed with non-Error object:", error);
  }
  process.exit(1);
});
