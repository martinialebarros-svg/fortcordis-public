"use client";

import type { PatientAgeValue } from "./paciente-idade";

export interface DadosPacienteImportados extends PatientAgeValue {
  nome: string;
  tutor: string;
  raca: string;
  especie: string;
  peso: string;
  idade: string;
  sexo: string;
  telefone: string;
  data_exame: string;
}

export interface DadosExameImportados {
  paciente: DadosPacienteImportados;
  medidas: Record<string, number | string>;
  clinica: string;
  veterinario_solicitante: string;
  fc: string;
  medidas_extraidas?: MedidaEcoExtraida[];
  meta_importacao_estudo?: MetaImportacaoEstudoEco;
}

export interface MedidaEcoExtraida {
  campo: string;
  rotulo: string;
  valor: number;
  unidade: string;
  valor_original: number;
  unidade_original: string;
  confianca: number;
  pagina: number;
  texto_origem: string;
  origem: string;
  tecnica?: "modo_m" | "2d" | null;
  status: "sugerida" | "candidata" | "duplicada" | "conflito";
}

export interface MetaImportacaoEstudoEco {
  formato: string;
  arquivo: string;
  perfil?: string;
  fabricante?: string;
  modelo_equipamento?: string;
  paginas: number;
  medidas_sugeridas: number;
  candidatos: number;
  conflitos: number;
  tecnicas_ve_detectadas?: Array<"modo_m" | "2d">;
  variantes_ocr?: Record<string, string>;
}

type XmlImportJobStatus = {
  job_id: number;
  status: string;
  filename?: string | null;
  erro?: string | null;
  dados?: DadosExameImportados | null;
};

const JOB_POLL_TIMEOUT_MS = 30000;

function getJobPollIntervalMs(attempt: number): number {
  if (attempt <= 1) return 1200;
  if (attempt === 2) return 1800;
  if (attempt === 3) return 2500;
  return 4000;
}

async function waitForXmlImportJob(jobId: number): Promise<XmlImportJobStatus> {
  const startedAt = Date.now();
  let attempts = 0;

  while (Date.now() - startedAt < JOB_POLL_TIMEOUT_MS) {
    attempts += 1;
    const response = await fetch(`/api/v1/xml/importar-eco/jobs/${jobId}`, {
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error("Nao foi possivel consultar o XML em processamento.");
    }

    const job = (await response.json()) as XmlImportJobStatus;
    if (job.status === "completed" || job.status === "failed") {
      return job;
    }

    await new Promise((resolve) => {
      window.setTimeout(resolve, getJobPollIntervalMs(attempts));
    });
  }

  throw new Error("Tempo limite excedido ao processar XML.");
}

async function importSynchronously(file: File): Promise<DadosExameImportados> {
  const formData = new FormData();
  formData.append("arquivo", file);

  const response = await fetch("/api/v1/xml/importar-eco", {
    method: "POST",
    body: formData,
    credentials: "include",
  });

  if (response.status === 401) {
    throw new Error("Sessao expirada. Faca login novamente.");
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Erro ${response.status}`);
  }

  if (!payload.success || !payload.dados) {
    throw new Error("Erro ao processar o arquivo.");
  }

  return payload.dados as DadosExameImportados;
}

export async function importarXmlEco(file: File): Promise<DadosExameImportados> {
  const formData = new FormData();
  formData.append("arquivo", file);

  try {
    const response = await fetch("/api/v1/xml/importar-eco/jobs", {
      method: "POST",
      body: formData,
      credentials: "include",
    });

    if (response.status === 401) {
      throw new Error("Sessao expirada. Faca login novamente.");
    }

    const initialJob = (await response.json().catch(() => ({}))) as XmlImportJobStatus & {
      detail?: string;
    };
    if (!response.ok) {
      throw new Error(initialJob.detail || `Erro ${response.status}`);
    }

    if (initialJob.status === "completed" && initialJob.dados) {
      return initialJob.dados;
    }

    const finalJob = await waitForXmlImportJob(initialJob.job_id);
    if (!finalJob.dados) {
      throw new Error(finalJob.erro || "Falha ao processar XML.");
    }
    return finalJob.dados;
  } catch {
    return importSynchronously(file);
  }
}
