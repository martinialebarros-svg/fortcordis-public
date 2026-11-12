import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createRequire } from "node:module";
import { request as httpRequest } from "node:http";
import { setTimeout as delay } from "node:timers/promises";

const require = createRequire(import.meta.url);
const port = 19463;
const origin = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start",
  "--hostname", "127.0.0.1", "--port", String(port)], { stdio: "ignore" });
const exited = once(server, "exit");
const get = (path, host) => new Promise((resolve, reject) => {
  // Node fetch may replace Host with the loopback URL's authority.
  const request = httpRequest(new URL(path, origin), {
    headers: { host, "x-forwarded-host": host, "x-forwarded-proto": "https" },
  }, (response) => {
    response.resume();
    resolve({ status: response.statusCode, headers: { get: (name) => response.headers[name] ?? null } });
  });
  request.setTimeout(5000, () => request.destroy(new Error("Smoke HTTP timeout")));
  request.on("error", reject);
  request.end();
});

try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    assert.equal(server.exitCode, null, "Compiled Next server exited before readiness");
    try { await get("/", "app.stage.fortcordis.com.br"); ready = true; break; }
    catch { await delay(100); }
  }
  assert.ok(ready, "Compiled Next server did not become ready");
  let count = 0;
  for (const host of ["app.stage.fortcordis.com.br", "app.fortcordis.com.br"]) {
    for (const path of ["/dashboard", "/fiscal?aba=rotina", "/agenda?_rsc=synthetic"]) {
      const response = await get(path, host);
      assert.equal(response.status, 307, `${host}${path}`);
      const target = new URL(response.headers.get("location"));
      assert.equal(target.origin, `https://${host}`);
      assert.equal(target.pathname, "/");
      // Next removes its private RSC cache marker before middleware routing.
      assert.equal(target.searchParams.get("next"), path.replace("?_rsc=synthetic", ""));
      assert.match(response.headers.get("cache-control"), /no-store/);
      count++;
    }
  }
  const institution = await get("/dashboard", "stage.fortcordis.com.br");
  assert.equal(institution.status, 307);
  assert.equal(institution.headers.get("location"), "https://app.stage.fortcordis.com.br/dashboard");
  count++;
  const invalidHost = await get("/dashboard", "evil.invalid");
  assert.equal(invalidHost.status, 503);
  assert.equal(invalidHost.headers.get("location"), null);
  count++;
  assert.equal((await get("/%64ashboard", "app.stage.fortcordis.com.br")).status, 404);
  count++;
  assert.equal((await get("/clinica-parceira", "app.stage.fortcordis.com.br")).status, 200);
  count++;
  console.log(`Compiled Auth proxy smoke: ${count} checks passed.`);
} finally {
  server.kill("SIGTERM");
  await Promise.race([exited, delay(5000).then(() => server.kill("SIGKILL"))]);
}
