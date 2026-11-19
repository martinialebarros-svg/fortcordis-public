"use client";

import { useState } from "react";
import { Loader2, PauseCircle, PlayCircle } from "lucide-react";
import api from "@/lib/axios";

interface PortalDownloadControlProps {
  laudo: {
    id: number;
    status: string;
    portal_clinica_liberado?: boolean;
    portal_veterinario_liberado?: boolean;
    portal_download_suspenso?: boolean;
  };
  onChange: (suspenso: boolean) => void;
}

export default function PortalDownloadControl({ laudo, onChange }: PortalDownloadControlProps) {
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const suspenso = Boolean(laudo.portal_download_suspenso);
  const liberado = laudo.status === "Liberado no portal" || laudo.portal_clinica_liberado || laudo.portal_veterinario_liberado;
  if (!suspenso && !liberado) return null;

  async function alterarSuspensao() {
    const mensagem = suspenso
      ? "A clínica e os veterinários parceiros voltarão a baixar o PDF salvo. Confirme após conferir a versão final."
      : "A clínica e os veterinários parceiros ficarão sem acesso ao PDF pelo portal, inclusive por links já enviados. Cópias já baixadas continuam com os destinatários.";
    if (!window.confirm(mensagem)) return;

    setSalvando(true);
    setErro("");
    try {
      const { data } = await api.put<{ portal_download_suspenso: boolean }>(
        `/laudos/${laudo.id}/portal/download-suspenso`,
        { suspenso: !suspenso },
      );
      onChange(data.portal_download_suspenso);
    } catch {
      setErro("Não foi possível confirmar a alteração. Atualize a página para conferir o status do download.");
    } finally {
      setSalvando(false);
    }
  }

  const Icone = salvando ? Loader2 : suspenso ? PlayCircle : PauseCircle;

  return (
    <section
      aria-label="Download por parceiros"
      className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 print:hidden"
    >
      <div>
        <p className={`text-sm font-semibold ${suspenso ? "text-amber-800" : "text-slate-900"}`} role="status">
          {suspenso ? "Download suspenso para parceiros" : "Download por parceiros"}
        </p>
        <p className="mt-1 text-sm text-slate-600">
          {suspenso ? "Retome o download após salvar e conferir a versão final." : "Suspenda o download enquanto corrige o laudo."}
        </p>
        {erro && <p className="mt-1 text-sm text-rose-700" role="alert">{erro}</p>}
      </div>
      <button
        type="button"
        onClick={() => void alterarSuspensao()}
        disabled={salvando}
        className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900 transition hover:bg-amber-100 disabled:opacity-60"
      >
        <Icone className={`h-4 w-4 ${salvando ? "animate-spin" : ""}`} aria-hidden />
        {salvando ? "Salvando..." : suspenso ? "Retomar download" : "Suspender download"}
      </button>
    </section>
  );
}
