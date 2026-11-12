"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";
import { Stethoscope, Search, Plus, Clock, Edit2, DollarSign, MapPin, Sun, Moon } from "lucide-react";

interface Precos {
  fortaleza_comercial: number;
  fortaleza_plantao: number;
  rm_comercial: number;
  rm_plantao: number;
  domiciliar_comercial: number;
  domiciliar_plantao: number;
}

interface Servico {
  id: number;
  nome: string;
  descricao?: string;
  duracao_minutos?: number;
  precos: Precos;
}

export default function ServicosPage() {
  const [servicos, setServicos] = useState<Servico[]>([]);
  const [loading, setLoading] = useState(true);
  const [busca, setBusca] = useState("");
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarServicos();
  }, [router]);

  const carregarServicos = async () => {
    try {
      const payload = await loadStableCatalog<{ items?: Servico[] }>({
        catalog: "servicos",
        variant: "list",
        load: () => api.get<{ items?: Servico[] }>("/servicos").then((response) => response.data),
      });
      setServicos(payload.items || []);
    } catch (error) {
      console.error("Erro ao carregar serviços:", error);
    } finally {
      setLoading(false);
    }
  };

  const servicosFiltrados = servicos.filter((s) =>
    s.nome.toLowerCase().includes(busca.toLowerCase())
  );

  const catalogoResumo = useMemo(() => {
    const precificados = servicos.filter((servico) =>
      Object.values(servico.precos).some((valor) => valor && valor > 0)
    ).length;
    const duracoes = servicos
      .map((servico) => Number(servico.duracao_minutos || 0))
      .filter((duracao) => duracao > 0);
    const duracaoMedia = duracoes.length
      ? Math.round(duracoes.reduce((total, duracao) => total + duracao, 0) / duracoes.length)
      : 0;

    return {
      precificados,
      semPreco: servicos.length - precificados,
      duracaoMedia,
    };
  }, [servicos]);

  const formatarValor = (valor: number) => {
    if (!valor || valor === 0) return "—";
    return valor.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
  };

  return (
    <DashboardLayout>
      <div className="fc-service-page">
        <header className="fc-service-header">
          <div>
            <span className="fc-service-kicker">
              <Stethoscope className="h-4 w-4" />
              Catalogo clinico
            </span>
            <h1>Serviços</h1>
            <p>Valores, duração e cobertura regional em uma visão operacional.</p>
          </div>
          <button
            onClick={() => router.push("/servicos/novo")}
            className="fc-service-primary"
          >
            <Plus className="h-4 w-4" />
            Novo Serviço
          </button>
        </header>

        <section className="fc-service-metrics" aria-label="Resumo do catálogo">
          <div className="fc-service-metric fc-service-metric-cordis">
            <Stethoscope className="fc-service-metric-icon" />
            <strong>{servicos.length}</strong>
            <span>Serviços cadastrados</span>
          </div>
          <div className="fc-service-metric fc-service-metric-vital">
            <DollarSign className="fc-service-metric-icon" />
            <strong>{catalogoResumo.precificados}</strong>
            <span>Com preços definidos</span>
          </div>
          <div className="fc-service-metric fc-service-metric-amber">
            <MapPin className="fc-service-metric-icon" />
            <strong>{catalogoResumo.semPreco}</strong>
            <span>Sem preço cadastrado</span>
          </div>
          <div className="fc-service-metric fc-service-metric-ink">
            <Clock className="fc-service-metric-icon" />
            <strong>{catalogoResumo.duracaoMedia ? `${catalogoResumo.duracaoMedia} min` : "—"}</strong>
            <span>Duração média</span>
          </div>
        </section>

        <section className="fc-service-search">
          <div className="fc-service-search-copy">
            <span>Carteira ativa</span>
            <strong>{servicosFiltrados.length} serviço(s) visível(is)</strong>
          </div>
          <div className="fc-service-search-field">
            <Search className="h-5 w-5" />
            <input
              type="text"
              placeholder="Buscar serviço..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
        </section>

        <section className="fc-service-list">
          <div className="fc-service-list-head">
            <span>Serviço</span>
            <span>Preços por cobertura</span>
            <span className="sr-only">Ações</span>
          </div>
          {loading ? (
            <div className="fc-service-loading">
              <span />
              Carregando catálogo...
            </div>
          ) : servicosFiltrados.length === 0 ? (
            <div className="fc-service-empty">
              <div><Stethoscope className="h-6 w-6" /></div>
              <span>Catálogo sem resultados</span>
              <p>Nenhum serviço corresponde à busca informada.</p>
            </div>
          ) : (
            <div>
              {servicosFiltrados.map((servico) => (
                <article key={servico.id} className="fc-service-row">
                  <button
                    type="button"
                    className="fc-service-row-main"
                    onClick={() => router.push(`/servicos/${servico.id}`)}
                  >
                    <span className="fc-service-avatar"><Stethoscope className="h-5 w-5" /></span>
                    <span className="fc-service-copy">
                      <span className="fc-service-title-line">
                        <strong>{servico.nome}</strong>
                        <small>#{servico.id}</small>
                      </span>
                      <span className="fc-service-description">{servico.descricao || "Sem descrição cadastrada"}</span>
                      <span className="fc-service-duration">
                        <Clock className="h-3.5 w-3.5" />
                        {servico.duracao_minutos ? `${servico.duracao_minutos} minutos` : "Duração não informada"}
                      </span>
                    </span>
                  </button>

                  <div className="fc-service-prices">
                    {[
                      {
                        label: "Fortaleza",
                        comercial: servico.precos.fortaleza_comercial,
                        plantao: servico.precos.fortaleza_plantao,
                        className: "fc-service-price-vital",
                      },
                      {
                        label: "Região metropolitana",
                        comercial: servico.precos.rm_comercial,
                        plantao: servico.precos.rm_plantao,
                        className: "fc-service-price-ink",
                      },
                      {
                        label: "Domiciliar",
                        comercial: servico.precos.domiciliar_comercial,
                        plantao: servico.precos.domiciliar_plantao,
                        className: "fc-service-price-amber",
                      },
                    ].map((regiao) => (
                      <div key={regiao.label} className={`fc-service-price ${regiao.className}`}>
                        <span><MapPin className="h-3.5 w-3.5" />{regiao.label}</span>
                        <small><Sun className="h-3 w-3" />{formatarValor(regiao.comercial)}</small>
                        <small><Moon className="h-3 w-3" />{formatarValor(regiao.plantao)}</small>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={() => router.push(`/servicos/${servico.id}`)}
                    className="fc-service-edit"
                    title="Editar serviço"
                    aria-label={`Editar ${servico.nome}`}
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
