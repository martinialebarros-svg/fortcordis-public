"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import { clinicCoordinates } from "@/lib/clinic-coordinates";
import {
  formatarCepVisual,
  formatarCnpjVisual,
  formatarTelefoneVisual,
  normalizarCep,
  normalizarCnpj,
  normalizarTelefone,
} from "@/lib/atendimento-cadastro";
import { Save, ArrowLeft, Building2, Trash2, AlertTriangle, MapPin, DollarSign, Calculator, Percent } from "lucide-react";
import ManualPinModal from "../components/ManualPinModal";
import ClinicaPortalAccessCard from "../components/ClinicaPortalAccessCard";
import WhatsappNumbersField from "../components/WhatsappNumbersField";
import EnderecoFiscalCard from "../components/EnderecoFiscalCard";
import {
  normalizarWhatsappsParaApi,
  prepararWhatsappsFormulario,
} from "@/lib/clinica-whatsapp";

const ESTADOS = [
  "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
  "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
  "RS", "RO", "RR", "SC", "SP", "SE", "TO"
];

const TABELAS_PRECO = [
  { id: 1, nome: "Fortaleza", descricao: "Clínicas na capital", cor: "blue" },
  { id: 2, nome: "Região Metropolitana", descricao: "Cidades próximas a Fortaleza", cor: "purple" },
  { id: 3, nome: "Domiciliar", descricao: "Atendimento domiciliar padrão", cor: "orange" },
  { id: 4, nome: "Personalizado", descricao: "Preço negociado para cidade distante", cor: "green" },
];

type PrecoNegociadoServico = {
  servico_id: number;
  servico_nome: string;
  preco_base_comercial: number;
  preco_base_plantao: number;
  preco_negociado_comercial: string;
  preco_negociado_plantao: string;
};

