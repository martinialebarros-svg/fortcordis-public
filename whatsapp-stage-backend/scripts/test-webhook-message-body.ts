import assert from "assert";
import { extractMessageBody } from "../src/controllers/webhookController";

function run(): void {
  assert.strictEqual(extractMessageBody({ type: "text", text: { body: "Ola" } }), "Ola");
  assert.strictEqual(extractMessageBody({ type: "image", image: { caption: "Foto do exame" } }), "Foto do exame");
  assert.strictEqual(extractMessageBody({ type: "image" }), "[image]");
  assert.strictEqual(extractMessageBody({ type: "audio" }), "[audio]");
  assert.strictEqual(extractMessageBody({ type: "reaction", reaction: { emoji: "👍" } }), "Reagiu com 👍");
  assert.strictEqual(extractMessageBody({ type: "reaction", reaction: { emoji: "" } }), "Removeu a reação");
  assert.strictEqual(extractMessageBody({ type: "reaction" }), "Removeu a reação");
  assert.strictEqual(extractMessageBody({ type: "unknown_future_type" }), "");

  console.log("Webhook message body extraction contracts passed.");
}

try {
  run();
} catch (error) {
  console.error("Webhook message body test failed:", error);
  process.exit(1);
}
