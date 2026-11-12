export const APPROVED_TEMPLATE_LANGUAGE = "pt_BR" as const;

export const APPROVED_UTILITY_TEMPLATES = {
  reservation: {
    name: "reserva_de_agendamento",
    metaId: "1850190569695780",
    body:
      "Olá, {{1}}. A Fort Cordis reservou o atendimento de {{2}} para {{3}}, às {{4}}. " +
      "Confirme até {{5}}. Após esse prazo, o horário poderá ser disponibilizado para outros clientes automaticamente.",
    quickReplies: ["Confirmar", "Solicitar alteração"],
    buttonActions: ["confirmar", "solicitar_alteracao"]
  },
  appointmentReminder: {
    name: "lembrete_de_agendamento",
    metaId: "2196951517539589",
    body:
      "Olá, {{1}}. Lembramos que o atendimento de {{2}} está confirmado para {{3}}, às {{4}}. " +
      "Se precisar alterar o horário, use uma das opções abaixo.",
    quickReplies: ["Confirmar presença", "Solicitar alteração"],
    buttonActions: ["confirmar_presenca", "solicitar_alteracao"]
  },
  appointmentReminderService: {
    name: "lembrete_de_agendamento_servico_v2",
    // Separate five-variable contract; the approved four-variable reminder is preserved.
    metaId: "1647759970059717",
    approvedBusinessAccountId: "1369494994627980",
    body:
      "Olá, {{1}}. Lembramos que o atendimento de {{2}} está agendado para {{3}}, às {{4}}. " +
      "Serviço agendado: {{5}}. Confira o serviço e o horário. Se precisar corrigir ou incluir outro serviço, " +
      "toque em Solicitar alteração e envie o que deve ser ajustado.",
    quickReplies: ["Confirmar presença", "Solicitar alteração"],
    buttonActions: ["confirmar_presenca", "solicitar_alteracao"]
  },
  appointmentChange: {
    name: "alteracao_de_agendamento",
    metaId: "1325207582741137",
    body:
      "Olá, {{1}}. O atendimento de {{2}} foi alterado para {{3}}, às {{4}}. " +
      "Confirme se o novo horário funciona para você.",
    quickReplies: ["Confirmar horário", "Solicitar alteração"],
    buttonActions: ["confirmar_horario", "solicitar_alteracao"]
  },
  appointmentCancellation: {
    name: "cancelamento_de_agendamento",
    metaId: "1072585772303343",
    body:
      "Olá, {{1}}. O atendimento de {{2}}, previsto para {{3}}, às {{4}}, foi cancelado. " +
      "Se desejar, solicite um novo horário.",
    quickReplies: ["Solicitar novo horário", "Falar com a equipe"],
    buttonActions: ["solicitar_novo_horario", "falar_equipe"]
  },
  appointmentMissingData: {
    name: "dados_pendentes_agendamento",
    metaId: "2094851784715594",
    body:
      "Olá, {{1}}. Para concluir o atendimento de {{2}} em {{3}}, às {{4}}, precisamos confirmar os dados " +
      "do tutor e do paciente. Responda a esta mensagem para continuarmos.",
    quickReplies: ["Enviar dados", "Falar com a equipe"],
    buttonActions: ["enviar_dados", "falar_equipe"]
  },
  appointmentFormalized: {
    name: "agendamento_formalizado",
    // Aguardando aprovacao da Meta - ver docs/specs/agenda-reserva-formalizacao-dados-pendentes/.
    // Atualizar com o ID real assim que o modelo for aprovado no Business Manager.
    metaId: "PENDING_META_APPROVAL",
    body:
      "Olá, {{1}}. Este é um aviso automático: o atendimento de {{2}} referente ao paciente {{3}}, " +
      "tutor(a) {{4}}, foi agendado para o dia {{5}}, às {{6}}, na unidade {{7}}. " +
      "Aguardamos vocês nessa data.",
    quickReplies: [],
    buttonActions: []
  },
  portalReportAvailable: {
    name: "laudo_disponivel_portal",
    metaId: "1682393009502350",
    body:
      "Olá, {{1}}. O laudo do exame {{2}} de {{3}} já está disponível no Portal Fort Cordis. " +
      "Por segurança, consulte o resultado diretamente no portal.",
    quickReplies: [],
    buttonActions: []
  },
  portalReportLink: {
    name: "laudo_disponivel_portal_link",
    // Aprovado pela Meta em 20/09/2026 nas duas contas ("Ativo").
    //
    // O ID aqui e o da WABA de PRODUCAO (Fort Cordis, 1369494994627980), como
    // nas demais entradas deste catalogo. A WABA de teste
    // (4413513738886247) aprovou o mesmo modelo com ID proprio,
    // 2146833716714375 - um campo so nao da conta dos dois, e nao precisa: o
    // envio usa `name`, nao `metaId`. Este campo serve para achar o modelo no
    // Business Manager. Se algum dia algo passar a enviar por ID, este campo
    // vira por ambiente.
    //
    // O link vai como variavel de corpo, e nao como botao de URL, seguindo o
    // precedente ja aprovado de "convite_portal_clinica_v2".
    metaId: "1341477634545137",
    body:
      "Olá, equipe {{1}}. O laudo do exame {{2}} do paciente {{3}} já está disponível. " +
      "Abra pelo link seguro da Fort Cordis: {{4}} — não é preciso senha.",
    quickReplies: [],
    buttonActions: []
  },
  homeReportPdf: {
    name: "laudo_domiciliar_pdf_tutor",
    // Ativo nas WABAs de producao (ID abaixo) e teste (974976974892713).
    // O envio usa o nome do modelo; a flag de runtime controla sua ativacao.
    metaId: "1445021354358408",
    headerType: "document",
    body: "Olá, {{1}}. O laudo do atendimento domiciliar de {{2}} está anexado em PDF. " +
      "Se tiver dúvidas sobre o resultado, fale com a equipe Fort Cordis.",
    quickReplies: [],
    buttonActions: []
  },
  receiptAvailable: {
    name: "recibo_disponivel",
    metaId: "934407008986859",
    body: "Olá, {{1}}. O recibo da OS {{2}}, referente ao atendimento de {{3}}, no valor de {{4}}, está disponível.",
    quickReplies: ["Falar com financeiro"],
    buttonActions: ["falar_financeiro"]
  },
  receiptPdf: {
    name: "recibo_pagamento_pdf",
    metaId: "1025876410335393",
    headerType: "document",
    body:
      "Olá, {{1}}. Confirmamos o recebimento da OS {{2}}, referente ao serviço {{3}}, realizado em {{4}}, " +
      "para o tutor {{5}} e o pet {{6}}, no valor de {{7}}. O recibo detalhado está anexado em PDF.",
    quickReplies: ["Falar com financeiro"],
    buttonActions: ["falar_financeiro"]
  },
  receiptPdfBulk: {
    name: "recibo_pagamento_pdf_multiplas_os",
    metaId: "940165775772306",
    headerType: "document",
    body:
      "Olá, {{1}}. Confirmamos o recebimento de {{2}} ordens de serviço, no total de {{3}}. " +
      "O recibo consolidado com OS, datas, serviços, tutores e pets está anexado em PDF.",
    quickReplies: ["Falar com financeiro"],
    buttonActions: ["falar_financeiro"]
  },
  pendingPaymentReminder: {
    name: "lembrete_pagamento_pendente_detalhado",
    metaId: "1265598002271332",
    body:
      "Olá, {{1}}. A OS {{2}}, referente ao serviço {{3}}, realizado em {{4}}, para o tutor {{5}} e o pet {{6}}, " +
      "continua pendente no valor de {{7}}. " +
      "Se o pagamento já foi realizado, desconsidere esta mensagem.",
    quickReplies: ["Já paguei", "Falar com financeiro"],
    buttonActions: ["ja_paguei", "falar_financeiro"]
  },
  pendingPaymentReminderBulk: {
    name: "lembrete_pagamento_pendente_multiplas_os",
    metaId: "1574210064240409",
    body:
      "Olá, {{1}}. Identificamos {{2}} ordens de serviço pendentes, no total de {{3}}. " +
      "Detalhamento: {{4}}. Se o pagamento já foi realizado, desconsidere esta mensagem.",
    quickReplies: ["Já paguei", "Falar com financeiro"],
    buttonActions: ["ja_paguei", "falar_financeiro"]
  },
  portalClinicInviteActivation: {
    name: "convite_portal_clinica_v2",
    // Aprovado pela Meta em 30/08/2026 (categoria Utilidade) - ver docs/specs/whatsapp-portal-clinic-invite-template/.
    // Nome mudou de "convite_portal_clinica" para "_v2": a primeira submissao foi rejeitada por
    // categoria (a Meta sugeriu Autenticacao) e nomes de modelo excluidos/rejeitados ficam bloqueados
    // por 30 dias no WhatsApp Manager.
    metaId: "1402681525155612",
    body:
      "Olá, equipe {{1}}. A Fort Cordis liberou o acesso da unidade ao Portal Fort Cordis, onde é " +
      "possível acompanhar exames e laudos dos pacientes atendidos. Para começar a usar, abra o link " +
      "a seguir: {{2}} (disponível por {{3}}).",
    quickReplies: [],
    buttonActions: []
  },
  portalClinicInviteLoginAccess: {
    name: "acesso_portal_clinica",
    // Aprovado pela Meta em 30/08/2026 (categoria Utilidade) - ver docs/specs/whatsapp-portal-clinic-invite-template/.
    metaId: "1758345232162346",
    body:
      "Olá, equipe {{1}}. A Fort Cordis atualizou o cadastro da unidade no Portal Fort Cordis. " +
      "Continue consultando exames e laudos pelo link {{2}}. Referência: {{3}}. Qualquer dúvida, " +
      "fale com a equipe Fort Cordis.",
    quickReplies: [],
    buttonActions: []
  },
  portalClinicInviteTemporaryPassword: {
    name: "senha_temporaria_portal_clinica",
    // Aprovado pela Meta em 30/08/2026 (categoria Utilidade) - ver docs/specs/whatsapp-portal-clinic-invite-template/.
    metaId: "1087880320425546",
    body:
      "Olá, equipe {{1}}. Concluímos o cadastro da unidade no Portal Fort Cordis. Continue " +
      "consultando exames e laudos pelo link {{2}}. Dados do cadastro: {{3}} / {{4}}. Qualquer " +
      "dúvida, fale com a equipe Fort Cordis.",
    quickReplies: [],
    buttonActions: []
  }
} as const;

