"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { patientAgeForm, patientAgePayload, type PatientAgeValue } from "@/lib/paciente-idade";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/axios";
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
import { ExternalLink, Plus, X } from "lucide-react";

interface ClienteInfoModalProps {
  pacienteId?: number | null;
  tutorId?: number | null;
  onClose: () => void;
  onSaved?: () => void;
}

interface ClienteForm extends PatientAgeValue {
  tutorId: string;
  tutorNome: string;
  tutorEmail: string;
  tutorTelefone: string;
  tutorWhatsapp: string;
  tutorCpf: string;
  tutorCep: string;
  tutorEndereco: string;
  tutorNumero: string;
  tutorComplemento: string;
  tutorBairro: string;
  tutorCidade: string;
  tutorEstado: string;
  petNome: string;
  especie: string;
  raca: string;
  sexo: string;
  pesoKg: string;
  data_nascimento: string;
  microchip: string;
  observacoes: string;
}

const FORM_INICIAL: ClienteForm = {
  tutorId: "",
  tutorNome: "",
  tutorEmail: "",
  tutorTelefone: "",
  tutorWhatsapp: "",
  tutorCpf: "",
  tutorCep: "",
  tutorEndereco: "",
  tutorNumero: "",
  tutorComplemento: "",
  tutorBairro: "",
  tutorCidade: "",
  tutorEstado: "CE",
  petNome: "",
  especie: "Canina",
  raca: "",
  sexo: "Macho",
  pesoKg: "",
  ...patientAgeForm(),
  microchip: "",
  observacoes: "",
};

