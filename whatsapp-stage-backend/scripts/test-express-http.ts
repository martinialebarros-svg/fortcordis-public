import assert from "assert";
import { AddressInfo } from "net";
import { once } from "events";

import app from "../src/app";

async function closeServer(server: ReturnType<typeof app.listen>): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function run(): Promise<void> {
  const server = app.listen(0, "127.0.0.1");
  try {
    await once(server, "listening");
    const address = server.address();
    assert(address && typeof address !== "string");
    const port = (address as AddressInfo).port;

    const health = await fetch(`http://127.0.0.1:${port}/health`);
    assert.strictEqual(health.status, 200);
    assert.match(health.headers.get("content-type") || "", /application\/json/i);
    assert.strictEqual((await health.json() as { status: string }).status, "ok");

    const missingRoute = await fetch(`http://127.0.0.1:${port}/not-found`);
    assert.strictEqual(missingRoute.status, 404);
    console.log("Express HTTP smoke test passed.");
  } finally {
    await closeServer(server);
  }
}

void run().catch((error: unknown) => {
  console.error(error);
  process.exitCode = 1;
});
