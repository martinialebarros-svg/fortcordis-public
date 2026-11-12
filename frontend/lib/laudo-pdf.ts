"use client";

type LaudoPdfJobStatus = {
  job_id: number;
  status: string;
  arquivo_nome?: string | null;
  erro?: string | null;
  download_url?: string | null;
};

const JOB_POLL_TIMEOUT_MS = 30000;

function getJobPollIntervalMs(attempt: number): number {
  if (attempt <= 1) return 1200;
  if (attempt === 2) return 1800;
  if (attempt === 3) return 2500;
  return 4000;
}

function extractFilename(contentDisposition: string | null, fallback: string): string {
  const match = contentDisposition?.match(/filename="?([^";\s]+)"?/);
  return match?.[1] || fallback;
}

async function triggerBrowserDownload(response: Response, fallbackFilename: string): Promise<void> {
  if (!response.ok) {
    throw new Error("Erro ao baixar PDF.");
  }

  const filename = extractFilename(
    response.headers.get("content-disposition"),
    fallbackFilename,
  );
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
}

async function downloadFromUrl(url: string, fallbackFilename: string): Promise<void> {
  const response = await fetch(url, {
    credentials: "include",
  });
  await triggerBrowserDownload(response, fallbackFilename);
}

async function downloadSynchronously(laudoId: number, fallbackFilename: string): Promise<void> {
  const response = await fetch(`/api/v1/laudos/${laudoId}/pdf`, {
    credentials: "include",
  });
  await triggerBrowserDownload(response, fallbackFilename);
}

async function waitForPdfJob(jobId: number): Promise<LaudoPdfJobStatus> {
  const startedAt = Date.now();
  let attempts = 0;

  while (Date.now() - startedAt < JOB_POLL_TIMEOUT_MS) {
    attempts += 1;
    const response = await fetch(`/api/v1/laudos/pdf-jobs/${jobId}`, {
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error("Nao foi possivel consultar o PDF em processamento.");
    }

    const job = (await response.json()) as LaudoPdfJobStatus;
    if (job.status === "completed" || job.status === "failed") {
      return job;
    }

    await new Promise((resolve) => {
      window.setTimeout(resolve, getJobPollIntervalMs(attempts));
    });
  }

  throw new Error("Tempo limite excedido ao preparar PDF.");
}

export async function baixarLaudoPdf(
  laudoId: number,
  fallbackFilename: string,
): Promise<void> {
  try {
    const response = await fetch(`/api/v1/laudos/${laudoId}/pdf-jobs`, {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error("Nao foi possivel iniciar a geracao assincrona do PDF.");
    }

    const initialJob = (await response.json()) as LaudoPdfJobStatus;
    if (initialJob.download_url) {
      await downloadFromUrl(initialJob.download_url, initialJob.arquivo_nome || fallbackFilename);
      return;
    }

    const finalJob = await waitForPdfJob(initialJob.job_id);
    if (!finalJob.download_url) {
      throw new Error(finalJob.erro || "Falha ao gerar PDF.");
    }

    await downloadFromUrl(finalJob.download_url, finalJob.arquivo_nome || fallbackFilename);
  } catch (error) {
    await downloadSynchronously(laudoId, fallbackFilename);
  }
}

export async function baixarLaudoPdfOriginal(
  laudoId: number,
  fallbackFilename: string,
): Promise<void> {
  const response = await fetch(`/api/v1/laudos/${laudoId}/pdf-original`, {
    credentials: "include",
  });
  await triggerBrowserDownload(response, fallbackFilename);
}