export default function ClienteInfoModal({ pacienteId, tutorId, onClose, onSaved }: ClienteInfoModalProps) {
  const router = useRouter();
  const modoPaciente = Boolean(pacienteId);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [erro, setErro] = useState("");
  const [form, setForm] = useState<ClienteForm>(FORM_INICIAL);
  const [novaRaca, setNovaRaca] = useState("");
  const [racasCustomPorEspecie, setRacasCustomPorEspecie] = useState<Record<string, string[]>>({});

  const opcoesRaca = getRacaOptions(form.especie, form.raca, racasCustomPorEspecie[form.especie] || []);

  useEffect(() => {
    setRacasCustomPorEspecie(loadRacasCustomPorEspecie());
  }, []);

  useEffect(() => {
    if (!pacienteId && !tutorId) return;
    let cancelado = false;
    setLoading(true);
    setErro("");

    const carregar = async () => {
      try {
        if (pacienteId) {
          const response = await api.get(`/pacientes/${pacienteId}`);
          if (cancelado) return;
          const data = response.data;
          setForm({
            tutorId: data.tutor_id ? String(data.tutor_id) : "",
            tutorNome: data.tutor || "",
            tutorEmail: data.tutor_email || "",
            tutorTelefone: formatarTelefoneVisual(data.tutor_telefone || ""),
            tutorWhatsapp: formatarTelefoneVisual(data.tutor_whatsapp || ""),
            tutorCpf: formatarCpfVisual(data.tutor_cpf || ""),
            tutorCep: formatarCepVisual(data.tutor_cep || ""),
            tutorEndereco: data.tutor_endereco || "",
            tutorNumero: data.tutor_numero || "",
            tutorComplemento: data.tutor_complemento || "",
            tutorBairro: data.tutor_bairro || "",
            tutorCidade: data.tutor_cidade || "",
            tutorEstado: data.tutor_estado || "CE",
            petNome: data.nome || "",
            especie: data.especie || "Canina",
            raca: data.raca || "",
            sexo: data.sexo || "Macho",
            pesoKg: data.peso_kg?.toString() || "",
            ...patientAgeForm(data),
            microchip: data.microchip || "",
            observacoes: data.observacoes || "",
          });
        } else if (tutorId) {
          const response = await api.get(`/tutores/${tutorId}`);
          if (cancelado) return;
          const data = response.data;
          setForm({
            ...FORM_INICIAL,
            tutorId: String(tutorId),
            tutorNome: data.nome || "",
            tutorEmail: data.email || "",
            tutorTelefone: formatarTelefoneVisual(data.telefone || ""),
            tutorWhatsapp: formatarTelefoneVisual(data.whatsapp || ""),
            tutorCpf: formatarCpfVisual(data.cpf || ""),
            tutorCep: formatarCepVisual(data.cep || ""),
            tutorEndereco: data.endereco || "",
            tutorNumero: data.numero || "",
            tutorComplemento: data.complemento || "",
            tutorBairro: data.bairro || "",
            tutorCidade: data.cidade || "",
            tutorEstado: data.estado || "CE",
          });
        }
      } catch (error) {
        console.error("Erro ao carregar cliente:", error);
        if (!cancelado) setErro("Nao foi possivel carregar os dados deste cliente agora.");
      } finally {
        if (!cancelado) setLoading(false);
      }
    };

    void carregar();
    return () => {
      cancelado = true;
    };
  }, [pacienteId, tutorId]);

  const atualizarCampo = <K extends keyof ClienteForm>(campo: K, valor: ClienteForm[K]) => {
    setForm((prev) => ({ ...prev, [campo]: valor }));
  };

  const handleAdicionarRaca = () => {
    const racaDigitada = novaRaca.trim();
    if (!racaDigitada) return;
    const racaExistente =
      opcoesRaca.find((item) => item.toLowerCase() === racaDigitada.toLowerCase()) || racaDigitada;
    const atualizado = addRacaCustomPorEspecie(racasCustomPorEspecie, form.especie, racaDigitada);
    setRacasCustomPorEspecie(atualizado);
    saveRacasCustomPorEspecie(atualizado);
    atualizarCampo("raca", racaExistente);
    setNovaRaca("");
  };

  const handleSalvar = async () => {
    setSaving(true);
    setErro("");
    try {
      if (modoPaciente && pacienteId) {
        await api.put(`/pacientes/${pacienteId}`, {
          nome: form.petNome,
          tutor_id: form.tutorId ? Number(form.tutorId) : null,
          tutor: form.tutorNome,
          tutor_email: form.tutorEmail || null,
          tutor_telefone: normalizarTelefone(form.tutorTelefone),
          tutor_whatsapp: normalizarTelefone(form.tutorWhatsapp),
          tutor_cpf: normalizarCpf(form.tutorCpf),
          tutor_cep: normalizarCep(form.tutorCep),
          tutor_endereco: form.tutorEndereco || null,
          tutor_numero: form.tutorNumero || null,
          tutor_complemento: form.tutorComplemento || null,
          tutor_bairro: form.tutorBairro || null,
          tutor_cidade: form.tutorCidade || null,
          tutor_estado: form.tutorEstado || null,
          especie: form.especie,
          raca: form.raca,
          sexo: form.sexo,
          peso_kg: form.pesoKg ? parseFloat(form.pesoKg) : null,
          ...patientAgePayload(form),
          microchip: form.microchip,
          observacoes: form.observacoes,
        });
      } else if (tutorId) {
        await api.put(`/tutores/${tutorId}`, {
          nome: form.tutorNome,
          email: form.tutorEmail || null,
          telefone: normalizarTelefone(form.tutorTelefone),
          whatsapp: normalizarTelefone(form.tutorWhatsapp),
          cpf: normalizarCpf(form.tutorCpf),
          cep: normalizarCep(form.tutorCep),
          endereco: form.tutorEndereco || null,
          numero: form.tutorNumero || null,
          complemento: form.tutorComplemento || null,
          bairro: form.tutorBairro || null,
          cidade: form.tutorCidade || null,
          estado: form.tutorEstado || null,
        });
      }
      onSaved?.();
      onClose();
    } catch (error) {
      console.error("Erro ao salvar cliente:", error);
      setErro("Nao foi possivel salvar as alteracoes. Tente novamente.");
    } finally {
      setSaving(false);
    }
  };

  const titulo = modoPaciente
    ? [form.petNome, form.tutorNome].filter(Boolean).join(" · ") || "Dados do cliente"
    : form.tutorNome || "Dados do tutor";

  return (
    <div
      className="fc-appointment-submodal-backdrop fixed inset-0 z-[70] flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="fc-appointment-submodal w-full max-w-3xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fc-cliente-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="fc-appointment-submodal-header flex items-center justify-between px-5 py-4">
          <h3 id="fc-cliente-modal-title" className="text-lg font-semibold pr-8">
            {loading ? "Carregando..." : titulo}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="fc-appointment-submodal-close"
            aria-label="Fechar"
            title="Fechar"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="fc-appointment-submodal-body space-y-5 px-5 py-4">
          {loading ? (
            <div className="py-10 text-center text-sm text-gray-500">Carregando dados do cliente...</div>
          ) : (
            <>
              {erro && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  {erro}
                </div>
              )}

              {!modoPaciente && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                  Este agendamento ainda nao tem um pet vinculado. Assim que o pet for cadastrado, seus dados
                  clinicos podem ser editados pela tela de Pacientes.
                </div>
              )}

              <div>
                <h4 className="mb-2 text-sm font-semibold text-slate-900">Tutor</h4>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Nome *</label>
                    <input
                      type="text"
                      value={form.tutorNome}
                      onChange={(e) => atualizarCampo("tutorNome", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Nome do tutor"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">CPF</label>
                    <input
                      type="text"
                      value={form.tutorCpf}
                      inputMode="numeric"
                      maxLength={14}
                      onChange={(e) => atualizarCampo("tutorCpf", formatarCpfVisual(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="000.000.000-00"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Telefone</label>
                    <input
                      type="text"
                      value={form.tutorTelefone}
                      inputMode="tel"
                      maxLength={15}
                      onChange={(e) => atualizarCampo("tutorTelefone", formatarTelefoneVisual(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="(00) 00000-0000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">WhatsApp</label>
                    <input
                      type="text"
                      value={form.tutorWhatsapp}
                      inputMode="tel"
                      maxLength={15}
                      onChange={(e) => atualizarCampo("tutorWhatsapp", formatarTelefoneVisual(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="(00) 00000-0000"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                    <input
                      type="email"
                      value={form.tutorEmail}
                      onChange={(e) => atualizarCampo("tutorEmail", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="email@exemplo.com"
                    />
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-3">
                <div className="text-sm font-semibold text-slate-900">Endereço do tutor</div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">CEP</label>
                    <input
                      type="text"
                      value={form.tutorCep}
                      inputMode="numeric"
                      maxLength={9}
                      onChange={(e) => atualizarCampo("tutorCep", formatarCepVisual(e.target.value))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="00000-000"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Bairro</label>
                    <input
                      type="text"
                      value={form.tutorBairro}
                      onChange={(e) => atualizarCampo("tutorBairro", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Bairro"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Endereço</label>
                    <input
                      type="text"
                      value={form.tutorEndereco}
                      onChange={(e) => atualizarCampo("tutorEndereco", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Rua / Avenida"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Numero</label>
                    <input
                      type="text"
                      value={form.tutorNumero}
                      onChange={(e) => atualizarCampo("tutorNumero", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="123"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Complemento</label>
                    <input
                      type="text"
                      value={form.tutorComplemento}
                      onChange={(e) => atualizarCampo("tutorComplemento", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Apto, bloco, sala"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Cidade</label>
                    <input
                      type="text"
                      value={form.tutorCidade}
                      onChange={(e) => atualizarCampo("tutorCidade", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Cidade"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">UF</label>
                    <input
                      type="text"
                      value={form.tutorEstado}
                      onChange={(e) => atualizarCampo("tutorEstado", e.target.value.toUpperCase().slice(0, 2))}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="CE"
                    />
                  </div>
                </div>
              </div>

              {modoPaciente && (
                <div>
                  <h4 className="mb-2 text-sm font-semibold text-slate-900">Pet</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Nome *</label>
                      <input
                        type="text"
                        value={form.petNome}
                        onChange={(e) => atualizarCampo("petNome", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        placeholder="Nome do pet"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Espécie</label>
                      <select
                        value={form.especie}
                        onChange={(e) => {
                          atualizarCampo("especie", e.target.value);
                          atualizarCampo("raca", "");
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
                      <label className="block text-sm font-medium text-gray-700 mb-1">Raça</label>
                      <select
                        value={form.raca}
                        onChange={(e) => atualizarCampo("raca", e.target.value)}
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
                          className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                          placeholder="Adicionar nova raça"
                        />
                        <button
                          type="button"
                          onClick={handleAdicionarRaca}
                          disabled={!novaRaca.trim()}
                          className="px-3 py-1.5 text-sm rounded-lg border border-blue-200 text-blue-700 hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          Adicionar
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Sexo</label>
                      <select
                        value={form.sexo}
                        onChange={(e) => atualizarCampo("sexo", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      >
                        <option value="Macho">Macho</option>
                        <option value="Fêmea">Fêmea</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Peso (kg)</label>
                      <input
                        type="text"
                        value={form.pesoKg}
                        onChange={(e) => atualizarCampo("pesoKg", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        placeholder="Ex: 10.5"
                      />
                    </div>
                    <PatientAgeFields value={form} onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))} />
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Microchip</label>
                      <input
                        type="text"
                        value={form.microchip}
                        onChange={(e) => atualizarCampo("microchip", e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                        placeholder="Numero do microchip"
                      />
                    </div>
                  </div>
                  <div className="mt-3">
                    <label className="block text-sm font-medium text-gray-700 mb-1">Observações</label>
                    <textarea
                      rows={3}
                      value={form.observacoes}
                      onChange={(e) => atualizarCampo("observacoes", e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                      placeholder="Observações adicionais..."
                    />
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="fc-appointment-submodal-footer flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          {modoPaciente && pacienteId ? (
            <button
              type="button"
              onClick={() => router.push(`/pacientes/${pacienteId}`)}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-blue-700 hover:text-blue-900"
            >
              <ExternalLink className="h-4 w-4" />
              Ver cadastro completo
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" onClick={onClose} className="fc-appointment-button-secondary" disabled={saving}>
              Cancelar
            </button>
            <button
              type="button"
              onClick={() => void handleSalvar()}
              className="fc-appointment-button-primary"
              disabled={saving || loading}
            >
              {saving ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
