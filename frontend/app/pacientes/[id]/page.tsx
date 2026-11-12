"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { patientAgeForm, patientAgePayload } from "@/lib/paciente-idade";
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import TutorIdentificacaoFields from "@/components/TutorIdentificacaoFields";
import { formatCalendarDate, formatOperationalDate } from "@/lib/calendar-date";
import {
  formatarCepVisual,
  formatarCpfVisual,
  formatarTelefoneVisual,
  normalizarCep,
  normalizarCpf,
  normalizarTelefone,
} from "@/lib/atendimento-cadastro";
import {
  addRacaCustomPorEspecie,
  getRacaOptions,
  loadRacasCustomPorEspecie,
  saveRacasCustomPorEspecie,
} from "@/lib/racas";
import { getLaudoViewPath, getTipoLaudoLabel } from "@/lib/laudos";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  FileCheck2,
  History,
  PawPrint,
  RefreshCw,
  Save,
  ShieldAlert,
  Stethoscope,
  Trash2,
  UserRound,
} from "lucide-react";

type AtendimentoResumoClinico = {
  id: number;
  data_atendimento?: string | null;
  status: string;
  queixa_principal: string;
  diagnostico_principal: string;
  veterinario: string;
};

type LaudoResumoClinico = {
  id: number;
  tipo: string;
  titulo: string;
  status: string;
  data_exame?: string | null;
  data_laudo?: string | null;
};

type AlertaResumoClinico = {
  id: number;
  titulo: string;
  descricao: string;
  gravidade: string;
};

type ResumoClinicoPaciente = {
  paciente_id: number;
  totais: {
    atendimentos: number;
    laudos_concluidos: number;
    alertas_ativos: number;
  };
  atendimentos_recentes: AtendimentoResumoClinico[];
  laudos_recentes: LaudoResumoClinico[];
  alertas_ativos: AlertaResumoClinico[];
};

const formatarDataClinica = (value?: string | null) => {
  return formatOperationalDate(value, "Data não informada");
};

