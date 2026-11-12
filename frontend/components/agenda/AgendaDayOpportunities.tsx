"use client";

import { useEffect, useId, useRef, useState } from "react";
import api from "@/lib/axios";

interface ServicoOption {
  id: number;
  nome: string;
  duracao_minutos: number;
  ativo?: boolean;
}

interface OportunidadeDia {
  clinica_id: number;
  clinica: string;
  cidade?: string | null;
  bairro?: string | null;
  dias_realizados_60d: number;
  atendimentos_realizados_60d: number;
  ultimo_atendimento?: string | null;
  inicio: string;
  fim: string;
  tempo_deslocamento_total_min: number;
  transicao_regional: boolean;
  fonte_estimativa?: string;
  estimativa_atualizada_em?: string | null;
}

interface OportunidadesResponse {
  ok: boolean;
  enabled: boolean;
  items: OportunidadeDia[];
  historico?: { inicio: string; fim: string; dias: number };
  sem_estimativa: number;
  total_clinicas_recorrentes: number;
  motivo?: string;
}

interface Props {
  data: string;
  identityKey: string;
}

const formatarData = (valor: string): string => {
  const dia = valor.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(dia) ? dia.split("-").reverse().join("/") : "";
};

const formatarHora = (valor: string): string => valor.match(/[T ](\d{2}:\d{2})/)?.[1] || "";

const mensagemErro = (erro: unknown, fallback: string): string => {
  const candidato = erro as { userMessage?: string; response?: { data?: { detail?: unknown } } };
  if (candidato?.userMessage) return candidato.userMessage;
  const detalhe = candidato?.response?.data?.detail;
  return typeof detalhe === "string" && detalhe.trim() ? detalhe : fallback;
};

