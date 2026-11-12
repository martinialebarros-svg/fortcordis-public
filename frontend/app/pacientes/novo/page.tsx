"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { patientAgeForm, patientAgePayload } from "@/lib/paciente-idade";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import TutorIdentificacaoFields from "@/components/TutorIdentificacaoFields";
import TutorExistenteSelector, { type TutorExistenteDetail } from "@/components/TutorExistenteSelector";
import { chaveOperacaoTutor, concluirOperacaoTutor } from "@/lib/tutor-mesclagem";
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
import { Save, ArrowLeft, Plus, UserRound, PawPrint } from "lucide-react";

const tutorInicial = () => ({
  tutor_id: "", tutor: "", tutor_identificacao_pendente: true,
  tutor_origem_cadastro: "", tutor_identificacao_observacoes: "", tutor_email: "",
  tutor_telefone: "", tutor_whatsapp: "", tutor_cpf: "", tutor_cep: "", tutor_endereco: "",
  tutor_numero: "", tutor_complemento: "", tutor_bairro: "", tutor_cidade: "", tutor_estado: "CE",
});

export default function NovoPacientePage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const salvandoRef = useRef(false);
  const [paciente, setPaciente] = useState({
    ...tutorInicial(),
    nome: "",
    especie: "",
    raca: "",
    sexo: "",
    peso_kg: "",
    ...patientAgeForm(),
    microchip: "",
    observacoes: "",
  });
  const [feedback, setFeedback] = useState("");
  const [buscarTutor, setBuscarTutor] = useState(false);
  const [novaRaca, setNovaRaca] = useState("");
  const [racasCustomPorEspecie, setRacasCustomPorEspecie] = useState<Record<string, string[]>>({});
  const [racasLoaded, setRacasLoaded] = useState(false);

  const selecionarTutor = (tutor: TutorExistenteDetail) => {
    setPaciente((prev) => ({ ...prev,
      tutor_id: String(tutor.id), tutor: tutor.nome ?? "",
      tutor_identificacao_pendente: tutor.identificacao_pendente ?? true,
      tutor_origem_cadastro: tutor.origem_cadastro ?? "",
      tutor_identificacao_observacoes: tutor.identificacao_observacoes ?? "",
      tutor_email: tutor.email ?? "", tutor_telefone: formatarTelefoneVisual(tutor.telefone ?? ""),
      tutor_whatsapp: formatarTelefoneVisual(tutor.whatsapp ?? ""), tutor_cpf: formatarCpfVisual(tutor.cpf ?? ""),
      tutor_cep: formatarCepVisual(tutor.cep ?? ""), tutor_endereco: tutor.endereco ?? "",
      tutor_numero: tutor.numero ?? "", tutor_complemento: tutor.complemento ?? "",
      tutor_bairro: tutor.bairro ?? "", tutor_cidade: tutor.cidade ?? "", tutor_estado: tutor.estado ?? "",
    }));
    setBuscarTutor(false);
    setFeedback("");
  };
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
    }
  }, [router]);

  const handleSalvar = async (cadastrarOutroPet = false) => {
    if (salvandoRef.current) return;
    salvandoRef.current = true;
    setLoading(true);
    setBuscarTutor(false);
    setFeedback("");
    try {
      const payload: Record<string, unknown> = {
        ...paciente,
        ...patientAgePayload(paciente),
        tutor_id: paciente.tutor_id ? Number(paciente.tutor_id) : null,
        tutor_telefone: normalizarTelefone(paciente.tutor_telefone),
        tutor_whatsapp: normalizarTelefone(paciente.tutor_whatsapp),
        tutor_cpf: normalizarCpf(paciente.tutor_cpf),
        tutor_cep: normalizarCep(paciente.tutor_cep),
        especie: paciente.especie || null,
        sexo: paciente.sexo || null,
        peso_kg: paciente.peso_kg ? parseFloat(paciente.peso_kg) : null,
      };
      if (paciente.tutor_id) {
        // Cadastrar outro animal não deve regravar os dados da pessoa selecionada.
        for (const campo of Object.keys(payload)) {
          if (campo === "tutor" || (campo.startsWith("tutor_") && campo !== "tutor_id")) delete payload[campo];
        }
      }
      
      const chave_operacao = await chaveOperacaoTutor("novo-paciente", payload);
      const response = await api.post("/pacientes", { ...payload, chave_operacao });
      concluirOperacaoTutor("novo-paciente");
      if (cadastrarOutroPet) {
        const tutorId = response.data?.tutor_id || paciente.tutor_id;
        setPaciente((prev) => ({
          ...prev,
          tutor_id: tutorId ? String(tutorId) : prev.tutor_id,
          nome: "",
          especie: "",
          raca: "",
          sexo: "",
          peso_kg: "",
          ...patientAgeForm(),
          microchip: "",
          observacoes: "",
        }));
        setNovaRaca("");
        setFeedback("Paciente salvo. Cadastre o proximo pet do mesmo tutor.");
        return;
      }
      router.push("/pacientes");
    } catch (error) {
      console.error("Erro ao salvar paciente:", error);
      setFeedback("Não foi possível cadastrar o paciente. Seus dados continuam preenchidos; tente salvar novamente.");
    } finally {
      salvandoRef.current = false;
      setLoading(false);
    }
  };

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
              <h1>Novo paciente</h1>
              <p>Cadastre o tutor e a identificação clínica do pet.</p>
            </div>
          </div>
          <div className="fc-patient-form-context">
            <span>Fluxo atual</span>
            <strong>Novo cadastro</strong>
          </div>
        </header>

        <main className="fc-patient-form-panel">
          {feedback && (
            <div role="status" className="fc-patient-form-feedback">
              {feedback}
            </div>
          )}

          <div className="fc-patient-form-section-header fc-patient-form-section-tutor">
            <UserRound className="h-5 w-5" />
            <div>
              <span>Responsável</span>
              <h2>Dados do tutor</h2>
            </div>
          </div>

          <div className="mb-4 flex flex-wrap items-center gap-3">
            <button type="button" disabled={loading} className="rounded-lg border border-blue-200 px-3 py-2 text-sm font-medium text-blue-700"
              onClick={() => setBuscarTutor(true)}>Selecionar tutor existente</button>
            {paciente.tutor_id && <button type="button" disabled={loading} className="rounded-lg border px-3 py-2 text-sm"
              onClick={() => {
                concluirOperacaoTutor("novo-paciente");
                setPaciente((prev) => ({ ...prev, ...tutorInicial() }));
                setBuscarTutor(false);
                setFeedback("");
              }}>Criar outra pessoa</button>}
            <p className="text-sm text-slate-600">Nome do tutor e do pet são suficientes para começar. Complemente os dados no atendimento.</p>
          </div>
          {buscarTutor && <TutorExistenteSelector onSelect={selecionarTutor} onCancel={() => setBuscarTutor(false)} />}
          {paciente.tutor_id && <p role="status" className="mb-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-900">
            Tutor selecionado: {paciente.tutor} #{paciente.tutor_id}. Os dados deste cadastro serão preservados; você pode complementá-los no atendimento.
          </p>}

          <fieldset disabled={Boolean(paciente.tutor_id) || loading} className="fc-patient-form-grid">
            {paciente.tutor_id && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  ID do tutor
                </label>
                <input
                  type="text"
                  value={paciente.tutor_id}
                  readOnly
                  className="w-full px-3 py-2 border border-gray-200 bg-gray-50 rounded-lg text-gray-700"
                />
              </div>
            )}

            <div className={paciente.tutor_id ? "" : "md:col-span-2"}>
              <label htmlFor="novo-paciente-tutor-nome" className="block text-sm font-medium text-gray-700 mb-1">
                Nome do tutor *
              </label>
              <input
                id="novo-paciente-tutor-nome"
                type="text"
                value={paciente.tutor}
                onChange={(e) => setPaciente({...paciente, tutor: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                placeholder="Primeiro nome já é suficiente"
              />
            </div>

            <details className="md:col-span-2">
              <summary className="cursor-pointer text-sm font-medium text-blue-700">Dados adicionais do tutor (opcionais)</summary>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
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
            </details>
          </fieldset>

          <div className="fc-patient-form-section-header fc-patient-form-section-pet">
            <PawPrint className="h-5 w-5" />
            <div>
              <span>Identificação clínica</span>
              <h2>Dados do pet</h2>
            </div>
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
                aria-label="Espécie do paciente"
                value={paciente.especie}
                onChange={(e) => {
                  setPaciente({ ...paciente, especie: e.target.value, raca: "" });
                  setNovaRaca("");
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Não informado</option>
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
                aria-label="Sexo do paciente"
                value={paciente.sexo}
                onChange={(e) => setPaciente({...paciente, sexo: e.target.value})}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
              >
                <option value="">Não informado</option>
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
              onClick={() => handleSalvar(true)}
              disabled={loading || !paciente.nome.trim() || !paciente.tutor.trim()}
              className="fc-patient-form-secondary"
            >
              <Plus className="w-4 h-4" />
              Salvar e adicionar outro pet
            </button>
            <button
              type="button"
              onClick={() => handleSalvar(false)}
              disabled={loading || !paciente.nome.trim() || !paciente.tutor.trim()}
              className="fc-patient-form-primary"
            >
              <Save className="w-4 h-4" />
              {loading ? "Salvando..." : "Salvar Paciente"}
            </button>
          </div>
        </main>
      </div>
    </DashboardLayout>
  );
}
