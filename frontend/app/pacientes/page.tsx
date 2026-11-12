"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../layout-dashboard";
import api from "@/lib/axios";
import { Users, Search, Plus, Dog, Cat, User, Edit2, Trash2, ListChecks, ChevronLeft, ChevronRight } from "lucide-react";

const PACIENTES_POR_PAGINA = 100;

interface Paciente {
  id: number;
  nome: string;
  tutor_id?: number | null;
  tutor: string;
  tutor_email?: string;
  especie?: string;
  raca?: string;
  sexo?: string;
  peso_kg?: number;
}

export default function PacientesPage() {
  const [pacientes, setPacientes] = useState<Paciente[]>([]);
  const [totalPacientes, setTotalPacientes] = useState(0);
  const [totalResultados, setTotalResultados] = useState(0);
  const [loading, setLoading] = useState(true);
  const [deletandoLote, setDeletandoLote] = useState(false);
  const [selecionados, setSelecionados] = useState<number[]>([]);
  const [mensagemAcao, setMensagemAcao] = useState("");
  const [erroAcao, setErroAcao] = useState("");
  const [buscaDigitada, setBuscaDigitada] = useState("");
  const [busca, setBusca] = useState("");
  const [pagina, setPagina] = useState(0);
  const [erroCarregamento, setErroCarregamento] = useState("");
  const [versaoConsulta, setVersaoConsulta] = useState(0);
  const router = useRouter();

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    let ativo = true;
    const carregarPacientes = async () => {
      setLoading(true);
      setErroCarregamento("");
      const params = new URLSearchParams({
        limit: String(PACIENTES_POR_PAGINA),
        skip: String(pagina * PACIENTES_POR_PAGINA),
      });
      if (busca) params.set("search", busca);

      try {
        const response = await api.get(`/pacientes?${params.toString()}`);
        if (!ativo) return;

        const total = Number(response.data.total || 0);
        const totalAtivos = Number(response.data.total_ativos ?? total);
        const totalPaginas = Math.max(1, Math.ceil(total / PACIENTES_POR_PAGINA));

        setPacientes(response.data.items || []);
        setTotalResultados(total);
        setTotalPacientes(totalAtivos);
        if (pagina >= totalPaginas && pagina > 0) {
          setPagina(totalPaginas - 1);
        }
      } catch (error) {
        console.error("Erro ao carregar pacientes:", error);
        if (!ativo) return;
        setPacientes([]);
        setTotalResultados(0);
        setErroCarregamento("Não foi possível carregar a carteira de pacientes. Tente novamente.");
      } finally {
        if (ativo) setLoading(false);
      }
    };

    void carregarPacientes();
    return () => {
      ativo = false;
    };
  }, [busca, pagina, router, versaoConsulta]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setBusca(buscaDigitada.trim());
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [buscaDigitada]);

  const selecionadosSet = useMemo(() => new Set(selecionados), [selecionados]);
  const idsVisiveis = useMemo(() => pacientes.map((paciente) => paciente.id), [pacientes]);
  const todosVisiveisSelecionados = useMemo(() => {
    if (idsVisiveis.length === 0) return false;
    return idsVisiveis.every((id) => selecionadosSet.has(id));
  }, [idsVisiveis, selecionadosSet]);
  const totalPaginas = Math.max(1, Math.ceil(totalResultados / PACIENTES_POR_PAGINA));
  const primeiroResultado = totalResultados === 0 ? 0 : pagina * PACIENTES_POR_PAGINA + 1;
  const ultimoResultado = Math.min((pagina + 1) * PACIENTES_POR_PAGINA, totalResultados);

  useEffect(() => {
    setSelecionados((prev) => prev.filter((id) => pacientes.some((paciente) => paciente.id === id)));
  }, [pacientes]);

  const getEspecieIcon = (especie?: string) => {
    if (especie?.toLowerCase().includes("gato")) return <Cat className="w-5 h-5 text-orange-500" />;
    if (especie?.toLowerCase().includes("cachorro")) return <Dog className="w-5 h-5 text-blue-500" />;
    return <User className="w-5 h-5 text-gray-400" />;
  };

  const alternarSelecaoPaciente = (pacienteId: number) => {
    setSelecionados((prev) => {
      if (prev.includes(pacienteId)) {
        return prev.filter((id) => id !== pacienteId);
      }
      return [...prev, pacienteId];
    });
  };

  const alternarSelecionarFiltrados = () => {
    setSelecionados((prev) => {
      if (todosVisiveisSelecionados) {
        return prev.filter((id) => !idsVisiveis.includes(id));
      }
      const merged = new Set(prev);
      for (const id of idsVisiveis) {
        merged.add(id);
      }
      return Array.from(merged);
    });
  };

  const excluirSelecionados = async () => {
    if (selecionados.length === 0 || deletandoLote) return;

    const confirmar = window.confirm(
      `Deseja excluir ${selecionados.length} paciente(s) selecionado(s)? Esta acao pode desativar pacientes com historico.`
    );
    if (!confirmar) return;

    setDeletandoLote(true);
    setMensagemAcao("");
    setErroAcao("");

    const listaSelecionados = [...selecionados];
    const mapaNomes = new Map(pacientes.map((paciente) => [paciente.id, paciente.nome]));

    const resultados = await Promise.all(
      listaSelecionados.map(async (pacienteId) => {
        try {
          const response = await api.delete(`/pacientes/${pacienteId}`);
          return {
            id: pacienteId,
            ok: true,
            mode: String(response.data?.mode || ""),
          };
        } catch (error: any) {
          return {
            id: pacienteId,
            ok: false,
            erro: String(error?.response?.data?.detail || error?.message || "Erro desconhecido"),
          };
        }
      })
    );

    const sucesso = resultados.filter((resultado) => resultado.ok);
    const falhas = resultados.filter((resultado) => !resultado.ok);
    const idsSucesso = new Set(sucesso.map((item) => item.id));
    const softDelete = sucesso.filter((item) => item.mode === "soft_delete").length;
    const hardDelete = sucesso.filter((item) => item.mode === "hard_delete").length;

    if (idsSucesso.size > 0) {
      setPacientes((prev) => prev.filter((paciente) => !idsSucesso.has(paciente.id)));
      setTotalPacientes((prev) => Math.max(0, prev - idsSucesso.size));
      setTotalResultados((prev) => Math.max(0, prev - idsSucesso.size));
    }

    if (falhas.length > 0) {
      const resumoFalhas = falhas
        .slice(0, 3)
        .map((falha) => `${mapaNomes.get(falha.id) || `ID ${falha.id}`}: ${falha.erro}`)
        .join(" | ");
      setErroAcao(
        `Falha ao excluir ${falhas.length} paciente(s). ${resumoFalhas}${falhas.length > 3 ? " | ..." : ""}`
      );
    } else {
      setErroAcao("");
    }

    if (sucesso.length > 0) {
      const detalhes: string[] = [];
      if (hardDelete > 0) detalhes.push(`${hardDelete} removido(s)`);
      if (softDelete > 0) detalhes.push(`${softDelete} desativado(s)`);
      setMensagemAcao(`Exclusao em lote concluida: ${detalhes.join(" e ")}.`);
    } else {
      setMensagemAcao("");
    }

    setSelecionados((prev) => prev.filter((id) => !idsSucesso.has(id)));
    setDeletandoLote(false);
    if (idsSucesso.size > 0) setVersaoConsulta((prev) => prev + 1);
  };

  return (
    <DashboardLayout>
      <div className="fc-registry-page">
        <header className="fc-registry-header fc-registry-header-patient">
          <div>
            <span className="fc-registry-kicker">
              <Users className="h-4 w-4" />
              Carteira clínica
            </span>
            <h1>Pacientes</h1>
            <p>Animais, tutores e identificação clínica organizados para acesso rápido.</p>
          </div>
          <button onClick={() => router.push("/pacientes/mesclagens")} className="fc-registry-primary">
            <Users className="w-4 h-4" /> Revisões de duplicidade
          </button>
          <button onClick={() => router.push("/tutores")} className="fc-registry-primary">
            <Users className="w-4 h-4" /> Tutores e mesclagens
          </button>
          <button
            onClick={() => router.push("/pacientes/novo")}
            className="fc-registry-primary"
          >
            <Plus className="w-4 h-4" />
            Novo Paciente
          </button>
        </header>

        <section className="fc-registry-metrics" aria-label="Resumo da carteira de pacientes">
          <div className="fc-registry-metric fc-registry-metric-cordis">
            <div className="fc-registry-metric-icon">
              <Users className="h-5 w-5" />
            </div>
            <div>
              <strong>{totalPacientes}</strong>
              <span>Total cadastrados</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-vital">
            <div className="fc-registry-metric-icon">
              <Search className="h-5 w-5" />
            </div>
            <div>
              <strong>{totalResultados}</strong>
              <span>Resultados encontrados</span>
            </div>
          </div>
          <div className="fc-registry-metric fc-registry-metric-ink">
            <div className="fc-registry-metric-icon">
              <ListChecks className="h-5 w-5" />
            </div>
            <div>
              <strong>{selecionados.length}</strong>
              <span>Selecionados</span>
            </div>
          </div>
        </section>

        <section className="fc-registry-search">
          <div className="fc-registry-search-copy">
            <span>Localização rápida</span>
            <strong>Encontre por paciente, tutor ou identificador</strong>
          </div>
          <div className="fc-registry-search-field">
            <Search className="h-5 w-5" />
            <input
              type="text"
              placeholder="Buscar por nome, tutor ou ID..."
              value={buscaDigitada}
              onChange={(e) => {
                setBuscaDigitada(e.target.value);
                setPagina(0);
              }}
            />
          </div>
        </section>

        {(mensagemAcao || erroAcao) && (
          <div className="space-y-2 mb-6">
            {mensagemAcao && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-700">
                {mensagemAcao}
              </div>
            )}
            {erroAcao && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{erroAcao}</div>
            )}
          </div>
        )}

        <section className="fc-registry-list">
          {loading ? (
            <div className="fc-registry-loading" aria-label="Carregando pacientes">
              {[0, 1, 2].map((item) => <span key={item} />)}
            </div>
          ) : erroCarregamento ? (
            <div className="fc-registry-empty" role="alert">
              <div><Users className="h-6 w-6" /></div>
              <span>Carteira indisponível</span>
              <p>{erroCarregamento}</p>
              <button type="button" onClick={() => setVersaoConsulta((prev) => prev + 1)} className="fc-registry-primary mt-5">
                Tentar novamente
              </button>
            </div>
          ) : pacientes.length === 0 ? (
            <div className="fc-registry-empty">
              <div><Users className="h-6 w-6" /></div>
              <span>Carteira sem resultados</span>
              <p>Nenhum paciente encontrado</p>
              <button type="button" onClick={() => router.push("/pacientes/novo")} className="fc-registry-primary mt-5">
                <Plus className="h-4 w-4" />
                Cadastrar paciente
              </button>
            </div>
          ) : (
            <div>
              <div className="fc-registry-selection-bar">
                <label>
                  <input
                    type="checkbox"
                    checked={todosVisiveisSelecionados}
                    onChange={alternarSelecionarFiltrados}
                    className="fc-registry-checkbox"
                  />
                  Selecionar visiveis ({idsVisiveis.length})
                </label>

                <div>
                  <span>{selecionados.length} selecionado(s)</span>
                  <button
                    onClick={excluirSelecionados}
                    disabled={selecionados.length === 0 || deletandoLote}
                    className="fc-registry-danger"
                  >
                    <Trash2 className="w-4 h-4" />
                    {deletandoLote ? "Excluindo..." : "Excluir selecionados"}
                  </button>
                </div>
              </div>

              <div className="divide-y divide-ink-100">
                {pacientes.map((paciente) => (
                  <div key={paciente.id} className="fc-registry-row group">
                    <label className="fc-registry-row-check" title="Selecionar paciente">
                      <input
                        type="checkbox"
                        checked={selecionadosSet.has(paciente.id)}
                        onChange={() => alternarSelecaoPaciente(paciente.id)}
                        className="fc-registry-checkbox"
                      />
                    </label>

                    <div className="fc-registry-avatar">
                      {getEspecieIcon(paciente.especie)}
                    </div>

                    <button type="button" className="fc-registry-row-main" onClick={() => router.push(`/pacientes/${paciente.id}`)}>
                      <div>
                        <h3>{paciente.nome}</h3>
                        <span className="fc-registry-id">
                          Pet #{paciente.id}
                        </span>
                      </div>
                      <p>
                        Tutor: {paciente.tutor || "Nao informado"}
                        {paciente.tutor_id ? ` | Tutor #${paciente.tutor_id}` : ""}
                      </p>
                      {paciente.tutor_email && (
                        <small>{paciente.tutor_email}</small>
                      )}
                    </button>

                    <div className="fc-registry-trailing">
                      {paciente.especie && <p>{paciente.especie}</p>}
                      {paciente.raca && <small>{paciente.raca}</small>}
                    </div>

                    <button
                      type="button"
                      onClick={() => router.push(`/pacientes/${paciente.id}`)}
                      className="fc-registry-edit"
                      title="Editar"
                      aria-label={`Editar paciente ${paciente.nome}`}
                    >
                      <Edit2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
              <nav className="mt-5 flex flex-wrap items-center justify-between gap-3" aria-label="Paginação de pacientes">
                <span className="text-sm text-ink-500">
                  Exibindo {primeiroResultado}-{ultimoResultado} de {totalResultados}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    className="fc-registry-danger bg-white text-ink-700 border border-ink-200 hover:bg-ink-50"
                    onClick={() => setPagina((prev) => Math.max(0, prev - 1))}
                    disabled={pagina === 0 || loading}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Anterior
                  </button>
                  <span className="text-sm font-medium text-ink-700" aria-label={`Página ${pagina + 1} de ${totalPaginas}`}>
                    Página {pagina + 1} de {totalPaginas}
                  </span>
                  <button
                    type="button"
                    className="fc-registry-danger bg-white text-ink-700 border border-ink-200 hover:bg-ink-50"
                    onClick={() => setPagina((prev) => Math.min(totalPaginas - 1, prev + 1))}
                    disabled={pagina >= totalPaginas - 1 || loading}
                  >
                    Próxima
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </nav>
            </div>
          )}
        </section>
      </div>
    </DashboardLayout>
  );
}