export default function AgendaDayOpportunities({ data, identityKey }: Props) {
  const painelId = useId();
  const [aberto, setAberto] = useState(false);
  const [servicos, setServicos] = useState<ServicoOption[]>([]);
  const [catalogoCarregado, setCatalogoCarregado] = useState(false);
  const [carregandoServicos, setCarregandoServicos] = useState(false);
  const [erroServicos, setErroServicos] = useState("");
  const [servicoId, setServicoId] = useState("");
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState("");
  const [resultado, setResultado] = useState<{ contexto: string; dados: OportunidadesResponse } | null>(null);
  const pedidoRef = useRef(0);
  const catalogoRef = useRef(0);
  const consultaControllerRef = useRef<AbortController | null>(null);
  const catalogoControllerRef = useRef<AbortController | null>(null);
  const identidadeRef = useRef(identityKey);
  const contexto = JSON.stringify([identityKey, data, servicoId]);
  const contextoRef = useRef(contexto);
  identidadeRef.current = identityKey;
  contextoRef.current = contexto;

  useEffect(() => {
    pedidoRef.current += 1;
    consultaControllerRef.current?.abort();
    setResultado(null);
    setErro("");
    setCarregando(false);
  }, [data, servicoId, identityKey]);

  useEffect(() => {
    catalogoRef.current += 1;
    catalogoControllerRef.current?.abort();
    setAberto(false);
    setServicos([]);
    setServicoId("");
    setCatalogoCarregado(false);
    setCarregandoServicos(false);
    setErroServicos("");
  }, [identityKey]);

  useEffect(() => () => {
    pedidoRef.current += 1;
    catalogoRef.current += 1;
    consultaControllerRef.current?.abort();
    catalogoControllerRef.current?.abort();
  }, []);

  const carregarServicos = async () => {
    const pedido = ++catalogoRef.current;
    const identidade = identityKey;
    catalogoControllerRef.current?.abort();
    const controller = new AbortController();
    catalogoControllerRef.current = controller;
    setCarregandoServicos(true);
    setErroServicos("");
    try {
      const response = await api.get("/servicos?limit=1000", { signal: controller.signal });
      if (controller.signal.aborted || pedido !== catalogoRef.current || identidade !== identidadeRef.current) return;
      const payload = response.data;
      const items: ServicoOption[] = Array.isArray(payload?.items) ? payload.items : Array.isArray(payload) ? payload : [];
      setServicos(items.filter((item) => Number.isInteger(item.id) && item.id > 0 && item.nome && item.ativo !== false && item.duracao_minutos > 0));
      setCatalogoCarregado(true);
    } catch (error) {
      if (controller.signal.aborted || pedido !== catalogoRef.current || identidade !== identidadeRef.current) return;
      setErroServicos(mensagemErro(error, "Não foi possível carregar os serviços."));
    } finally {
      if (!controller.signal.aborted && pedido === catalogoRef.current && identidade === identidadeRef.current) {
        setCarregandoServicos(false);
      }
    }
  };

  const alternarPainel = () => {
    if (aberto) {
      pedidoRef.current += 1;
      catalogoRef.current += 1;
      consultaControllerRef.current?.abort();
      catalogoControllerRef.current?.abort();
      setCarregando(false);
      setCarregandoServicos(false);
      setResultado(null);
      setErro("");
      setAberto(false);
      return;
    }
    setAberto(true);
    if (!catalogoCarregado) void carregarServicos();
  };

  const consultar = async () => {
    const servico = Number(servicoId);
    if (!Number.isInteger(servico) || servico <= 0 || !data) return;
    const pedido = ++pedidoRef.current;
    const contextoPedido = contexto;
    consultaControllerRef.current?.abort();
    const controller = new AbortController();
    consultaControllerRef.current = controller;
    setCarregando(true);
    setErro("");
    setResultado(null);
    try {
      const response = await api.post<OportunidadesResponse>("/agenda/oportunidades-dia", {
        data,
        servico_id: servico,
        limite: null,
      }, { signal: controller.signal, timeout: 45_000 });
      if (controller.signal.aborted || pedido !== pedidoRef.current || contextoPedido !== contextoRef.current) return;
      if (!response.data?.ok || !Array.isArray(response.data.items)) throw new Error("Resposta de consulta inválida");
      setResultado({ contexto: contextoPedido, dados: response.data });
    } catch (error) {
      if (controller.signal.aborted || pedido !== pedidoRef.current || contextoPedido !== contextoRef.current) return;
      setErro(mensagemErro(error, "Não foi possível consultar as oportunidades deste dia. Tente novamente."));
    } finally {
      if (!controller.signal.aborted && pedido === pedidoRef.current && contextoPedido === contextoRef.current) {
        setCarregando(false);
      }
    }
  };

  const dados = resultado?.contexto === contexto ? resultado.dados : null;

  return (
    <section className="rounded-xl border border-teal-200 bg-white p-3" aria-label="Oportunidades para completar o dia">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-gray-700">Encontre clínicas com atendimentos recentes e horários que cabem na rota do dia.</p>
        <button type="button" onClick={alternarPainel} aria-expanded={aberto} aria-controls={painelId} className="fc-agenda-button-secondary">
          {aberto ? "Fechar oportunidades" : "Completar dia"}
        </button>
      </div>
      {aberto && (
        <div id={painelId} className="mt-3 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-48 flex-1">
              <label htmlFor={`${painelId}-servico`} className="mb-1 block text-xs font-medium text-gray-600">Serviço para {formatarData(data)}</label>
              <select id={`${painelId}-servico`} value={servicoId} onChange={(event) => setServicoId(event.target.value)} disabled={carregandoServicos || !catalogoCarregado} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                <option value="">{carregandoServicos ? "Carregando serviços..." : "Selecione o serviço"}</option>
                {servicos.map((servico) => <option key={servico.id} value={servico.id}>{servico.nome} ({servico.duracao_minutos} min)</option>)}
              </select>
            </div>
            <button type="button" onClick={() => void consultar()} disabled={!servicoId || !data || carregando} className="fc-agenda-button-primary disabled:opacity-50">
              {carregando ? "Consultando oportunidades..." : erro ? "Tentar novamente" : "Consultar oportunidades"}
            </button>
          </div>
          {erroServicos && <p role="alert" className="text-sm text-red-700">{erroServicos} <button type="button" onClick={() => void carregarServicos()} className="font-semibold underline">Tentar carregar serviços novamente</button></p>}
          {catalogoCarregado && !servicos.length && <p className="text-sm text-gray-600">Nenhum serviço ativo com duração disponível.</p>}
          {erro && <p role="alert" className="text-sm text-red-700">{erro}</p>}
          {carregando && <p role="status" className="text-sm text-gray-600">Consultando encaixes para o serviço e a data selecionados.</p>}
          {dados && (
            <div className="space-y-2" aria-live="polite">
              <p className="text-xs text-gray-600">
                {dados.historico ? `Histórico de ${formatarData(dados.historico.inicio)} a ${formatarData(dados.historico.fim)} (${dados.historico.dias} dias). ` : ""}
                {dados.total_clinicas_recorrentes} clínicas com atendimentos realizados no período.
              </p>
              {dados.items.length > 0 && <p className="text-sm font-medium text-teal-800">{dados.items.length} clínicas com horários disponíveis.</p>}
              {!dados.items.length && <p className="text-sm text-gray-700">{dados.motivo || "Nenhuma oportunidade encontrada para este serviço e esta data."}</p>}
              <ol className="space-y-2">
                {dados.items.map((item) => (
                  <li key={`${item.clinica_id}-${item.inicio}`} className="rounded-lg border border-gray-200 px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-start justify-between gap-1">
                      <div><strong className="text-gray-900">{item.clinica}</strong><p className="text-xs text-gray-500">{[item.bairro, item.cidade].filter(Boolean).join(" · ")}</p></div>
                      <strong className="text-teal-800">{formatarHora(item.inicio)}–{formatarHora(item.fim)}</strong>
                    </div>
                    <p className="mt-1 text-xs text-gray-600">{item.dias_realizados_60d} dias com atendimentos · {item.atendimentos_realizados_60d} atendimentos realizados{item.ultimo_atendimento ? ` · último em ${formatarData(item.ultimo_atendimento)}` : ""}.</p>
                    <p className="mt-1 text-xs text-gray-600">Deslocamento entre atendimentos: {item.tempo_deslocamento_total_min} min estimados{item.estimativa_atualizada_em ? ` · estimativa de ${formatarData(item.estimativa_atualizada_em)}` : ""}.</p>
                    {item.transicao_regional && <p className="mt-1 text-xs font-medium text-amber-800">Usa a transição regional do dia: viagem de até 50 min e margem total de pelo menos 15 min.</p>}
                  </li>
                ))}
              </ol>
              {dados.sem_estimativa > 0 && <p className="text-xs text-amber-800">{dados.sem_estimativa} clínicas ficaram sem avaliação por falta de estimativa de viagem.</p>}
              <p className="text-xs text-gray-600">Consulte a disponibilidade da clínica antes de agendar. Os horários são sugestões, sem reserva.</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
