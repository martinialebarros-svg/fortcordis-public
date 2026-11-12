import assert from "assert";
import axios from "axios";
import { buildAgendaButtonReceipt } from "../src/services/agendaButtonReceipt";
import { sendWhatsAppApprovedUtilityTemplateWithRetry } from "../src/services/whatsappService";
import {
  APPROVED_TEMPLATE_LANGUAGE,
  APPROVED_UTILITY_TEMPLATES,
  getTemplateBodyParameterCount,
  isTemplateDeliveryApproved,
  renderApprovedTemplateBody
} from "../src/templates/approvedTemplates";

async function run(): Promise<void> {
  const expectedCatalog = {
    reservation: ["reserva_de_agendamento", "1850190569695780", 5, 2],
    appointmentReminder: ["lembrete_de_agendamento", "2196951517539589", 4, 2],
    appointmentReminderService: ["lembrete_de_agendamento_servico_v2", "1647759970059717", 5, 2],
    appointmentChange: ["alteracao_de_agendamento", "1325207582741137", 4, 2],
    appointmentCancellation: ["cancelamento_de_agendamento", "1072585772303343", 4, 2],
    appointmentMissingData: ["dados_pendentes_agendamento", "2094851784715594", 4, 2],
    appointmentFormalized: ["agendamento_formalizado", "PENDING_META_APPROVAL", 7, 0],
    portalReportAvailable: ["laudo_disponivel_portal", "1682393009502350", 3, 0],
    portalReportLink: ["laudo_disponivel_portal_link", "1341477634545137", 4, 0],
    homeReportPdf: ["laudo_domiciliar_pdf_tutor", "1445021354358408", 2, 0],
    receiptAvailable: ["recibo_disponivel", "934407008986859", 4, 1],
    receiptPdf: ["recibo_pagamento_pdf", "1025876410335393", 7, 1],
    receiptPdfBulk: ["recibo_pagamento_pdf_multiplas_os", "940165775772306", 3, 1],
    pendingPaymentReminder: ["lembrete_pagamento_pendente_detalhado", "1265598002271332", 7, 2],
    pendingPaymentReminderBulk: ["lembrete_pagamento_pendente_multiplas_os", "1574210064240409", 4, 2],
    portalClinicInviteActivation: ["convite_portal_clinica_v2", "1402681525155612", 3, 0],
    portalClinicInviteLoginAccess: ["acesso_portal_clinica", "1758345232162346", 3, 0],
    portalClinicInviteTemporaryPassword: ["senha_temporaria_portal_clinica", "1087880320425546", 4, 0]
  } as const;

  assert.strictEqual(Object.keys(APPROVED_UTILITY_TEMPLATES).length, Object.keys(expectedCatalog).length);
  assert.strictEqual(APPROVED_TEMPLATE_LANGUAGE, "pt_BR");
  for (const [templateKey, definition] of Object.entries(APPROVED_UTILITY_TEMPLATES)) {
    const expected = expectedCatalog[templateKey as keyof typeof expectedCatalog];
    assert.deepStrictEqual(
      [
        definition.name,
        definition.metaId,
        getTemplateBodyParameterCount(templateKey as keyof typeof APPROVED_UTILITY_TEMPLATES),
        definition.quickReplies.length
      ],
      expected
    );
    assert.strictEqual(
      definition.quickReplies.length,
      definition.buttonActions.length,
      `${templateKey} must keep quick replies and actions aligned`
    );
  }
  assert.strictEqual(getTemplateBodyParameterCount("reservation"), 5);
  assert.strictEqual(getTemplateBodyParameterCount("portalReportAvailable"), 3);
  assert.strictEqual(getTemplateBodyParameterCount("appointmentReminder"), 4, "the existing Meta contract stays unchanged");
  assert.strictEqual(getTemplateBodyParameterCount("appointmentReminderService"), 5);
  assert.deepStrictEqual(APPROVED_UTILITY_TEMPLATES.appointmentReminderService.buttonActions,
    ["confirmar_presenca", "solicitar_alteracao"]);
  assert.strictEqual(APPROVED_UTILITY_TEMPLATES.appointmentReminderService.approvedBusinessAccountId, "1369494994627980");
  assert.strictEqual(renderApprovedTemplateBody("appointmentReminderService", ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"]),
    "Olá, Clínica teste. Lembramos que o atendimento de Pet teste está agendado para 15/10/2026, às 14:00. " +
    "Serviço agendado: Eletrocardiograma. Confira o serviço e o horário. Se precisar corrigir ou incluir outro serviço, " +
    "toque em Solicitar alteração e envie o que deve ser ajustado.");
  assert.throws(() => renderApprovedTemplateBody("appointmentReminderService", ["Clínica teste", "Pet teste", "15/10/2026", "14:00"]),
    /expects 5 body parameters/, "a missing service cannot silently render the reminder");
  const presence = { agendamento_id: 42, action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" };
  assert.deepStrictEqual(buildAgendaButtonReceipt("appointmentReminderService", "confirmar_presenca", 42, presence),
    { source: "appointmentReminder", action: "confirmar_presenca", result: "presenca_confirmada", status: "Agendado" });
  assert.strictEqual(buildAgendaButtonReceipt("appointmentReminderFuture", "confirmar_presenca", 42, presence), undefined,
    "only the explicit successor is normalized to the existing reminder receipt");
  assert.strictEqual(
    renderApprovedTemplateBody("reservation", [
      "Animal Care",
      "gamora",
      "15/08/2026",
      "09:00",
      "14/08/2026 às 21:02"
    ]),
    "Olá, Animal Care. A Fort Cordis reservou o atendimento de gamora para 15/08/2026, às 09:00. " +
      "Confirme até 14/08/2026 às 21:02. Após esse prazo, o horário poderá ser disponibilizado para outros clientes automaticamente."
  );
  assert.throws(
    () => renderApprovedTemplateBody("receiptAvailable", ["Animal Care"]),
    /expects 4 body parameters/
  );

  const originalPost = axios.post;
  const serviceReminderDefinition = APPROVED_UTILITY_TEMPLATES.appointmentReminderService as unknown as { metaId: string };
  const originalServiceReminderMetaId = serviceReminderDefinition.metaId;
  const originalBusinessAccountId = process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
  const capturedPayloads: any[] = [];
  try {
    (axios.post as unknown as (url: string, payload: unknown) => Promise<unknown>) = async (_url, payload) => {
      capturedPayloads.push(payload);
      return {
        data: {
          messaging_product: "whatsapp",
          messages: [{ id: `wamid.approved.${capturedPayloads.length}` }]
        }
      };
    };

    await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      to: "558588281436",
      templateKey: "portalReportAvailable",
      bodyParameters: ["Animal Care", "Ecocardiograma", "gamora"],
      quickReplyPayloads: []
    });
    await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "1279142515283484",
      accessToken: "secret-token",
      to: "558588281436",
      templateKey: "pendingPaymentReminder",
      bodyParameters: [
        "Animal Care",
        "12345",
        "Ecocardiograma",
        "15/08/2026",
        "Maria",
        "gamora",
        "R$ 350,00"
      ],
      quickReplyPayloads: ["payment-confirmed-token", "finance-contact-token"]
    });

    assert.strictEqual(capturedPayloads[0].template.name, "laudo_disponivel_portal");
    assert.strictEqual(capturedPayloads[0].template.language.code, "pt_BR");
    assert.strictEqual(capturedPayloads[0].template.components.length, 1);
    assert.strictEqual(capturedPayloads[1].template.name, "lembrete_pagamento_pendente_detalhado");
    assert.strictEqual(capturedPayloads[1].template.components.length, 3);
    assert.deepStrictEqual(capturedPayloads[1].template.components[2], {
      type: "button",
      sub_type: "quick_reply",
      index: "1",
      parameters: [{ type: "payload", payload: "finance-contact-token" }]
    });
    process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = "1369494994627980";
    for (const unavailableId of ["PENDING_META_APPROVAL", "", "0", "-1", "123abc", "1e5"]) {
      serviceReminderDefinition.metaId = unavailableId;
      assert.strictEqual(isTemplateDeliveryApproved("appointmentReminderService"), false);
    }
    assert.strictEqual(isTemplateDeliveryApproved("appointmentReminder"), true);
    assert.strictEqual(isTemplateDeliveryApproved("appointmentFormalized"), true, "the existing formalization behavior is untouched");
    await assert.rejects(() => sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "synthetic-phone-id", accessToken: "synthetic-token", to: "558500000000",
      templateKey: "appointmentReminderService",
      bodyParameters: ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"],
      quickReplyPayloads: ["synthetic-presence-token", "synthetic-change-token"]
    }), (error: unknown) => error instanceof Error
      && error.message === "O lembrete com serviço aguarda aprovação da Meta."
      && (error as Error & { statusCode: number }).statusCode === 409);
    assert.strictEqual(capturedPayloads.length, 2, "an unapproved template never reaches Graph");
    // Exercise the approved branch using an in-memory synthetic ID only.
    serviceReminderDefinition.metaId = "99900000000001";
    for (const unavailableAccount of [undefined, "", "invalid", "4413513738886247", "1369494994627980 "]) {
      if (unavailableAccount === undefined) delete process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
      else process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = unavailableAccount;
      assert.strictEqual(isTemplateDeliveryApproved("appointmentReminderService"), false,
        "a valid global ID does not approve a missing, invalid, or stage WABA");
      assert.strictEqual(isTemplateDeliveryApproved("appointmentReminder"), true, "legacy reminders keep working in other accounts");
      assert.strictEqual(isTemplateDeliveryApproved("appointmentFormalized"), true, "existing formalization is outside this approval gate");
      await assert.rejects(() => sendWhatsAppApprovedUtilityTemplateWithRetry({
        phoneNumberId: "synthetic-phone-id", accessToken: "synthetic-token", to: "558500000000",
        templateKey: "appointmentReminderService",
        bodyParameters: ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"],
        quickReplyPayloads: ["synthetic-presence-token", "synthetic-change-token"]
      }), (error: unknown) => error instanceof Error
        && (error as Error & { statusCode: number }).statusCode === 409);
      assert.strictEqual(capturedPayloads.length, 2, "unapproved account cannot call Graph");
    }
    process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = "1369494994627980";
    assert.strictEqual(isTemplateDeliveryApproved("appointmentReminderService"), true);
    await sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "synthetic-phone-id", accessToken: "synthetic-token", to: "558500000000",
      templateKey: "appointmentReminderService",
      bodyParameters: ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"],
      quickReplyPayloads: ["synthetic-presence-token", "synthetic-change-token"]
    });
    assert.strictEqual(capturedPayloads[2].template.name, "lembrete_de_agendamento_servico_v2");
    assert.deepStrictEqual(capturedPayloads[2].template.components[0].parameters.map((item: { text: string }) => item.text),
      ["Clínica teste", "Pet teste", "15/10/2026", "14:00", "Eletrocardiograma"], "the service is always variable five");
    assert.deepStrictEqual(capturedPayloads[2].template.components[2], {
      type: "button", sub_type: "quick_reply", index: "1",
      parameters: [{ type: "payload", payload: "synthetic-change-token" }]
    });
    await assert.rejects(() => sendWhatsAppApprovedUtilityTemplateWithRetry({
      phoneNumberId: "synthetic-phone-id", accessToken: "synthetic-token", to: "558500000000",
      templateKey: "appointmentReminderService",
      bodyParameters: ["Clínica teste", "Pet teste", "15/10/2026", "14:00"],
      quickReplyPayloads: ["synthetic-presence-token", "synthetic-change-token"]
    }), /expects 5 body parameters/);

    await assert.rejects(
      () =>
        sendWhatsAppApprovedUtilityTemplateWithRetry({
          phoneNumberId: "1279142515283484",
          accessToken: "secret-token",
          to: "558588281436",
          templateKey: "appointmentReminder",
          bodyParameters: ["Animal Care"],
          quickReplyPayloads: []
        }),
      /expects 4 body parameters/
    );
    assert.strictEqual(capturedPayloads.length, 3, "invalid parameters fail before any provider request");
  } finally {
    axios.post = originalPost;
    serviceReminderDefinition.metaId = originalServiceReminderMetaId;
    if (originalBusinessAccountId === undefined) delete process.env.WHATSAPP_BUSINESS_ACCOUNT_ID;
    else process.env.WHATSAPP_BUSINESS_ACCOUNT_ID = originalBusinessAccountId;
  }

  console.log("Approved template catalog and payload tests passed.");
}

void run().catch((error) => {
  console.error("Approved template catalog test failed:", error);
  process.exit(1);
});
