import assert from "assert";
import {
  areEquivalentWhatsAppNumbers,
  canonicalWhatsAppIdentity,
  digitsOnly,
  shouldForceBrMobileNinthDigit,
  whatsappGraphRecipient
} from "../src/utils/phoneNumber";

function run(): void {
  assert.strictEqual(digitsOnly("+55 (85) 98801-8899"), "5585988018899");
  assert.strictEqual(canonicalWhatsAppIdentity("5585988018899"), "558588018899");
  assert.strictEqual(canonicalWhatsAppIdentity("558588018899"), "558588018899");
  // Default DESLIGADO: e o comportamento de producao, que entrega hoje.
  // Medido em 2026-08-24: 96 saidas sent/delivered/read contra 1 falha, em 30
  // conversas com identidade de 12 digitos. Reescrever esse destino seria
  // trocar evidencia por suposicao num canal vivo.
  delete process.env.WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT;
  assert.strictEqual(shouldForceBrMobileNinthDigit(), false);
  assert.strictEqual(whatsappGraphRecipient("558588018899"), "558588018899");
  assert.strictEqual(whatsappGraphRecipient("5585988018899"), "5585988018899");
  assert.strictEqual(whatsappGraphRecipient("558532101234"), "558532101234");
  assert.strictEqual(whatsappGraphRecipient("14155552671"), "14155552671");

  // Valor diferente de "true" nao liga: so o opt-in explicito conta.
  process.env.WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT = "1";
  assert.strictEqual(whatsappGraphRecipient("558588018899"), "558588018899");

  // LIGADO: necessario para o numero de TESTE da Meta em stage, cuja lista de
  // permitidos guarda o numero com o nono digito.
  process.env.WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT = "true";
  assert.strictEqual(shouldForceBrMobileNinthDigit(), true);
  assert.strictEqual(whatsappGraphRecipient("558588018899"), "5585988018899");
  assert.strictEqual(whatsappGraphRecipient("5585988018899"), "5585988018899");
  // Fixo brasileiro e numero internacional nao mudam nem com a flag ligada.
  assert.strictEqual(whatsappGraphRecipient("558532101234"), "558532101234");
  assert.strictEqual(whatsappGraphRecipient("14155552671"), "14155552671");
  delete process.env.WHATSAPP_GRAPH_FORCE_BR_MOBILE_NINTH_DIGIT;

  assert.strictEqual(areEquivalentWhatsAppNumbers("5585988018899", "558588018899"), true);
  assert.strictEqual(areEquivalentWhatsAppNumbers("+55 85 98801-8899", "55 85 8801-8899"), true);
  assert.strictEqual(areEquivalentWhatsAppNumbers("5585988018899", "558588018898"), false);
  assert.strictEqual(areEquivalentWhatsAppNumbers("5585988018899", "558688018899"), false);
  assert.strictEqual(areEquivalentWhatsAppNumbers("", ""), false);
  assert.strictEqual(areEquivalentWhatsAppNumbers("14155552671", "14155552671"), true);
  assert.strictEqual(areEquivalentWhatsAppNumbers("14155552671", "14155552672"), false);

  console.log("WhatsApp phone identity tests passed.");
}

try {
  run();
} catch (error) {
  console.error("WhatsApp phone identity tests failed:", error);
  process.exit(1);
}
