"use client";

import { DadosExameImportados } from "./xml-import";

const ALLOWED_EXTENSIONS = [
  ".jpg",
  ".jpeg",
  ".png",
  ".bmp",
  ".gif",
  ".webp",
  ".tif",
  ".tiff",
];

function hasAllowedImageExtension(filename: string): boolean {
  const lower = (filename || "").toLowerCase();
  return ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export async function importarCabecalhoPorImagem(file: File): Promise<DadosExameImportados> {
  if (!hasAllowedImageExtension(file.name)) {
    throw new Error("Arquivo invalido. Envie uma imagem JPG, PNG, WEBP, BMP, GIF ou TIFF.");
  }

  const formData = new FormData();
  formData.append("arquivo", file);

  const response = await fetch("/api/v1/xml/importar-cabecalho-imagem", {
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
    throw new Error("Nao foi possivel processar a imagem.");
  }

  return payload.dados as DadosExameImportados;
}
