"use client";

import { useEffect, useRef, useState } from "react";
import { CircleStop, FileAudio, Loader2, Mic, Sparkles, Trash2 } from "lucide-react";
import api from "@/lib/axios";
import AtendimentoAssistenteLote from "./AtendimentoAssistenteLote";
import AtendimentoTranscricaoRevisao from "./AtendimentoTranscricaoRevisao";
import type { AssistenteLote } from "@/lib/atendimento-assistente-lote";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import type { ClinicalFieldKey } from "@/lib/atendimento-clinical-notes";
import {
  ASSISTENTE_AUDIO_ACCEPT, ASSISTENTE_AUDIO_MAX_BYTES, ASSISTENTE_CAMPO_LABELS, ASSISTENTE_FILE_ACCEPT,
  podeIncorporarAchado, podeIncorporarCampo, temRevisaoRacaConfirmada, textoAchadoParaRevisao, validarArquivosAssistente, validarAudioParaTranscricao, type AssistenteIAResultado, type AssistenteIAStatus, type AssistenteTranscricaoFonteRevisao, type AssistenteTranscricaoResultado,
} from "@/lib/atendimento-assistente-ia";
import { useAtendimentoAudio } from "@/lib/use-atendimento-audio";
import { guardarRevisaoAssistenteMemoria, lerRascunhoAssistenteMemoria, type AssistenteMemoryReview } from "@/lib/atendimento-assistente-memory";

interface AtendimentoAssistenteIAProps {
  atendimentoId: number | null;
  patientLabel: string;
  pacienteId: number;
  onApplyField: (campo: ClinicalFieldKey, texto: string) => void;
  onAttachFiles?: (files: File[]) => Promise<void>;
  onEnsureSaved?: () => Promise<boolean>;
  onPendingChange?: (pending: boolean) => void;
  onBusyChange?: (busy: boolean) => void;
}

const buttonClass = "inline-flex items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
const identificarAudio = (file: File) => JSON.stringify([file.name, file.size, file.type, file.lastModified]);

function AudioPreview({ audio }: { audio: File }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(audio);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [audio]);
  if (!url) return null;
  return <div className="space-y-2">
    <audio controls src={url} className="w-full" aria-label="Ouvir áudio original" />
    <a href={url} download={audio.name} className="text-sm font-medium text-teal-800 underline">Baixar áudio original ({(audio.size / 1_000_000).toFixed(1)} MB)</a>
  </div>;
}

function ArquivoOriginalLink({ arquivo }: { arquivo: File }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const next = URL.createObjectURL(arquivo);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [arquivo]);
  return url ? <a href={url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-teal-800 underline">Ver original</a> : null;
}

