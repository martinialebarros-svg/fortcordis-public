import { Request, Response } from "express";
import {
  APPROVED_TEMPLATE_LANGUAGE,
  APPROVED_UTILITY_TEMPLATES,
  ApprovedUtilityTemplateKey,
  getTemplateBodyParameterCount,
  templateRequiresDocumentHeader
} from "../templates/approvedTemplates";

interface TemplateCatalogMetadata {
  category: "agenda" | "laudos" | "financeiro";
  workflow_label: string;
  variable_labels: readonly string[];
}

// Modelos sem entrada aqui (ex.: convite de acesso ao Portal Clinicas) nao aparecem no catalogo
// consultado pela caixa de entrada - sao disparados apenas pelo fluxo automatizado que os origina,
// nao pela escolha manual do atendente durante uma conversa.
const TEMPLATE_CATALOG_METADATA: Partial<Record<ApprovedUtilityTemplateKey, TemplateCatalogMetadata>> = {
  reservation: {
    category: "agenda",
    workflow_label: "Reserva de agendamento",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário", "Prazo de confirmação"]
  },
  appointmentReminder: {
    category: "agenda",
    workflow_label: "Lembrete de agendamento",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário"]
  },
  appointmentReminderService: {
    category: "agenda",
    workflow_label: "Lembrete com serviço agendado",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário", "Serviço agendado"]
  },
  appointmentChange: {
    category: "agenda",
    workflow_label: "Alteração de agendamento",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário"]
  },
  appointmentCancellation: {
    category: "agenda",
    workflow_label: "Cancelamento de agendamento",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário"]
  },
  appointmentMissingData: {
    category: "agenda",
    workflow_label: "Dados pendentes do agendamento",
    variable_labels: ["Clínica ou destinatário", "Pet", "Data", "Horário"]
  },
  appointmentFormalized: {
    category: "agenda",
    workflow_label: "Agendamento formalizado",
    variable_labels: ["Clínica ou destinatário", "Serviço", "Pet", "Tutor", "Data", "Horário", "Unidade"]
  },
  portalReportAvailable: {
    category: "laudos",
    workflow_label: "Laudo disponível no portal",
    variable_labels: ["Clínica ou destinatário", "Exame", "Pet"]
  },
  receiptAvailable: {
    category: "financeiro",
    workflow_label: "Recibo disponível",
    variable_labels: ["Clínica ou destinatário", "Número da OS", "Data do atendimento", "Valor"]
  },
  receiptPdf: {
    category: "financeiro",
    workflow_label: "Recibo de pagamento com PDF",
    variable_labels: [
      "Clínica ou destinatário",
      "Número da OS",
      "Serviço",
      "Data",
      "Tutor",
      "Pet",
      "Valor"
    ]
  },
  receiptPdfBulk: {
    category: "financeiro",
    workflow_label: "Recibo consolidado com PDF",
    variable_labels: ["Clínica ou destinatário", "Quantidade de OS", "Valor total"]
  },
  pendingPaymentReminder: {
    category: "financeiro",
    workflow_label: "Cobrança detalhada",
    variable_labels: [
      "Clínica ou destinatário",
      "Número da OS",
      "Serviço",
      "Data",
      "Tutor",
      "Pet",
      "Valor"
    ]
  },
  pendingPaymentReminderBulk: {
    category: "financeiro",
    workflow_label: "Cobrança consolidada",
    variable_labels: ["Clínica ou destinatário", "Quantidade de OS", "Valor total", "Detalhamento"]
  }
};

export async function listApprovedTemplateCatalog(_req: Request, res: Response): Promise<void> {
  const data = Object.entries(APPROVED_UTILITY_TEMPLATES)
    .filter(([key]) => (key as ApprovedUtilityTemplateKey) in TEMPLATE_CATALOG_METADATA)
    .map(([key, definition]) => {
      const templateKey = key as ApprovedUtilityTemplateKey;
      const metadata = TEMPLATE_CATALOG_METADATA[templateKey] as TemplateCatalogMetadata;
      return {
        key: templateKey,
        name: definition.name,
        meta_id: definition.metaId,
        language: APPROVED_TEMPLATE_LANGUAGE,
        body: definition.body,
        body_parameter_count: getTemplateBodyParameterCount(templateKey),
        variable_labels: metadata.variable_labels,
        quick_replies: definition.quickReplies,
        category: metadata.category,
        workflow_label: metadata.workflow_label,
        requires_document: templateRequiresDocumentHeader(templateKey),
        can_copy_as_free_text: !templateRequiresDocumentHeader(templateKey),
        meta_approval_live: null
      };
    });

  res.json({
    data,
    source: "configured_catalog",
    meta_approval_live: null
  });
}
