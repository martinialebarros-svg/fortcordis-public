import assert from "assert";
import axios from "axios";
import { sendWhatsAppReservationTemplateWithRetry } from "../src/services/whatsappService";

async function run(): Promise<void> {
  const originalPost = axios.post;
  let capturedUrl = "";
  let capturedPayload: any;

  try {
    (axios.post as unknown as (url: string, payload: unknown) => Promise<unknown>) = async (url, payload) => {
      capturedUrl = url;
      capturedPayload = payload;
      return {
        data: {
          messaging_product: "whatsapp",
          messages: [{ id: "wamid.template.success" }]
        }
      };
    };

    const response = await sendWhatsAppReservationTemplateWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      to: "558588281436",
      templateName: "reserva_de_agendamento",
      languageCode: "pt_BR",
      bodyParameters: ["Maria", "Thor", "12/08/2026", "14:30", "11/08/2026 às 18:00"],
      confirmPayload: "random-confirm-payload",
      changePayload: "random-change-payload"
    });

    assert.match(capturedUrl, /\/1279142515283484\/messages$/);
    assert.strictEqual(capturedPayload.type, "template");
    assert.strictEqual(capturedPayload.template.name, "reserva_de_agendamento");
    assert.strictEqual(capturedPayload.template.language.code, "pt_BR");
    assert.deepStrictEqual(
      capturedPayload.template.components[0].parameters.map((item: { text: string }) => item.text),
      ["Maria", "Thor", "12/08/2026", "14:30", "11/08/2026 às 18:00"]
    );
    assert.deepStrictEqual(capturedPayload.template.components[1], {
      type: "button",
      sub_type: "quick_reply",
      index: "0",
      parameters: [{ type: "payload", payload: "random-confirm-payload" }]
    });
    assert.deepStrictEqual(capturedPayload.template.components[2], {
      type: "button",
      sub_type: "quick_reply",
      index: "1",
      parameters: [{ type: "payload", payload: "random-change-payload" }]
    });
    assert.strictEqual(response.messages?.[0]?.id, "wamid.template.success");
    console.log("Reservation template payload test passed.");
  } finally {
    axios.post = originalPost;
  }
}

void run().catch((error) => {
  console.error("Reservation template payload test failed:", error);
  process.exit(1);
});
