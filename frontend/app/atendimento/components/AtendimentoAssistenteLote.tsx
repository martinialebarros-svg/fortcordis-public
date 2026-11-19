"use client";

import { useEffect, useImperativeHandle, useRef, useState, type Ref } from "react";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import AtendimentoTranscricaoRevisao from "./AtendimentoTranscricaoRevisao";
import { ASSISTENTE_AUDIO_ACCEPT, ASSISTENTE_AUDIO_MAX_BYTES, ASSISTENTE_FILE_ACCEPT } from "@/lib/atendimento-assistente-ia";
import {
  STATUS_FONTE_LOTE, tipoArquivoLote, validarArquivosLote,
  type ArquivoLoteLocal, type AssistenteLote, type FonteLote, type ModoAssistenteLote,
} from "@/lib/atendimento-assistente-lote";

export interface AtendimentoAssistenteLoteAcoes {
  iniciarComFontes: (files: File[], modo: ModoAssistenteLote) => boolean;
}

interface Props {
  acoesRef?: Ref<AtendimentoAssistenteLoteAcoes>;
  atendimentoId: number;
  pacienteId: number;
  usuarioId: number;
  texto: string;
  consentimento: boolean;
  habilitado: boolean;
  disabled: boolean;
  audioAtual?: File | null;
  onEnsureSaved?: () => Promise<boolean>;
  onReview: (lote: AssistenteLote) => void;
  onBusyChange: (busy: boolean) => void;
  onActiveChange: (active: boolean) => void;
  onPendingChange: (pending: boolean) => void;
  onResultInvalidated?: (loteId: string) => void;
  onSnapshot?: (lote: AssistenteLote | null) => void;
}

const buttonBaseClass = "rounded-xl border border-teal-300 px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";
const buttonClass = `${buttonBaseClass} bg-white text-teal-900`;
const accept = `${ASSISTENTE_AUDIO_ACCEPT},${ASSISTENTE_FILE_ACCEPT}`;

type ArquivoSelecionado = ArquivoLoteLocal & { audioDoAtendimento?: true };
type AcaoRevisao = "revisar-raca" | "revogar-revisao-raca" | "revisar-identidade" | "revogar-revisao-identidade";

