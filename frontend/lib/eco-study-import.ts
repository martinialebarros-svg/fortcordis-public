"use client";

import { DadosExameImportados } from "./xml-import";

interface EcoStudyImportJobStatus {
  job_id: number;
  status: string;
  filename?: string | null;
  erro?: string | null;
  dados?: DadosExameImportados | null;
  detail?: string;
}

const POLL_TIMEOUT_MS = 90000;

function getPollInterval(attempt: number): number {
  if (attempt <= 2) return 1200;
  if (attempt <= 5) return 2000;
  return 3500;
}

async function parseResponse(response: Response): Promise<EcoStudyImportJobStatus> {
  return (await response.json().catch(() => ({}))) as EcoStudyImportJobStatus;
}

export async function importarEstudoEco(file: File): Promise<DadosExameImportados> {
  const formData = new FormData();
  formData.append("arquivo", file);

  const response = await fetch("/api/v1/eco-study-import/jobs", {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  if (response.status === 401) {
    throw new Error("Sessao expirada. Faca login novamente.");
  }

  const initial = await parseResponse(response);
  if (!response.ok) {
    throw new Error(initial.detail || `Erro ${response.status}`);
  }
  if (initial.status === "completed" && initial.dados) {
    return initial.dados;
  }

  const startedAt = Date.now();
  let attempt = 0;
  while (Date.now() - startedAt < POLL_TIMEOUT_MS) {
    attempt += 1;
    await new Promise((resolve) => window.setTimeout(resolve, getPollInterval(attempt)));
    const jobResponse = await fetch(`/api/v1/eco-study-import/jobs/${initial.job_id}`, {
      credentials: "include",
    });
    const job = await parseResponse(jobResponse);
    if (!jobResponse.ok) {
      throw new Error(job.detail || "Nao foi possivel consultar o estudo em processamento.");
    }
    if (job.status === "failed") {
      throw new Error(job.erro || "Falha ao processar o estudo.");
    }
    if (job.status === "completed") {
      if (!job.dados) {
        throw new Error("O estudo terminou sem resultado de extracao.");
      }
      return job.dados;
    }
  }

  throw new Error("Tempo limite excedido ao processar o estudo.");
}