export default function EditarClinicaPage() {
  const router = useRouter();
  const params = useParams();
  const clinicaId = params.id as string;
  
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [loadingCep, setLoadingCep] = useState(false);
  const [loadingGeocode, setLoadingGeocode] = useState(false);
  const [lastGeocodeSignature, setLastGeocodeSignature] = useState("");
  const [localizacaoConfirmada, setLocalizacaoConfirmada] = useState(false);
  const [bairroEditadoManual, setBairroEditadoManual] = useState(false);
  const [statusEndereco, setStatusEndereco] = useState("");
  const [showManualPinModal, setShowManualPinModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [tabelaSugerida, setTabelaSugerida] = useState<number | null>(null);
  
  const [clinica, setClinica] = useState({
    nome: "",
    razao_social: "",
    cnpj: "",
    telefone: "",
    whatsapps: [""],
    email: "",
    endereco: "",
    numero: "",
    complemento: "",
    bairro: "",
    cidade: "",
    estado: "CE",
    cep: "",
    regiao_operacional: "",
    latitude: null as number | null,
    longitude: null as number | null,
    place_id: "",
    endereco_normalizado: "",
    observacoes: "",
    tabela_preco_id: 1,
    preco_personalizado_km: "",
    preco_personalizado_base: "",
    observacoes_preco: "",
  });
  const [precosServicos, setPrecosServicos] = useState<PrecoNegociadoServico[]>([]);
  const [loadingPrecosServicos, setLoadingPrecosServicos] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    carregarClinica();
  }, [router, clinicaId]);

  // Sugerir tabela de preço quando a cidade mudar
  useEffect(() => {
    if (clinica.cidade) {
      sugerirTabelaPreco();
    }
  }, [clinica.cidade, clinica.estado]);

  useEffect(() => {
    if (loading) return;
    carregarPrecosServicos();
  }, [loading, clinicaId, clinica.tabela_preco_id]);

  const assinaturaGeocode = (dados = clinica) =>
    [
      dados.endereco,
      dados.numero,
      dados.complemento,
      dados.bairro,
      dados.cidade,
      dados.estado,
      normalizarCep(dados.cep),
    ]
      .map((item) => String(item || "").trim().toLowerCase())
      .join("|");

  const limparGeocodeCache = (mensagem?: string) => {
    setClinica((prev) => ({
      ...prev,
      latitude: null,
      longitude: null,
      place_id: "",
      endereco_normalizado: "",
    }));
    setLocalizacaoConfirmada(false);
    if (mensagem) {
      setStatusEndereco(mensagem);
    }
  };

  const abrirMapaConfirmacao = () => {
    if (clinicCoordinates(clinica.latitude, clinica.longitude).latitude === null) {
      alert("Nao ha latitude/longitude para confirmar.");
      return;
    }
    const params = new URLSearchParams({
      api: "1",
      query: `${clinica.latitude},${clinica.longitude}`,
    });
    if (clinica.place_id) {
      params.set("query_place_id", clinica.place_id);
    }
    window.open(`https://www.google.com/maps/search/?${params.toString()}`, "_blank", "noopener,noreferrer");
    setLocalizacaoConfirmada(true);
    setStatusEndereco("Localizacao confirmada no mapa.");
  };

  const aplicarPinManual = ({ lat, lng }: { lat: number; lng: number }) => {
    if (clinicCoordinates(lat, lng).latitude === null) return;
    setClinica((prev) => ({
      ...prev,
      latitude: lat,
      longitude: lng,
      place_id: "",
      endereco_normalizado:
        prev.endereco_normalizado ||
        [prev.endereco, prev.numero, prev.bairro, prev.cidade, prev.estado]
          .filter((p) => String(p || "").trim())
          .join(", "),
    }));
    setLastGeocodeSignature(assinaturaGeocode());
    setLocalizacaoConfirmada(true);
    setStatusEndereco("Pin manual aplicado com sucesso.");
    setShowManualPinModal(false);
  };

  const consultarCep = async () => {
    const cep = normalizarCep(clinica.cep);
    if (cep.length !== 8) return;
    try {
      setLoadingCep(true);
      const response = await api.get(`/clinicas/cep/${cep}`);
      const item = response?.data?.item || {};
      setClinica((prev) => ({
        ...prev,
        cep: formatarCepVisual(item.cep || cep),
        endereco: item.logradouro || prev.endereco,
        complemento: prev.complemento || item.complemento || "",
        bairro: item.bairro || prev.bairro,
        cidade: item.cidade || prev.cidade,
        estado: item.estado || prev.estado,
        latitude: null,
        longitude: null,
        place_id: "",
        endereco_normalizado: "",
      }));
      setLocalizacaoConfirmada(false);
      setBairroEditadoManual(false);
      setStatusEndereco(
        item?.bairro_origem === "aprendizado"
          ? "CEP preenchido com bairro aprendido."
          : "CEP preenchido pelo ViaCEP."
      );
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "Falha ao consultar CEP.";
      setStatusEndereco(String(detail));
    } finally {
      setLoadingCep(false);
    }
  };

  const geocodificarEndereco = async (force = false) => {
    if (!clinica.endereco.trim() || !clinica.numero.trim()) {
      setStatusEndereco("Preencha endereco e numero para geocodificar.");
      return;
    }
    if (!clinica.cidade.trim() || !clinica.estado.trim()) return;

    const signature = assinaturaGeocode();
    const temResultadoAtual =
      clinica.latitude !== null &&
      clinica.longitude !== null &&
      (clinica.place_id.trim() !== "" || clinica.endereco_normalizado.trim() !== "");
    if (!force && temResultadoAtual && signature === lastGeocodeSignature) {
      return;
    }

    try {
      setLoadingGeocode(true);
      const response = await api.post("/clinicas/geocode-endereco", {
        endereco: clinica.endereco,
        numero: clinica.numero,
        complemento: clinica.complemento,
        bairro: clinica.bairro,
        cidade: clinica.cidade,
        estado: clinica.estado,
        cep: clinica.cep,
      });
      const item = response?.data?.item || {};
      const coordinates = clinicCoordinates(item.latitude, item.longitude);
      if (coordinates.latitude === null) throw new Error("O serviço não retornou coordenadas válidas. Revise o endereço ou ajuste o pin manualmente.");
      setClinica((prev) => ({
        ...prev,
        bairro: item.bairro || prev.bairro,
        cidade: item.cidade || prev.cidade,
        estado: item.estado || prev.estado,
        cep: item.cep ? formatarCepVisual(item.cep) : prev.cep,
        regiao_operacional: item.regiao_operacional || prev.regiao_operacional,
        ...coordinates,
        place_id: item.place_id || prev.place_id,
        endereco_normalizado: item.endereco_normalizado || prev.endereco_normalizado,
      }));
      setLocalizacaoConfirmada(false);
      setLastGeocodeSignature(signature);
      setStatusEndereco("Geocoding concluido. Confirme a localizacao no mapa.");
      if (item?.bairro_origem !== "aprendizado") {
        setBairroEditadoManual(false);
      }
    } catch (error: any) {
      const detail = error?.response?.data?.detail || error?.message || "Falha no geocoding.";
      setStatusEndereco(String(detail));
    } finally {
      setLoadingGeocode(false);
    }
  };

  const orientarGeocodificacao = () => {
    if (!clinica.endereco.trim()) return;
    if (!clinica.numero.trim()) {
      setStatusEndereco("Informe o numero para concluir o geocoding.");
      return;
    }
    setStatusEndereco("Endereco pronto. Use Geocodificar endereco para consultar o Google Maps. A política e os limites são verificados pelo servidor.");
  };

  const carregarClinica = async () => {
    try {
      const response = await api.get(`/clinicas/${clinicaId}`);
      const data = response.data;
      const clinicaCarregada = {
        nome: data.nome || "",
        razao_social: data.razao_social || "",
        cnpj: formatarCnpjVisual(data.cnpj || ""),
        telefone: formatarTelefoneVisual(data.telefone || ""),
        whatsapps: prepararWhatsappsFormulario(data.whatsapps, data.telefone),
        email: data.email || "",
        endereco: data.endereco || "",
        numero: data.numero || "",
        complemento: data.complemento || "",
        bairro: data.bairro || "",
        cidade: data.cidade || "",
        estado: data.estado || "CE",
        cep: formatarCepVisual(data.cep || ""),
        regiao_operacional: data.regiao_operacional || "",
        ...clinicCoordinates(data.latitude, data.longitude),
        place_id: data.place_id || "",
        endereco_normalizado: data.endereco_normalizado || "",
        observacoes: data.observacoes || "",
        tabela_preco_id: data.tabela_preco_id || 1,
        preco_personalizado_km: data.preco_personalizado_km?.toString() || "",
        preco_personalizado_base: data.preco_personalizado_base?.toString() || "",
        observacoes_preco: data.observacoes_preco || "",
      };
      
      setClinica(clinicaCarregada);
      setLastGeocodeSignature(assinaturaGeocode(clinicaCarregada));

      setLocalizacaoConfirmada(clinicaCarregada.latitude !== null && clinicaCarregada.longitude !== null);
      
      setTabelaSugerida(data.tabela_preco_id || null);
    } catch (error) {
      console.error("Erro ao carregar clinica:", error);
      alert("Erro ao carregar dados da clinica");
      router.push("/clinicas");
    } finally {
      setLoading(false);
    }
  };

  const sugerirTabelaPreco = async () => {
    if (!clinica.cidade) return;
    
    try {
      const response = await api.post(
        `/clinicas/sugerir-tabela-preco?cidade=${encodeURIComponent(clinica.cidade)}&estado=${encodeURIComponent(clinica.estado || "")}`
      );
      const sugestao = response.data;
      
      if (sugestao.tabela_sugerida) {
        setTabelaSugerida(sugestao.tabela_sugerida.id);
        if (sugestao.regiao_operacional) {
          setClinica((prev) => ({ ...prev, regiao_operacional: sugestao.regiao_operacional }));
        }
        // Se a cidade nao for reconhecida, sugerir tabela 3 (Domiciliar)
        if (!sugestao.cidade_reconhecida && clinica.tabela_preco_id === 1) {
          setClinica((prev) => ({ ...prev, tabela_preco_id: 3 }));
        }
      }
    } catch (error) {
      console.error("Erro ao sugerir tabela:", error);
    }
  };

  const carregarPrecosServicos = async () => {
    setLoadingPrecosServicos(true);
    try {
      const response = await api.get(`/clinicas/${clinicaId}/precos-servicos`);
      const items = (response.data?.items || []).map((item: any) => ({
        servico_id: item.servico_id,
        servico_nome: item.servico_nome,
        preco_base_comercial: Number(item.preco_base_comercial || 0),
        preco_base_plantao: Number(item.preco_base_plantao || 0),
        preco_negociado_comercial:
          item.preco_negociado_comercial === null || item.preco_negociado_comercial === undefined
            ? ""
            : String(item.preco_negociado_comercial),
        preco_negociado_plantao:
          item.preco_negociado_plantao === null || item.preco_negociado_plantao === undefined
            ? ""
            : String(item.preco_negociado_plantao),
      }));
      setPrecosServicos(items);
    } catch (error) {
      console.error("Erro ao carregar precos negociados:", error);
      setPrecosServicos([]);
    } finally {
      setLoadingPrecosServicos(false);
    }
  };

  const atualizarPrecoServico = (
    servicoId: number,
    campo: "preco_negociado_comercial" | "preco_negociado_plantao",
    valor: string
  ) => {
    setPrecosServicos((prev) =>
      prev.map((row) => (row.servico_id === servicoId ? { ...row, [campo]: valor } : row))
    );
  };

  const parsePrecoOpcional = (valor: string) => {
    if (!valor || !valor.trim()) return null;
    const parsed = parseFloat(valor.replace(",", "."));
    return Number.isNaN(parsed) ? null : parsed;
  };

  const handleSalvar = async () => {
    if (!clinica.nome.trim()) {
      alert("Digite o nome fantasia da clinica");
      return;
    }

    if (clinica.latitude !== null && clinica.longitude !== null && !localizacaoConfirmada) {
      alert("Confirme a localizacao no mapa antes de salvar.");
      return;
    }

    setSaving(true);
    try {
      const payload = {
        ...clinica,
        nome: clinica.nome.trim(),
        razao_social: clinica.razao_social.trim(),
        cnpj: normalizarCnpj(clinica.cnpj),
        telefone: normalizarTelefone(clinica.telefone),
        whatsapps: normalizarWhatsappsParaApi(clinica.whatsapps),
        cep: normalizarCep(clinica.cep),
        bairro_manual: bairroEditadoManual,
        tabela_preco_id: parseInt(clinica.tabela_preco_id.toString()),
        preco_personalizado_km: clinica.preco_personalizado_km
          ? parseFloat(clinica.preco_personalizado_km.replace(",", "."))
          : 0,
        preco_personalizado_base: clinica.preco_personalizado_base
          ? parseFloat(clinica.preco_personalizado_base.replace(",", "."))
          : 0,
      };

      const payloadPrecosNegociados = {
        items: precosServicos.map((row) => ({
          servico_id: row.servico_id,
          preco_comercial: parsePrecoOpcional(row.preco_negociado_comercial),
          preco_plantao: parsePrecoOpcional(row.preco_negociado_plantao),
        })),
      };

      await api.put(`/clinicas/${clinicaId}`, payload);
      await api.put(`/clinicas/${clinicaId}/precos-servicos`, payloadPrecosNegociados);
      alert("Clinica atualizada com sucesso!");
      router.push("/clinicas");
    } catch (error: any) {
      console.error("Erro ao salvar clinica:", error);
      alert("Erro ao atualizar clinica: " + (error.response?.data?.detail || error.message));
    } finally {
      setSaving(false);
    }
  };
  const handleExcluir = async () => {
    try {
      await api.delete(`/clinicas/${clinicaId}`);
      alert("Clínica excluída com sucesso!");
      router.push("/clinicas");
    } catch (error) {
      console.error("Erro ao excluir clinica:", error);
      alert("Erro ao excluir clinica");
    }
  };

  const formatarValor = (valor: string | number | null | undefined) => {
    if (valor === null || valor === undefined || valor === "") return "0,00";
    const valorString = typeof valor === "number" ? String(valor) : valor;
    const num = parseFloat(valorString.replace(',', '.'));
    if (Number.isNaN(num)) return "0,00";
    return num.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  const tabelaAtual = TABELAS_PRECO.find(t => t.id === clinica.tabela_preco_id);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="fc-clinic-form-page">
          <div className="fc-clinic-form-loading">
            <span aria-hidden="true" />
            Carregando clínica...
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="fc-clinic-form-page">
        <header className="fc-clinic-form-header">
          <div className="fc-clinic-form-heading">
            <button
              type="button"
              onClick={() => router.push("/clinicas")}
              className="fc-clinic-form-back"
              aria-label="Voltar para clínicas"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-clinic-form-kicker">
                <Building2 className="h-4 w-4" />
                Rede assistida
              </span>
              <h1>Editar clínica</h1>
              <p>Atualize cadastro, localização e condições de {clinica.nome || "esta unidade"}.</p>
            </div>
          </div>
          <div className="fc-clinic-form-header-actions">
            <div className="fc-clinic-form-context">
              <span>Registro</span>
              <strong>Clínica #{clinicaId}</strong>
            </div>
            <button
              type="button"
              onClick={() => setShowDeleteModal(true)}
              className="fc-clinic-form-delete"
            >
              <Trash2 className="w-4 h-4" />
              Excluir
            </button>
          </div>
        </header>

        <div className="fc-clinic-form-content">
          {/* Informações Básicas */}
          <section className="fc-clinic-form-card fc-clinic-form-card-profile">
            <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Building2 className="w-5 h-5 text-purple-600" />
              Informações Básicas
            </h2>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="md:col-span-2 rounded-lg border border-purple-100 bg-purple-50 px-4 py-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-purple-700">
                  ID da clinica
                </p>
                <p className="mt-1 text-2xl font-bold text-purple-950">{clinicaId}</p>
                <p className="mt-1 text-sm text-purple-800">
                  Use este identificador para testar o portal da clinica parceira.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Nome Fantasia *
                </label>
                <input
                  type="text"
                  value={clinica.nome}
                  onChange={(e) => setClinica({...clinica, nome: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Ex: Clínica Veterinária ABC"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Razão Social
                </label>
                <input
                  type="text"
                  value={clinica.razao_social}
                  onChange={(e) => setClinica({...clinica, razao_social: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Ex: Clínica Veterinária ABC LTDA"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  CNPJ
                </label>
                <input
                  type="text"
                  value={clinica.cnpj}
                  onChange={(e) => setClinica({...clinica, cnpj: formatarCnpjVisual(e.target.value)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="00.000.000/0000-00"
                  inputMode="numeric"
                  maxLength={18}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Telefone geral
                </label>
                <input
                  type="tel"
                  value={clinica.telefone}
                  onChange={(e) => setClinica({...clinica, telefone: formatarTelefoneVisual(e.target.value)})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="(00) 00000-0000"
                  inputMode="tel"
                  autoComplete="tel"
                  maxLength={15}
                />
              </div>

              <WhatsappNumbersField
                value={clinica.whatsapps}
                onChange={(whatsapps) => setClinica({ ...clinica, whatsapps })}
              />
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  E-mail
                </label>
                <input
                  type="email"
                  value={clinica.email}
                  onChange={(e) => setClinica({...clinica, email: e.target.value})}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="email@clinica.com"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  CEP
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={clinica.cep}
                    onChange={(e) => {
                      const valor = formatarCepVisual(e.target.value);
                      setClinica({ ...clinica, cep: valor });
                      limparGeocodeCache();
                    }}
                    onBlur={consultarCep}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                    placeholder="00000-000"
                    inputMode="numeric"
                    autoComplete="postal-code"
                    maxLength={9}
                  />
                  <button
                    type="button"
                    onClick={consultarCep}
                    disabled={loadingCep}
                    className="px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                  >
                    {loadingCep ? "..." : "Buscar"}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  <MapPin className="w-4 h-4 inline mr-1" />
                  Cidade
                </label>
                <input
                  type="text"
                  value={clinica.cidade}
                  onChange={(e) => {
                    setClinica({ ...clinica, cidade: e.target.value });
                    limparGeocodeCache("Cidade alterada. Rode o geocoding novamente.");
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Cidade"
                />
              </div>

              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Endereco
                </label>
                <input
                  type="text"
                  value={clinica.endereco}
                  onChange={(e) => {
                    setClinica({ ...clinica, endereco: e.target.value });
                    limparGeocodeCache();
                  }}
                  onBlur={orientarGeocodificacao}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Rua / Avenida"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Numero
                  </label>
                  <input
                    type="text"
                    value={clinica.numero}
                    onChange={(e) => {
                      setClinica({ ...clinica, numero: e.target.value });
                      limparGeocodeCache();
                    }}
                    onBlur={orientarGeocodificacao}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                    placeholder="123"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Complemento
                  </label>
                  <input
                    type="text"
                    value={clinica.complemento}
                    onChange={(e) => {
                      setClinica({ ...clinica, complemento: e.target.value });
                      limparGeocodeCache();
                    }}
                    onBlur={orientarGeocodificacao}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                    placeholder="Sala, bloco, etc."
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Bairro
                </label>
                <input
                  type="text"
                  value={clinica.bairro}
                  onChange={(e) => {
                    setClinica({ ...clinica, bairro: e.target.value });
                    setBairroEditadoManual(true);
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Bairro"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Estado
                  </label>
                  <select
                    value={clinica.estado}
                    onChange={(e) => {
                      setClinica({ ...clinica, estado: e.target.value });
                      limparGeocodeCache("UF alterada. Rode o geocoding novamente.");
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  >
                    {ESTADOS.map((uf) => (
                      <option key={uf} value={uf}>
                        {uf}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Regiao operacional
                  </label>
                  <input
                    type="text"
                    value={clinica.regiao_operacional}
                    readOnly
                    className="w-full px-3 py-2 border border-gray-200 bg-gray-50 rounded-lg text-gray-700"
                    placeholder="Calculada automaticamente"
                  />
                </div>
              </div>

              <div className="md:col-span-2 rounded-lg border border-indigo-100 bg-indigo-50 p-3">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <button
                    type="button"
                    onClick={() => geocodificarEndereco(true)}
                    disabled={loadingGeocode}
                    className="px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {loadingGeocode ? "Geocodificando..." : "Geocodificar endereco"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowManualPinModal(true)}
                    className="px-3 py-2 border border-indigo-300 text-indigo-700 rounded-lg hover:bg-indigo-100"
                  >
                    Ajustar pin manual
                  </button>
                  {clinica.latitude !== null && clinica.longitude !== null && (
                    <button
                      type="button"
                      onClick={abrirMapaConfirmacao}
                      className="px-3 py-2 border border-indigo-300 text-indigo-700 rounded-lg hover:bg-indigo-100"
                    >
                      Confirmar localizacao no mapa
                    </button>
                  )}
                </div>
                <p className="text-xs text-indigo-900">
                  {statusEndereco || "Fluxo: CEP -> endereco completo -> geocoding -> confirmar no mapa."}
                </p>
                {clinica.endereco_normalizado && (
                  <p className="text-xs text-indigo-800 mt-1">
                    Endereco padronizado: {clinica.endereco_normalizado}
                  </p>
                )}
                {(clinica.latitude !== null || clinica.longitude !== null) && (
                  <p className="text-xs text-indigo-800 mt-1">
                    Lat/Lng: {clinica.latitude ?? "-"}, {clinica.longitude ?? "-"}{" "}
                    {localizacaoConfirmada ? "(confirmado)" : "(pendente confirmacao)"}
                  </p>
                )}
              </div>
              
              <div className="md:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Observações
                </label>
                <textarea
                  value={clinica.observacoes}
                  onChange={(e) => setClinica({...clinica, observacoes: e.target.value})}
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                  placeholder="Observações adicionais..."
                />
              </div>
            </div>
          </section>

          {/* Tabela de Preços */}
          <section className="fc-clinic-form-card fc-clinic-form-card-pricing">
            <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <DollarSign className="w-5 h-5 text-green-600" />
              Tabela de Preços
            </h2>
            <p className="text-sm text-gray-500 mb-4">
              A tabela é sugerida automaticamente baseada na cidade, mas pode ser alterada manualmente.
            </p>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
              {TABELAS_PRECO.map((tabela) => (
                <label
                  key={tabela.id}
                  className={`cursor-pointer border-2 rounded-xl p-4 transition-all ${
                    clinica.tabela_preco_id === tabela.id
                      ? `border-${tabela.cor}-500 bg-${tabela.cor}-50`
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <input
                      type="radio"
                      name="tabela_preco"
                      value={tabela.id}
                      checked={clinica.tabela_preco_id === tabela.id}
                      onChange={() => setClinica({...clinica, tabela_preco_id: tabela.id})}
                      className="mt-1"
                    />
                    <div>
                      <p className={`font-medium ${clinica.tabela_preco_id === tabela.id ? `text-${tabela.cor}-700` : "text-gray-900"}`}>
                        {tabela.nome}
                      </p>
                      <p className="text-sm text-gray-500">{tabela.descricao}</p>
                      {tabelaSugerida === tabela.id && clinica.tabela_preco_id === tabela.id && (
                        <span className="inline-block mt-1 text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                          Sugerido
                        </span>
                      )}
                    </div>
                  </div>
                </label>
              ))}
            </div>

            {/* Preço Personalizado */}
            {clinica.tabela_preco_id === 4 && (
              <div className="bg-green-50 border border-green-200 rounded-xl p-5">
                <h3 className="font-medium text-green-900 mb-3 flex items-center gap-2">
                  <Calculator className="w-4 h-4" />
                  Preço Personalizado (Negociado)
                </h3>
                <p className="text-sm text-green-700 mb-4">
                  Use esta opção para cidades distantes como Aracati, onde o valor é negociado caso a caso.
                </p>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-green-800 mb-1">
                      Valor Base do Atendimento
                    </label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-green-600">R$</span>
                      <input
                        type="text"
                        value={clinica.preco_personalizado_base}
                        onChange={(e) => setClinica({...clinica, preco_personalizado_base: e.target.value})}
                        className="w-full pl-10 pr-3 py-2 border border-green-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        placeholder="0,00"
                      />
                    </div>
                    <p className="text-xs text-green-600 mt-1">Valor mínimo do atendimento</p>
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-green-800 mb-1">
                      Valor por KM Adicional
                    </label>
                    <div className="relative">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-green-600">R$</span>
                      <input
                        type="text"
                        value={clinica.preco_personalizado_km}
                        onChange={(e) => setClinica({...clinica, preco_personalizado_km: e.target.value})}
                        className="w-full pl-10 pr-3 py-2 border border-green-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        placeholder="0,00"
                      />
                    </div>
                    <p className="text-xs text-green-600 mt-1">Valor cobrado por km de distância</p>
                  </div>
                </div>
                
                <div className="mt-4">
                  <label className="block text-sm font-medium text-green-800 mb-1">
                    Observações sobre o Preço Negociado
                  </label>
                  <textarea
                    value={clinica.observacoes_preco}
                    onChange={(e) => setClinica({...clinica, observacoes_preco: e.target.value})}
                    rows={3}
                    className="w-full px-3 py-2 border border-green-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
                    placeholder="Ex: Preço negociado para atendimento em Aracati. Valor fixo de R$ 800,00 + R$ 2,00/km após 150km."
                  />
                </div>
                
                {/* Resumo do cálculo */}
                {(clinica.preco_personalizado_base || clinica.preco_personalizado_km) && (
                  <div className="mt-4 p-3 bg-white rounded-lg border border-green-200">
                    <p className="text-sm text-green-800">
                      <strong>Exemplo de cálculo:</strong>
                      <br />
                      Base: {formatarValor(clinica.preco_personalizado_base)}
                      <br />
                      + KM: {formatarValor(clinica.preco_personalizado_km)}/km
                    </p>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Precos negociados por servico */}
          <section className="fc-clinic-form-card fc-clinic-form-card-negotiated">
            <h2 className="text-lg font-semibold text-gray-900 mb-2 flex items-center gap-2">
              <Percent className="w-5 h-5 text-emerald-600" />
              Precos negociados por servico
            </h2>
            <p className="text-sm text-gray-500 mb-4">
              Defina valores especiais para esta clinica. Campos em branco usam o valor padrao da tabela.
            </p>

            {loadingPrecosServicos ? (
              <div className="py-10 text-center text-sm text-gray-500">Carregando precos por servico...</div>
            ) : precosServicos.length === 0 ? (
              <div className="py-10 text-center text-sm text-gray-500">Nenhum servico ativo encontrado.</div>
            ) : (
              <div className="overflow-x-auto border rounded-lg">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="text-left px-4 py-3 font-medium text-gray-700">Servico</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-700">Base Comercial</th>
                      <th className="text-right px-4 py-3 font-medium text-gray-700">Base Plantao</th>
                      <th className="text-right px-4 py-3 font-medium text-emerald-700">Negociado Comercial</th>
                      <th className="text-right px-4 py-3 font-medium text-emerald-700">Negociado Plantao</th>
                    </tr>
                  </thead>
                  <tbody>
                    {precosServicos.map((row) => (
                      <tr key={row.servico_id} className="border-t">
                        <td className="px-4 py-3 text-gray-900">{row.servico_nome}</td>
                        <td className="px-4 py-3 text-right text-gray-600">R$ {formatarValor(row.preco_base_comercial)}</td>
                        <td className="px-4 py-3 text-right text-gray-600">R$ {formatarValor(row.preco_base_plantao)}</td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end">
                            <input
                              type="text"
                              value={row.preco_negociado_comercial}
                              onChange={(e) =>
                                atualizarPrecoServico(row.servico_id, "preco_negociado_comercial", e.target.value)
                              }
                              className="w-32 px-2 py-1 border border-emerald-200 rounded text-right focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                              placeholder="padrao"
                            />
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end">
                            <input
                              type="text"
                              value={row.preco_negociado_plantao}
                              onChange={(e) =>
                                atualizarPrecoServico(row.servico_id, "preco_negociado_plantao", e.target.value)
                              }
                              className="w-32 px-2 py-1 border border-emerald-200 rounded text-right focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
                              placeholder="padrao"
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <EnderecoFiscalCard clinicaId={Number.parseInt(clinicaId, 10)} />

          <ClinicaPortalAccessCard
            clinicaId={Number.parseInt(clinicaId, 10)}
            clinicaNome={clinica.nome || "Clinica parceira"}
            defaultWhatsapp={clinica.whatsapps.find((numero) => numero.trim()) || clinica.telefone || ""}
            defaultEmail={clinica.email || ""}
          />

          {/* Resumo */}
          <aside className="fc-clinic-form-summary">
            <h3 className="text-sm font-medium text-gray-700 mb-2">Resumo da Configuração</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Tabela aplicada:</span>
                <span className={`ml-2 font-medium ${tabelaAtual ? `text-${tabelaAtual.cor}-600` : "text-gray-900"}`}>
                  {tabelaAtual?.nome || "Fortaleza"}
                </span>
              </div>
              <div>
                <span className="text-gray-500">Cidade:</span>
                <span className="ml-2 font-medium">{clinica.cidade || "Não informada"}</span>
              </div>
            </div>
          </aside>
          
          {/* Botões */}
          <div className="fc-clinic-form-actions">
            <button
              type="button"
              onClick={() => router.push("/clinicas")}
              className="fc-clinic-form-cancel"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={handleSalvar}
              disabled={saving || !clinica.nome}
              className="fc-clinic-form-primary"
            >
              <Save className="w-4 h-4" />
              {saving ? "Salvando..." : "Salvar Alterações"}
            </button>
          </div>
        </div>

        <ManualPinModal
          isOpen={showManualPinModal}
          initialLat={clinica.latitude}
          initialLng={clinica.longitude}
          onClose={() => setShowManualPinModal(false)}
          onConfirm={aplicarPinManual}
        />


        {/* Modal de Confirmação de Exclusão */}
        {showDeleteModal && (
          <div className="fc-clinic-form-modal-backdrop" role="presentation">
            <div className="fc-clinic-form-modal" role="dialog" aria-modal="true" aria-labelledby="clinic-delete-title">
              <div className="flex items-center gap-3 mb-4">
                <div className="fc-clinic-form-modal-icon">
                  <AlertTriangle className="w-6 h-6 text-red-600" />
                </div>
                <div>
                  <h3 id="clinic-delete-title" className="text-lg font-semibold text-gray-900">Confirmar exclusão</h3>
                  <p className="text-sm text-gray-500">
                    Tem certeza que deseja excluir esta clínica? Esta ação não pode ser desfeita.
                  </p>
                </div>
              </div>
              
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowDeleteModal(false)}
                  className="fc-clinic-form-cancel"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleExcluir}
                  className="fc-clinic-form-delete-confirm"
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
