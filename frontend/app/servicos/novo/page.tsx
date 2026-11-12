"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { extractApiErrorMessageSync } from "@/lib/api-error";
import { Save, ArrowLeft, Wrench, MapPin, Clock, DollarSign, Sun, Moon } from "lucide-react";

interface Precos {
  fortaleza_comercial: string;
  fortaleza_plantao: string;
  rm_comercial: string;
  rm_plantao: string;
  domiciliar_comercial: string;
  domiciliar_plantao: string;
}

export default function NovoServicoPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
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
    }
  }, [router]);

  const handlePrecoChange = (campo: keyof Precos, valor: string) => {
    // Remove caracteres não numéricos exceto ponto e vírgula
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

    // Verificar se o usuário está autenticado
    const token = localStorage.getItem("token");
    
    if (!token) {
      alert("Sessão expirada. Por favor, faça login novamente.");
      router.push("/");
      return;
    }

    setLoading(true);
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
      
      await api.post("/servicos", payload);
      alert("Serviço cadastrado com sucesso!");
      router.push("/servicos");
    } catch (error) {
      console.error("Erro ao salvar serviço:", error);
      alert(`Erro ao cadastrar serviço: ${extractApiErrorMessageSync(error, "Falha ao cadastrar serviço.")}`);
    } finally {
      setLoading(false);
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
        {/* Horário Comercial */}
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
          <p className="fc-service-field-hint">
            Seg-Sex: 08h às 18h
          </p>
        </div>

        {/* Plantão */}
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
          <p className="fc-service-field-hint">
            Após 18h, fins de semana e feriados
          </p>
        </div>
      </div>
    </div>
  );

  return (
    <DashboardLayout>
      <div className="fc-service-form-page">
        <header className="fc-service-form-header">
          <div className="fc-service-form-header-copy">
            <button onClick={() => router.push("/servicos")} className="fc-service-form-back" title="Voltar" aria-label="Voltar para serviços">
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-service-form-kicker">Catálogo clínico</span>
              <h1>Novo Serviço</h1>
              <p>Cadastre o serviço e configure sua cobertura comercial.</p>
            </div>
          </div>
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
              disabled={loading || !servico.nome}
              className="fc-service-form-save"
            >
              <Save className="h-4 w-4" />
              {loading ? "Salvando..." : "Salvar Serviço"}
            </button>
          </div>
          </aside>
        </div>
      </div>
    </DashboardLayout>
  );
}
