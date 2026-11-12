"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { Save, ArrowLeft, Wrench, Trash2, AlertTriangle, MapPin, Clock, DollarSign, Sun, Moon } from "lucide-react";

interface Precos {
  fortaleza_comercial: string;
  fortaleza_plantao: string;
  rm_comercial: string;
  rm_plantao: string;
  domiciliar_comercial: string;
  domiciliar_plantao: string;
}

export default function EditarServicoPage() {
  const router = useRouter();
  const params = useParams();
  const servicoId = params.id as string;
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [servico, setServico] = useState({
    nome: "",
    descricao: "",
    duracao_minutos: "30",
  });
  
  const [precos, setPrecos] = useState<Precos>({
    fortaleza_comercial: "",
    fortaleza_plantao: "",
    rm_comercial: "",
    rm_plantao: "",
    domiciliar_comercial: "",
    domiciliar_plantao: "",
  });

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarServico();
  }, [router, servicoId]);

  const carregarServico = async () => {
    try {
      const response = await api.get(`/servicos/${servicoId}`);
      const data = response.data;
      
      setServico({
        nome: data.nome || "",
        descricao: data.descricao || "",
        duracao_minutos: data.duracao_minutos?.toString() || "30",
      });
      
      const p = data.precos || {};
      setPrecos({
        fortaleza_comercial: p.fortaleza_comercial?.toString() || "",
        fortaleza_plantao: p.fortaleza_plantao?.toString() || "",
        rm_comercial: p.rm_comercial?.toString() || "",
        rm_plantao: p.rm_plantao?.toString() || "",
        domiciliar_comercial: p.domiciliar_comercial?.toString() || "",
        domiciliar_plantao: p.domiciliar_plantao?.toString() || "",
      });
    } catch (error) {
      console.error("Erro ao carregar servico:", error);
      alert(extractApiErrorMessageSync(error, "Erro ao carregar dados do serviço."));
      router.push("/servicos");
    } finally {
      setLoading(false);
    }
  };

  const handlePrecoChange = (campo: keyof Precos, valor: string) => {
    const valorLimpo = valor.replace(/[^\d.,]/g, '');
    setPrecos({ ...precos, [campo]: valorLimpo });
  };

  const formatarValor = (valor: string) => {
    if (!valor) return "0,00";
    const num = parseFloat(valor.replace(',', '.'));
    if (isNaN(num)) return "0,00";
    return num.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const handleSalvar = async () => {
    if (!servico.nome.trim()) {
      alert("Digite o nome do serviço");
      return;
    }

    setSaving(true);
    try {
      const payload = {
        nome: servico.nome,
        descricao: servico.descricao,
        duracao_minutos: servico.duracao_minutos ? parseInt(servico.duracao_minutos) : 30,
        precos: {
          fortaleza_comercial: precos.fortaleza_comercial ? parseFloat(precos.fortaleza_comercial.replace(',', '.')) : 0,
          fortaleza_plantao: precos.fortaleza_plantao ? parseFloat(precos.fortaleza_plantao.replace(',', '.')) : 0,
          rm_comercial: precos.rm_comercial ? parseFloat(precos.rm_comercial.replace(',', '.')) : 0,
          rm_plantao: precos.rm_plantao ? parseFloat(precos.rm_plantao.replace(',', '.')) : 0,
          domiciliar_comercial: precos.domiciliar_comercial ? parseFloat(precos.domiciliar_comercial.replace(',', '.')) : 0,
          domiciliar_plantao: precos.domiciliar_plantao ? parseFloat(precos.domiciliar_plantao.replace(',', '.')) : 0,
        }
      };
      
      await api.put(`/servicos/${servicoId}`, payload);
      alert("Serviço atualizado com sucesso!");
      router.push("/servicos");
    } catch (error) {
      console.error("Erro ao salvar servico:", error);
      alert(`Erro ao atualizar serviço: ${extractApiErrorMessageSync(error, "Falha ao atualizar serviço.")}`);
    } finally {
      setSaving(false);
    }
  };

  const handleExcluir = async () => {
    try {
      await api.delete(`/servicos/${servicoId}`);
      alert("Serviço excluído com sucesso!");
      router.push("/servicos");
    } catch (error) {
      console.error("Erro ao excluir servico:", error);
      alert(extractApiErrorMessageSync(error, "Erro ao excluir serviço."));
    }
  };

  const PrecoCard = ({ 
    titulo, 
    icone: Icon, 
    cor,
    campoComercial, 
    campoPlantao 
  }: { 
    titulo: string; 
    icone: any; 
    cor: string;
    campoComercial: keyof Precos; 
    campoPlantao: keyof Precos;
  }) => (
    <div className={`fc-service-region ${cor}`}>
      <div className="fc-service-region-header">
        <Icon className="h-5 w-5" />
        <h3>{titulo}</h3>
      </div>
      
      <div className="space-y-4">
        <div>
          <label className="fc-service-form-label">
            <Sun className="h-3.5 w-3.5" />
            Horário Comercial
          </label>
          <div className="fc-service-money-field">
            <span>R$</span>
            <input
              type="text"
              value={precos[campoComercial]}
              onChange={(e) => handlePrecoChange(campoComercial, e.target.value)}
              placeholder="0,00"
            />
          </div>
          <p className="fc-service-field-hint">Seg-Sex: 08h às 18h</p>
        </div>

        <div>
          <label className="fc-service-form-label">
            <Moon className="h-3.5 w-3.5" />
            Plantão
          </label>
          <div className="fc-service-money-field">
            <span>R$</span>
            <input
              type="text"
              value={precos[campoPlantao]}
              onChange={(e) => handlePrecoChange(campoPlantao, e.target.value)}
              placeholder="0,00"
            />
          </div>
          <p className="fc-service-field-hint">Após 18h, fins de semana e feriados</p>
        </div>
      </div>
    </div>
  );

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-service-form-loading">
          <span />
          Carregando serviço...
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="fc-service-form-page">
        <header className="fc-service-form-header">
          <div className="fc-service-form-header-copy">
            <button onClick={() => router.push("/servicos")} className="fc-service-form-back" title="Voltar" aria-label="Voltar para serviços">
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-service-form-kicker">Catálogo clínico · #{servicoId}</span>
              <h1>Editar Serviço</h1>
              <p>Atualize os dados e preços da cobertura comercial.</p>
            </div>
          </div>
          <button
            onClick={() => setShowDeleteModal(true)}
            className="fc-service-form-delete"
          >
            <Trash2 className="h-4 w-4" />
            Excluir
          </button>
        </header>

        <div className="fc-service-form-layout">
          <main className="space-y-4">
            <section className="fc-service-form-panel fc-service-form-panel-cordis">
              <div className="fc-service-form-panel-title">
                <Wrench className="h-5 w-5" />
                <div>
                  <span>Identificação</span>
                  <h2>Informações básicas</h2>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="fc-service-form-label">
                  Nome do Serviço *
                  </label>
                  <input
                    type="text"
                    value={servico.nome}
                    onChange={(e) => setServico({...servico, nome: e.target.value})}
                    className="fc-service-form-control"
                    placeholder="Ex: Combo Eco + Eletro + PA"
                  />
                </div>

                <div className="md:col-span-2">
                  <label className="fc-service-form-label">
                  Descrição
                  </label>
                  <textarea
                    value={servico.descricao}
                    onChange={(e) => setServico({...servico, descricao: e.target.value})}
                    rows={3}
                    className="fc-service-form-control"
                    placeholder="Descrição detalhada do serviço..."
                  />
                </div>

                <div>
                  <label className="fc-service-form-label">
                  <Clock className="h-4 w-4" />
                  Duração (minutos)
                  </label>
                  <input
                    type="number"
                    value={servico.duracao_minutos}
                    onChange={(e) => setServico({...servico, duracao_minutos: e.target.value})}
                    className="fc-service-form-control"
                    placeholder="30"
                    min="1"
                  />
                </div>
              </div>
            </section>

            <section className="fc-service-form-panel fc-service-form-panel-vital">
              <div className="fc-service-form-panel-title">
                <DollarSign className="h-5 w-5" />
                <div>
                  <span>Tabela comercial</span>
                  <h2>Preços por região e horário</h2>
                </div>
              </div>
              <p className="fc-service-form-panel-copy">Deixe os valores em branco quando o serviço não estiver disponível naquela cobertura.</p>

              <div className="fc-service-region-grid">
              <PrecoCard
                titulo="Fortaleza"
                icone={MapPin}
                cor="fc-service-region-vital"
                campoComercial="fortaleza_comercial"
                campoPlantao="fortaleza_plantao"
              />
              
              <PrecoCard
                titulo="Região Metropolitana"
                icone={MapPin}
                cor="fc-service-region-ink"
                campoComercial="rm_comercial"
                campoPlantao="rm_plantao"
              />
              
              <PrecoCard
                titulo="Atendimento Domiciliar"
                icone={MapPin}
                cor="fc-service-region-amber"
                campoComercial="domiciliar_comercial"
                campoPlantao="domiciliar_plantao"
              />
              </div>
            </section>
          </main>

          <aside className="fc-service-form-summary">
            <div className="fc-service-form-summary-heading">
              <span>Conferência</span>
              <h2>Resumo dos preços</h2>
            </div>
            <div className="fc-service-form-summary-list">
              {[
                ["Fortaleza comercial", precos.fortaleza_comercial],
                ["Fortaleza plantão", precos.fortaleza_plantao],
                ["RM comercial", precos.rm_comercial],
                ["RM plantão", precos.rm_plantao],
                ["Domiciliar comercial", precos.domiciliar_comercial],
                ["Domiciliar plantão", precos.domiciliar_plantao],
              ].map(([label, valor]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>R$ {formatarValor(valor)}</strong>
                </div>
              ))}
            </div>
            <div className="fc-service-form-actions">
            <button
              onClick={() => router.push("/servicos")}
              className="fc-service-form-secondary"
            >
              Cancelar
            </button>
            <button
              onClick={handleSalvar}
              disabled={saving || !servico.nome}
              className="fc-service-form-save"
            >
              <Save className="h-4 w-4" />
              {saving ? "Salvando..." : "Salvar Alterações"}
            </button>
            </div>
          </aside>
        </div>

        {showDeleteModal && (
          <div className="fc-service-delete-backdrop">
            <div className="fc-service-delete-modal" role="dialog" aria-modal="true" aria-labelledby="service-delete-title">
              <div className="flex items-start gap-3">
                <div className="fc-service-delete-icon">
                  <AlertTriangle className="h-6 w-6" />
                </div>
                <div>
                  <h3 id="service-delete-title">Confirmar Exclusão</h3>
                  <p>
                    Tem certeza que deseja excluir este serviço? Esta ação não pode ser desfeita.
                  </p>
                </div>
              </div>
              
              <div className="fc-service-delete-actions">
                <button
                  onClick={() => setShowDeleteModal(false)}
                  className="fc-service-form-secondary"
                >
                  Cancelar
                </button>
                <button
                  onClick={handleExcluir}
                  className="fc-service-delete-confirm"
                >
                  <Trash2 className="h-4 w-4" />
                  Sim, Excluir
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