export default function AtendimentoAssistenteLote(props: Props) {
  const { atendimentoId, pacienteId, usuarioId, texto, consentimento, habilitado, disabled, audioAtual,
    onEnsureSaved, onReview, onBusyChange, onActiveChange, onPendingChange, onResultInvalidated, onSnapshot } = props;
  const painel = useRef<HTMLElement | null>(null);
  const [lote, setLote] = useState<AssistenteLote | null>(null);
  const [selecao, setArquivos] = useState<ArquivoSelecionado[]>([]);
  const arquivos = selecao.filter((item) => !item.audioDoAtendimento || item.file === audioAtual);
  const audioJaSelecionado = Boolean(audioAtual && arquivos.some((item) => item.file === audioAtual));
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [erro, setErro] = useState("");
  const [confirmarNovo, setConfirmarNovo] = useState(false);
  const [fontesRaca, setFontesRaca] = useState<string[]>([]);
  const [confirmoPaciente, setConfirmoPaciente] = useState(false);
  const [confirmoRaca, setConfirmoRaca] = useState(false);
  const [fonteConferida, setFonteConferida] = useState<string | null>(null);
  const [avisoRevisao, setAvisoRevisao] = useState("");
  const alive = useRef(true);
  const request = useRef<AbortController | null>(null);
  const activeOperation = useRef(false);
  const latestRead = useRef(0);
  const audioAtualRef = useRef(audioAtual);
  audioAtualRef.current = audioAtual;
  const snapshotCallback = useRef(onSnapshot);
  snapshotCallback.current = onSnapshot;
  const revisaoAnterior = useRef<string | null>(null);
  const pedidoRevisao = useRef<{
    acao: AcaoRevisao;
    id: string;
    token: string;
    arquivos: string[];
    request_id: string;
  } | null>(null);
  const manifest = useRef<{
    request_id: string; transcricao: string; consentimento: true; modo?: ModoAssistenteLote;
    arquivos: Array<Pick<FonteLote, "id" | "nome" | "tipo" | "tamanho" | "mime">>;
  } | null>(null);
  const base = `/atendimentos/${atendimentoId}/assistente/lotes`;
  const active = Boolean(lote && ["uploading", "queued", "processing"].includes(lote.status));
  const revisaoIdentidade = lote?.revisao_identidade;
  const tokenRevisao = revisaoIdentidade?.token ?? lote?.revisao_raca?.token ?? null;

  const aceitarLote = (data: AssistenteLote | null) => {
    if (data && (data.atendimento_id !== atendimentoId || data.paciente_id !== pacienteId)) {
      throw new Error("O conjunto pertence a outro contexto. Confira o paciente e o atendimento.");
    }
    latestRead.current += 1;
    if (alive.current) {
      setLote(data);
      snapshotCallback.current?.(data);
    }
    return data;
  };

  const consultar = async (signal: AbortSignal, id?: string) => {
    const sequence = ++latestRead.current;
    try {
      const { data } = await api.get<AssistenteLote | null>(id ? `${base}/${id}` : `${base}/atual`, { signal });
      if (signal.aborted) return null;
      if (sequence !== latestRead.current) {
        throw new Error("O estado do conjunto mudou durante a consulta. Consulte o progresso e tente novamente.");
      }
      return aceitarLote(data);
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (id && (status === 404 || status === 410) && !signal.aborted && sequence === latestRead.current) {
        aceitarLote(null); manifest.current = null;
      }
      throw error;
    }
  };

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    setLoading(true);
    void consultar(controller.signal).catch((error) => {
      if (!controller.signal.aborted) setErro(extractApiErrorMessageSync(error, "Não foi possível recuperar o conjunto. Consulte novamente antes de iniciar."));
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { alive.current = false; controller.abort(); request.current?.abort(); };
    // The parent keys this component by user, patient and attendance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [atendimentoId, pacienteId, usuarioId]);

  useEffect(() => {
    if (busy || !lote || !["queued", "processing"].includes(lote.status)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      // Mutations reconcile their own state. Do not supersede that read with a poll.
      if (activeOperation.current || controller.signal.aborted) return;
      try {
        await consultar(controller.signal, lote.id);
        if (!controller.signal.aborted) setErro("");
      } catch (error) {
        if (!controller.signal.aborted) setErro(extractApiErrorMessageSync(error, "A consulta do progresso falhou. Tentaremos recuperar o estado novamente."));
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 3000);
    };
    timer = setTimeout(() => void poll(), 2000);
    return () => { controller.abort(); clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [busy, lote?.id, lote?.status]);

  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false); }, [busy, onBusyChange]);
  useEffect(() => { onActiveChange(active); return () => onActiveChange(false); }, [active, onActiveChange]);
  useEffect(() => {
    setArquivos((current) => current.some((item) => item.audioDoAtendimento && item.file !== audioAtual)
      ? current.filter((item) => !item.audioDoAtendimento || item.file === audioAtual)
      : current);
  }, [audioAtual]);
  useEffect(() => {
    if (revisaoAnterior.current !== tokenRevisao) {
      if (revisaoAnterior.current && !activeOperation.current) {
        setAvisoRevisao("A revisão do conjunto mudou. Confira os documentos novamente antes de registrar outra decisão.");
      }
      revisaoAnterior.current = tokenRevisao;
      setFontesRaca([]); setConfirmoPaciente(false); setConfirmoRaca(false);
      setFonteConferida(null);
      if (!activeOperation.current) pedidoRevisao.current = null;
    }
  }, [tokenRevisao]);
  useEffect(() => {
    onPendingChange(Boolean(arquivos.length && (!lote || lote.status === "uploading")));
    return () => onPendingChange(false);
  }, [arquivos.length, lote, onPendingChange]);

  const executar = async (operation: (signal: AbortSignal) => Promise<void>) => {
    if (activeOperation.current) return;
    activeOperation.current = true;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setErro("");
    try { await operation(controller.signal); }
    catch (error) {
      if (alive.current && !controller.signal.aborted) setErro(extractApiErrorMessageSync(error, "Não foi possível concluir. Consulte o estado e retome os arquivos pendentes."));
    } finally {
      activeOperation.current = false;
      if (alive.current && request.current === controller) { setBusy(false); request.current = null; }
    }
  };

  const enviarFonte = async (loteId: string, fonte: FonteLote, file: File, signal: AbortSignal) => {
    const url = `${base}/${loteId}/arquivos/${fonte.id}`;
    if (fonte.tipo !== "audio" || file.size <= ASSISTENTE_AUDIO_MAX_BYTES) {
      const payload = new FormData();
      payload.append("arquivo", file);
      const { data } = await api.put<AssistenteLote>(url, payload, { signal, timeout: 300000 });
      if (!signal.aborted) aceitarLote(data);
      return;
    }

    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    const hash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    if (fonte.upload_sha256 && fonte.upload_sha256 !== hash) {
      throw new Error("Selecione o mesmo áudio original para continuar o envio.");
    }
    let offset = fonte.bytes_recebidos ?? 0;
    while (offset < file.size && !signal.aborted) {
      const end = Math.min(offset + 8_000_000, file.size);
      const payload = new FormData();
      payload.append("arquivo", file.slice(offset, end), file.name);
      const { data } = await api.put<AssistenteLote>(url, payload, {
        params: { deslocamento: offset }, headers: { "X-Audio-Sha256": hash }, signal, timeout: 300000,
      });
      if (signal.aborted) return;
      aceitarLote(data);
      const saved = data.arquivos.find((item) => item.id === fonte.id);
      if (saved?.status === "uploaded" && end === file.size) return;
      if (saved?.bytes_recebidos !== end) throw new Error("Consulte o progresso para retomar o envio do áudio.");
      offset = end;
    }
  };

  const enviar = (novasFontes?: File[], modo: ModoAssistenteLote = "analise") => void executar(async (signal) => {
    if (!consentimento || !habilitado || disabled) return;
    if (onEnsureSaved && !(await onEnsureSaved())) throw new Error("Salve o atendimento e confirme o paciente antes de analisar o conjunto.");
    if (signal.aborted) return;
    // Reconcile uncertain writes before uploading or scheduling again.
    const substituindoTranscricao = Boolean(manifest.current && lote?.modo === "transcricao" && lote.status === "completed");
    let atual = await consultar(signal, substituindoTranscricao ? undefined : lote?.id);
    if (substituindoTranscricao && atual?.id === lote?.id) atual = null;
    if (signal.aborted) return;
    const podeContinuarComExames = modo === "analise" && novasFontes && atual?.modo === "transcricao" && atual.status === "completed";
    if (podeContinuarComExames && !texto.trim()) {
      throw new Error("Use a transcrição concluída antes de organizar o texto com os exames.");
    }
    if (novasFontes && atual && !podeContinuarComExames) {
      throw new Error("Já existe um conjunto neste atendimento. Consulte o progresso ou prepare um novo conjunto para usar outras fontes.");
    }
    let fontes = arquivos;
    if (novasFontes) {
      if (manifest.current && !atual) {
        throw new Error("Consulte o progresso ou retome o envio da tentativa anterior no painel do conjunto.");
      }
      if (!atual && arquivos.some((item) => !novasFontes.includes(item.file))) {
        throw new Error("Há outras fontes selecionadas no conjunto. Confira a seleção antes de iniciar.");
      }
      fontes = novasFontes.map((file): ArquivoSelecionado => ({
        id: crypto.randomUUID(), file, tipo: tipoArquivoLote(file),
        ...(file === audioAtual ? { audioDoAtendimento: true } : {}),
      }));
    }
    const audioDisponivel = (item: ArquivoSelecionado) => !item.audioDoAtendimento || item.file === audioAtualRef.current;
    if (!atual || podeContinuarComExames) {
      if (!fontes.length) throw new Error("Selecione os áudios e exames deste atendimento.");
      if (!fontes.every(audioDisponivel)) throw new Error("O áudio deste atendimento mudou. Confira o conjunto antes de analisar.");
      if (manifest.current?.arquivos.some((fonte) => !fontes.some((item) => item.id === fonte.id))) {
        throw new Error("Uma fonte da tentativa anterior foi retirada. Use Preparar novo conjunto para escolher as fontes novamente.");
      }
      const invalid = validarArquivosLote(fontes.map((item) => item.file));
      if (invalid) throw new Error(invalid);
      if (modo === "analise" && texto.length > 80000) throw new Error("A transcrição excede 80.000 caracteres. Revise o texto antes de iniciar.");
      manifest.current ??= {
        request_id: crypto.randomUUID(), transcricao: modo === "transcricao" ? "" : texto, consentimento: true,
        ...(modo === "transcricao" ? { modo } : {}),
        arquivos: fontes.map(({ id, file, tipo }) => ({ id, nome: file.name, tipo, tamanho: file.size, mime: file.type })),
      };
      setArquivos(fontes);
      const { data } = await api.post<AssistenteLote>(base, manifest.current, { signal, timeout: 30000 });
      if (signal.aborted) return;
      atual = aceitarLote(data);
    }
    if (!atual) return;
    if (atual.status === "failed") {
      const { data } = await api.post<AssistenteLote>(`${base}/${atual.id}/retomar`, {}, { signal, timeout: 30000 });
      if (!signal.aborted) aceitarLote(data);
      return;
    }
    if (atual.status !== "uploading") return;
    const falhas: string[] = [];
    for (const fonte of atual.arquivos.filter((item) => item.status === "pending")) {
      if (signal.aborted) return;
      const local = fontes.find((item) => item.id === fonte.id && audioDisponivel(item));
      if (!local) { falhas.push(fonte.nome); continue; }
      try {
        await enviarFonte(atual.id, fonte, local.file, signal);
      } catch {
        if (signal.aborted) return;
        // The server may have accepted the file even if its response was lost.
        const refreshed = await consultar(signal, atual.id);
        if (refreshed?.arquivos.find((item) => item.id === fonte.id)?.status === "pending") falhas.push(fonte.nome);
      }
    }
    const refreshed = await consultar(signal, atual.id);
    if (signal.aborted || !refreshed) return;
    if (refreshed.arquivos.some((item) => item.status === "pending")) {
      throw new Error(`Envio pendente de ${falhas.length || refreshed.arquivos.filter((item) => item.status === "pending").length} arquivo(s). Selecione os arquivos indicados e retome o envio.`);
    }
    const { data } = await api.post<AssistenteLote>(`${base}/${atual.id}/iniciar`, {}, { signal, timeout: 30000 });
    if (!signal.aborted) {
      aceitarLote(data);
      manifest.current = null;
    }
  });

  useImperativeHandle(props.acoesRef, () => ({
    iniciarComFontes(files, modo) {
      if (loading || activeOperation.current) return false;
      painel.current?.scrollIntoView?.({ block: "nearest" });
      enviar(files, modo);
      return true;
    },
  }));

  const selecionarFontePendente = (fonte: FonteLote, file: File) => {
    if (file.name !== fonte.nome || file.size !== fonte.tamanho) {
      setErro("Selecione o arquivo original com o mesmo nome e tamanho para esta fonte.");
      return;
    }
    setArquivos((current) => [...current.filter((item) => item.id !== fonte.id), { id: fonte.id, file, tipo: fonte.tipo }]);
    setErro("");
  };

  const selecionar = (files: File[]) => {
    if (lote) {
      const next = [...arquivos];
      for (const fonte of lote.arquivos.filter((item) => item.status === "pending")) {
        const matches = files.filter((file) => file.name === fonte.nome && file.size === fonte.tamanho);
        const slots = lote.arquivos.filter((item) => item.status === "pending" && item.nome === fonte.nome && item.tamanho === fonte.tamanho);
        if (matches.length !== 1 || slots.length !== 1) {
          if (matches.length) setErro("Há arquivos com o mesmo nome e tamanho. Selecione cada original no campo da fonte correspondente.");
          continue;
        }
        const index = next.findIndex((item) => item.id === fonte.id);
        const local = { id: fonte.id, file: matches[0], tipo: fonte.tipo };
        if (index >= 0) next[index] = local;
        else next.push(local);
      }
      setArquivos(next);
      return;
    }
    const novos: ArquivoSelecionado[] = files
      .filter((file, index) => file !== audioAtual || (!audioJaSelecionado && files.indexOf(file) === index))
      .map((file) => ({
        id: crypto.randomUUID(), file, tipo: tipoArquivoLote(file),
        ...(file === audioAtual ? { audioDoAtendimento: true } : {}),
      }));
    const next = [...arquivos, ...novos];
    const invalid = validarArquivosLote(next.map((item) => item.file));
    if (invalid) { setErro(invalid); return; }
    setArquivos(next); setErro("");
  };

  const removerLote = () => void executar(async (signal) => {
    let atual: AssistenteLote | null;
    try { atual = await consultar(signal, lote?.id); }
    catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status !== 404 && status !== 410) throw error;
      atual = null;
    }
    if (signal.aborted) return;
    if (atual) await api.delete(`${base}/${atual.id}`, { signal, timeout: 30000 });
    if (signal.aborted) return;
    aceitarLote(null); setArquivos([]); manifest.current = null; setConfirmarNovo(false);
  });
  const selecionarRaca = (id: string, checked: boolean) => {
    setFontesRaca((current) => checked ? [...current, id] : current.filter((item) => item !== id));
    setConfirmoPaciente(false); setConfirmoRaca(false); setAvisoRevisao(""); pedidoRevisao.current = null;
  };
  const decidirRevisao = (acao: AcaoRevisao, ids = fontesRaca) => void executar(async (signal) => {
    const exibido = lote;
    const identidade = acao.endsWith("identidade");
    const chave = identidade ? "revisao_identidade" : "revisao_raca";
    const revisao = exibido?.[chave];
    if (!exibido || !revisao?.pode_revisar || disabled || !habilitado || !ids.length) return;
    const confirmar = !acao.startsWith("revogar-");
    if (confirmar && (!consentimento || (identidade ? ids[0] !== fonteConferida : !confirmoPaciente || !confirmoRaca))) return;
    const escolhidos = [...ids].sort();
    const fontes = revisao.fontes.filter((fonte) => escolhidos.includes(fonte.arquivo_id));
    if (fontes.length !== escolhidos.length || fontes.some((fonte) => confirmar ? !fonte.elegivel || fonte.confirmada : !fonte.confirmada)) return;
    setAvisoRevisao("");
    if (onEnsureSaved && !(await onEnsureSaved())) throw new Error("Salve o atendimento antes de revisar a identificação dos exames.");
    if (signal.aborted) return;
    const anterior = pedidoRevisao.current;
    const mesmoPedido = anterior?.id === exibido.id && anterior.acao === acao &&
      anterior.token === revisao.token && JSON.stringify(anterior.arquivos) === JSON.stringify(escolhidos);
    const pedido = mesmoPedido ? anterior : {
      acao, id: exibido.id, token: revisao.token, arquivos: escolhidos, request_id: crypto.randomUUID(),
    };
    pedidoRevisao.current = pedido;
    const aplicada = (atual: AssistenteLote | null) => Boolean(atual?.[chave] && escolhidos.every((id) => {
      const fonte = atual[chave]?.fontes.find((item) => item.arquivo_id === id);
      return fonte && (confirmar ? fonte.confirmada : !fonte.confirmada);
    }));
    const concluir = () => {
      onResultInvalidated?.(exibido.id);
      pedidoRevisao.current = null;
      setFontesRaca([]); setConfirmoPaciente(false); setConfirmoRaca(false);
      setFonteConferida(null);
      setAvisoRevisao(confirmar
        ? identidade ? "Identificação confirmada para este arquivo." : "Decisão registrada. A raça continua pendente; o cadastro e os documentos originais foram preservados."
        : "Confirmação retirada. A análise anterior precisa ser revista antes de incorporar informações.");
    };
    // Consult before any replay. A lost response must not schedule synthesis twice.
    const atual = await consultar(signal, exibido.id);
    if (signal.aborted) return;
    if (mesmoPedido && aplicada(atual)) { concluir(); return; }
    if (!atual?.[chave] || atual[chave]?.token !== pedido.token) {
      setFontesRaca([]); setConfirmoPaciente(false); setConfirmoRaca(false);
      setFonteConferida(null); pedidoRevisao.current = null;
      throw new Error("O conjunto mudou desde a conferência. Revise a identificação novamente antes de continuar.");
    }
    if (!atual[chave]?.pode_revisar) throw new Error("A revisão não está disponível neste estado do conjunto. Consulte o progresso.");
    const payload = {
      request_id: pedido.request_id, revisao_token: pedido.token, arquivo_ids: pedido.arquivos,
      ...(confirmar ? { confirmo_mesmo_paciente: true, consentimento: true, ...(identidade
        ? { confirmo_apenas_nome_idade: true, atualizar_contexto: Boolean(exibido.revisao_identidade?.contexto_mudou) }
        : { confirmo_apenas_raca: true }) } : {}),
    };
    // An uncertain response also invalidates the displayed analysis until reconciled.
    onResultInvalidated?.(exibido.id);
    try {
      const { data } = await api.post<AssistenteLote>(`${base}/${exibido.id}/${acao}`, payload, { signal, timeout: 30000 });
      if (signal.aborted) return;
      aceitarLote(data);
      if (!aplicada(data)) throw new Error("A decisão precisa ser conferida no estado atual do conjunto.");
      concluir();
    } catch (error) {
      if (signal.aborted) return;
      try {
        const recuperado = await consultar(signal, exibido.id);
        if (!signal.aborted && aplicada(recuperado)) { concluir(); return; }
      } catch { /* Keep the same request id until an explicit reconciled retry. */ }
      throw error;
    }
  });
  const bloqueado = busy || disabled || loading;
  const pendingUpload = lote?.status === "uploading";
  const identidadesPendentes = revisaoIdentidade?.fontes.some((fonte) => !fonte.confirmada);
  const fontesRevisaoRaca = lote?.revisao_raca?.fontes.filter((fonte) =>
    !revisaoIdentidade?.fontes.some((item) => item.arquivo_id === fonte.arquivo_id && item.confirmada)) ?? [];
  const original = (id: string) => `/api/v1${base}/${lote?.id}/arquivos/${id}/original`;
  const substituicaoPendente = Boolean(manifest.current && lote?.modo === "transcricao" && lote.status === "completed");
  const statusText = lote ? {
    uploading: "Enviando fontes do conjunto",
    queued: "Conjunto na fila de processamento",
    processing: lote.modo === "transcricao" ? "Transcrevendo áudio" : "Analisando áudios e exames",
    failed: "Conjunto aguardando retomada",
    completed: lote.modo === "transcricao" ? "Transcrição concluída" : lote.resultado?.bloqueado_integracao || !lote.resultado ? "Leitura concluída — identificação aguardando revisão" : "Análise conjunta concluída",
  }[lote.status] : "";

  return <section ref={painel} aria-label="Análise conjunta de áudios e exames" className="mt-4 space-y-3 rounded-2xl border border-teal-200 bg-teal-50 p-4">
    <h4 className="font-semibold text-teal-950">Analisar áudios e exames em conjunto</h4>
    <p className="text-sm text-slate-700">Selecione os áudios, fotos ou PDFs do mesmo paciente. Uma única solicitação transcreve os áudios, lê os exames e cruza as fontes com o atendimento salvo. O texto já preenchido abaixo também entra na análise.</p>
    <p className="text-xs text-slate-600">Até 5 áudios de 60 MB e 70 minutos cada, e até 15 exames de 10 MB cada, com 60 MB de exames no total. Os arquivos e o resultado do conjunto ficam disponíveis por 24 horas para retomada e revisão.</p>
    {loading ? <p role="status">Recuperando conjunto…</p> : null}
    {!lote || pendingUpload ? <label className="block text-sm font-medium text-slate-800">
      {pendingUpload ? "Selecionar novamente arquivos pendentes" : "Áudios e PDFs do conjunto"}
      <input aria-label={pendingUpload ? "Selecionar novamente arquivos pendentes" : "Áudios e PDFs do conjunto"} type="file" multiple accept={accept} disabled={bloqueado || (!lote && Boolean(manifest.current))} className="mt-2 block w-full" onChange={(event) => { selecionar(Array.from(event.target.files || [])); event.target.value = ""; }} />
    </label> : null}
    {!lote && audioAtual ? <button type="button" className={buttonClass}
      disabled={bloqueado || Boolean(manifest.current) || audioJaSelecionado}
      onClick={() => selecionar([audioAtual])}
    >{audioJaSelecionado ? "Áudio do atendimento no conjunto" : "Usar áudio deste atendimento"}</button> : null}
    {!lote && arquivos.length ? <ol className="space-y-2">{arquivos.map(({ id, file, tipo, audioDoAtendimento }, index) => <li key={id} className="flex items-center justify-between gap-3 rounded-lg bg-white p-2 text-sm">
      <span className="min-w-0 flex-1 break-all">{index + 1}. {file.name} · {audioDoAtendimento ? "Áudio deste atendimento" : tipo === "audio" ? "Áudio" : "Exame"} · {(file.size / 1_000_000).toFixed(1)} MB</span>
      <button type="button" className="shrink-0 text-red-700 disabled:opacity-50" disabled={bloqueado || Boolean(manifest.current)} onClick={() => setArquivos((current) => current.filter((item) => item.id !== id))} aria-label={`Retirar ${file.name} do conjunto`}>Retirar</button>
    </li>)}</ol> : null}
    {lote ? <>
      {lote.status === "completed" && lote.modo !== "transcricao" ? <p className="text-sm text-slate-700">Confira os trechos já salvos no prontuário antes de incluir novamente. A revisão do conjunto fica disponível abaixo ao abrir o resultado.</p> : null}
      <p role="status" className="font-medium text-teal-950">{statusText}</p>
      <ol className="space-y-2">{lote.arquivos.map((fonte, index) => <li key={fonte.id} className="rounded-lg bg-white p-2 text-sm">
        <span className="break-all">{index + 1}. {fonte.nome} — {STATUS_FONTE_LOTE[fonte.status]}</span>
        {fonte.status !== "pending" ? <a className="ml-3 text-teal-800 underline" href={original(fonte.id)} target="_blank" rel="noopener noreferrer">Baixar original</a> : null}
        {fonte.erro ? <p className="mt-1 text-red-700">{fonte.erro}</p> : null}
        {fonte.status === "pending" ? <label className="mt-2 block text-amber-900">
          {arquivos.some((item) => item.id === fonte.id) ? "Arquivo selecionado para retomada" : "Selecione novamente este arquivo para concluir o envio."}
          <input type="file" accept={accept} aria-label={`Original da fonte ${index + 1}: ${fonte.nome}`} disabled={bloqueado} className="mt-1 block w-full text-sm" onChange={(event) => { const file = event.target.files?.[0]; if (file) selecionarFontePendente(fonte, file); event.target.value = ""; }} />
        </label> : null}
      </li>)}</ol>
      {lote.status !== "completed" && lote.revisoes_transcricao?.length ? <AtendimentoTranscricaoRevisao fontes={lote.revisoes_transcricao} /> : null}
      {lote.erro ? <p role="alert" className="text-red-800">{lote.erro}</p> : null}
      {lote.status === "queued" || lote.status === "processing" ? <p className="text-sm text-slate-700">O processamento continua no servidor. Ao voltar a este atendimento, o progresso é recuperado. A revisão será liberada depois que todas as fontes forem processadas.</p> : null}
      {revisaoIdentidade && revisaoIdentidade.fontes.length > 0 ? <fieldset className="space-y-3 rounded-xl border border-amber-200 bg-white p-3" disabled={bloqueado || !habilitado || !revisaoIdentidade.pode_revisar}>
        <legend className="px-1 font-semibold text-amber-950">Confirmar paciente por arquivo</legend>
        <p className="text-sm text-slate-700">
          Paciente do atendimento <strong>{revisaoIdentidade.paciente_nome}</strong>
          {revisaoIdentidade.paciente_idade ? ` · Idade no cadastro ${revisaoIdentidade.paciente_idade}` : ""}.
          Confira a identificação no original. Ao resolver as pendências, a análise retoma com os arquivos já processados.
        </p>
        {revisaoIdentidade.contexto_mudou ? <p className="text-sm text-amber-900">
          O atendimento salvo mudou. Confira novamente cada exame com os dados atuais. A primeira confirmação atualiza o contexto do conjunto e invalida as confirmações anteriores.
        </p> : null}
        <ul className="space-y-3">{revisaoIdentidade.fontes.map((fonte) => <li key={fonte.arquivo_id} className="rounded-lg bg-slate-50 p-3 text-sm">
          <p className="break-all font-medium">{fonte.nome}</p>
          <a className="text-teal-800 underline" href={original(fonte.arquivo_id)} target="_blank" rel="noopener noreferrer">Baixar original de {fonte.nome}</a>
          <p>{fonte.paciente_nome || "Paciente não identificado"} · {fonte.especie || "Espécie ausente"}{fonte.data_exame ? ` · ${fonte.data_exame}` : ""}</p>
          <p className="mt-1 text-slate-600">Identificação na leitura original: {fonte.motivo || fonte.identidade}</p>
          {fonte.confirmada ? <>
            <p className="mt-1 font-medium text-teal-900">Vínculo confirmado pelo veterinário{fonte.registrado_em ? ` em ${new Date(fonte.registrado_em).toLocaleString("pt-BR")}` : ""}.</p>
            <button type="button" className={`${buttonClass} mt-2`} onClick={() => decidirRevisao("revogar-revisao-identidade", [fonte.arquivo_id])}>Retirar confirmação de identidade de {fonte.nome}</button>
          </> : fonte.elegivel ? <>
            <label className="mt-2 flex items-start gap-2">
              <input type="checkbox" checked={fonteConferida === fonte.arquivo_id} onChange={(event) => {
                setFonteConferida(event.target.checked ? fonte.arquivo_id : null);
                setAvisoRevisao(""); pedidoRevisao.current = null;
              }} className="mt-1" />
              Conferi o original de {fonte.nome}. É o mesmo paciente e qualquer divergência se limita ao nome ou à idade.
            </label>
            <button type="button" className={`${buttonBaseClass} mt-2 bg-teal-700 text-white`} disabled={fonteConferida !== fonte.arquivo_id || !consentimento}
              onClick={() => decidirRevisao("revisar-identidade", [fonte.arquivo_id])}>Confirmar identidade de {fonte.nome}</button>
          </> : <p className="mt-1 text-amber-900">{fonte.impedimento}</p>}
        </li>)}</ul>
      </fieldset> : null}
      {lote.revisao_raca && fontesRevisaoRaca.some((fonte) => fonte.identidade !== "compativel" || fonte.confirmada) ? <fieldset className="space-y-3 rounded-xl border border-amber-200 bg-white p-3" disabled={bloqueado || !habilitado || !lote.revisao_raca.pode_revisar}>
        <legend className="px-1 font-semibold text-amber-950">Revisar a raça depois</legend>
        <p className="text-sm text-slate-700">Raça no cadastro: <strong>{lote.revisao_raca.raca_cadastrada || "Não informada"}</strong>. Se a única divergência for a raça, confira o paciente nos originais e confirme cada documento. Você poderá decidir a raça correta depois, sem alterar o cadastro ou os exames agora.</p>
        <ul className="space-y-3">{fontesRevisaoRaca.map((fonte) => <li key={fonte.arquivo_id} className="rounded-lg bg-slate-50 p-3 text-sm">
          <p className="break-all font-medium">{fonte.nome}</p>
          <p>{fonte.paciente_nome || "Paciente não identificado"} · {fonte.especie || "Espécie ausente"}</p>
          <p className="mt-1 text-slate-600">Identificação na leitura original: {fonte.motivo || fonte.identidade}</p>
          {fonte.confirmada ? <>
            <p className="mt-1 font-medium text-teal-900">Identidade confirmada pelo veterinário. Raça pendente de revisão.</p>
            {fonte.registrado_em ? <p className="text-xs text-slate-600">Decisão registrada em {new Date(fonte.registrado_em).toLocaleString("pt-BR")}</p> : null}
            <button type="button" className={`${buttonClass} mt-2`} onClick={() => decidirRevisao("revogar-revisao-raca", [fonte.arquivo_id])}>Retirar confirmação de {fonte.nome}</button>
          </> : fonte.elegivel ? <label className="mt-2 flex items-start gap-2">
            <input type="checkbox" checked={fontesRaca.includes(fonte.arquivo_id)} onChange={(event) => selecionarRaca(fonte.arquivo_id, event.target.checked)} className="mt-1" />
            Conferi o original de {fonte.nome}
          </label> : <p className="mt-1 text-amber-900">{fonte.impedimento || "Esta identificação precisa ser esclarecida antes da análise."}</p>}
        </li>)}</ul>
        {fontesRevisaoRaca.some((fonte) => fonte.elegivel && !fonte.confirmada) ? <>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmoPaciente} onChange={(event) => { setConfirmoPaciente(event.target.checked); pedidoRevisao.current = null; }} className="mt-1" />Confirmo que os documentos selecionados pertencem ao mesmo paciente deste atendimento.</label>
          <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmoRaca} onChange={(event) => { setConfirmoRaca(event.target.checked); pedidoRevisao.current = null; }} className="mt-1" />Confirmei que a única divergência de identificação é a raça. Vou decidir a raça correta depois.</label>
          <p className="text-xs text-slate-600">A decisão fica registrada e atualiza a análise do conjunto. A revisão anterior será preservada como referência, com inclusão desabilitada até abrir o novo resultado. Documentos não confirmados continuam bloqueados.</p>
          <button type="button" className={`${buttonBaseClass} bg-teal-700 text-white`} disabled={!fontesRaca.length || !confirmoPaciente || !confirmoRaca || !consentimento} onClick={() => decidirRevisao("revisar-raca")}>Confirmar documentos e revisar raça depois</button>
        </> : null}
      </fieldset> : null}
      {avisoRevisao ? <p role="status" className="text-sm text-teal-900">{avisoRevisao}</p> : null}
    </> : null}
    <div className="flex flex-wrap gap-2">
      {!lote || pendingUpload || lote.status === "failed" || substituicaoPendente ? <button type="button" className={`${buttonBaseClass} bg-teal-700 text-white`} disabled={bloqueado || !habilitado || !consentimento || (!lote && !arquivos.length) || (lote?.status === "failed" && Boolean(identidadesPendentes) && lote.arquivos.every((fonte) => fonte.status === "completed"))} onClick={() => enviar()}>{busy ? "Preparando conjunto…" : lote?.status === "failed" ? lote.arquivos.every((fonte) => fonte.status === "completed") ? "Retomar análise do conjunto" : "Retomar arquivos que falharam" : pendingUpload || substituicaoPendente ? "Retomar envio dos arquivos" : "Analisar conjunto"}</button> : null}
      <button type="button" className={buttonClass} disabled={bloqueado} onClick={() => void executar(async (signal) => { await consultar(signal, lote?.id); })}>Consultar progresso</button>
      {lote?.status === "completed" && lote.modo === "transcricao" && lote.transcricao && !substituicaoPendente
        ? <button type="button" className={buttonClass} disabled={bloqueado} onClick={() => onReview(lote)}>Usar transcrição</button> : null}
      {lote?.status === "completed" && lote.resultado ? <button type="button" className={buttonClass} disabled={bloqueado} onClick={() => onReview(lote)}>Abrir revisão do conjunto</button> : null}
      {lote || manifest.current ? <button type="button" className={buttonClass} disabled={bloqueado} onClick={() => setConfirmarNovo(true)}>Preparar novo conjunto</button> : null}
    </div>
    {confirmarNovo ? <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm">
      <p>Encerrar este conjunto e apagar suas cópias temporárias? Guarde o resultado que deseja revisar antes de iniciar outro conjunto.</p>
      <div className="mt-2 flex flex-wrap gap-2"><button type="button" className={buttonClass} disabled={bloqueado} onClick={removerLote}>Encerrar conjunto</button><button type="button" className={buttonClass} disabled={bloqueado} onClick={() => setConfirmarNovo(false)}>Continuar neste conjunto</button></div>
    </div> : null}
    {erro ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{erro}</p> : null}
  </section>;
}
