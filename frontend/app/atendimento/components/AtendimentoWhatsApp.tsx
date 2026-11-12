"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Download, FileText, MessageCircle, Share2 } from "lucide-react";

import {
  buildAtendimentoWhatsAppUrl,
  canShareAtendimentoPdf,
  downloadAtendimentoPdf,
  formatAtendimentoWhatsAppPhone,
  normalizeAtendimentoWhatsAppPhone,
  type AtendimentoWhatsAppDocumentKind,
} from "@/lib/atendimento-whatsapp";

export type AtendimentoWhatsAppProps = {
  atendimentoId: number | null;
  phone: string;
  tutorName: string;
  patientName: string;
  /** Changes when the selected prescription or editable document content changes. */
  documentRevision?: string;
  hasPrescription?: boolean;
  hasExamRequest?: boolean;
  onPrepareDocument: (kind: AtendimentoWhatsAppDocumentKind) => Promise<File | null>;
  onEditPhone?: () => void;
};

export default function AtendimentoWhatsApp({
  atendimentoId,
  phone,
  tutorName,
  patientName,
  documentRevision = "",
  hasPrescription = true,
  hasExamRequest = true,
  onPrepareDocument,
  onEditPhone,
}: AtendimentoWhatsAppProps) {
  const [kind, setKind] = useState<AtendimentoWhatsAppDocumentKind>("prescricao");
  const [confirmedRecipient, setConfirmedRecipient] = useState<string | null>(null);
  const [prepared, setPrepared] = useState<{ file: File; key: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [message, setMessage] = useState("");
  const normalizedPhone = normalizeAtendimentoWhatsAppPhone(phone);
  const conversationUrl = buildAtendimentoWhatsAppUrl(phone);
  const recipientKey = JSON.stringify([atendimentoId, normalizedPhone, tutorName, patientName]);
  const confirmed = confirmedRecipient === recipientKey;
  const contextKey = JSON.stringify([recipientKey, kind, documentRevision]);
  const contextRef = useRef(contextKey);
  contextRef.current = contextKey;
  const mountedRef = useRef(true);
  const requestRef = useRef(0);
  const file = prepared?.key === contextKey ? prepared.file : null;
  const hasDocument = kind === "prescricao" ? hasPrescription : hasExamRequest;
  const canProceed = Boolean(atendimentoId && normalizedPhone && confirmed);
  const nativeShareAvailable = file ? canShareAtendimentoPdf(file) : false;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setConfirmedRecipient(null);
  }, [recipientKey]);

  useEffect(() => {
    requestRef.current += 1;
    setPrepared(null);
    setBusy(false);
    setSharing(false);
    setMessage("");
  }, [contextKey]);

  async function prepareDocument() {
    if (!canProceed || !hasDocument || busy) return;
    const request = ++requestRef.current;
    const requestedContext = contextKey;
    const stillCurrent = () => mountedRef.current && requestRef.current === request
      && contextRef.current === requestedContext;
    setBusy(true);
    setPrepared(null);
    setMessage("");
    try {
      const result = await onPrepareDocument(kind);
      if (!stillCurrent()) return;
      if (!result || result.size === 0 || result.type !== "application/pdf") {
        setMessage("O PDF não foi preparado. Revise os dados e os avisos do atendimento e tente novamente.");
        return;
      }
      setPrepared({ file: result, key: requestedContext });
      setMessage("PDF preparado. Confira o documento antes de compartilhar.");
    } catch {
      if (stillCurrent()) setMessage("Não foi possível preparar o PDF. Revise os avisos do atendimento e tente novamente.");
    } finally {
      if (stillCurrent()) setBusy(false);
    }
  }

  async function shareDocument() {
    if (!file || !canProceed || sharing || !nativeShareAvailable) return;
    const requestedContext = contextKey;
    setSharing(true);
    setMessage("");
    try {
      // File sharing cannot preselect a WhatsApp recipient. The UI makes that explicit.
      await navigator.share({ files: [file], title: "Documento Fort Cordis" });
      if (mountedRef.current && contextRef.current === requestedContext) {
        setMessage("Compartilhamento concluído no dispositivo. Confira o envio e o destinatário no WhatsApp.");
      }
    } catch (error) {
      if (mountedRef.current && contextRef.current === requestedContext) {
        setMessage(typeof error === "object" && error !== null && "name" in error && error.name === "AbortError"
          ? "Compartilhamento cancelado. O PDF continua disponível."
          : "Não foi possível compartilhar neste dispositivo. Baixe o PDF e anexe-o na conversa.");
      }
    } finally {
      if (mountedRef.current && contextRef.current === requestedContext) setSharing(false);
    }
  }

  function downloadDocument() {
    if (!file || !canProceed) return;
    downloadAtendimentoPdf(file);
    setMessage("Download solicitado. Abra a conversa e anexe o PDF baixado antes de enviar.");
  }

  return (
    <details className="group rounded-[26px] border border-emerald-200 bg-white p-5 shadow-sm" aria-labelledby="atendimento-whatsapp-title">
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <div className="rounded-2xl bg-emerald-50 p-3"><MessageCircle className="h-5 w-5 text-emerald-700" /></div>
        <div>
          <h3 id="atendimento-whatsapp-title" className="text-lg font-semibold text-slate-900">WhatsApp do tutor</h3>
          <p className="text-sm text-slate-600">Receitas e solicitações de exames</p>
        </div>
        <ChevronDown className="ml-auto h-5 w-5 shrink-0 text-emerald-700 transition-transform group-open:rotate-180" />
      </summary>

      {!atendimentoId ? <p className="mt-4 text-sm text-amber-800">Salve o atendimento para preparar os documentos.</p> : null}
      {!normalizedPhone ? (
        <div className="mt-4 rounded-2xl bg-amber-50 p-4 text-sm text-amber-900">
          <p>Cadastre um WhatsApp brasileiro válido com DDD para o tutor.</p>
          {onEditPhone ? <button type="button" onClick={onEditPhone} className="mt-2 font-semibold underline">Editar cadastro do tutor</button> : null}
        </div>
      ) : (
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm">
          <p className="font-semibold text-slate-900">{tutorName || "Tutor sem nome"} · {formatAtendimentoWhatsAppPhone(normalizedPhone)}</p>
          <p className="mt-1 text-slate-600">Paciente: {patientName || "Não informado"}</p>
          <label className="mt-3 flex items-start gap-2 text-slate-700">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmedRecipient(event.target.checked ? recipientKey : null)} className="mt-1" />
            Conferi o número e o tutor autorizou receber os documentos neste WhatsApp.
          </label>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex min-w-56 flex-col gap-1 text-sm font-medium text-slate-700">
          Documento
          <select value={kind} onChange={(event) => setKind(event.target.value as AtendimentoWhatsAppDocumentKind)} disabled={busy || sharing}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2">
            <option value="prescricao">Receita ativa no atendimento</option>
            <option value="exames">Solicitação de exames</option>
          </select>
        </label>
        <button type="button" onClick={() => void prepareDocument()} disabled={!canProceed || !hasDocument || busy || sharing}
          className="inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
          <FileText className="h-4 w-4" />{busy ? "Preparando PDF…" : "Preparar PDF"}
        </button>
        {canProceed && conversationUrl ? (
          <a href={conversationUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-xl border border-emerald-700 px-4 py-2 text-sm font-semibold text-emerald-800">
            <MessageCircle className="h-4 w-4" />Abrir conversa no WhatsApp
          </a>
        ) : null}
      </div>
      {!hasDocument ? <p className="mt-2 text-sm text-amber-800">Inclua {kind === "prescricao" ? "uma receita" : "ao menos um exame"} no atendimento antes de preparar o PDF.</p> : null}

      {file ? (
        <div className="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="break-all text-sm font-semibold text-emerald-950">{file.name}</p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button type="button" onClick={downloadDocument} disabled={!canProceed || sharing} className="inline-flex items-center gap-2 rounded-xl border border-emerald-700 bg-white px-4 py-2 text-sm font-semibold text-emerald-800 disabled:opacity-50">
              <Download className="h-4 w-4" />Baixar PDF para conferir e anexar
            </button>
            {nativeShareAvailable ? (
              <button type="button" onClick={() => void shareDocument()} disabled={!canProceed || sharing} className="inline-flex items-center gap-2 rounded-xl bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                <Share2 className="h-4 w-4" />{sharing ? "Compartilhando…" : "Compartilhar PDF"}
              </button>
            ) : null}
          </div>
          <p className="mt-3 text-sm text-emerald-900">{nativeShareAvailable
            ? "Ao compartilhar, escolha o WhatsApp e selecione o tutor acima. Confira o destinatário antes de enviar."
            : "Baixe o PDF, abra a conversa e anexe o arquivo no WhatsApp."}</p>
        </div>
      ) : null}
      <p className="mt-4 text-xs leading-5 text-slate-500">Abrir a conversa não envia a mensagem nem anexa o documento. O envio é concluído por você no WhatsApp.</p>
      {message ? <p role="status" className="mt-3 text-sm text-slate-700">{message}</p> : null}
    </details>
  );
}
