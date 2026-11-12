"use client";

import { useCallback, useMemo, useState } from "react";

import { SECOES_EXPORT_OPCOES, SECOES_POR_DOMINIO } from "../constants";
import {
  listarClinicasRelatorio,
  listarProfissionaisRelatorio,
  listarServicosRelatorio,
  obterContextoFinanceiro,
  obterRelatorioControle,
  exportarRelatorioControle,
} from "../repositories/relatoriosRepository";
import {
  ClinicaOption,
  DominioRelatorio,
  FiltrosRelatorio,
  FinanceiroContextoResponse,
  PerfilDeslocamento,
  ProfissionalOption,
  RelatorioControleResponse,
  SecaoExport,
  ServicoOption,
} from "../types";
import { dateToIsoLocal } from "../formatters";

type ModoExportacao = "contexto" | "personalizado";

const parseNumber = (value: string): number | undefined => {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

export const useRelatoriosModule = () => {
  const hoje = useMemo(() => new Date(), []);
  const hojeIso = useMemo(() => dateToIsoLocal(hoje), [hoje]);
  const inicioMesIso = useMemo(
    () => dateToIsoLocal(new Date(hoje.getFullYear(), hoje.getMonth(), 1)),
    [hoje]
  );

  const [dominioAtivo, setDominioAtivo] = useState<DominioRelatorio>("visao-geral");

  const [periodoInicio, setPeriodoInicio] = useState(inicioMesIso);
  const [periodoFim, setPeriodoFim] = useState(hojeIso);
  const [dataReferencia, setDataReferencia] = useState(hojeIso);
  const [perfilDeslocamento, setPerfilDeslocamento] = useState<PerfilDeslocamento>("comercial");
  const [clinicaBaseId, setClinicaBaseId] = useState("");
  const [clinicaId, setClinicaId] = useState("");
  const [servicoId, setServicoId] = useState("");
  const [profissionalId, setProfissionalId] = useState("");
  const [regiao, setRegiao] = useState("");

  const [clinicas, setClinicas] = useState<ClinicaOption[]>([]);
  const [servicos, setServicos] = useState<ServicoOption[]>([]);
  const [profissionais, setProfissionais] = useState<ProfissionalOption[]>([]);

  const [relatorio, setRelatorio] = useState<RelatorioControleResponse | null>(null);
  const [financeiroContexto, setFinanceiroContexto] = useState<FinanceiroContextoResponse | null>(
    null
  );

  const [loading, setLoading] = useState(false);
  const [loadingOpcoes, setLoadingOpcoes] = useState(false);
  const [erro, setErro] = useState("");
  const [baixandoCsv, setBaixandoCsv] = useState(false);
  const [baixandoPdf, setBaixandoPdf] = useState(false);
  const [modoExportacao, setModoExportacao] = useState<ModoExportacao>("contexto");
  const [secoesPersonalizadas, setSecoesPersonalizadas] = useState<SecaoExport[]>(
    SECOES_EXPORT_OPCOES.map((item) => item.id)
  );

  const filtrosApi = useMemo<FiltrosRelatorio>(
    () => ({
      data_inicio: periodoInicio,
      data_fim: periodoFim,
      data_referencia: dataReferencia,
      perfil_deslocamento: perfilDeslocamento,
      clinica_base_id: parseNumber(clinicaBaseId),
      clinica_id: parseNumber(clinicaId),
      servico_id: parseNumber(servicoId),
      profissional_id: parseNumber(profissionalId),
      regiao: regiao || undefined,
    }),
    [
      periodoInicio,
      periodoFim,
      dataReferencia,
      perfilDeslocamento,
      clinicaBaseId,
      clinicaId,
      servicoId,
      profissionalId,
      regiao,
    ]
  );

  const regioes = useMemo(() => {
    const opcoes = new Set<string>();
    for (const clinica of clinicas) {
      const campos = [
        clinica.regiao_operacional,
        clinica.bairro,
        clinica.cidade,
        clinica.estado,
      ];
      for (const campo of campos) {
        const valor = String(campo || "").trim();
        if (valor) opcoes.add(valor);
      }
    }
    return Array.from(opcoes).sort((a, b) => a.localeCompare(b));
  }, [clinicas]);

  const secoesContexto = useMemo(() => SECOES_POR_DOMINIO[dominioAtivo], [dominioAtivo]);

  const secoesAtivasExport = useMemo(() => {
    if (modoExportacao === "contexto") return secoesContexto;
    return secoesPersonalizadas;
  }, [modoExportacao, secoesContexto, secoesPersonalizadas]);

  const alternarSecaoPersonalizada = useCallback((secao: SecaoExport) => {
    setSecoesPersonalizadas((atual) => {
      if (atual.includes(secao)) {
        return atual.filter((item) => item !== secao);
      }
      return [...atual, secao];
    });
  }, []);

  const carregarOpcoes = useCallback(async () => {
    try {
      setLoadingOpcoes(true);
      const [clinicasResp, servicosResp, profissionaisResp] = await Promise.all([
        listarClinicasRelatorio(),
        listarServicosRelatorio(),
        listarProfissionaisRelatorio(),
      ]);
      setClinicas(clinicasResp);
      setServicos(servicosResp);
      setProfissionais(profissionaisResp);
    } catch (error) {
      console.error("Erro ao carregar opcoes de relatorio:", error);
    } finally {
      setLoadingOpcoes(false);
    }
  }, []);

  const carregarRelatorios = useCallback(async () => {
    if (!periodoInicio || !periodoFim || !dataReferencia) return;

    try {
      setLoading(true);
      setErro("");
      const [controle, financeiro] = await Promise.all([
        obterRelatorioControle(filtrosApi),
        obterContextoFinanceiro(filtrosApi),
      ]);
      setRelatorio(controle);
      setFinanceiroContexto(financeiro);
    } catch (error: unknown) {
      const detail =
        typeof error === "object" &&
        error &&
        "response" in error &&
        typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ===
          "string"
          ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : "Falha ao carregar relatorios.";
      setErro(detail || "Falha ao carregar relatorios.");
    } finally {
      setLoading(false);
    }
  }, [periodoInicio, periodoFim, dataReferencia, filtrosApi]);

  const inicializar = useCallback(async () => {
    await Promise.all([carregarOpcoes(), carregarRelatorios()]);
  }, [carregarOpcoes, carregarRelatorios]);

  const baixar = useCallback(
    async (formato: "csv" | "pdf") => {
      const secoes = secoesAtivasExport;
      if (secoes.length === 0) {
        setErro("Selecione pelo menos uma secao para exportar.");
        return;
      }

      try {
        setErro("");
        if (formato === "csv") setBaixandoCsv(true);
        if (formato === "pdf") setBaixandoPdf(true);

        const { blob, filename } = await exportarRelatorioControle({
          formato,
          filtros: filtrosApi,
          secoes,
        });

        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } catch (error: unknown) {
        const detail =
          typeof error === "object" &&
          error &&
          "response" in error &&
          typeof (error as { response?: { data?: { detail?: string } } }).response?.data?.detail ===
            "string"
            ? (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : `Falha ao exportar ${formato.toUpperCase()}.`;
        setErro(detail || `Falha ao exportar ${formato.toUpperCase()}.`);
      } finally {
        if (formato === "csv") setBaixandoCsv(false);
        if (formato === "pdf") setBaixandoPdf(false);
      }
    },
    [filtrosApi, secoesAtivasExport]
  );

  return {
    dominioAtivo,
    setDominioAtivo,

    periodoInicio,
    setPeriodoInicio,
    periodoFim,
    setPeriodoFim,
    dataReferencia,
    setDataReferencia,
    perfilDeslocamento,
    setPerfilDeslocamento,
    clinicaBaseId,
    setClinicaBaseId,
    clinicaId,
    setClinicaId,
    servicoId,
    setServicoId,
    profissionalId,
    setProfissionalId,
    regiao,
    setRegiao,

    clinicas,
    servicos,
    profissionais,
    regioes,
    loadingOpcoes,

    relatorio,
    financeiroContexto,
    loading,
    erro,

    modoExportacao,
    setModoExportacao,
    secoesContexto,
    secoesPersonalizadas,
    setSecoesPersonalizadas,
    secoesAtivasExport,
    alternarSecaoPersonalizada,
    baixandoCsv,
    baixandoPdf,

    filtrosApi,
    inicializar,
    carregarRelatorios,
    baixarCsv: () => baixar("csv"),
    baixarPdf: () => baixar("pdf"),
  };
};

