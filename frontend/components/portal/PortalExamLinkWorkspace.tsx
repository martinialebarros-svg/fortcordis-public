"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Download, FileText, Loader2, MonitorCheck, PawPrint, ShieldCheck } from "lucide-react";

import {
  downloadPortalAttachment,
  PortalRequestError,
  resolvePortalExamLink,
  resumePortalDeviceSession,
  savePortalSession,
  trustPortalDevice,
  type PortalDownloadItem,
  type PortalExamLinkResponse,
} from "@/lib/portal-api";
import { formatPortalDate } from "@/lib/portal-datetime";

type PortalExamLinkWorkspaceProps = {
  linkToken: string;
};

/**
 * Tela de um laudo so, aberta pelo link que a clinica recebe no WhatsApp.
 *
 * Quem usa e a secretaria, quase sempre no celular, no meio do atendimento: a
 * tela tem uma acao principal (baixar o laudo) e nenhuma exigencia de login.
 * Ver docs/specs/portal-clinica-link-laudo-whatsapp/.
 */
export default function PortalExamLinkWorkspace({ linkToken }: PortalExamLinkWorkspaceProps) {
  const [exame, setExame] = useState<PortalExamLinkResponse | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");
  const [baixando, setBaixando] = useState<number | null>(null);
  const [erroDownload, setErroDownload] = useState("");
  const [conectando, setConectando] = useState(false);
  const [conectado, setConectado] = useState(false);
  const [erroConexao, setErroConexao] = useState("");

  useEffect(() => {
    let ativo = true;

    async function carregar() {
      setCarregando(true);
      setErro("");
      try {
        const resposta = await resolvePortalExamLink(linkToken);
        if (ativo) {
          setExame(resposta);
        }
      } catch {
        // Mensagem unica de proposito: o backend nao distingue link inexistente,
        // revogado ou laudo fora do ar, e a tela nao pode inventar essa distincao.
        if (ativo) {
          setErro("Este link não está mais disponível.");
        }
      } finally {
        if (ativo) {
          setCarregando(false);
        }
      }
    }

    carregar();
    return () => {
      ativo = false;
    };
  }, [linkToken]);

  const baixar = useCallback(async (item: PortalDownloadItem) => {
    setBaixando(item.anexo_id);
    setErroDownload("");
    try {
      await downloadPortalAttachment(item);
    } catch {
      setErroDownload("Não foi possível baixar o arquivo. Tente abrir o link de novo.");
    } finally {
      setBaixando(null);
    }
  }, []);

  const conectarComputador = useCallback(async () => {
    setConectando(true);
    setErroConexao("");

    // Falha em qualquer etapa não pode atrapalhar o que a pessoa veio fazer: o
    // laudo segue na tela e o download continua funcionando (CB-002).
    try {
      await trustPortalDevice(linkToken);
    } catch {
      setErroConexao("Não foi possível conectar este computador. O laudo acima continua disponível.");
      setConectando(false);
      return;
    }

    // O 200 acima diz que o servidor criou a confiança — não que ESTE navegador
    // guardou o cookie dela. Num navegador que bloqueia cookies o pedido passa e
    // o `Set-Cookie` é descartado em silêncio: sem esta confirmação a tela diria
    // "Pronto" para uma recepção que amanhã encontra o portal pedindo senha, e a
    // suspeita cairia no link. Confirmado em stage em 20/09/2026.
    try {
      const sessao = await resumePortalDeviceSession();
      savePortalSession(sessao);
      setConectado(true);
    } catch (erro) {
      setErroConexao(
        erro instanceof PortalRequestError
          ? "Este navegador não guardou o acesso, então o computador não ficou conectado. " +
            "Se estiver em uma janela anônima ou com cookies bloqueados, tente de novo em uma " +
            "janela normal. O laudo acima continua disponível."
          : "Não foi possível confirmar a conexão deste computador. O laudo acima continua disponível.",
      );
    } finally {
      setConectando(false);
    }
  }, [linkToken]);

  if (carregando) {
    return (
      <div
        className="flex items-center justify-center gap-3 rounded-lg border border-white/80 bg-white/95 p-8 text-slate-600 shadow-2xl"
        role="status"
      >
        <Loader2 className="h-5 w-5 animate-spin" />
        <span className="text-sm">Abrindo o laudo...</span>
      </div>
    );
  }

  if (erro || !exame) {
    return (
      <div className="rounded-lg border border-white/80 bg-white/95 p-6 shadow-2xl sm:p-8">
        <h2 className="text-xl font-bold text-slate-950">{erro || "Este link não está mais disponível."}</h2>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          O laudo pode ter sido substituído ou o acesso encerrado. Procure a mensagem mais recente da Fort
          Cordis no WhatsApp da unidade ou fale com a nossa equipe.
        </p>
        <Link
          href="/clinica-parceira"
          className="mt-5 inline-flex text-sm font-semibold text-teal-700 underline underline-offset-4"
        >
          Acessar o portal completo da clínica
        </Link>
      </div>
    );
  }

  // formatPortalDate devolve "-" quando nao ha data; a linha inteira sai fora
  // nesse caso, em vez de mostrar um campo vazio.
  const dataExame = exame.data_exame ? formatPortalDate(exame.data_exame) : "";

  return (
    <div className="rounded-lg border border-white/80 bg-white/95 p-6 shadow-2xl sm:p-8">
      <p className="text-xs font-semibold uppercase tracking-wide text-teal-700">{exame.clinica_nome}</p>

      <h2 className="mt-2 flex items-center gap-2 text-2xl font-bold text-slate-950">
        <PawPrint className="h-6 w-6 shrink-0 text-teal-700" aria-hidden />
        {exame.paciente_nome || "Paciente"}
      </h2>

      <dl className="mt-4 space-y-1 text-sm text-slate-600">
        <div className="flex gap-2">
          <dt className="font-semibold text-slate-700">Exame:</dt>
          <dd>{exame.tipo_exame}</dd>
        </div>
        {dataExame ? (
          <div className="flex gap-2">
            <dt className="font-semibold text-slate-700">Data:</dt>
            <dd>{dataExame}</dd>
          </div>
        ) : null}
      </dl>

      {exame.arquivos.length === 0 ? (
        <p className="mt-6 rounded-md bg-amber-50 p-4 text-sm leading-6 text-amber-900">
          O laudo já foi liberado, mas o arquivo ainda não está disponível para download. Tente de novo em
          alguns minutos.
        </p>
      ) : (
        <div className="mt-6 space-y-3">
          {exame.arquivos.map((item) => (
            <button
              key={item.anexo_id}
              type="button"
              onClick={() => baixar(item)}
              disabled={baixando !== null}
              className="flex w-full items-center justify-between gap-3 rounded-md bg-teal-700 px-5 py-4 text-left text-white shadow-sm transition hover:bg-teal-800 disabled:opacity-60"
            >
              <span className="flex min-w-0 items-center gap-3">
                <FileText className="h-5 w-5 shrink-0" aria-hidden />
                <span className="truncate text-sm font-semibold">{item.nome_original}</span>
              </span>
              {baixando === item.anexo_id ? (
                <Loader2 className="h-5 w-5 shrink-0 animate-spin" aria-hidden />
              ) : (
                <Download className="h-5 w-5 shrink-0" aria-hidden />
              )}
            </button>
          ))}
        </div>
      )}

      {erroDownload ? (
        <p className="mt-4 text-sm font-medium text-rose-700" role="alert">
          {erroDownload}
        </p>
      ) : null}

      {exame.dispositivo_confiavel_disponivel ? (
        <div className="mt-6 rounded-md border border-teal-200 bg-teal-50/60 p-4">
          {conectado ? (
            <p className="flex items-start gap-2 text-sm leading-6 text-teal-900">
              <MonitorCheck className="h-5 w-5 shrink-0" aria-hidden />
              <span>
                Pronto. Este computador agora abre os laudos da unidade direto, sem senha.
                <Link
                  href="/clinica-parceira"
                  className="ml-1 font-semibold underline underline-offset-4"
                >
                  Ver todos os laudos
                </Link>
              </span>
            </p>
          ) : (
            <>
              <p className="text-sm font-semibold text-teal-900">É este o computador da recepção?</p>
              <p className="mt-1 text-sm leading-6 text-teal-900/80">
                Deixe conectado e a equipe passa a abrir os laudos da unidade sem senha — incluindo
                os antigos. Financeiro e agenda continuam exigindo login.
              </p>
              <button
                type="button"
                onClick={conectarComputador}
                disabled={conectando}
                className="mt-3 inline-flex items-center gap-2 rounded-md border border-teal-700 px-4 py-2 text-sm font-semibold text-teal-800 transition hover:bg-teal-700 hover:text-white disabled:opacity-60"
              >
                {conectando ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <MonitorCheck className="h-4 w-4" aria-hidden />
                )}
                Manter esta unidade conectada neste computador
              </button>
            </>
          )}
          {erroConexao ? (
            <p className="mt-3 text-sm font-medium text-rose-700" role="alert">
              {erroConexao}
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="mt-6 flex items-start gap-2 text-xs leading-5 text-slate-500">
        <ShieldCheck className="h-4 w-4 shrink-0 text-teal-700" aria-hidden />
        Este link abre apenas este laudo e é de uso exclusivo da unidade. Não encaminhe para terceiros.
      </p>

      <Link
        href="/clinica-parceira"
        className="mt-4 inline-flex text-xs font-semibold text-teal-700 underline underline-offset-4"
      >
        Acessar o portal completo da clínica
      </Link>
    </div>
  );
}
