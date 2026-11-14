import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright-core";

// Build with API_BACKEND_URL=http://127.0.0.1:19464 before running this smoke.
const apiPort = 19464;
const frontendPort = 19465;
const origin = `http://127.0.0.1:${frontendPort}`;
const editor = `${origin}/laudos/novo`;
const list = `${origin}/laudos`;
const session = {
  user_id: 1, nome: "QA Fictício", email: "qa@example.invalid", papeis: [],
  access_token: "qa-only", provider: "legacy", expires_at: null,
};
const drafts = new Map();
const unexpectedWrites = [];
let rejectNextDraftWrite = false;

const api = createServer(async (request, response) => {
  const path = new URL(request.url, origin).pathname.replace(/^\/api\/v1/, "");
  const reply = (status, value) => {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(value));
  };
  if (request.method === "GET" && path === "/auth/session") {
    return reply(request.headers.cookie?.includes("fortcordis_session=qa-only") ? 200 : 401, session);
  }
  if (request.method === "POST" && path === "/observability/frontend-performance") {
    return reply(200, {});
  }
  const draftId = /^\/laudos\/editor-drafts\/([\w-]+)$/.exec(path)?.[1];
  if (draftId && request.headers["x-editor-owner-id"] === "1") {
    const current = drafts.get(draftId);
    if (request.method === "GET") return current ? reply(200, current) : reply(404, {});
    if (request.method === "PUT") {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks));
      if (rejectNextDraftWrite) {
        rejectNextDraftWrite = false;
        return reply(503, {});
      }
      if (body.expected_revision !== (current?.revision ?? 0)) return reply(409, {});
      const record = {
        draft_id: draftId, context_key: body.context_key, snapshot: body.snapshot,
        revision: body.expected_revision + 1, updated_at: new Date().toISOString(),
      };
      drafts.set(draftId, record);
      return reply(200, record);
    }
  }
  if (request.method !== "GET") {
    unexpectedWrites.push(`${request.method} ${path}`);
    return reply(405, {});
  }
  if (path === "/configuracoes") return reply(200, {});
  if (path === "/configuracoes/logomarca") return reply(404, {});
  return reply(200, { items: [], total: 0 });
});