function AtendimentoAssistenteSalvo({ atendimentoId, patientLabel, pacienteId, onApplyField, onAttachFiles, onEnsureSaved, onPendingChange, onBusyChange }: AtendimentoAssistenteIAProps & { atendimentoId: number }) {
  const [status, setStatus] = useState<AssistenteIAStatus | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [consentimento, setConsentimento] = useState(false);
  const [texto, setTexto] = useState("");
  const [audioTranscrito, setAudioTranscrito] = useState<string | null>(null);
  const [revisoesTranscricao, setRevisoesTranscricao] = useState<AssistenteTranscricaoFonteRevisao[]>([]);
  const [transcricaoEditadaDesdeRevisao, setTranscricaoEditadaDesdeRevisao] = useState(false);
  const [arquivos, setArquivos] = useState<File[]>([]);
  const [resultado, setResultado] = useState<AssistenteIAResultado | null>(null);
  const [edicoes, setEdicoes] = useState<Record<number, string>>({});
  const [revisados, setRevisados] = useState<Record<number, boolean>>({});
  const [aplicados, setAplicados] = useState<Record<number, boolean>>({});
  const [achadosEditados, setAchadosEditados] = useState<Record<number, string>>({});
  const [achadosRevisados, setAchadosRevisados] = useState<Record<number, boolean>>({});
  const [achadosAplicados, setAchadosAplicados] = useState<Record<number, boolean>>({});
  const [loteBusy, setLoteBusy] = useState(false);
  const [loteAtivo, setLoteAtivo] = useState(false);
  const [lotePendente, setLotePendente] = useState(false);
  const [resultadoLoteId, setResultadoLoteId] = useState<string | null>(null);
  const [loteParaRevisar, setLoteParaRevisar] = useState<AssistenteLote | null>(null);
  const [busy, setBusy] = useState<"transcrever" | "analisar" | "anexar" | "incorporar" | null>(null);
  const [erro, setErro] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);
  const [anexados, setAnexados] = useState(false);
  const [confirmarDescarte, setConfirmarDescarte] = useState(false);
  const [reviewLoadedKey, setReviewLoadedKey] = useState("");
  const [revisaoRecuperada, setRevisaoRecuperada] = useState(false);
  const alive = useRef(true);
  const request = useRef<AbortController | null>(null);
  const incorporando = useRef(false);
  const audio = useAtendimentoAudio(atendimentoId, status?.usuario_id ?? null, pacienteId);
  const erroEnvioAudio = audio.audio ? validarAudioParaTranscricao(audio.audio, status?.limites?.audio_bytes) : null;
  const podeUsarIA = status?.habilitado && status.configurado && consentimento;
  const transferindo = Boolean(busy) || loteBusy || audio.gravando || audio.iniciando;
  const ocupada = transferindo || loteAtivo;
  const pendente = Boolean(audio.audio || audio.gravando || audio.iniciando || texto || arquivos.length || resultado || lotePendente);
  const reviewKey = status?.usuario_id ? `${status.usuario_id}:${atendimentoId}:${pacienteId}` : "";
  const revisaoPronta = Boolean(reviewKey && reviewLoadedKey === reviewKey);
  const latestReview = useRef<AssistenteMemoryReview | null>(null);
  latestReview.current = { texto, arquivos, resultado, edicoes, revisados, aplicados, achadosEditados, achadosRevisados, achadosAplicados, audioTranscrito, anexados, resultadoLoteId, revisoesTranscricao, transcricaoEditadaDesdeRevisao };

  useEffect(() => {
    if (!status?.usuario_id || !pacienteId) return;
    const identity = { usuarioId: status.usuario_id, atendimentoId, pacienteId };
    const review = lerRascunhoAssistenteMemoria(identity)?.review;
    if (review) {
      setTexto(review.texto); setArquivos(review.arquivos); setResultado(review.resultado);
      setEdicoes(review.edicoes); setRevisados(review.revisados); setAplicados(review.aplicados);
      setAchadosEditados(review.achadosEditados); setAchadosRevisados(review.achadosRevisados); setAchadosAplicados(review.achadosAplicados);
      setAudioTranscrito(review.audioTranscrito); setAnexados(review.anexados);
      setResultadoLoteId(review.resultadoLoteId ?? null);
      setRevisoesTranscricao(review.revisoesTranscricao ?? []);
      setTranscricaoEditadaDesdeRevisao(review.transcricaoEditadaDesdeRevisao ?? false);
      setRevisaoRecuperada(Boolean(review.texto || review.arquivos.length || review.resultado));
    }
    setReviewLoadedKey(reviewKey);
    return () => {
      if (latestReview.current) guardarRevisaoAssistenteMemoria(identity, latestReview.current);
    };
  }, [status?.usuario_id, atendimentoId, pacienteId, reviewKey]);

  useEffect(() => {
    if (!revisaoPronta || !status?.usuario_id || !latestReview.current) return;
    guardarRevisaoAssistenteMemoria({ usuarioId: status.usuario_id, atendimentoId, pacienteId }, latestReview.current);
  }, [revisaoPronta, status?.usuario_id, atendimentoId, pacienteId, texto, arquivos, resultado, edicoes, revisados, aplicados, achadosEditados, achadosRevisados, achadosAplicados, audioTranscrito, anexados, resultadoLoteId, revisoesTranscricao, transcricaoEditadaDesdeRevisao]);

  useEffect(() => {
    onPendingChange?.(pendente);
    return () => onPendingChange?.(false);
  }, [pendente, onPendingChange]);

  useEffect(() => {
    onBusyChange?.(transferindo);
    return () => onBusyChange?.(false);
  }, [transferindo, onBusyChange]);

  useEffect(() => {
    if (!pendente) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [pendente]);

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    void api.get<AssistenteIAStatus>(`/atendimentos/${atendimentoId}/assistente/status`, { signal: controller.signal }).then(({ data }) => {
      if (alive.current) setStatus(data);
    }).catch((error) => {
      if (!controller.signal.aborted && alive.current) setErro(extractApiErrorMessageSync(error, "Não foi possível verificar a disponibilidade da IA."));
    }).finally(() => { if (alive.current) setLoadingStatus(false); });
    return () => { alive.current = false; controller.abort(); request.current?.abort(); };
  }, [atendimentoId]);

  const limparAnalise = () => { setResultadoLoteId(null); setResultado(null); setEdicoes({}); setRevisados({}); setAplicados({}); setAchadosEditados({}); setAchadosRevisados({}); setAchadosAplicados({}); setAvisos([]); };

  const abrirRevisaoLote = (lote: AssistenteLote) => {
    if (!lote.resultado || lote.paciente_id !== pacienteId || lote.atendimento_id !== atendimentoId) return;
    if (resultadoLoteId === lote.id && resultado && JSON.stringify(resultado) === JSON.stringify(lote.resultado)) return;
    limparAnalise();
    setResultadoLoteId(lote.id);
    setResultado(lote.resultado);
    setTexto(lote.transcricao || "");
    setRevisoesTranscricao(lote.revisoes_transcricao ?? []);
    setTranscricaoEditadaDesdeRevisao(false);
    setEdicoes(Object.fromEntries(lote.resultado.campos.map((campo, index) => [index, campo.texto])));
    setAchadosEditados(Object.fromEntries(lote.resultado.achados_exames.map((achado, index) => [index, textoAchadoParaRevisao(lote.resultado!, achado)])));
    setLoteParaRevisar(null);
  };
  const invalidarRevisaoLote = (id: string) => {
    if (latestReview.current?.resultadoLoteId !== id) return;
    // Preserve edited text as reference, but an obsolete decision cannot be used.
    setResultado((previous) => previous && !previous.revisao_desatualizada ? {
      ...previous, revisao_desatualizada: true, bloqueado_integracao: true,
    } : previous);
    setLoteParaRevisar(null);
  };

  const incorporarResultado = (tipo: "campo" | "achado", index: number) => {
    const revisao = latestReview.current;
    if (ocupada || incorporando.current || !revisao?.resultado) return;
    const ehCampo = tipo === "campo";
    const item = ehCampo ? revisao.resultado.campos[index] : revisao.resultado.achados_exames[index];
    const textoRevisado = (ehCampo ? revisao.edicoes[index] : revisao.achadosEditados[index])?.trim();
    if (!item || !textoRevisado || (ehCampo ? revisao.aplicados[index] || !revisao.revisados[index] || !podeIncorporarCampo(revisao.resultado, revisao.resultado.campos[index]) : revisao.achadosAplicados[index] || !revisao.achadosRevisados[index] || !podeIncorporarAchado(revisao.resultado, revisao.resultado.achados_exames[index]))) return;
    const aplicar = () => {
      const atual = latestReview.current;
      if (!alive.current || atual?.resultado !== revisao.resultado || atual.resultadoLoteId !== revisao.resultadoLoteId ||
        (ehCampo ? atual.edicoes[index]?.trim() !== textoRevisado || !atual.revisados[index] || atual.aplicados[index] : atual.achadosEditados[index]?.trim() !== textoRevisado || !atual.achadosRevisados[index] || atual.achadosAplicados[index])) return;
      onApplyField(ehCampo ? revisao.resultado!.campos[index].campo : "dados_clinicos", textoRevisado);
      if (ehCampo) setAplicados((previous) => ({ ...previous, [index]: true }));
      else setAchadosAplicados((previous) => ({ ...previous, [index]: true }));
    };
    if (!revisao.resultadoLoteId) { aplicar(); return; }
    const id = revisao.resultadoLoteId;
    const controller = new AbortController();
    request.current = controller; incorporando.current = true; setBusy("incorporar"); setErro("");
    // A decision can be revoked in another tab. Verify current server evidence
    // immediately before adding a reviewed batch finding to the encounter.
    void api.get<AssistenteLote>(`/atendimentos/${atendimentoId}/assistente/lotes/${id}`, { signal: controller.signal, timeout: 30000 }).then(({ data }) => {
      if (controller.signal.aborted) return;
      if (!data || data.id !== id || data.atendimento_id !== atendimentoId || data.paciente_id !== pacienteId || data.status !== "completed" || JSON.stringify(data.resultado) !== JSON.stringify(revisao.resultado)) {
        invalidarRevisaoLote(id); return;
      }
      aplicar();
    }).catch((error) => {
      if (!controller.signal.aborted && alive.current) {
        invalidarRevisaoLote(id);
        setErro(extractApiErrorMessageSync(error, "Não foi possível confirmar a revisão atual do conjunto. O texto foi preservado; consulte o progresso antes de incorporar."));
      }
    }).finally(() => {
      incorporando.current = false;
      if (alive.current && request.current === controller) { setBusy(null); request.current = null; }
    });
  };

  const transcrever = async () => {
    if (!audio.audio || identificarAudio(audio.audio) === audioTranscrito || !podeUsarIA || ocupada) return;
    const arquivoAudio = audio.audio;
    const invalidAudio = validarAudioParaTranscricao(arquivoAudio, status?.limites?.audio_bytes);
    if (invalidAudio) { setErro(invalidAudio); return; }
    const controller = new AbortController();
    request.current = controller;
    setBusy("transcrever"); setErro(""); limparAnalise();
    const payload = new FormData();
    payload.append("audio", arquivoAudio, arquivoAudio.name);
    payload.append("consentimento", "true");
    try {
      if (onEnsureSaved && !(await onEnsureSaved())) {
        if (alive.current && !controller.signal.aborted) setErro("Salve o atendimento e confirme o paciente antes de transcrever. O áudio foi preservado.");
        return;
      }
      if (!alive.current || controller.signal.aborted) return;
      const { data } = await api.post<AssistenteTranscricaoResultado>(`/atendimentos/${atendimentoId}/assistente/transcrever`, payload, { signal: controller.signal, timeout: 300000 });
      if (!alive.current || controller.signal.aborted) return;
      setTexto((previous) => previous ? `${previous}\n\n${data.texto}` : data.texto);
      if (data.revisao_transcricao) {
        setRevisoesTranscricao((previous) => [...previous, { nome: arquivoAudio.name, revisao_transcricao: data.revisao_transcricao! }]);
      }
      setAudioTranscrito(identificarAudio(arquivoAudio));
      setAvisos(data.avisos || []);
    } catch (error) {
      if (alive.current && !controller.signal.aborted) setErro(extractApiErrorMessageSync(error, "A transcrição falhou. O áudio continua disponível para ouvir, baixar ou tentar novamente."));
    } finally { if (alive.current && request.current === controller) { setBusy(null); request.current = null; } }
  };

  const analisar = async () => {
    if (!podeUsarIA || ocupada || (!texto.trim() && !arquivos.length)) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy("analisar"); setErro(""); limparAnalise();
    const payload = new FormData();
    payload.append("transcricao", texto);
    payload.append("consentimento", "true");
    arquivos.forEach((file) => payload.append("arquivos", file));
    try {
      if (onEnsureSaved && !(await onEnsureSaved())) {
        if (alive.current && !controller.signal.aborted) setErro("Salve o atendimento e confirme o paciente antes de analisar. As fontes foram preservadas.");
        return;
      }
      if (!alive.current || controller.signal.aborted) return;
      const { data } = await api.post<AssistenteIAResultado>(`/atendimentos/${atendimentoId}/assistente/analisar`, payload, { signal: controller.signal, timeout: 300000 });
      if (!alive.current || controller.signal.aborted) return;
      setResultado(data);
      setEdicoes(Object.fromEntries(data.campos.map((campo, index) => [index, campo.texto])));
      setAchadosEditados(Object.fromEntries(data.achados_exames.map((achado, index) => [index, textoAchadoParaRevisao(data, achado)])));
    } catch (error) {
      if (alive.current && !controller.signal.aborted) setErro(extractApiErrorMessageSync(error, "A análise falhou. Seus arquivos e a transcrição permanecem disponíveis para tentar novamente."));
    } finally { if (alive.current && request.current === controller) { setBusy(null); request.current = null; } }
  };

  const guardarArquivos = async () => {
    if (!onAttachFiles || ocupada || !arquivos.length || anexados) return;
    setBusy("anexar"); setErro("");
    try {
      if (onEnsureSaved && !(await onEnsureSaved())) {
        if (alive.current) setErro("Salve o atendimento e confirme o paciente antes de guardar os arquivos. As fontes foram preservadas.");
        return;
      }
      if (!alive.current) return;
      await onAttachFiles(arquivos);
      if (alive.current) setAnexados(true);
    } catch (error) {
      if (alive.current) setErro(extractApiErrorMessageSync(error, "Não foi possível guardar todos os arquivos no prontuário. Confira os anexos antes de tentar novamente."));
    } finally { if (alive.current) setBusy(null); }
  };

  return <details aria-label="Assistente de atendimento" className="rounded-[26px] border border-teal-200 bg-white p-5 shadow-sm">
    <summary className="flex cursor-pointer items-start gap-3">
      <Sparkles aria-hidden className="mt-1 h-6 w-6 shrink-0 text-teal-700" />
      <div>
        <h3 className="text-lg font-semibold text-slate-900">Assistente de atendimento {audio.gravando ? <span className="ml-2 text-sm text-red-700">● Gravando · {Math.floor(audio.seconds / 60)}:{(audio.seconds % 60).toString().padStart(2, "0")}</span> : <span className="ml-2 text-sm font-normal text-teal-700">Abrir áudio e exames</span>}</h3>
        <p className="mt-1 text-sm text-slate-600">Grave a conversa e analise exames de <strong>{patientLabel}</strong>. Confira fontes, nomes, medicamentos, doses e unidades antes de incorporar cada informação.</p>
        <p className="mt-1 text-xs text-slate-500">A análise usa o atendimento já salvo. Salve alterações clínicas antes de analisar. Sugestões não alteram receitas, diagnósticos ou documentos automaticamente.</p>
      </div>
    </summary>

    {loadingStatus ? <p className="mt-4 text-sm text-slate-600">Verificando disponibilidade…</p> : null}
    {revisaoRecuperada ? <p role="status" className="mt-4 rounded-xl bg-teal-50 p-3 text-sm text-teal-900">Revisão recuperada nesta aba para este paciente e atendimento. Confira o contexto salvo antes de continuar.</p> : null}
    {status && (!status.habilitado || !status.configurado) ? <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">A assistência por IA ainda não está habilitada ou configurada neste ambiente. Você pode preparar e ouvir o áudio; a transcrição e a análise serão liberadas após a configuração.</p> : null}
    <label className="mt-4 flex items-start gap-2 rounded-xl border border-slate-200 p-3 text-sm text-slate-700">
      <input type="checkbox" checked={consentimento} disabled={transferindo} onChange={(event) => setConsentimento(event.target.checked)} className="mt-1" />
      Confirmei a autorização do tutor para gravar a conversa e enviar áudio, transcrição e exames selecionados à OpenAI para análise clínica assistida.
    </label>

    {revisaoPronta && status?.usuario_id ? <AtendimentoAssistenteLote
      key={`${status.usuario_id}:${atendimentoId}:${pacienteId}`}
      atendimentoId={atendimentoId} pacienteId={pacienteId} usuarioId={status.usuario_id}
      texto={texto} consentimento={consentimento} habilitado={Boolean(status.habilitado && status.configurado)}
      disabled={Boolean(busy) || audio.gravando || audio.iniciando}
      onEnsureSaved={onEnsureSaved} onBusyChange={setLoteBusy} onActiveChange={setLoteAtivo} onPendingChange={setLotePendente}
      onResultInvalidated={invalidarRevisaoLote}
      onSnapshot={(lote) => {
        const current = latestReview.current;
        if (!lote) { if (current?.resultadoLoteId) invalidarRevisaoLote(current.resultadoLoteId); return; }
        if (current?.resultadoLoteId === lote.id && current.resultado &&
          (lote.status !== "completed" || JSON.stringify(current.resultado) !== JSON.stringify(lote.resultado))) {
          invalidarRevisaoLote(lote.id);
        }
      }}
      onReview={(lote) => {
        if (resultado && (resultadoLoteId !== lote.id || JSON.stringify(resultado) !== JSON.stringify(lote.resultado))) setLoteParaRevisar(lote);
        else abrirRevisaoLote(lote);
      }}
    /> : null}
    {loteParaRevisar ? <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
      <p>Abrir a análise do conjunto substituirá as sugestões e edições pendentes desta revisão. Confira os trechos que deseja incluir antes de continuar.</p>
      <div className="mt-2 flex gap-2"><button type="button" className={buttonClass} onClick={() => abrirRevisaoLote(loteParaRevisar)}>Abrir nova revisão</button><button type="button" className={buttonClass} onClick={() => setLoteParaRevisar(null)}>Manter revisão atual</button></div>
    </div> : null}

    <div className="mt-4 grid gap-4 xl:grid-cols-2">
      <div className="space-y-3 rounded-2xl bg-slate-50 p-4">
        <h4 className="font-semibold text-slate-900">1. Gravar e transcrever</h4>
        <p className="text-xs text-slate-600">Faça um teste curto do microfone. Envie uma gravação de até 30 minutos e 24 MB. O assistente divide gravações longas automaticamente. Mantenha a tela aberta até a transcrição terminar e baixe o áudio original para guardá-lo.</p>
        <p className="rounded-lg border border-teal-100 bg-white p-3 text-xs text-slate-700">Vai alternar entre celular e computador? Pare a gravação, revise e incorpore os trechos desejados e confira se o atendimento foi salvo antes de abrir no outro aparelho. Áudio e revisão pendente ficam neste navegador; não são transferidos automaticamente. Baixe o áudio se precisar levá-lo ao outro aparelho.</p>
        <label className="flex items-start gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={audio.manterCopia} disabled={ocupada || audio.carregandoBackup || !status?.usuario_id} onChange={(event) => void audio.setManterCopia(event.target.checked)} className="mt-1" />
          Permitir recuperação neste dispositivo por 24 horas. Cópias vencidas são apagadas na próxima abertura. Evite em computadores compartilhados e apague ao terminar.
        </label>
        <div className="flex flex-wrap items-center gap-2">
          {audio.gravando ? <button type="button" className={`${buttonClass} border-red-300 text-red-700`} onClick={audio.parar}><CircleStop className="h-4 w-4" />Parar gravação</button>
            : <button type="button" className={buttonClass} disabled={!consentimento || !revisaoPronta || loadingStatus || ocupada || Boolean(audio.audio) || audio.carregandoBackup} onClick={() => void audio.iniciar(status?.limites?.audio_bytes)}><Mic className="h-4 w-4" />{audio.iniciando ? "Abrindo microfone…" : "Iniciar gravação"}</button>}
          <span className="font-mono text-sm" aria-label="Tempo de gravação">{Math.floor(audio.seconds / 60).toString().padStart(2, "0")}:{(audio.seconds % 60).toString().padStart(2, "0")}</span>
          {audio.gravando ? <span className="text-xs font-semibold text-red-700">● Gravando</span> : null}
        </div>
        {audio.gravando ? <div>
          <meter aria-label="Nível do microfone" min="0" max="100" value={audio.nivel} className="w-full" />
          <p className="text-xs text-slate-500">Confira se o medidor reage à voz. Silêncio e ruído podem prejudicar a transcrição.</p>
        </div> : null}
        {!audio.audio ? <label className="block text-sm text-slate-700">Ou carregar áudio
          <input aria-label="Carregar áudio" type="file" accept={ASSISTENTE_AUDIO_ACCEPT} disabled={!revisaoPronta || loadingStatus || ocupada || audio.carregandoBackup} className="mt-1 block w-full text-sm" onChange={(event) => { const file = event.target.files?.[0]; if (file) audio.importar(file, status?.limites?.audio_bytes ?? ASSISTENTE_AUDIO_MAX_BYTES); event.target.value = ""; }} />
        </label> : null}
        {audio.audio ? <>
          <AudioPreview audio={audio.audio} />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={!podeUsarIA || ocupada || Boolean(erroEnvioAudio) || identificarAudio(audio.audio) === audioTranscrito} onClick={() => void transcrever()}><FileAudio className="h-4 w-4" />{busy === "transcrever" ? "Transcrevendo…" : identificarAudio(audio.audio) === audioTranscrito ? "Áudio transcrito" : "Transcrever áudio"}</button>
            <button type="button" className={buttonClass} disabled={ocupada} onClick={() => setConfirmarDescarte(true)}><Trash2 className="h-4 w-4" />Descartar áudio</button>
          </div>
          {confirmarDescarte ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
            <p>Apagar este áudio e sua cópia local? A transcrição já obtida continuará nesta tela.</p>
            <div className="mt-2 flex gap-2"><button type="button" className={buttonClass} onClick={() => { void audio.descartar(); setConfirmarDescarte(false); }}>Apagar áudio</button><button type="button" className={buttonClass} onClick={() => setConfirmarDescarte(false)}>Cancelar</button></div>
          </div> : null}
        </> : null}
        {audio.aviso ? <p role="status" className="text-sm text-amber-800">{audio.aviso}</p> : null}
        {erroEnvioAudio || audio.erro ? <p role="alert" className="text-sm text-red-700">{erroEnvioAudio || audio.erro}</p> : null}
      </div>

      <div className="space-y-3 rounded-2xl bg-slate-50 p-4">
        <h4 className="font-semibold text-slate-900">2. Conferir texto e exames</h4>
        <label className="block text-sm font-medium text-slate-700" htmlFor={`transcricao-${atendimentoId}`}>Transcrição para revisão</label>
        <textarea id={`transcricao-${atendimentoId}`} value={texto} disabled={!revisaoPronta || ocupada} maxLength={status?.limites?.transcricao_chars ?? 60000} onChange={(event) => { setTexto(event.target.value); if (revisoesTranscricao.length) setTranscricaoEditadaDesdeRevisao(true); limparAnalise(); }} rows={7} placeholder="A transcrição aparecerá aqui. Você também pode colar ou digitar o relato para organizar." className="w-full rounded-xl border border-slate-300 bg-white p-3 text-sm" />
        <AtendimentoTranscricaoRevisao fontes={revisoesTranscricao} textoEditado={transcricaoEditadaDesdeRevisao} />
        <label className="block text-sm text-slate-700">Fotografias ou PDFs dos exames
          <input aria-label="Fotografias ou PDFs dos exames" type="file" multiple accept={ASSISTENTE_FILE_ACCEPT} disabled={!revisaoPronta || ocupada} className="mt-1 block w-full text-sm" onChange={(event) => {
            const next = [...arquivos, ...Array.from(event.target.files || [])];
            const error = validarArquivosAssistente(next, status?.limites);
            if (error) setErro(error);
            else { setArquivos(next); setAnexados(false); limparAnalise(); setErro(""); }
            event.target.value = "";
          }} />
        </label>
        <p className="text-xs text-slate-500">Até 5 arquivos, 10 MB por arquivo e 20 MB no total. Selecione documentos do mesmo paciente; confira identificação, data e legibilidade.</p>
        {arquivos.length ? <ul className="space-y-2">{arquivos.map((file, index) => <li key={`${file.name}-${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-sm"><span className="break-all">{file.name}</span><ArquivoOriginalLink arquivo={file} /><button aria-label={`Remover ${file.name}`} type="button" className="text-red-700 disabled:opacity-50" disabled={ocupada} onClick={() => { setArquivos((prev) => prev.filter((_, i) => i !== index)); setAnexados(false); limparAnalise(); }}>Remover</button></li>)}</ul> : null}
        {arquivos.length ? <div>
          <p className="text-xs text-slate-600">{anexados ? "Arquivos guardados no prontuário." : "Selecionar ou analisar arquivos não os salva no prontuário."}</p>
          {onAttachFiles ? <button type="button" className={`${buttonClass} mt-2`} disabled={ocupada || anexados} onClick={() => void guardarArquivos()}>{busy === "anexar" ? "Guardando…" : anexados ? "Arquivos guardados" : "Guardar arquivos no prontuário"}</button> : null}
        </div> : null}
      </div>
    </div>

    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" className="inline-flex items-center gap-2 rounded-xl bg-teal-700 px-4 py-3 text-sm font-semibold text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-50" disabled={!podeUsarIA || ocupada || (!texto.trim() && !arquivos.length)} onClick={() => void analisar()}>{busy === "analisar" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{busy === "analisar" ? "Analisando fontes…" : "Organizar e sugerir para revisão"}</button>
      {status ? <span className="text-xs text-slate-500">Análise: {status.modelo} · {arquivos.length ? status.esforco : (status.esforco_texto ?? status.esforco)}. Transcrição: {status.modelo_transcricao}.</span> : null}
      {busy === "analisar" || busy === "transcrever" ? <button type="button" className={buttonClass} onClick={() => { request.current?.abort(); request.current = null; setBusy(null); setAvisos(["Solicitação cancelada nesta tela. As fontes foram preservadas. O processamento no servidor pode já ter começado."]); }}>Cancelar espera</button> : null}
    </div>
    {busy === "analisar" ? <p role="status" className="mt-2 text-sm text-slate-600">A análise aprofundada pode levar alguns minutos. Mantenha esta tela aberta.</p> : null}
    {erro ? <p role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm text-red-800">{erro}</p> : null}
    {avisos.map((aviso, index) => <p key={index} className="mt-2 text-sm text-amber-800">{aviso}</p>)}

    {resultado ? <div className="mt-6 space-y-4 border-t border-slate-200 pt-5">
      <h4 className="font-semibold text-slate-900">3. Revisão do veterinário</h4>
      {resultado.revisao_desatualizada ? <p role="alert" className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Esta revisão está desatualizada. Os textos editados foram mantidos como referência, com inclusão desabilitada. Consulte o progresso e abra a nova revisão do conjunto antes de continuar.</p> : resultado.bloqueado_integracao ? <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">Integração bloqueada: há identificação ausente ou divergente nas fontes. Se a única divergência for a raça, confira os originais e registre sua decisão no conjunto. As demais divergências precisam ser esclarecidas antes de incorporar informações.</p> : null}
      {resultado.raca_pendente_revisao ? <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Raça pendente de revisão veterinária. A análise considera a raça não confirmada; o cadastro e a identificação original dos exames permanecem preservados.</p> : null}
      {resultado.avisos.map((aviso, index) => <p key={index} className="text-sm text-amber-800">{aviso}</p>)}
      {resultado.fontes?.length ? <div className="rounded-xl bg-slate-50 p-4"><h5 className="font-medium">Identificação das fontes</h5><ul className="mt-2 space-y-2 text-sm">{resultado.fontes.map((fonte, index) => <li key={index}><strong className="break-all">{fonte.arquivo}</strong>: {fonte.paciente_nome || "Paciente não identificado"} · {fonte.especie || "Espécie ausente"} · {fonte.data_exame || "Data ausente"}<p className={fonte.identidade === "compativel" ? "text-slate-600" : "text-amber-800"}>Leitura original: {fonte.motivo}</p>{temRevisaoRacaConfirmada(fonte) ? <p className="mt-1 font-medium text-teal-900">Decisão veterinária: documento do mesmo paciente, com raça pendente de revisão. Registrada em {new Date(fonte.revisao_raca!.registrado_em).toLocaleString("pt-BR")}.</p> : null}</li>)}</ul></div> : null}
      {resultado.pendencias.length ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-4"><h5 className="font-medium text-amber-900">Informações para confirmar</h5><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900">{resultado.pendencias.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
      {resultado.campos.length ? <div className="space-y-3"><h5 className="font-medium">Informações propostas para o atendimento</h5>{resultado.campos.map((campo, index) => <article key={index} className="rounded-xl border border-slate-200 p-4">
        <label htmlFor={`campo-ia-${atendimentoId}-${index}`} className="text-sm font-semibold">{ASSISTENTE_CAMPO_LABELS[campo.campo] || campo.campo}</label>
        <p className="mt-1 text-xs text-slate-500">Fonte: {campo.fonte}</p>
        <blockquote className="my-2 border-l-2 border-teal-300 pl-3 text-sm text-slate-600">{campo.evidencia}</blockquote>
        <textarea id={`campo-ia-${atendimentoId}-${index}`} rows={3} className="w-full rounded-lg border border-slate-300 p-2 text-sm" value={edicoes[index] ?? campo.texto} disabled={aplicados[index] || resultado.bloqueado_integracao} onChange={(event) => { setEdicoes((prev) => ({ ...prev, [index]: event.target.value })); setRevisados((prev) => ({ ...prev, [index]: false })); }} />
        <label className="mt-2 flex items-start gap-2 text-sm text-slate-700"><input type="checkbox" checked={Boolean(revisados[index])} disabled={aplicados[index] || !podeIncorporarCampo(resultado, campo)} onChange={(event) => setRevisados((prev) => ({ ...prev, [index]: event.target.checked }))} className="mt-1" />Conferi este trecho com a fonte e aprovo sua inclusão.</label>
        <button type="button" className={`${buttonClass} mt-2`} disabled={ocupada || Boolean(aplicados[index]) || !revisados[index] || !edicoes[index]?.trim() || !podeIncorporarCampo(resultado, campo)} onClick={() => incorporarResultado("campo", index)}>{aplicados[index] ? "Adicionado ao atendimento" : "Adicionar ao atendimento"}</button>
      </article>)}</div> : null}
      {resultado.achados_exames.length ? <div className="space-y-3"><h5 className="font-medium">Dados extraídos dos exames — conferir no original</h5>{resultado.achados_exames.map((achado, index) => <article key={index} className="rounded-xl border border-slate-200 p-4 text-sm">
        <p className="break-all text-xs text-slate-500">{achado.arquivo}{achado.pagina ? ` · página ${achado.pagina}` : ""} · confiança informada pela IA: {achado.confianca}</p>
        <p className="mt-1 font-medium">{achado.descricao}</p>
        <blockquote className="my-2 border-l-2 border-teal-300 pl-3 text-slate-600">{achado.evidencia}</blockquote>
        {achado.valor ? <p>Valor: {achado.valor} {achado.unidade || "(unidade não informada)"}</p> : null}
        {achado.referencia ? <p>Referência no documento: {achado.referencia}</p> : null}
        {achado.alertas.map((alerta, i) => <p key={i} className="mt-1 text-amber-800">{alerta}</p>)}
        {podeIncorporarAchado(resultado, achado) ? <div className="mt-3 border-t border-slate-100 pt-3">
          <label className="text-sm font-medium" htmlFor={`achado-ia-${atendimentoId}-${index}`}>Texto para os dados clínicos</label>
          <textarea id={`achado-ia-${atendimentoId}-${index}`} rows={3} className="mt-1 w-full rounded-lg border border-slate-300 p-2" value={achadosEditados[index] ?? ""} disabled={achadosAplicados[index]} onChange={(event) => { setAchadosEditados((prev) => ({ ...prev, [index]: event.target.value })); setAchadosRevisados((prev) => ({ ...prev, [index]: false })); }} />
          <label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={Boolean(achadosRevisados[index])} disabled={achadosAplicados[index]} onChange={(event) => setAchadosRevisados((prev) => ({ ...prev, [index]: event.target.checked }))} className="mt-1" />Conferi este achado no exame original, incluindo paciente, data, valor e unidade.</label>
          <button type="button" className={`${buttonClass} mt-2`} disabled={ocupada || achadosAplicados[index] || !achadosRevisados[index] || !achadosEditados[index]?.trim()} onClick={() => incorporarResultado("achado", index)}>{achadosAplicados[index] ? "Achado adicionado" : "Adicionar achado aos dados clínicos"}</button>
        </div> : <p className="mt-2 text-xs text-amber-800">Confira ou complemente a fonte antes de usar este achado no prontuário.</p>}
      </article>)}</div> : null}
      {resultado.sugestoes.length ? <div className="space-y-3 rounded-2xl bg-indigo-50 p-4"><h5 className="font-medium text-indigo-950">Plano e condutas para sua avaliação</h5><p className="text-sm text-indigo-900">Estas são hipóteses e propostas da IA. Avalie sua pertinência clínica antes de redigir o plano ou emitir documentos.</p>{resultado.sugestoes.map((sugestao, index) => <article key={index} className="rounded-xl bg-white p-4 text-sm"><h6 className="font-semibold">{sugestao.titulo}</h6><p className="mt-2 whitespace-pre-wrap">{sugestao.conduta}</p><p className="mt-2 text-slate-600">Justificativa: {sugestao.justificativa}</p>{sugestao.limitacoes.map((item, i) => <p key={i} className="mt-1 text-amber-800">{item}</p>)}</article>)}</div> : null}
      <p className="text-xs text-slate-500">Resultado gerado por {resultado.modelo} ({resultado.esforco}). A confiança declarada pela IA não substitui a conferência clínica. Ao navegar, a revisão permanece temporariamente na memória desta aba para o mesmo usuário, paciente e atendimento. Recarregar ou fechar a aba apaga essa revisão; a cópia de áudio no dispositivo segue a opção de recuperação acima.</p>
    </div> : null}
  </details>;
}

export default function AtendimentoAssistenteIA(props: AtendimentoAssistenteIAProps) {
  if (!props.atendimentoId) return <section className="rounded-2xl border border-teal-200 bg-teal-50 p-4"><h3 className="font-semibold text-teal-950">Assistente de atendimento</h3><p className="mt-1 text-sm text-teal-900">Salve o atendimento e confirme o paciente para gravar, transcrever ou analisar exames.</p></section>;
  return <AtendimentoAssistenteSalvo key={`${props.atendimentoId}:${props.pacienteId}`} {...props} atendimentoId={props.atendimentoId} />;
}
