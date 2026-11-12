/** Converte o rascunho de historico do painel no formato que a API espera.
 *
 * Uma linha por mensagem, prefixada com `cliente:` ou `nos:`. Sem prefixo, a
 * linha conta como do cliente -- e o caso mais comum ao testar, e exigir
 * prefixo em toda linha so criaria erro de digitacao silencioso.
 *
 * Existe para o admin poder testar a memoria de conversa no painel; sem isso
 * a feature so seria verificavel numa conversa real de WhatsApp.
 */
export interface MensagemHistorico {
  de: "cliente" | "nos";
  texto: string;
}

export const MAX_HISTORICO_SIMULACAO = 12;

export function parseHistorico(bruto: string): MensagemHistorico[] {
  const linhas = String(bruto || "").split("\n");
  const mensagens: MensagemHistorico[] = [];

  for (const linha of linhas) {
    const limpa = linha.trim();
    if (!limpa) continue;

    const separador = limpa.indexOf(":");
    // `indexOf` e nao regex: uma mensagem pode conter ":" no meio
    // ("funciona das 8:00 as 14:00"), e so o primeiro delimita o prefixo.
    const prefixo = separador > 0 ? limpa.slice(0, separador).trim().toLowerCase() : "";

    if (prefixo === "nos" || prefixo === "nós") {
      const texto = limpa.slice(separador + 1).trim();
      if (texto) mensagens.push({ de: "nos", texto });
      continue;
    }
    if (prefixo === "cliente") {
      const texto = limpa.slice(separador + 1).trim();
      if (texto) mensagens.push({ de: "cliente", texto });
      continue;
    }
    mensagens.push({ de: "cliente", texto: limpa });
  }

  // Mantem as MAIS RECENTES: o fim da caixa e o turno mais proximo do atual.
  return mensagens.slice(-MAX_HISTORICO_SIMULACAO);
}