const require = createRequire(import.meta.url);
let frontend;
let exited;
let browser;
try {
  api.listen(apiPort, "127.0.0.1");
  await once(api, "listening");
  frontend = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "start",
    "--hostname", "127.0.0.1", "--port", String(frontendPort)], {
    env: { ...process.env, API_BACKEND_URL: `http://127.0.0.1:${apiPort}` }, stdio: "inherit",
  });
  exited = once(frontend, "exit");
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    assert.equal(frontend.exitCode, null, "Next.js não iniciou. Rode o build antes do smoke.");
    if ((await fetch(origin).catch(() => null))?.ok) { ready = true; break; }
    await delay(100);
  }
  assert.ok(ready, "Next.js não respondeu no loopback.");
  browser = await chromium.launch({ channel: process.env.ECHO_QA_CHROME_CHANNEL || "chrome" });
  for (const scenario of ["button", "sidebar", "save-failure", "stalled-router", "superseded-route"]) {
    const context = await browser.newContext();
    try {
      // A página e as requisições do Chrome ficam limitadas ao servidor local.
      await context.route((url) => url.origin !== origin, (route) => route.abort());
      await context.addCookies([{ name: "fortcordis_session", value: "qa-only", url: origin, httpOnly: true }]);
      await context.addInitScript(({ appOrigin, qaSession }) => {
        if (location.origin !== appOrigin) return;
        localStorage.setItem("token", qaSession.access_token);
        localStorage.setItem("user", JSON.stringify({ id: qaSession.user_id }));
      }, { appOrigin: origin, qaSession: session });
      const page = await context.newPage();
      page.setDefaultTimeout(12_000);
      const trace = [];
      let listDocuments = 0;
      page.on("console", (message) => {
        if (message.text().startsWith("[laudo-rascunho:saida] ")) trace.push(message.text().split("] ")[1]);
      });
      page.on("request", (request) => {
        if (request.isNavigationRequest() && request.url() === list) listDocuments++;
      });
      let releaseTransition;
      let markTransitionStarted;
      const transitionStarted = new Promise((resolve) => { markTransitionStarted = resolve; });
      const stalledTransition = new Promise((resolve) => { releaseTransition = resolve; });
      if (["stalled-router", "superseded-route"].includes(scenario)) {
        await page.route((url) => url.origin === origin && url.pathname === "/laudos", async (route) => {
          if (route.request().isNavigationRequest()) {
            await route.continue();
            return;
          }
          // The click may reuse a pending App Router prefetch for this URL.
          markTransitionStarted();
          await stalledTransition;
          await route.abort().catch(() => {});
        });
      }
      const field = (name) => page.locator("label").filter({ hasText: name }).locator("..").locator("input");
      const diastole = field(/^DIVEd \(mm/);
      const aorta = field(/^Aorta \(mm\)$/);
      try {
        await page.goto(editor);
        await field(/^Nome do Paciente$/).fill("QA FICTÍCIO NAVEGAÇÃO");
        await page.getByRole("button", { name: "Medidas", exact: true }).click();
        await diastole.fill("30");
        await aorta.fill("10");
        await page.getByRole("button", { name: "Salvar rascunho", exact: true }).click();
        await page.getByText(/Rascunho salvo às/).waitFor();

        const back = page.getByRole("button", { name: "Voltar para laudos", exact: true });
        if (scenario === "sidebar") {
          await page.getByRole("navigation", { name: "Navegação principal" })
            .getByRole("link", { name: "Laudos", exact: true }).click();
        } else {
          if (scenario === "save-failure") {
            await diastole.fill("31");
            rejectNextDraftWrite = true;
          }
          await back.click();
        }
        if (scenario === "save-failure") {
          await page.getByText(/Não foi possível confirmar o rascunho antes de sair/).waitFor();
          assert.equal(page.url(), editor);
          assert.equal(await diastole.inputValue(), "31");
          assert.deepEqual(trace, ["inicio", "rascunho-nao-confirmado"]);
          await back.click();
        }
        if (["stalled-router", "superseded-route"].includes(scenario)) {
          await Promise.race([transitionStarted, delay(3_000, false).then(() => {
            throw new Error("O roteador não solicitou a próxima página.");
          })]);
          await page.getByRole("status").filter({ hasText: "Saindo do editor" }).waitFor();
          assert.equal(await back.isEnabled(), false);
          assert.equal(page.url(), editor);
        }
        if (scenario === "superseded-route") {
          await page.goto(`${origin}/laudos?qa=outra-navegacao`);
          await page.getByRole("heading", { name: "Central de laudos" }).waitFor();
          await delay(4_200);
          assert.equal(page.url(), `${origin}/laudos?qa=outra-navegacao`);
          assert.equal(listDocuments, 0);
          assert.equal(trace.includes("navegacao-documento"), false);
          console.log(`Chrome: ${scenario} aprovado.`);
          continue;
        }
        await page.waitForURL(list);
        await page.getByRole("heading", { name: "Central de laudos" }).waitFor();
        const expected = ["inicio", "rascunho-confirmado", "rota-solicitada"];
        if (scenario === "stalled-router") expected.push("navegacao-documento");
        assert.deepEqual(trace.slice(-expected.length), expected);
        assert.equal(listDocuments, scenario === "stalled-router" ? 1 : 0);
      } finally {
        releaseTransition();
      }

      await page.getByRole("button", { name: "Novo Laudo", exact: true }).click();
      await page.getByRole("menuitem", { name: /Laudo estruturado/ }).click();
      await page.waitForURL(editor);
      const emit = page.getByRole("button", { name: "Emitir laudo", exact: true });
      const resume = page.getByRole("button", { name: "Retomar rascunho", exact: true });
      await resume.waitFor();
      assert.equal(await emit.isEnabled(), false);
      await resume.click();
      await page.getByRole("button", { name: "Medidas", exact: true }).click();
      assert.equal(await diastole.inputValue(), scenario === "save-failure" ? "31" : "30");
      assert.equal(await aorta.inputValue(), "10");
      assert.equal(await emit.isEnabled(), true);
      console.log(`Chrome: ${scenario} aprovado.`);
    } finally {
      await context.close();
    }
  }
  assert.deepEqual(unexpectedWrites, []);
} finally {
  await browser?.close();
  if (frontend && frontend.exitCode === null) {
    frontend.kill("SIGTERM");
    const stop = setTimeout(() => frontend.kill("SIGKILL"), 5_000);
    try { await exited; }
    finally { clearTimeout(stop); }
  }
  api.close();
}
