import type { AssistenteTranscricaoFonteRevisao } from "@/lib/atendimento-assistente-ia";

const estados = {
  concluida: "Comparação concluída",
  parcial: "Comparação parcial",
  indisponivel: "Comparação indisponível",
};

function tempo(seconds: number): string {
  const value = Math.max(0, Math.floor(seconds));
  return `${Math.floor(value / 60).toString().padStart(2, "0")}:${(value % 60).toString().padStart(2, "0")}`;
}

export default function AtendimentoTranscricaoRevisao({ fontes, textoEditado = false }: {
  fontes: AssistenteTranscricaoFonteRevisao[];
  textoEditado?: boolean;
}) {
  if (!fontes.length) return null;
  return <section aria-label="Revisão das incertezas da transcrição" className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-slate-800">
    <h5 className="font-semibold text-amber-950">Trechos para conferir no áudio</h5>
    <p>A comparação procura palavras reconhecidas de formas diferentes. As alternativas abaixo são hipóteses, não correções. Nenhum nome, medicamento ou dose foi substituído automaticamente.</p>
    <p className="text-xs">Mesmo quando as leituras concordam, a fidelidade não está garantida. Confira nomes, medicamentos, doses, unidades e negações no áudio original.</p>
    {textoEditado ? <p role="status" className="rounded-lg border border-amber-300 bg-white p-2 font-medium">Você editou o texto. Os avisos abaixo se referem à transcrição original; suas edições não foram reavaliadas.</p> : null}
    <p className="text-xs">Os horários indicam o trecho inteiro de cada arquivo, não a posição exata da palavra.</p>
    {fontes.map((fonte, sourceIndex) => {
      const revisao = fonte.revisao_transcricao;
      const divergencias = revisao.trechos.reduce((total, trecho) => total + trecho.divergencias.length, 0);
      return <details key={`${fonte.arquivo_id ?? fonte.nome}-${sourceIndex}`} className="rounded-lg border border-amber-200 bg-white p-3">
        <summary className="cursor-pointer font-medium">
          <span className="break-all">{fonte.nome}</span> — {estados[revisao.estado]} · {revisao.trechos_revisados}/{revisao.trechos_total} trechos comparados · {divergencias} divergência(s)
        </summary>
        <div className="mt-3 space-y-3">
          {revisao.estado !== "concluida" ? <p className="font-medium text-amber-900">A comparação não ficou completa. A transcrição principal foi preservada; confira os trechos sem comparação ou com comparação limitada.</p> : null}
          {revisao.avisos.map((aviso, index) => <p key={index} className="text-amber-900">{aviso}</p>)}
          {revisao.trechos.map((trecho) => <details key={trecho.indice} className="rounded-lg bg-slate-50 p-3">
            <summary className="cursor-pointer font-medium">Trecho {trecho.indice} · {tempo(trecho.inicio_segundos)}–{tempo(trecho.fim_segundos)} · {trecho.estado === "indisponivel" ? "Sem comparação" : `${trecho.divergencias.length} divergência(s)`}{trecho.marcacoes_incerteza.length ? " · Fala incerta sinalizada" : ""}</summary>
            <div className="mt-3 space-y-3">
              {trecho.estado === "indisponivel" ? <p>Este trecho não teve segunda leitura. Ouça o original para conferir o texto.</p> : null}
              {trecho.limitado ? <p className="font-medium text-amber-900">A comparação deste trecho ficou limitada. A lista pode não mostrar todas as diferenças; confira o trecho inteiro.</p> : null}
              {trecho.estado === "concluido" && !trecho.limitado && !trecho.divergencias.length ? <p>Nenhuma divergência detectada entre as duas leituras neste trecho. Isso não confirma que todas as palavras estão corretas.</p> : null}
              {trecho.marcacoes_incerteza.length ? <div><h6 className="font-medium">Fala incerta na transcrição original</h6><ul className="mt-1 list-disc space-y-1 pl-5">{trecho.marcacoes_incerteza.map((marcacao, index) => <li key={index} className="whitespace-pre-wrap break-words">{marcacao}</li>)}</ul></div> : null}
              {trecho.divergencias.map((divergencia, index) => <div key={index} className="grid gap-3 rounded-lg border border-slate-200 bg-white p-3 sm:grid-cols-2">
                <div><h6 className="text-xs font-semibold uppercase text-slate-600">Transcrição original</h6><p className="mt-1 whitespace-pre-wrap break-words">{divergencia.texto_original || "(Nenhum texto neste ponto.)"}</p></div>
                <div><h6 className="text-xs font-semibold uppercase text-slate-600">Outra leitura — conferir no áudio</h6><p className="mt-1 whitespace-pre-wrap break-words">{divergencia.leitura_alternativa || "(Nenhum texto nesta leitura.)"}</p></div>
              </div>)}
            </div>
          </details>)}
        </div>
      </details>;
    })}
  </section>;
}
