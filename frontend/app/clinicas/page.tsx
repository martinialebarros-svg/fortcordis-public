"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import { listarTodasClinicas } from "@/lib/clinicas";
import { Building2, Search, Plus, MapPin, Phone, Edit2, ListFilter, MapPinned, ShieldCheck } from "lucide-react";

interface Clinica {
  id: number;
  nome: string;
  razao_social?: string | null;
  cnpj?: string;
  telefone?: string;
  whatsapps?: string[];
  email?: string;
  endereco?: string;
}

export default function ClinicasPage() {
  const [clinicas, setClinicas] = useState<Clinica[]>([]);
  const [loading, setLoading] = useState(true);
  const [busca, setBusca] = useState("");
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarClinicas();
  }, [router]);

  const carregarClinicas = async () => {
    try {
      const items = await listarTodasClinicas<Clinica>();
      setClinicas(items);
    } catch (error) {
      console.error("Erro ao carregar clínicas:", error);
    } finally {
      setLoading(false);
    }
  };

  const clinicasFiltradas = clinicas.filter((c) => {
    const termo = busca.toLowerCase();
    return (
      c.nome.toLowerCase().includes(termo) ||
      (c.razao_social || "").toLowerCase().includes(termo)
    );
  });
  const clinicasComEndereco = clinicas.filter((clinica) => Boolean(clinica.endereco?.trim())).length;

  return (
    <DashboardLayout>
      <div className="fc-registry-page">
        <header className="fc-registry-header fc-registry-header-network">
          <div>
            <span className="fc-registry-kicker">
              <Building2 className="h-4 w-4" />
              Rede assistida
            </span>
            <h1>Clínicas parceiras</h1>
            <p>Contatos e localização da rede de atendimento em uma leitura objetiva.</p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => router.push("/clinicas/portal")}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900"
            >
              <ShieldCheck className="w-4 h-4" />
              Portal das clinicas
            </button>
            <button
              onClick={() => router.push("/clinicas/novo")}
              className="fc-registry-primary"
            >
              <Plus className="w-4 h-4" />
              Nova Clínica
            </button>
          </div>
        </header>

        <section className="fc-registry-metrics" aria-label="Resumo da rede de clínicas">
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <Building2 className="h-5 w-5" />
            </div>
            <div>
              <strong>{clinicas.length}</strong>
              <span>Parceiras ativas</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <ListFilter className="h-5 w-5" />
            </div>
            <div>
              <strong>{clinicasFiltradas.length}</strong>
              <span>Resultados visíveis</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <MapPinned className="h-5 w-5" />
            </div>
            <div>
              <strong>{clinicasComEndereco}</strong>
              <span>Com endereço</span>
            </div>
          </div>
        </section>

        <section className="fc-registry-search">
          <div className="fc-registry-search-copy">
            <span>Localização rápida</span>
            <strong>Encontre por nome ou razão social</strong>
          </div>
          <div className="fc-registry-search-field">
            <Search className="h-5 w-5" />
            <input
              type="text"
              placeholder="Buscar clínica ou razão social..."
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
            />
          </div>
        </section>

        <section className="fc-registry-list">
          {loading ? (
            <div className="fc-registry-loading" aria-label="Carregando clínicas">
              {[0, 1, 2].map((item) => <span key={item} />)}
            </div>
          ) : clinicasFiltradas.length === 0 ? (
            <div className="fc-registry-empty">
              <div><Building2 className="h-6 w-6" /></div>
              <span>Rede sem resultados</span>
              <p>Nenhuma clínica encontrada</p>
              <button type="button" onClick={() => router.push("/clinicas/novo")} className="fc-registry-primary mt-5">
                <Plus className="h-4 w-4" />
                Cadastrar clínica
              </button>
            </div>
          ) : (
            <div className="divide-y divide-ink-100">
              {clinicasFiltradas.map((clinica) => (
                <div key={clinica.id} className="fc-registry-row fc-registry-row-clinic group">
                  <div className="fc-registry-avatar fc-registry-avatar-clinic">
                    <Building2 className="w-5 h-5 text-purple-600" />
                  </div>
                  <button
                    type="button"
                    className="fc-registry-row-main"
                    onClick={() => router.push(`/clinicas/${clinica.id}`)}
                  >
                    <div>
                      <h3>{clinica.nome}</h3>
                      <span className="fc-registry-id">Clínica #{clinica.id}</span>
                    </div>
                    {clinica.razao_social && (
                      <p>
                        Razão social: {clinica.razao_social}
                      </p>
                    )}
                  </button>
                  <div className="fc-registry-clinic-contact">
                    {clinica.endereco ? (
                      <span><MapPin className="h-3.5 w-3.5" />{clinica.endereco}</span>
                    ) : <small>Endereço não informado</small>}
                    {(clinica.whatsapps?.[0] || clinica.telefone) && (
                      <span><Phone className="h-3.5 w-3.5" />{clinica.whatsapps?.[0] || clinica.telefone}</span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => router.push(`/clinicas/${clinica.id}`)}
                    className="fc-registry-edit"
                    title="Editar"
                    aria-label={`Editar clínica ${clinica.nome}`}
                  >
                    <Edit2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
