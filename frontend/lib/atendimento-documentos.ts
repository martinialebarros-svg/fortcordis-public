export async function validarPdfDocumento(blob: Blob): Promise<void> {
  if (!blob.size || (blob.type && !blob.type.toLowerCase().includes("application/pdf"))) {
    throw new Error("O servidor nao retornou um PDF valido. O documento continua salvo.");
  }
  const assinatura = new TextDecoder().decode(await blob.slice(0, 5).arrayBuffer());
  if (assinatura !== "%PDF-") {
    throw new Error("O arquivo recebido nao e um PDF valido. Tente baixar novamente.");
  }
}

export function iniciarDownloadDocumento(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // O dono do URL o conserva para abrir/repetir o download e revoga no cleanup.
}

export function documentoPersistido<T extends { id: number }>(documentos: T[], id: number): T {
  const documento = documentos.find((item) => item.id === id);
  if (!documento) throw new Error("O documento nao foi confirmado na lista do servidor. Seu texto local foi preservado; atualize a lista antes de continuar.");
  return documento;
}

type EditorDocumento = { id: number | null; titulo: string; corpo: string };

/** Conserva o que foi digitado durante a requisicao e atualiza a versao salva. */
export function reconciliarDocumentoSalvo<T extends EditorDocumento>(atual: T, enviado: T, salvo: T): T {
  if (atual.id !== enviado.id) return atual;
  return {
    ...salvo,
    titulo: atual.titulo === enviado.titulo ? salvo.titulo : atual.titulo,
    corpo: atual.corpo === enviado.corpo ? salvo.corpo : atual.corpo,
  };
}