export type ApprovedUtilityTemplateKey = keyof typeof APPROVED_UTILITY_TEMPLATES;

export function isTemplateDeliveryApproved(templateKey: ApprovedUtilityTemplateKey): boolean {
  // Approval belongs to this account; another WABA cannot inherit it from the
  // shared catalog. Existing contracts keep their current delivery behavior.
  const serviceReminder = APPROVED_UTILITY_TEMPLATES.appointmentReminderService;
  return templateKey !== "appointmentReminderService"
    || (/^[1-9]\d*$/.test(serviceReminder.metaId)
      && process.env.WHATSAPP_BUSINESS_ACCOUNT_ID === serviceReminder.approvedBusinessAccountId);
}

export function assertTemplateDeliveryApproved(templateKey: ApprovedUtilityTemplateKey): void {
  if (!isTemplateDeliveryApproved(templateKey)) {
    throw Object.assign(new Error("O lembrete com serviço aguarda aprovação da Meta."), {
      statusCode: 409,
      code: "WHATSAPP_TEMPLATE_APPROVAL_PENDING"
    });
  }
}

export function templateRequiresDocumentHeader(templateKey: ApprovedUtilityTemplateKey): boolean {
  const definition = APPROVED_UTILITY_TEMPLATES[templateKey];
  return "headerType" in definition && definition.headerType === "document";
}

export function getTemplateBodyParameterCount(templateKey: ApprovedUtilityTemplateKey): number {
  const matches = APPROVED_UTILITY_TEMPLATES[templateKey].body.match(/\{\{\d+\}\}/g);
  return matches?.length ?? 0;
}

export function renderApprovedTemplateBody(
  templateKey: ApprovedUtilityTemplateKey,
  bodyParameters: readonly string[]
): string {
  const definition = APPROVED_UTILITY_TEMPLATES[templateKey];
  const expected = getTemplateBodyParameterCount(templateKey);
  if (bodyParameters.length !== expected) {
    throw new Error(
      `Template '${definition.name}' expects ${expected} body parameters, received ${bodyParameters.length}`
    );
  }

  return definition.body.replace(/\{\{(\d+)\}\}/g, (_placeholder, rawIndex: string) => {
    const index = Number(rawIndex) - 1;
    return bodyParameters[index];
  });
}
