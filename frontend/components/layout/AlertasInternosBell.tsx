"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Loader2, X } from "lucide-react";
import api from "@/lib/axios";

const POLL_INTERVAL_MS = 45_000;

interface AlertaInternoItem {
  id: number;
  tipo: string;
  nivel: "info" | "aviso" | "critico";
  titulo: string;
  mensagem: string;
  clinica_id: number | null;
  criado_em: string;
  lido: boolean;
}

interface AlertaInternoListResponse {
  total_nao_lidos: number;
  items: AlertaInternoItem[];
}

interface AlertasInternosBellProps {
  containerClassName?: string;
}

function nivelClasses(nivel: string): string {
  switch (nivel) {
    case "critico":
      return "border-red-200 bg-red-50 text-red-900";
    case "aviso":
      return "border-amber-200 bg-amber-50 text-amber-900";
    default:
      return "border-slate-200 bg-slate-50 text-slate-900";
  }
}

function formatarDataHora(valor: string): string {
  try {
    return new Date(valor).toLocaleString("pt-BR");
  } catch {
    return valor;
  }
}

export default function AlertasInternosBell({
  containerClassName = "fixed right-3 top-3 z-[70]",
}: AlertasInternosBellProps) {
  const [aberto, setAberto] = useState(false);
  const [carregandoTodos, setCarregandoTodos] = useState(false);
  const [alertas, setAlertas] = useState<AlertaInternoItem[]>([]);
  const [totalNaoLidos, setTotalNaoLidos] = useState(0);
  const [marcandoId, setMarcandoId] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const carregarAlertas = useCallback(async () => {
    try {
      const response = await api.get<AlertaInternoListResponse>("/alertas-internos");
      setAlertas(response.data.items);
      setTotalNaoLidos(response.data.total_nao_lidos);
    } catch {
      // Silencioso: uma falha ao buscar alertas nao deve interromper a navegacao.
      // A proxima rodada de polling tenta de novo.
    }
  }, []);

  useEffect(() => {
    void carregarAlertas();
    const intervalo = setInterval(() => void carregarAlertas(), POLL_INTERVAL_MS);
    return () => clearInterval(intervalo);
  }, [carregarAlertas]);

  useEffect(() => {
    if (!aberto) {
      return;
    }
    function handleClickFora(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setAberto(false);
      }
    }
    document.addEventListener("mousedown", handleClickFora);
    return () => document.removeEventListener("mousedown", handleClickFora);
  }, [aberto]);

  async function marcarComoLido(alertaId: number) {
    setMarcandoId(alertaId);
    try {
      await api.patch(`/alertas-internos/${alertaId}/marcar-lido`);
      setAlertas((atuais) => atuais.filter((alerta) => alerta.id !== alertaId));
      setTotalNaoLidos((atual) => Math.max(0, atual - 1));
    } catch {
      // Silencioso: o item continua na lista para nova tentativa.
    } finally {
      setMarcandoId(null);
    }
  }

  async function marcarTodosComoLidos() {
    setCarregandoTodos(true);
    try {
      await api.post("/alertas-internos/marcar-todos-lidos");
      setAlertas([]);
      setTotalNaoLidos(0);
    } catch {
      // Silencioso; os itens continuam visiveis para nova tentativa.
    } finally {
      setCarregandoTodos(false);
    }
  }

  return (
    <div ref={containerRef} className={containerClassName}>
      <button
        type="button"
        onClick={() => setAberto((atual) => !atual)}
        aria-label={`Alertas internos${totalNaoLidos > 0 ? ` (${totalNaoLidos} nao lidos)` : ""}`}
        className="relative flex h-10 w-10 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-700 shadow-md transition hover:bg-slate-50"
      >
        <Bell className="h-5 w-5" />
        {totalNaoLidos > 0 ? (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[11px] font-bold text-white">
            {totalNaoLidos > 99 ? "99+" : totalNaoLidos}
          </span>
        ) : null}
      </button>

      {aberto ? (
        <div className="absolute right-0 mt-2 w-80 max-w-[90vw] rounded-lg border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
            <p className="text-sm font-bold text-slate-950">Alertas</p>
            <div className="flex items-center gap-3">
              {alertas.length > 0 ? (
                <button
                  type="button"
                  onClick={() => void marcarTodosComoLidos()}
                  disabled={carregandoTodos}
                  className="text-xs font-semibold text-teal-700 hover:underline disabled:opacity-50"
                >
                  Marcar tudo como lido
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => setAberto(false)}
                aria-label="Fechar"
                className="text-slate-400 hover:text-slate-700"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <div className="max-h-96 overflow-y-auto p-2">
            {alertas.length === 0 ? (
              <p className="p-3 text-sm text-slate-500">Nenhum alerta pendente.</p>
            ) : (
              <div className="space-y-2">
                {alertas.map((alerta) => (
                  <div key={alerta.id} className={`rounded-lg border p-3 text-sm ${nivelClasses(alerta.nivel)}`}>
                    <p className="font-bold">{alerta.titulo}</p>
                    <p className="mt-1 text-xs leading-5">{alerta.mensagem}</p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-[11px] opacity-70">{formatarDataHora(alerta.criado_em)}</span>
                      <button
                        type="button"
                        onClick={() => void marcarComoLido(alerta.id)}
                        disabled={marcandoId === alerta.id}
                        className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold underline disabled:opacity-50"
                      >
                        {marcandoId === alerta.id ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
                        Marcar como lido
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
