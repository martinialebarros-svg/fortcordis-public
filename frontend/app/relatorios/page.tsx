"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { BarChart3 } from "lucide-react";

import DashboardLayout from "../layout-dashboard";
import { DOMINIOS_RELATORIO } from "./constants";
import RelatoriosExportPanel from "./components/RelatoriosExportPanel";
import RelatoriosFiltrosGlobais from "./components/RelatoriosFiltrosGlobais";
import RelatoriosFinanceiroView from "./components/views/RelatoriosFinanceiroView";
import RelatoriosLogisticaView from "./components/views/RelatoriosLogisticaView";
import RelatoriosOperacaoView from "./components/views/RelatoriosOperacaoView";
import RelatoriosRentabilidadeView from "./components/views/RelatoriosRentabilidadeView";
import RelatoriosVisaoGeralView from "./components/views/RelatoriosVisaoGeralView";
import { useRelatoriosModule } from "./hooks/useRelatoriosModule";

export default function RelatoriosControlePage() {
  const router = useRouter();
  const {
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
    relatorio,
    financeiroContexto,
    loading,
    erro,
    modoExportacao,
    setModoExportacao,
    secoesContexto,
    secoesPersonalizadas,
    setSecoesPersonalizadas,
    alternarSecaoPersonalizada,
    baixandoCsv,
    baixandoPdf,
    inicializar,
    carregarRelatorios,
    baixarCsv,
    baixarPdf,
  } = useRelatoriosModule();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    void inicializar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const renderDominio = () => {
    if (!relatorio) return null;

    if (dominioAtivo === "visao-geral") {
      return <RelatoriosVisaoGeralView relatorio={relatorio} financeiroContexto={financeiroContexto} />;
    }

    if (dominioAtivo === "operacao") {
      return <RelatoriosOperacaoView relatorio={relatorio} />;
    }

    if (dominioAtivo === "logistica") {
      return <RelatoriosLogisticaView relatorio={relatorio} clinicas={clinicas} />;
    }

    if (dominioAtivo === "financeiro") {
      return <RelatoriosFinanceiroView relatorio={relatorio} financeiroContexto={financeiroContexto} />;
    }

    return <RelatoriosRentabilidadeView relatorio={relatorio} />;
  };

  return (
    <DashboardLayout>
      <div className="fc-reports-page">
        <header className="fc-reports-header">
          <div>
            <span className="fc-reports-kicker"><BarChart3 className="h-4 w-4" />Inteligência operacional</span>
            <h1>Relatórios &amp; Controle</h1>
            <p>Indicadores executivos, operação, logística, financeiro e rentabilidade.</p>
          </div>
          <span className="fc-reports-context">{DOMINIOS_RELATORIO.find((item) => item.id === dominioAtivo)?.label}</span>
        </header>

        <nav className="fc-reports-domains" role="tablist" aria-label="Domínios dos relatórios">
            {DOMINIOS_RELATORIO.map((dominio) => {
              const ativo = dominioAtivo === dominio.id;
              return (
                <button
                  key={dominio.id}
                  type="button"
                  onClick={() => setDominioAtivo(dominio.id)}
                  role="tab"
                  aria-selected={ativo}
                  className={`fc-reports-domain ${ativo ? "fc-reports-domain-active" : ""}`}
                >
                  {dominio.label}
                </button>
              );
            })}
        </nav>

        <RelatoriosFiltrosGlobais
          periodoInicio={periodoInicio}
          setPeriodoInicio={setPeriodoInicio}
          periodoFim={periodoFim}
          setPeriodoFim={setPeriodoFim}
          dataReferencia={dataReferencia}
          setDataReferencia={setDataReferencia}
          perfilDeslocamento={perfilDeslocamento}
          setPerfilDeslocamento={setPerfilDeslocamento}
          clinicaBaseId={clinicaBaseId}
          setClinicaBaseId={setClinicaBaseId}
          clinicaId={clinicaId}
          setClinicaId={setClinicaId}
          servicoId={servicoId}
          setServicoId={setServicoId}
          profissionalId={profissionalId}
          setProfissionalId={setProfissionalId}
          regiao={regiao}
          setRegiao={setRegiao}
          clinicas={clinicas}
          servicos={servicos}
          profissionais={profissionais}
          regioes={regioes}
          loading={loading}
          onAtualizar={carregarRelatorios}
        />

        <RelatoriosExportPanel
          dominioAtivo={dominioAtivo}
          modoExportacao={modoExportacao}
          setModoExportacao={setModoExportacao}
          secoesContexto={secoesContexto}
          secoesPersonalizadas={secoesPersonalizadas}
          alternarSecaoPersonalizada={alternarSecaoPersonalizada}
          setSecoesPersonalizadas={setSecoesPersonalizadas}
          baixandoCsv={baixandoCsv}
          baixandoPdf={baixandoPdf}
          onExportCsv={baixarCsv}
          onExportPdf={baixarPdf}
        />

        {relatorio ? (
          <p className="fc-reports-base-note">
            Base operacional: {relatorio.base_operacional.clinica_nome || "Não definida"} (
            {relatorio.base_operacional.criterio})
          </p>
        ) : null}

        {erro ? (
          <div className="fc-reports-error">
            {erro}
          </div>
        ) : null}

        {loading && !relatorio ? (
          <div className="fc-reports-loading"><span />Carregando relatórios...</div>
        ) : null}

        {relatorio ? <div className="fc-reports-content">{renderDominio()}</div> : null}
      </div>
    </DashboardLayout>
  );
}