export default function EditarPacientePage() {
  const router = useRouter();
  const params = useParams();
  const pacienteId = params.id as string;
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mescladoEm, setMescladoEm] = useState<number | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [resumoClinico, setResumoClinico] = useState<ResumoClinicoPaciente | null>(null);
  const [resumoClinicoLoading, setResumoClinicoLoading] = useState(true);
  const [resumoClinicoError, setResumoClinicoError] = useState("");
  const [paciente, setPaciente] = useState({
    tutor_id: "",
    tutor_identificacao_pendente: true,
    tutor_origem_cadastro: "",
    tutor_identificacao_observacoes: "",
    nome: "",
    tutor: "",
    tutor_email: "",
    tutor_telefone: "",
    tutor_whatsapp: "",
    tutor_cpf: "",
    tutor_cep: "",
    tutor_endereco: "",
    tutor_numero: "",
    tutor_complemento: "",
    tutor_bairro: "",
    tutor_cidade: "",
    tutor_estado: "CE",
    especie: "Canina",
    raca: "",
    sexo: "Macho",
    peso_kg: "",
    ...patientAgeForm(),
    microchip: "",
    observacoes: "",
  });
  const [novaRaca, setNovaRaca] = useState("");
  const [racasCustomPorEspecie, setRacasCustomPorEspecie] = useState<Record<string, string[]>>({});
  const [racasLoaded, setRacasLoaded] = useState(false);
  const opcoesRaca = getRacaOptions(
    paciente.especie,
    paciente.raca,
    racasCustomPorEspecie[paciente.especie] || [],
  );

  const handleAdicionarRaca = () => {
    const racaDigitada = novaRaca.trim();
    if (!racaDigitada) return;

    const racaExistente =
      opcoesRaca.find((item) => item.toLowerCase() === racaDigitada.toLowerCase()) || racaDigitada;

    setRacasCustomPorEspecie((prev) => addRacaCustomPorEspecie(prev, paciente.especie, racaDigitada));
    setPaciente((prev) => ({ ...prev, raca: racaExistente }));
    setNovaRaca("");
  };

  useEffect(() => {
    setRacasCustomPorEspecie(loadRacasCustomPorEspecie());
    setRacasLoaded(true);
  }, []);

  useEffect(() => {
    if (!racasLoaded) return;
    saveRacasCustomPorEspecie(racasCustomPorEspecie);
  }, [racasLoaded, racasCustomPorEspecie]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarPaciente();
    carregarResumoClinico();
  }, [router, pacienteId]);

  const carregarPaciente = async () => {
    try {
      const response = await api.get(`/pacientes/${pacienteId}`);
      const data = response.data;
      setMescladoEm(data.mesclado_em_id || null);
      setPaciente({
        tutor_id: data.tutor_id ? String(data.tutor_id) : "",
        tutor_identificacao_pendente: data.tutor_identificacao_pendente ?? true,
        tutor_origem_cadastro: data.tutor_origem_cadastro ?? "",
        tutor_identificacao_observacoes: data.tutor_identificacao_observacoes ?? "",
        nome: data.nome || "",
        tutor: data.tutor || "",
        tutor_email: data.tutor_email || "",
        tutor_telefone: formatarTelefoneVisual(data.tutor_telefone || ""),
        tutor_whatsapp: formatarTelefoneVisual(data.tutor_whatsapp || ""),
        tutor_cpf: formatarCpfVisual(data.tutor_cpf || ""),
        tutor_cep: formatarCepVisual(data.tutor_cep || ""),
        tutor_endereco: data.tutor_endereco || "",
        tutor_numero: data.tutor_numero || "",
        tutor_complemento: data.tutor_complemento || "",
        tutor_bairro: data.tutor_bairro || "",
        tutor_cidade: data.tutor_cidade || "",
        tutor_estado: data.tutor_estado || "CE",
        especie: data.especie || "Canina",
        raca: data.raca || "",
        sexo: data.sexo || "Macho",
        peso_kg: data.peso_kg?.toString() || "",
        ...patientAgeForm(data),
        microchip: data.microchip || "",
        observacoes: data.observacoes || "",
      });
    } catch (error) {
      console.error("Erro ao carregar paciente:", error);
      alert("Erro ao carregar dados do paciente");
      router.push("/pacientes");
    } finally {
      setLoading(false);
    }
  };

  const carregarResumoClinico = async () => {
    setResumoClinicoLoading(true);
    setResumoClinicoError("");
    try {
      const response = await api.get(`/pacientes/${pacienteId}/resumo-clinico?limite=4`);
      setResumoClinico(response.data);
    } catch (error) {
      console.error("Erro ao carregar resumo clínico do paciente:", error);
      setResumoClinico(null);
      setResumoClinicoError("Não foi possível carregar o histórico resumido agora.");
    } finally {
      setResumoClinicoLoading(false);
    }
  };

  const handleSalvar = async () => {
    setSaving(true);
    try {
      const payload = {
        ...paciente,
        ...patientAgePayload(paciente),
        tutor_id: paciente.tutor_id ? Number(paciente.tutor_id) : null,
        tutor_telefone: normalizarTelefone(paciente.tutor_telefone),
        tutor_whatsapp: normalizarTelefone(paciente.tutor_whatsapp),
        tutor_cpf: normalizarCpf(paciente.tutor_cpf),
        tutor_cep: normalizarCep(paciente.tutor_cep),
        peso_kg: paciente.peso_kg ? parseFloat(paciente.peso_kg) : null,
      };
      
      await api.put(`/pacientes/${pacienteId}`, payload);
      alert("Paciente atualizado com sucesso!");
      router.push("/pacientes");
    } catch (error) {
      console.error("Erro ao salvar paciente:", error);
      alert("Erro ao atualizar paciente");
    } finally {
      setSaving(false);
    }
  };

  const handleExcluir = async () => {
    try {
      await api.delete(`/pacientes/${pacienteId}`);
      alert("Paciente excluído com sucesso!");
      router.push("/pacientes");
    } catch (error) {
      console.error("Erro ao excluir paciente:", error);
      alert("Erro ao excluir paciente");
    }
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-patient-form-page">
          <div className="fc-patient-form-loading">
            <span aria-hidden="true" />
            Carregando paciente...
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (mescladoEm) {
    return <DashboardLayout>
      <div className="fc-patient-form-page">
        <section className="space-y-3 rounded-xl border bg-white p-5">
          <h1 className="text-xl font-semibold">Cadastro de paciente arquivado</h1>
          <p>{paciente.nome} #{pacienteId} foi mesclado. Consulte o histórico no cadastro principal.</p>
          <button type="button" className="rounded-lg border px-4 py-2 text-blue-800"
            onClick={() => router.push(`/pacientes/${mescladoEm}`)}>Abrir paciente #{mescladoEm}</button>
        </section>
      </div>
    </DashboardLayout>;
  }

  return (
    <DashboardLayout>
      <div className="fc-patient-form-page">
        <header className="fc-patient-form-header">
          <div className="fc-patient-form-heading">
            <button
              type="button"
              onClick={() => router.push("/pacientes")}
              className="fc-patient-form-back"
              aria-label="Voltar para pacientes"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-patient-form-kicker">
                <PawPrint className="h-4 w-4" />
                Carteira clínica
              </span>
              <h1>Editar paciente</h1>
              <p>Atualize o tutor e os dados clínicos de {paciente.nome || "este paciente"}.</p>
            </div>
          </div>
          <div className="fc-patient-form-header-actions">
            <div className="fc-patient-form-context">
              <span>Registro</span>
              <strong>Paciente #{pacienteId}</strong>
            </div>
            <button
              type="button"
              onClick={() => router.push(`/atendimento?paciente_id=${encodeURIComponent(pacienteId)}`)}
              className="fc-patient-form-start-care"
            >
              <Stethoscope className="h-4 w-4" />
              Iniciar atendimento
            </button>
            <button
              type="button"
              onClick={() => setShowDeleteModal(true)}
              className="fc-patient-form-delete"
            >
              <Trash2 className="w-4 h-4" />
              Excluir
            </button>
          </div>
        </header>

        <section className="fc-patient-summary-panel" aria-labelledby="patient-summary-title">
          <div className="fc-patient-summary-header">
            <div className="fc-patient-summary-heading">
              <Activity className="h-5 w-5" />
              <div>
                <span>Prontuário longitudinal</span>
                <h2 id="patient-summary-title">
                  Histórico resumido de {paciente.nome || "este paciente"}
                </h2>
                <p>Consulte rapidamente os registros relevantes antes de editar ou atender.</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void carregarResumoClinico()}
              disabled={resumoClinicoLoading}
              className="fc-patient-summary-refresh"
            >
              <RefreshCw className={`h-4 w-4 ${resumoClinicoLoading ? "animate-spin" : ""}`} />
              Atualizar
            </button>
          </div>

          {resumoClinicoLoading ? (
            <div className="fc-patient-summary-loading" role="status">
              <span aria-hidden="true" />
              Carregando histórico clínico...
            </div>
          ) : resumoClinicoError ? (
            <div className="fc-patient-summary-error" role="alert">
              <AlertTriangle className="h-5 w-5" />
              <div>
                <strong>Histórico indisponível</strong>
                <p>{resumoClinicoError}</p>
              </div>
              <button type="button" onClick={() => void carregarResumoClinico()}>
                Tentar novamente
              </button>
            </div>
          ) : resumoClinico ? (
            <>
              <div className="fc-patient-summary-metrics">
                <article className="fc-patient-summary-metric fc-patient-summary-metric-care">
                  <History className="h-5 w-5" />
                  <div>
                    <span>Atendimentos</span>
                    <strong>{resumoClinico.totais.atendimentos}</strong>
                    <small>Total registrado</small>
                  </div>
                </article>
                <article className="fc-patient-summary-metric fc-patient-summary-metric-report">
                  <FileCheck2 className="h-5 w-5" />
                  <div>
                    <span>Exames laudados</span>
                    <strong>{resumoClinico.totais.laudos_concluidos}</strong>
                    <small>Finalizados ou liberados</small>
                  </div>
                </article>
                <article className="fc-patient-summary-metric fc-patient-summary-metric-alert">
                  <ShieldAlert className="h-5 w-5" />
                  <div>
                    <span>Alertas clínicos</span>
                    <strong>{resumoClinico.totais.alertas_ativos}</strong>
                    <small>Ativos no prontuário</small>
                  </div>
                </article>
              </div>

              <div className="fc-patient-summary-content">
                <article className="fc-patient-summary-card">
                  <div className="fc-patient-summary-card-header">
                    <div>
                      <span>Consulta clínica</span>
                      <h3>Atendimentos anteriores</h3>
                    </div>
                    <History className="h-5 w-5" />
                  </div>
                  {resumoClinico.atendimentos_recentes.length > 0 ? (
                    <div className="fc-patient-summary-list">
                      {resumoClinico.atendimentos_recentes.map((atendimento) => (
                        <button
                          key={atendimento.id}
                          type="button"
                          onClick={() => router.push(`/atendimento?atendimento_id=${atendimento.id}`)}
                          className="fc-patient-summary-item"
                        >
                          <div>
                            <div className="fc-patient-summary-item-title">
                              <strong>
                                {atendimento.diagnostico_principal ||
                                  atendimento.queixa_principal ||
                                  "Atendimento clínico"}
                              </strong>
                              <span>{atendimento.status || "Sem status"}</span>
                            </div>
                            <p>
                              {formatarDataClinica(atendimento.data_atendimento)}
                              {atendimento.veterinario ? ` · ${atendimento.veterinario}` : ""}
                            </p>
                          </div>
                          <ChevronRight className="h-4 w-4" />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="fc-patient-summary-empty">
                      <History className="h-5 w-5" />
                      Nenhum atendimento anterior registrado.
                    </div>
                  )}
                </article>

                <article className="fc-patient-summary-card">
                  <div className="fc-patient-summary-card-header">
                    <div>
                      <span>Documentos concluídos</span>
                      <h3>Exames laudados</h3>
                    </div>
                    <FileCheck2 className="h-5 w-5" />
                  </div>
                  {resumoClinico.laudos_recentes.length > 0 ? (
                    <div className="fc-patient-summary-list">
                      {resumoClinico.laudos_recentes.map((laudo) => (
                        <button
                          key={laudo.id}
                          type="button"
                          onClick={() => router.push(getLaudoViewPath(laudo.id, laudo.tipo))}
                          className="fc-patient-summary-item"
                        >
                          <div>
                            <div className="fc-patient-summary-item-title">
                              <strong>{laudo.titulo || getTipoLaudoLabel(laudo.tipo)}</strong>
                              <span>{laudo.status}</span>
                            </div>
                            <p>
                              {getTipoLaudoLabel(laudo.tipo)} ·{" "}
                              {laudo.data_exame
                                ? formatCalendarDate(laudo.data_exame)
                                : formatarDataClinica(laudo.data_laudo)}
                            </p>
                          </div>
                          <ChevronRight className="h-4 w-4" />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="fc-patient-summary-empty">
                      <FileCheck2 className="h-5 w-5" />
                      Nenhum exame laudado registrado.
                    </div>
                  )}
                </article>
              </div>

              {resumoClinico.alertas_ativos.length > 0 ? (
                <div className="fc-patient-summary-alerts">
                  <div>
                    <ShieldAlert className="h-5 w-5" />
                    <strong>Atenção clínica</strong>
                  </div>
                  <div className="fc-patient-summary-alert-list">
                    {resumoClinico.alertas_ativos.map((alerta) => (
                      <span key={alerta.id}>
                        {alerta.titulo}
                        {alerta.gravidade ? ` · ${alerta.gravidade}` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </section>

        <main className="fc-patient-form-panel">
          <div className="fc-patient-form-section-header fc-patient-form-section-tutor">
            <UserRound className="h-5 w-5" />
            <div>
              <span>Responsável</span>
              <h2>Dados do tutor</h2>
            </div>
          </div>

          <div className="fc-patient-form-grid">
            <TutorIdentificacaoFields value={{
              identificacao_pendente: paciente.tutor_identificacao_pendente,
              origem_cadastro: paciente.tutor_origem_cadastro,
              identificacao_observacoes: paciente.tutor_identificacao_observacoes,
            }} onChange={(value) => setPaciente((prev) => ({ ...prev,
              tutor_identificacao_pendente: value.identificacao_pendente,
              tutor_origem_cadastro: value.origem_cadastro,
              tutor_identificacao_observacoes: value.identificacao_observacoes,
            }))} />

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ID do tutor
              </label>
              <input
                type="text"
                value={paciente.tutor_id || "Sem ID vinculado"}
                readOnly
                className="w-full px-3 py-2 border border-gray-200 bg-gray-50 rounded-lg text-gray-700"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nome do tutor *
              </label>
              <input
                type="text"
                value={paciente.tutor}
                onChange={(e) => setPaciente({...paciente, tutor: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Ex: João Silva"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                E-mail do tutor
              </label>
              <input
                type="email"
                value={paciente.tutor_email}
                onChange={(e) => setPaciente({...paciente, tutor_email: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="email@tutor.com"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Telefone
              </label>
              <input
                type="tel"
                value={paciente.tutor_telefone}
                onChange={(e) => setPaciente({...paciente, tutor_telefone: formatarTelefoneVisual(e.target.value)})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="(00) 00000-0000"
                inputMode="tel"
                autoComplete="tel"
                maxLength={15}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                WhatsApp
              </label>
              <input
                type="tel"
                value={paciente.tutor_whatsapp}
                onChange={(e) => setPaciente({...paciente, tutor_whatsapp: formatarTelefoneVisual(e.target.value)})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="(00) 00000-0000"
                inputMode="tel"
                autoComplete="tel"
                maxLength={15}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                CPF
              </label>
              <input
                type="text"
                value={paciente.tutor_cpf}
                onChange={(e) => setPaciente({...paciente, tutor_cpf: formatarCpfVisual(e.target.value)})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="000.000.000-00"
                inputMode="numeric"
                maxLength={14}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                CEP
              </label>
              <input
                type="text"
                value={paciente.tutor_cep}
                onChange={(e) => setPaciente({...paciente, tutor_cep: formatarCepVisual(e.target.value)})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="00000-000"
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={9}
              />
            </div>

            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Endereço
              </label>
              <input
                type="text"
                value={paciente.tutor_endereco}
                onChange={(e) => setPaciente({...paciente, tutor_endereco: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Rua / Avenida"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Número
              </label>
              <input
                type="text"
                value={paciente.tutor_numero}
                onChange={(e) => setPaciente({...paciente, tutor_numero: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="123"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Complemento
              </label>
              <input
                type="text"
                value={paciente.tutor_complemento}
                onChange={(e) => setPaciente({...paciente, tutor_complemento: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Apto, bloco, sala"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Bairro
              </label>
              <input
                type="text"
                value={paciente.tutor_bairro}
                onChange={(e) => setPaciente({...paciente, tutor_bairro: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Bairro"
              />
            </div>

            <div className="grid grid-cols-[1fr_96px] gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Cidade
                </label>
                <input
                  type="text"
                  value={paciente.tutor_cidade}
                  onChange={(e) => setPaciente({...paciente, tutor_cidade: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  placeholder="Cidade"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  UF
                </label>
                <input
                  type="text"
                  value={paciente.tutor_estado}
                  onChange={(e) => setPaciente({...paciente, tutor_estado: e.target.value.toUpperCase().slice(0, 2)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  placeholder="CE"
                />
              </div>
            </div>
          </div>

          <div className="fc-patient-form-section-header fc-patient-form-section-pet">
            <PawPrint className="h-5 w-5" />
            <div>
              <span>Identificação clínica</span>
              <h2>Dados do pet</h2>
            </div>
            <strong className="fc-patient-form-id">
              ID do pet: {pacienteId}
            </strong>
          </div>

          <div className="fc-patient-form-grid">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nome do Paciente *
              </label>
              <input
                type="text"
                value={paciente.nome}
                onChange={(e) => setPaciente({...paciente, nome: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Ex: Rex"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Espécie
              </label>
              <select
                value={paciente.especie}
                onChange={(e) => {
                  setPaciente({ ...paciente, especie: e.target.value, raca: "" });
                  setNovaRaca("");
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="Canina">Canina</option>
                <option value="Felina">Felina</option>
                <option value="Equina">Equina</option>
                <option value="Outra">Outra</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Raça
              </label>
              <select
                value={paciente.raca}
                onChange={(e) => setPaciente({...paciente, raca: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Selecione...</option>
                {opcoesRaca.map((raca) => (
                  <option key={raca} value={raca}>
                    {raca}
                  </option>
                ))}
              </select>
              <div className="mt-2 flex gap-2">
                <input
                  type="text"
                  value={novaRaca}
                  onChange={(e) => setNovaRaca(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAdicionarRaca();
                    }
                  }}
                  placeholder="Adicionar nova raça"
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                />
                <button
                  type="button"
                  onClick={handleAdicionarRaca}
                  disabled={!novaRaca.trim()}
                  className="px-3 py-2 rounded-lg border border-blue-200 text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Adicionar
                </button>
              </div>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Sexo
              </label>
              <select
                value={paciente.sexo}
                onChange={(e) => setPaciente({...paciente, sexo: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="Macho">Macho</option>
                <option value="Fêmea">Fêmea</option>
              </select>
            </div>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Peso (kg)
              </label>
              <input
                type="text"
                value={paciente.peso_kg}
                onChange={(e) => setPaciente({...paciente, peso_kg: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Ex: 10.5"
              />
            </div>
            
            <PatientAgeFields value={paciente} onChange={(patch) => setPaciente((prev) => ({ ...prev, ...patch }))} />
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Microchip
              </label>
              <input
                type="text"
                value={paciente.microchip}
                onChange={(e) => setPaciente({...paciente, microchip: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Número do microchip"
              />
            </div>
            
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Observações
              </label>
              <textarea
                value={paciente.observacoes}
                onChange={(e) => setPaciente({...paciente, observacoes: e.target.value})}
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Observações adicionais..."
              />
            </div>
          </div>
          
          <div className="fc-patient-form-actions">
            <button
              type="button"
              onClick={() => router.push("/pacientes")}
              className="fc-patient-form-cancel"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleSalvar}
              disabled={saving || !paciente.nome || !paciente.tutor}
              className="fc-patient-form-primary"
            >
              <Save className="w-4 h-4" />
              {saving ? "Salvando..." : "Salvar Alterações"}
            </button>
          </div>
        </main>

        {/* Modal de Confirmação de Exclusão */}
        {showDeleteModal && (
          <div className="fc-patient-form-modal-backdrop" role="presentation">
            <div className="fc-patient-form-modal" role="dialog" aria-modal="true" aria-labelledby="patient-delete-title">
              <div className="flex items-center gap-3 mb-4">
                <div className="fc-patient-form-modal-icon">
                  <AlertTriangle className="w-6 h-6 text-red-600" />
                </div>
                <div>
                  <h3 id="patient-delete-title" className="text-lg font-semibold text-gray-900">Confirmar exclusão</h3>
                  <p className="text-sm text-gray-500">
                    Tem certeza que deseja excluir este paciente? Esta ação não pode ser desfeita.
                  </p>
                </div>
              </div>
              
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowDeleteModal(false)}
                  className="fc-patient-form-cancel"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleExcluir}
                  className="fc-patient-form-delete-confirm"
                >
                  <Trash2 className="w-4 h-4" />
                  Sim, excluir
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
