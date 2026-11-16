"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { calcularIdadeComFonte, patientAgeForm, patientAgePayload, importedPatientAge, type PatientAgeValue } from "@/lib/paciente-idade";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import DashboardLayout from "../../../layout-dashboard";
import api from "@/lib/axios";
import {
  getLaudoEditPath,
  TIPO_LAUDO_ECOCARDIOGRAMA,
  TIPO_LAUDO_PRESSAO_ARTERIAL,
  TIPO_LAUDO_ULTRASSOM_ABDOMINAL,
} from "@/lib/laudos";
import {
  addRacaCustomPorEspecie,
  getRacaOptions,
  loadRacasCustomPorEspecie,
  saveRacasCustomPorEspecie,
} from "@/lib/racas";
import XmlUploader from "../../components/XmlUploader";
import ImageHeaderUploader from "../../components/ImageHeaderUploader";
import ImageUploader from "../../components/ImageUploader";
import EchoFinalReview from "../../components/EchoFinalReview";
import { buildEchoFinalReviewIssues } from "@/lib/echo-final-review";
import { echoEditorImageSelection, echoPreviewSnapshotKey, navigateEchoFinalReview } from "@/lib/echo-preview-request";
import ImagePreviewModal from "../../components/ImagePreviewModal";
import EcoStudyImportUploader from "../../components/EcoStudyImportUploader";
import EcocardiogramaEstruturadoEditor from "../../components/EcocardiogramaEstruturadoEditor";
import EcocardiogramaEstruturadoBiblioteca from "../../components/EcocardiogramaEstruturadoBiblioteca";
import EchoVoiceAssistant from "../../components/EchoVoiceAssistant";
import EchoUnitReview from "../../components/EchoUnitReview";
import EchoNarrativeConsistencyNotice from "../../components/EchoNarrativeConsistencyNotice";
import EchoOutflowMeasurements from "../../components/EchoOutflowMeasurements";
import { mapImportedEchoMeasurements, updateEchoOutflowMeasurement } from "@/lib/echo-outflow-editor";
import { ECHO_OUTFLOW_KEYS } from "@/lib/echo-outflow";
import FelineWaveReview from "../../components/FelineWaveReview";
import { discardFelineFusedMeasurements, isEchoDiastolicRatioCalculated, updateFelineDiastolicMeasurement } from "@/lib/echo-feline-wave-review";
import { calculateCanine2DNormalizedLVIDd, getCanine2DReference, type Echo2DView } from "@/lib/echo-2d-reference";
import { ArrowLeft, Save, User, Activity, Heart, BookOpen, Settings, Image as ImageIcon, Minus, Plus, FolderOpen, GripVertical, X } from "lucide-react";
import { ReferenciaComparison } from "../../components/ReferenciaComparison";
import {
  criarEcocardiogramaEstruturadoInicial,
  derivarLegadoDeEcocardiogramaEstruturado,
  EcocardiogramaEstruturadoPersistido,
  extrairQualitativaEcoDaDescricao,
  hidratarEcocardiogramaEstruturadoDeLegado,
  montarDescricaoEcocardiograma,
  normalizarEcocardiogramaEstruturado,
  removerPresetDiastolicoFelino,
  resolverTextoClinicoNaEdicao,
  serializarEcocardiogramaEstruturado,
  temPresetDiastolicoFelinoAplicado,
} from "@/lib/ecocardiograma-estruturado";
import { listarTodasClinicas } from "@/lib/clinicas";
import { extrairIdadePaciente, normalizarSexoPaciente, parsePesoKg } from "@/lib/paciente";
import {
  calculateLeftAtrialFractionalShortening,
  deriveAutomaticEchoMeasurements,
  hasAnyMeasurement,
  LV_2D_KEYS,
  LV_M_MODE_KEYS,
  parseStoredEchoMeasurements,
} from "@/lib/echo-derived-measurements";
import { criarMensagemAlertaSalvamentoEcocardiograma } from "@/lib/ecocardiograma-save-alert";
import { operationalTodayDateInput } from "@/lib/calendar-date";
import { confirmedUnitKey, echoLengthInMm, echoLengthInputLabel } from "@/lib/echo-unit-provenance";
import { isFelineEchoSpecies, normalizeEchoSpecies } from "@/lib/echo-species";
import { useEchoMeasurements } from "../../hooks/useEchoMeasurements";
import { useEchoEditorDraft } from "../../hooks/useEchoEditorDraft";
import EchoDraftStatus from "../../components/EchoDraftStatus";
import { cloneEchoEditorDraftSnapshot, serializeDraftImages, type EchoEditorDraftSnapshot } from "@/lib/echo-editor-draft";

// Componente de input de medida com botões +/-
interface MedidaInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  reference?: string;
  readOnly?: boolean;
}

function MedidaInput({ label, value, onChange, reference, readOnly = false }: MedidaInputProps) {
  const handleDecrement = () => {
    if (readOnly) return;
    const numValue = parseFloat(value) || 0;
    if (numValue > 0) {
      onChange((numValue - 0.01).toFixed(2));
    }
  };

  const handleIncrement = () => {
    if (readOnly) return;
    const numValue = parseFloat(value) || 0;
    onChange((numValue + 0.01).toFixed(2));
  };

  return (
    <div className="space-y-1">
      <label className="block text-xs text-gray-600 leading-tight">
        {label}
      </label>
      {reference && (
        <span className="text-[10px] text-gray-400">{reference}</span>
      )}
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={value}
          onChange={(e) => {
            if (!readOnly) onChange(e.target.value);
          }}
          readOnly={readOnly}
          className="flex-1 px-2 py-1.5 bg-blue-50 border-0 rounded text-sm text-gray-700 focus:ring-1 focus:ring-teal-500"
          placeholder="0,00"
        />
        {!readOnly && (
          <>
            <button
              onClick={handleDecrement}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
              type="button"
            >
              <Minus className="w-3 h-3" />
            </button>
            <button
              onClick={handleIncrement}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
              type="button"
            >
              <Plus className="w-3 h-3" />
            </button>
          </>
        )}
      </div>
    </div>
  );
}

const parseNumero = (valor?: string): number | null => {
  if (!valor) return null;
  const numero = Number(valor.toString().replace(",", ".").trim());
  return Number.isFinite(numero) ? numero : null;
};

const formatar2Casas = (valor: number): string => valor.toFixed(2);

const parseInteiroPositivo = (valor?: string): number | null => {
  if (!valor) return null;
  const numero = Math.round(Number(valor.toString().replace(",", ".").trim()));
  if (!Number.isFinite(numero) || numero <= 0) return null;
  return numero;
};

const OPCOES_MANGUITO = [
  "Manguito 01",
  "Manguito 02",
  "Manguito 03",
  "Manguito 04",
  "Manguito 05",
  "Manguito 06",
  "Outro",
];

const OPCOES_MEMBRO = [
  "Membro anterior direito",
  "Membro anterior esquerdo",
  "Membro posterior direito",
  "Membro posterior esquerdo",
  "Cauda",
  "Outro",
];

const OPCOES_DECUBITO = [
  "Decubito lateral direito",
  "Decubito lateral esquerdo",
  "Decubito esternal",
  "Decubito dorsal",
  "Em estacao",
  "Outro",
];

const OPCOES_RITMO = [
  "Sinusal",
  "Arritmia sinusal",
  "Fibrilacao atrial",
  "Taquicardia sinusal",
  "Bradicardia sinusal",
];

const OPCOES_ESTADO_PACIENTE = [
  "Calmo",
  "Agitado",
  "Ofegante",
  "Dispneico",
  "Sedado",
];

const incluirOpcaoAtual = (opcoes: string[], valorAtual: string) =>
  valorAtual && !opcoes.includes(valorAtual) ? [valorAtual, ...opcoes] : opcoes;

interface Clinica {
  id: number;
  nome: string;
}

interface ParceiroVeterinario {
  id: number;
  nome_exibicao: string;
  email_login?: string | null;
  cidade_base?: string | null;
  estado_base?: string | null;
  crmv?: string | null;
}

interface Imagem {
  id: number;
  nome: string;
  ordem: number;
  descricao: string;
  url: string;
  dataUrl?: string;
  tamanho: number;
  incluir_no_pdf: boolean;
}

interface Laudo {
  editor_revision?: string;
  id: number;
  paciente_id: number;
  paciente?: Paciente;
  tipo: string;
  titulo: string;
  descricao: string;
  diagnostico: string;
  observacoes: string;
  status: string;
  data_laudo: string;
  data_exame?: string;
  clinic_id?: number;
  clinica?: string;
  veterinario_parceiro_id?: number | null;
  veterinario_parceiro_nome?: string | null;
  veterinario_parceiro_crmv?: string | null;
  medico_solicitante?: string;
  imagens?: Imagem[];
  pressao_arterial?: {
    pas_1?: number | null;
    pas_2?: number | null;
    pas_3?: number | null;
    pas_media?: number | null;
    metodo?: string;
    manguito?: string;
    membro?: string;
    decubito?: string;
    obs_extra?: string;
  } | null;
  ecocardiograma_cabecalho?: {
    ritmo?: string | null;
    estado?: string | null;
    fc?: string | null;
  } | null;
  criado_por_nome: string;
}

interface Paciente extends PatientAgeValue {
  id: number;
  nome: string;
  especie: string;
  raca: string;
  sexo: string;
  peso_kg: number | null;
  idade: string;
  tutor: string;
  telefone: string;
  tutor_id?: number;
}

interface DadosExame {
  paciente: PatientAgeValue & {
    nome: string;
    tutor: string;
    raca: string;
    especie: string;
    peso: string;
    idade: string;
    sexo: string;
    telefone: string;
    data_exame: string;
  };
  medidas: Record<string, number | string>;
  clinica: string | { id: number; nome: string };
  veterinario_solicitante: string;
  fc: string;
}

interface EcocardiogramaCabecalho {
  ritmo: string;
  estado: string;
  fc: string;
}

const readEditorOwner = (): number | null => {
  try {
    const user = JSON.parse(localStorage.getItem("user") || "null");
    const id = Number(user?.id ?? user?.user_id);
    return Number.isSafeInteger(id) && id > 0 ? id : null;
  } catch { return null; }
};

const imagePreview = async (url: string, signal?: AbortSignal): Promise<string> => {
  const response = await api.get(url, { responseType: "blob", timeout: 10_000, signal });
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Prévia indisponível"));
    reader.readAsDataURL(response.data);
  });
};

export default function EditarLaudoPage() {
  const router = useRouter();
  const routeParams = useParams<{ id?: string | string[] }>();
  const laudoId = Array.isArray(routeParams.id) ? routeParams.id[0] : routeParams.id;
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [laudo, setLaudo] = useState<Laudo | null>(null);
  const [paciente, setPaciente] = useState<Paciente | null>(null);

  // Abas
  const [aba, setAba] = useState<"paciente" | "medidas" | "qualitativa" | "biblioteca" | "imagens" | "pressao" | "referencias">("paciente");

  // Form state
  const [titulo, setTitulo] = useState("");
  const [diagnostico, setDiagnostico] = useState("");
  const [observacoes, setObservacoes] = useState("");
  const [descricao, setDescricao] = useState("");
  const [status, setStatus] = useState("Rascunho");

  // Medidas
  const { measurements: medidas, setMeasurements: setMedidas, importMeasurements: importarMedidas, replaceMeasurements: substituirMedidas, exportState, restoreState } = useEchoMeasurements();

  // Qualitativa
  const [qualitativa, setQualitativa] = useState({
    valvas: "",
    camaras: "",
    funcao: "",
    pericardio: "",
    vasos: "",
    ad_vd: "",
  });
  const [ecocardiogramaEstruturado, setEcocardiogramaEstruturado] = useState(
    criarEcocardiogramaEstruturadoInicial()
  );
  const [qualitativaEstruturadaAplicada, setQualitativaEstruturadaAplicada] = useState(false);
  const [conclusaoEstruturadaAplicada, setConclusaoEstruturadaAplicada] = useState(false);
  const [ecocardiogramaCabecalho, setEcocardiogramaCabecalho] = useState<EcocardiogramaCabecalho>({
    ritmo: "",
    estado: "",
    fc: "",
  });

  const [pressaoArterial, setPressaoArterial] = useState({
    pas_1: "",
    pas_2: "",
    pas_3: "",
    manguito_select: "Manguito 02",
    manguito_outro: "",
    membro_select: "Membro anterior esquerdo",
    membro_outro: "",
    decubito_select: "Decubito lateral direito",
    decubito_outro: "",
    obs_extra: "",
  });

  // Dados do paciente (editáveis)
  const [pacienteForm, setPacienteForm] = useState({
    nome: "",
    especie: "Canina",
    raca: "",
    sexo: "Macho",
    peso: "",
    ...patientAgeForm(),
    tutor: "",
    telefone: "",
    data_exame: operationalTodayDateInput(),
  });
  const originalForm = useRef(pacienteForm);
  const [novaRaca, setNovaRaca] = useState("");
  const [racasCustomPorEspecie, setRacasCustomPorEspecie] = useState<Record<string, string[]>>({});
  const [racasLoaded, setRacasLoaded] = useState(false);
  const opcoesRaca = getRacaOptions(
    pacienteForm.especie,
    pacienteForm.raca,
    racasCustomPorEspecie[pacienteForm.especie] || [],
  );

  const handleAdicionarRaca = () => {
    const racaDigitada = novaRaca.trim();
    if (!racaDigitada) return;

    const racaExistente =
      opcoesRaca.find((item) => item.toLowerCase() === racaDigitada.toLowerCase()) || racaDigitada;

    setRacasCustomPorEspecie((prev) => addRacaCustomPorEspecie(prev, pacienteForm.especie, racaDigitada));
    setPacienteForm((prev) => ({ ...prev, raca: racaExistente }));
    setNovaRaca("");
  };

  // Clínica
  const [clinicaId, setClinicaId] = useState<string>("");
  const [clinicaNome, setClinicaNome] = useState<string>("");
  const [clinicas, setClinicas] = useState<Clinica[]>([]);
  const [veterinarioParceiroId, setVeterinarioParceiroId] = useState<string>("");
  const [parceirosVeterinarios, setParceirosVeterinarios] = useState<ParceiroVeterinario[]>([]);
  const [medicoSolicitante, setMedicoSolicitante] = useState("");

  // Imagens
  const [imagens, setImagens] = useState<Imagem[]>([]);
  const [imagensTemp, setImagensTemp] = useState<any[]>([]);
  const [imageUploadActive, setImageUploadActive] = useState(false);
  const [previewImagemIndex, setPreviewImagemIndex] = useState<number | null>(null);
  const [draggedImagemIndex, setDraggedImagemIndex] = useState<number | null>(null);
  const [sessionId, setSessionId] = useState<string>(() => Math.random().toString(36).substring(2, 15));
  const [imagensRemovidas, setImagensRemovidas] = useState<number[]>([]);
  const [sourceRevision, setSourceRevision] = useState("");
  const [sourceConflict, setSourceConflict] = useState(false);
  const [draftUserId, setDraftUserId] = useState<number | null>(null);
  const [sessionChanged, setSessionChanged] = useState(false);
  const ownerRef = useRef<number | null>(null);
  const loadGeneration = useRef(0);
  const updateInProgress = useRef(false);
  const [leaving, setLeaving] = useState(false);
  const [draftNotice, setDraftNotice] = useState<string | null>(null);
  const [submission, setSubmission] = useState<EchoEditorDraftSnapshot["submission"]>();
  const navigationHandler = useRef<(href: string) => Promise<void>>(async () => {});
  const routeIdentity = useRef(laudoId);
  routeIdentity.current = laudoId;
  const uploadSessionIdentity = useRef(sessionId);
  uploadSessionIdentity.current = sessionId;
  const renderContext = { laudoId, generation: loadGeneration.current, owner: draftUserId, sessionId };
  const isCurrentEditorContext = () => renderContext.laudoId === routeIdentity.current
    && renderContext.generation === loadGeneration.current && renderContext.owner === readEditorOwner()
    && renderContext.sessionId === uploadSessionIdentity.current;
  const draftApplies = (laudo?.tipo || "").toLowerCase() === TIPO_LAUDO_ECOCARDIOGRAMA;

  const salvarConfiguracaoImagens = async (novasImagens: Imagem[], anteriores: Imagem[]) => {
    if (!isCurrentEditorContext()) return;
    setImagens(novasImagens);
    if (draftApplies) return;
    if (!laudoId) return;
    try {
      await api.put(`/imagens/laudo/${laudoId}/configuracao`, {
        imagens: novasImagens.map((imagem, index) => ({
          id: imagem.id,
          ordem: index,
          incluir_no_pdf: imagem.incluir_no_pdf !== false,
          descricao: imagem.descricao,
        })),
      });
    } catch (error) {
      console.error("Erro ao salvar configuração das imagens:", error);
      setImagens(anteriores);
      alert("Não foi possível salvar a ordem ou a seleção das imagens para o PDF.");
    }
  };

  const moverImagemPersistida = (origem: number, destino: number) => {
    if (origem === destino || origem < 0 || destino < 0 || destino >= imagens.length) return;
    const anteriores = imagens;
    const reordenadas = [...imagens];
    const [movida] = reordenadas.splice(origem, 1);
    reordenadas.splice(destino, 0, movida);
    void salvarConfiguracaoImagens(
      reordenadas.map((imagem, index) => ({ ...imagem, ordem: index })),
      anteriores,
    );
  };

  const alternarImagemNoPdf = (index: number) => {
    const anteriores = imagens;
    const atualizadas = imagens.map((imagem, atual) =>
      atual === index ? { ...imagem, incluir_no_pdf: imagem.incluir_no_pdf === false } : imagem
    );
    void salvarConfiguracaoImagens(atualizadas, anteriores);
  };

  const draftSnapshot = useMemo<EchoEditorDraftSnapshot>(() => ({
    schema_version: 1, editor: "existing-echo",
    source: { laudo_id: Number(laudoId), editor_revision: sourceRevision },
    existing: {
      qualitativaAplicada: qualitativaEstruturadaAplicada,
      conclusaoAplicada: conclusaoEstruturadaAplicada,
      imagensPersistidas: serializeDraftImages(imagens.map((image) => ({ ...image,
        id: String(image.id), serverId: image.id, uploaded: true, persisted: true,
        incluirNoPdf: image.incluir_no_pdf !== false }))),
      imagensRemovidas,
    },
    paciente: { ...pacienteForm, id: paciente?.id, tutor_id: paciente?.tutor_id },
    measurementState: exportState(), qualitativa,
    conteudo: { titulo, diagnostico, observacoes, descricao, status, veterinarioParceiroId, medicoSolicitante },
    ecocardiogramaCabecalho, ecocardiogramaEstruturado, pressaoArterial,
    clinicaId, clinicaNome, veterinario: medicoSolicitante, agendamentoVinculadoId: null,
    sessionId, draftLaudoId: Number(laudoId), imagens: serializeDraftImages(imagensTemp), aba, submission,
  }), [laudoId, sourceRevision, qualitativaEstruturadaAplicada, conclusaoEstruturadaAplicada,
    imagens, imagensRemovidas, pacienteForm, paciente, exportState, qualitativa, titulo, diagnostico,
    observacoes, descricao, status, veterinarioParceiroId, medicoSolicitante, ecocardiogramaCabecalho,
    ecocardiogramaEstruturado, pressaoArterial, clinicaId, clinicaNome, sessionId, imagensTemp, aba, submission]);
  const snapshotRef = useRef(draftSnapshot);
  snapshotRef.current = draftSnapshot;
  const restoreDraft = async (snapshot: EchoEditorDraftSnapshot) => {
    const generation = loadGeneration.current;
    const owner = ownerRef.current;
    if (snapshot.editor !== "existing-echo" || snapshot.source?.laudo_id !== Number(laudoId) || !snapshot.existing) {
      throw new Error("O rascunho não corresponde a este laudo.");
    }
    const available = snapshot.imagens.some((image) => image.uploaded && image.tempId)
      ? (await api.get(`/imagens/temp/session/${encodeURIComponent(snapshot.sessionId)}`)).data.items || [] : [];
    const ids = new Set(available.map((image: { id: number }) => image.id));
    const tempImages = await Promise.all(snapshot.imagens.map(async (image) => {
      if (!image.uploaded || !image.tempId || !ids.has(image.tempId)) {
        return { ...image, dataUrl: "", uploaded: false, tempId: undefined, requerReenvio: true };
      }
      let dataUrl = "";
      try { dataUrl = await imagePreview(`/imagens/temp/${image.tempId}`); } catch { /* Preview only. */ }
      return { ...image, dataUrl, requerReenvio: false };
    }));
    const existingImages = snapshot.existing.imagensPersistidas.map((image) => {
      const official = laudo?.imagens?.find((item) => item.id === image.serverId);
      return { id: image.serverId!, nome: image.nome, ordem: image.ordem, descricao: image.descricao,
        tamanho: image.tamanho, incluir_no_pdf: image.incluirNoPdf !== false,
        url: official?.url || `/imagens/${image.serverId}`,
        dataUrl: imagens.find((item) => item.id === image.serverId)?.dataUrl };
    });
    if (generation !== loadGeneration.current || owner !== readEditorOwner()) {
      throw new Error("A sessão mudou durante a recuperação. Reabra o editor.");
    }
    const { id: _id, tutor_id: _tutor, ...form } = snapshot.paciente;
    void _id; void _tutor;
    setPacienteForm(form as typeof pacienteForm);
    restoreState(snapshot.measurementState, String(snapshot.paciente.especie || ""));
    setQualitativa(snapshot.qualitativa as typeof qualitativa);
    setTitulo(snapshot.conteudo.titulo); setDiagnostico(snapshot.conteudo.diagnostico);
    setObservacoes(snapshot.conteudo.observacoes); setDescricao(snapshot.conteudo.descricao);
    setStatus(snapshot.conteudo.status); setVeterinarioParceiroId(snapshot.conteudo.veterinarioParceiroId);
    setMedicoSolicitante(snapshot.conteudo.medicoSolicitante);
    setEcocardiogramaEstruturado(snapshot.ecocardiogramaEstruturado);
    setQualitativaEstruturadaAplicada(snapshot.existing.qualitativaAplicada);
    setConclusaoEstruturadaAplicada(snapshot.existing.conclusaoAplicada);
    setEcocardiogramaCabecalho(snapshot.ecocardiogramaCabecalho);
    setPressaoArterial(snapshot.pressaoArterial as typeof pressaoArterial);
    setClinicaId(snapshot.clinicaId); setClinicaNome(snapshot.clinicaNome);
    setImagens(existingImages); setImagensRemovidas(snapshot.existing.imagensRemovidas);
    setSessionId(snapshot.sessionId); setImagensTemp(tempImages); setSubmission(snapshot.submission);
    setSourceConflict(snapshot.source.editor_revision !== laudo?.editor_revision);
    setSourceRevision(snapshot.source.editor_revision);
    if (["paciente", "medidas", "qualitativa", "biblioteca", "imagens", "pressao", "referencias"].includes(snapshot.aba || "")) {
      setAba(snapshot.aba as typeof aba);
    }
    setDraftNotice(tempImages.some((image) => image.requerReenvio) ? "Há imagens temporárias para reenviar antes de atualizar." : null);
    return { ...snapshot, imagens: serializeDraftImages(tempImages) };
  };
  const editorDraft = useEchoEditorDraft({ enabled: draftApplies && laudo?.id === Number(laudoId) && !loading && !sessionChanged && Boolean(sourceRevision),
    userId: draftUserId, contextKey: `edit:laudo:${laudoId}`, snapshot: draftSnapshot, onRestore: restoreDraft });
  const opcoesRitmoPaciente = incluirOpcaoAtual(OPCOES_RITMO, ecocardiogramaCabecalho.ritmo);
  const opcoesEstadoPaciente = incluirOpcaoAtual(
    OPCOES_ESTADO_PACIENTE,
    ecocardiogramaCabecalho.estado,
  );

  // Mensagem de sucesso
  const [mensagemSucesso, setMensagemSucesso] = useState<string | null>(null);

  useEffect(() => {
    setRacasCustomPorEspecie(loadRacasCustomPorEspecie());
    setRacasLoaded(true);
  }, []);

  useEffect(() => {
    if (!racasLoaded) return;
    saveRacasCustomPorEspecie(racasCustomPorEspecie);
  }, [racasLoaded, racasCustomPorEspecie]);

  const handleEcocardiogramaEstruturadoChange = (next: EcocardiogramaEstruturadoPersistido) => {
    if (updateInProgress.current || !isCurrentEditorContext()) return;
    const chavesAlteradas = Object.keys({ ...ecocardiogramaEstruturado.textos, ...next.textos })
      .filter((key) => ecocardiogramaEstruturado.textos[key] !== next.textos[key]);
    const ativadoAgora = next.usar_no_laudo && !ecocardiogramaEstruturado.usar_no_laudo;
    setEcocardiogramaEstruturado(next);
    if (!next.usar_no_laudo || (!chavesAlteradas.length && !ativadoAgora)) return;
    const legado = derivarLegadoDeEcocardiogramaEstruturado(next);
    if (ativadoAgora || chavesAlteradas.some((key) => key !== "conclusao")) {
      setQualitativa(legado.qualitativa);
      setQualitativaEstruturadaAplicada(true);
    }
    if (ativadoAgora || chavesAlteradas.includes("conclusao")) {
      setDiagnostico(legado.conclusao);
      setConclusaoEstruturadaAplicada(true);
    }
  };

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    const owner = readEditorOwner();
    if (ownerRef.current !== null && ownerRef.current !== owner) { setSessionChanged(true); return; }
    ownerRef.current = owner; setDraftUserId(owner); setLoading(true);
    setSessionId(crypto.randomUUID()); setImagensTemp([]); setImagensRemovidas([]);
    setImagens([]); setSubmission(undefined); setSourceRevision(""); setSourceConflict(false);
    setImageUploadActive(false); setDraftNotice(null); setLaudo(null); setPaciente(null);
    const checkOwner = () => {
      if (owner !== readEditorOwner()) { ++loadGeneration.current; controller.abort(); setSessionChanged(true); }
    };
    window.addEventListener("storage", checkOwner); window.addEventListener("focus", checkOwner);
    void carregarLaudo(generation, owner, controller.signal);
    void carregarClinicas();
    return () => {
      ++loadGeneration.current; controller.abort();
      window.removeEventListener("storage", checkOwner); window.removeEventListener("focus", checkOwner);
    };
  }, [router, laudoId]);

  useEffect(() => {
    // Refaz a lista quando a clínica do laudo muda: a ordem depende dela.
    carregarParceirosVeterinarios(clinicaId || undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clinicaId]);

  useEffect(() => {
    const aoNivelAp = echoLengthInMm(medidas, "Ao_nivel_AP");
    const arteriaPulmonar = echoLengthInMm(medidas, "AP");
    const divedMm = echoLengthInMm(medidas, "DIVEd");
    const peso = parsePesoKg(pacienteForm.peso);

    const apAoCalculado =
      aoNivelAp !== null && aoNivelAp > 0 && arteriaPulmonar !== null && arteriaPulmonar > 0
        ? formatar2Casas(arteriaPulmonar / aoNivelAp)
        : null;

    const divedNormalizadoCalculado =
      normalizeEchoSpecies(pacienteForm.especie) === "Canina" && divedMm !== null && divedMm > 0 && peso !== null && peso > 0
        ? formatar2Casas((divedMm / 10.0) / Math.pow(peso, 0.294))
        : null;

    const atualizacoes: Record<string, string> = {};
    if (apAoCalculado !== null && medidas["AP_Ao"] !== apAoCalculado) {
      atualizacoes.AP_Ao = apAoCalculado;
    }
    if (divedNormalizadoCalculado !== null && medidas["DIVEd_normalizado"] !== divedNormalizadoCalculado) {
      atualizacoes.DIVEd_normalizado = divedNormalizadoCalculado;
    }
    const automaticas = deriveAutomaticEchoMeasurements(medidas, pacienteForm.peso, pacienteForm.especie, pacienteForm.idade);
    Object.entries(automaticas).forEach(([key, value]) => {
      if (medidas[key] !== value) atualizacoes[key] = value;
    });

    if (Object.keys(atualizacoes).length > 0) {
      setMedidas((prev) => ({
        ...prev,
        ...atualizacoes,
      }));
    }
  }, [medidas, pacienteForm.peso, pacienteForm.especie, pacienteForm.idade]);

  useEffect(() => {
    const resolved = calcularIdadeComFonte(pacienteForm, pacienteForm.data_exame);
    if (resolved !== null && resolved !== pacienteForm.idade) {
      setPacienteForm((prev) => ({ ...prev, idade: resolved }));
    }
  }, [pacienteForm.idade_fonte, pacienteForm.idade_informada, pacienteForm.idade_referencia, pacienteForm.data_nascimento, pacienteForm.data_exame]);

  const laudoEhPressao = (laudo?.tipo || "").toLowerCase() === TIPO_LAUDO_PRESSAO_ARTERIAL;

  const pasMediaCalculada = (() => {
    const valores = [
      parseInteiroPositivo(pressaoArterial.pas_1),
      parseInteiroPositivo(pressaoArterial.pas_2),
      parseInteiroPositivo(pressaoArterial.pas_3),
    ].filter((valor): valor is number => valor !== null);
    if (valores.length === 0) return null;
    return Math.round(valores.reduce((acc, valor) => acc + valor, 0) / valores.length);
  })();

  const montarPayloadPressao = () => {
    const manguitoFinal =
      pressaoArterial.manguito_select === "Outro"
        ? pressaoArterial.manguito_outro.trim()
        : pressaoArterial.manguito_select;
    const membroFinal =
      pressaoArterial.membro_select === "Outro"
        ? pressaoArterial.membro_outro.trim()
        : pressaoArterial.membro_select;
    const decubitoFinal =
      pressaoArterial.decubito_select === "Outro"
        ? pressaoArterial.decubito_outro.trim()
        : pressaoArterial.decubito_select;

    const payload = {
      pas_1: parseInteiroPositivo(pressaoArterial.pas_1),
      pas_2: parseInteiroPositivo(pressaoArterial.pas_2),
      pas_3: parseInteiroPositivo(pressaoArterial.pas_3),
      pas_media: pasMediaCalculada,
      metodo: "Doppler",
      manguito: manguitoFinal,
      membro: membroFinal,
      decubito: decubitoFinal,
      obs_extra: pressaoArterial.obs_extra.trim(),
    };

    const temDados = Boolean(payload.pas_1 || payload.pas_2 || payload.pas_3 || payload.pas_media);

    return temDados ? payload : null;
  };

  const carregarClinicas = async () => {
    try {
      const items = await listarTodasClinicas<Clinica>();
      setClinicas(items);
    } catch (error) {
      console.error("Erro ao carregar clínicas:", error);
    }
  };

  const carregarParceirosVeterinarios = async (clinicaSelecionada?: string) => {
    try {
      // Com a clínica do laudo, quem atende nela vem no topo da lista.
      const response = await api.get("/portal/parceiros/veterinarios/opcoes", {
        params: {
          limit: 100,
          ...(clinicaSelecionada ? { clinica_id: Number(clinicaSelecionada) } : {}),
        },
      });
      setParceirosVeterinarios(Array.isArray(response.data?.items) ? response.data.items : []);
    } catch (error) {
      console.error("Erro ao carregar veterinários parceiros:", error);
    }
  };

  const handleDadosImportados = (dados: DadosExame) => {
    if (updateInProgress.current || !isCurrentEditorContext() || sessionChanged || (draftApplies && (submission || editorDraft.blocked))) return;

    if (dados.paciente) {
      const pesoImportado = parsePesoKg(dados.paciente.peso);
      setPacienteForm((anterior) => ({
        ...anterior,
        nome: dados.paciente.nome || anterior.nome,
        especie: dados.paciente.especie || anterior.especie || "Canina",
        raca: dados.paciente.raca || anterior.raca,
        sexo:
          normalizarSexoPaciente(dados.paciente.sexo || anterior.sexo || "Macho") || "Macho",
        peso: pesoImportado !== null ? String(pesoImportado) : anterior.peso,
        ...importedPatientAge(anterior, dados.paciente, dados.paciente.data_exame?.substring(0, 10) || anterior.data_exame),
        tutor: dados.paciente.tutor || anterior.tutor,
        telefone: dados.paciente.telefone || anterior.telefone,
        data_exame: dados.paciente.data_exame
          ? dados.paciente.data_exame.substring(0, 10)
          : anterior.data_exame || operationalTodayDateInput(),
      }));
    }

    if (dados.medidas) {
      const medidasFormatadas = mapImportedEchoMeasurements(dados.medidas);
      importarMedidas(medidasFormatadas);
    }

    if (dados.clinica) {
      if (typeof dados.clinica === 'string') {
        const clinicaEncontrada = clinicas.find(c => c.nome === dados.clinica);
        if (clinicaEncontrada) {
          setClinicaId(clinicaEncontrada.id.toString());
          setClinicaNome(clinicaEncontrada.nome);
        } else {
          setClinicaNome(dados.clinica);
        }
      } else if (dados.clinica && typeof dados.clinica === 'object') {
        setClinicaId(dados.clinica.id?.toString() || "");
        setClinicaNome(dados.clinica.nome || "");
      }
    }

    if (dados.veterinario_solicitante) {
      setMedicoSolicitante(dados.veterinario_solicitante);
    }

    if (dados.fc) {
      setEcocardiogramaCabecalho((prev) => ({
        ...prev,
        fc: String(dados.fc || "").trim(),
      }));
    }

    setMensagemSucesso("Dados importados com sucesso!");
    setTimeout(() => setMensagemSucesso(null), 5000);
  };

  const carregarLaudo = async (generation: number, owner: number | null, signal: AbortSignal) => {
    const current = () => generation === loadGeneration.current && owner === readEditorOwner() && !signal.aborted;
    try {
      if (!laudoId) return;
      const { data } = await api.get(`/laudos/${laudoId}`, { signal });
      if (!current()) return;
      if (data.tipo === TIPO_LAUDO_ULTRASSOM_ABDOMINAL) {
        router.replace(getLaudoEditPath(laudoId, data.tipo)); return;
      }
      const patientData = data.paciente || (data.paciente_id
        ? (await api.get(`/pacientes/${data.paciente_id}`, { signal })).data : null);
      const loadedImages = await Promise.all((data.imagens || []).map(async (image: Imagem) => {
        let dataUrl = "";
        try { dataUrl = await imagePreview(image.url, signal); } catch { /* Metadata remains available. */ }
        return { ...image, dataUrl, incluir_no_pdf: image.incluir_no_pdf !== false };
      }));
      if (!current()) return;
      const form = {
        nome: patientData?.nome || "", especie: patientData?.especie || "Canina",
        raca: patientData?.raca || "", sexo: normalizarSexoPaciente(patientData?.sexo || "Macho") || "Macho",
        peso: patientData?.peso_kg != null ? String(patientData.peso_kg) : "",
        ...patientAgeForm(patientData || {}),
        idade: patientData?.idade || "", tutor: patientData?.tutor || "",
        telefone: patientData?.telefone || "",
        data_exame: data.data_exame ? data.data_exame.substring(0, 10) : operationalTodayDateInput(),
      };
      originalForm.current = form;
      setLaudo(data); setPaciente(patientData); setPacienteForm(form);
      setTitulo(data.titulo || ""); setDiagnostico(data.diagnostico || "");
      setObservacoes(data.observacoes || ""); setDescricao(data.descricao || "");
      setStatus(data.status || "Rascunho");
      setSourceRevision(data.editor_revision || ""); setSourceConflict(false);
      setClinicaId(data.clinic_id ? String(data.clinic_id) : ""); setClinicaNome(data.clinica || "");
      setVeterinarioParceiroId(data.veterinario_parceiro_id ? String(data.veterinario_parceiro_id) : "");
      setMedicoSolicitante(data.medico_solicitante || "");
      setEcocardiogramaCabecalho({ ritmo: String(data.ecocardiograma_cabecalho?.ritmo || ""),
        estado: String(data.ecocardiograma_cabecalho?.estado || ""), fc: String(data.ecocardiograma_cabecalho?.fc || "") });
      const pressure = data.pressao_arterial || {};
      const selection = (value: unknown, options: string[], fallback: string) => {
        const text = String(value || "");
        return { selected: text ? (options.includes(text) ? text : "Outro") : fallback,
          other: text && !options.includes(text) ? text : "" };
      };
      const cuff = selection(pressure.manguito, OPCOES_MANGUITO, "Manguito 02");
      const limb = selection(pressure.membro, OPCOES_MEMBRO, "Membro anterior esquerdo");
      const position = selection(pressure.decubito, OPCOES_DECUBITO, "Decubito lateral direito");
      setPressaoArterial({ pas_1: pressure.pas_1 != null ? String(pressure.pas_1) : "",
        pas_2: pressure.pas_2 != null ? String(pressure.pas_2) : "", pas_3: pressure.pas_3 != null ? String(pressure.pas_3) : "",
        manguito_select: cuff.selected, manguito_outro: cuff.other, membro_select: limb.selected,
        membro_outro: limb.other, decubito_select: position.selected, decubito_outro: position.other,
        obs_extra: String(pressure.obs_extra || "") });
      setAba((data.tipo || "").toLowerCase() === TIPO_LAUDO_PRESSAO_ARTERIAL ? "pressao" : "paciente");
      setImagens(loadedImages); setImagensTemp([]); setImagensRemovidas([]); setSubmission(undefined);
      const extracted = extrairQualitativaEcoDaDescricao(data.descricao || "");
      substituirMedidas(parseStoredEchoMeasurements(data.medidas, data.descricao || ""));
      setQualitativa(extracted);
      setEcocardiogramaEstruturado(hidratarEcocardiogramaEstruturadoDeLegado(
        normalizarEcocardiogramaEstruturado(data.ecocardiograma_estruturado), extracted, data.diagnostico || ""));
      setQualitativaEstruturadaAplicada(false); setConclusaoEstruturadaAplicada(false);
    } catch (error) {
      if (current()) { console.error("Erro ao carregar laudo:", error); setDraftNotice("Não foi possível carregar a versão oficial. Reabra o editor."); }
    } finally { if (current()) setLoading(false); }
  };

  // Keep serialization metadata stable while the clinical snapshot is unchanged,
  // so the optional preview and the explicit emission share the same intent.
  const estruturaParaPayload = useMemo(() => serializarEcocardiogramaEstruturado(ecocardiogramaEstruturado), [ecocardiogramaEstruturado]);

  const montarPayloadEdicao = () => {
    const medidasPayload = {
      ...medidas,
      ...deriveAutomaticEchoMeasurements(medidas, pacienteForm.peso, pacienteForm.especie, pacienteForm.idade),
    };
    const pressaoPayload = montarPayloadPressao();
    const ecoEstruturadoPayload = laudoEhPressao
      ? null
      : estruturaParaPayload;
    const textoClinico = resolverTextoClinicoNaEdicao(
      ecoEstruturadoPayload,
      qualitativa,
      diagnostico,
      {
        qualitativa: qualitativaEstruturadaAplicada,
        conclusao: conclusaoEstruturadaAplicada,
      }
    );
    const qualitativaPayload = textoClinico.qualitativa;
    const diagnosticoPayload = textoClinico.conclusao;

    // 2. Montar descricao do laudo conforme tipo
    let descricao = "";
    if (laudoEhPressao) {
      const pas1 = parseInteiroPositivo(pressaoArterial.pas_1) || 0;
      const pas2 = parseInteiroPositivo(pressaoArterial.pas_2) || 0;
      const pas3 = parseInteiroPositivo(pressaoArterial.pas_3) || 0;
      descricao = "## Afericao de Pressao Arterial\n";
      descricao += `- 1a afericao (PAS): ${pas1} mmHg\n`;
      descricao += `- 2a afericao (PAS): ${pas2} mmHg\n`;
      descricao += `- 3a afericao (PAS): ${pas3} mmHg\n`;
      descricao += `- PAS media: ${pasMediaCalculada || 0} mmHg\n`;
      descricao += "- Metodo: Doppler\n";
    } else {
      descricao = montarDescricaoEcocardiograma(
        medidasPayload,
        qualitativaPayload
      );
    }

    // 3. Salvar laudo
    const payload: any = {
      titulo:
        titulo ||
        (laudoEhPressao
          ? `Laudo de Pressao Arterial - ${pacienteForm.nome || "Paciente"}`
          : `Laudo de Ecocardiograma - ${pacienteForm.nome || "Paciente"}`),
      descricao,
      diagnostico: diagnosticoPayload,
      observacoes,
      status,
      data_exame: pacienteForm.data_exame,
      tipo_laudo: laudoEhPressao ? "pressao_arterial" : "ecocardiograma",
      pressao_arterial: pressaoPayload,
      ecocardiograma_cabecalho: laudoEhPressao ? null : ecocardiogramaCabecalho,
      ecocardiograma_estruturado: ecoEstruturadoPayload,
      aplicar_qualitativa_estruturada: qualitativaEstruturadaAplicada,
      aplicar_conclusao_estruturada: conclusaoEstruturadaAplicada,
    };

    // Adicionar clinic_id se selecionado
    if (clinicaId) {
      payload.clinic_id = parseInt(clinicaId);
    }

    payload.veterinario_parceiro_id = veterinarioParceiroId
      ? parseInt(veterinarioParceiroId)
      : null;

    // Adicionar médico solicitante
    if (medicoSolicitante) {
      payload.medico_solicitante = medicoSolicitante;
    }
    return { payload, medidasPayload };
  };

  const montarAlteracoesCadastro = () => {
    const patientPatch: Record<string, unknown> = {};
    for (const key of ["nome", "especie", "raca", "sexo", "idade_informada", "idade_referencia", "idade_fonte", "data_nascimento"] as const) {
      if (pacienteForm[key] !== originalForm.current[key]) patientPatch[key] = pacienteForm[key];
    }
    if (parsePesoKg(pacienteForm.peso) !== parsePesoKg(originalForm.current.peso)) patientPatch.peso_kg = parsePesoKg(pacienteForm.peso);
    if (["idade_informada", "idade_referencia", "idade_fonte", "data_nascimento"].some((key) => key in patientPatch)) {
      Object.assign(patientPatch, patientAgePayload(pacienteForm));
    }
    const tutorPatch: Record<string, unknown> = {};
    if (pacienteForm.tutor !== originalForm.current.tutor) tutorPatch.nome = pacienteForm.tutor;
    if (pacienteForm.telefone !== originalForm.current.telefone) tutorPatch.telefone = pacienteForm.telefone;
    return { patientPatch, tutorPatch };
  };

  const requestPdfPreview = async (signal: AbortSignal): Promise<Blob> => {
    if (!draftApplies || !draftUserId || readEditorOwner() !== draftUserId || sourceConflict || submission
      || !editorDraft.canEmit || updateInProgress.current || imageUploadActive) {
      throw new Error("Conclua a recuperação e confira a versão oficial antes de gerar a prévia.");
    }
    const captured = cloneEchoEditorDraftSnapshot(snapshotRef.current);
    const generation = loadGeneration.current;
    const key = echoPreviewSnapshotKey(captured);
    if (captured.imagens.some((image) => !image.uploaded || !image.tempId)) {
      throw new Error("Reenvie ou remova as imagens pendentes antes de gerar a prévia.");
    }
    const { payload } = montarPayloadEdicao();
    payload.clinic_id = captured.clinicaId ? Number(captured.clinicaId) : null;
    payload.medico_solicitante = captured.conteudo.medicoSolicitante;
    const { patientPatch, tutorPatch } = montarAlteracoesCadastro();
    if (Object.keys(tutorPatch).length && !paciente?.tutor_id) {
      throw new Error("Vincule o tutor ao paciente no cadastro antes de atualizar os dados do tutor.");
    }
    const assertCurrent = () => {
      if (signal.aborted || readEditorOwner() !== draftUserId || generation !== loadGeneration.current
        || echoPreviewSnapshotKey(snapshotRef.current) !== key) {
        throw new DOMException("O conteúdo ou a sessão da prévia mudou.", "AbortError");
      }
    };
    const saved = await editorDraft.flush(captured);
    assertCurrent();
    if (!saved) throw new Error("O rascunho não foi confirmado para a prévia.");
    const response = await api.post(`/laudos/editor-drafts/${saved.draft_id}/preview`, {
      expected_revision: saved.revision, payload_laudo: payload,
      ...(Object.keys(patientPatch).length ? { paciente: patientPatch } : {}),
      ...(Object.keys(tutorPatch).length ? { tutor: { ...tutorPatch, id: paciente!.tutor_id } } : {}),
      imagens: echoEditorImageSelection(captured),
    }, { signal, responseType: "blob", timeout: 30_000, headers: { "X-Editor-Owner-Id": draftUserId } });
    assertCurrent();
    return response.data;
  };

  const handleSalvar = async () => {
    if (updateInProgress.current || leaving || sessionChanged || laudo?.id !== Number(laudoId)) return;
    if (draftApplies && (!draftUserId || readEditorOwner() !== draftUserId || sourceConflict || submission || !editorDraft.canEmit)) return;
    const captured = draftApplies ? cloneEchoEditorDraftSnapshot(snapshotRef.current) : null;
    const updateGeneration = loadGeneration.current;
    updateInProgress.current = true;
    let applied = false;
    let clinicalRequestStarted = false;
    setSalvando(true);
    try {
      const { payload, medidasPayload } = montarPayloadEdicao();
      if (
        hasAnyMeasurement(medidasPayload, LV_M_MODE_KEYS) &&
        hasAnyMeasurement(medidasPayload, LV_2D_KEYS) &&
        !medidasPayload["VE_tecnica_relatorio"]
      ) {
        alert("Escolha se o PDF deve usar as medidas do VE em Modo M ou Modo 2D.");
        setAba("medidas");
        return;
      }
      const laudoEhEcocardiograma =
        (laudo?.tipo || "").toLowerCase() === TIPO_LAUDO_ECOCARDIOGRAMA;
      if (laudoEhEcocardiograma) {
        const mensagemAlerta = criarMensagemAlertaSalvamentoEcocardiograma({
          analiseQualitativaAplicada: ecocardiogramaEstruturado.usar_no_laudo,
          imagensCarregadas:
            imagens.length > 0 || imagensTemp.some((imagem) => imagem.uploaded),
        });
        if (mensagemAlerta && !window.confirm(mensagemAlerta)) {
          setAba(
            ecocardiogramaEstruturado.usar_no_laudo ? "imagens" : "qualitativa"
          );
          return;
        }
      }

      // 1. Salvar dados do paciente primeiro
      if (!draftApplies && paciente?.id) {
        const pacientePayload = {
          nome: pacienteForm.nome,
          tutor: pacienteForm.tutor || undefined,
          especie: pacienteForm.especie,
          raca: pacienteForm.raca,
          sexo: normalizarSexoPaciente(pacienteForm.sexo),
          peso_kg: parsePesoKg(pacienteForm.peso),
          ...patientAgePayload(pacienteForm),
        };
        await api.put(`/pacientes/${paciente.id}`, pacientePayload);

        // 2. Salvar/atualizar tutor
        if (pacienteForm.tutor) {
          try {
            const tutorPayload = {
              nome: pacienteForm.tutor,
              telefone: pacienteForm.telefone,
            };

            // Se já existe tutor, atualiza; senão, cria novo
            if (paciente?.tutor_id) {
              await api.put(`/tutores/${paciente.tutor_id}`, tutorPayload);
            } else {
              const respTutor = await api.post("/tutores", tutorPayload);
              if (respTutor?.data?.id) {
                await api.put(`/tutores/${respTutor.data.id}`, tutorPayload);
              }
            }
          } catch (e) {
            console.error("Erro ao salvar tutor:", e);
          }
        }
      }


      if (!laudoId) return;
      if (draftApplies && captured) {
        payload.clinic_id = captured.clinicaId ? Number(captured.clinicaId) : null;
        payload.medico_solicitante = captured.conteudo.medicoSolicitante;
        if (imageUploadActive || imagensTemp.some((image) => !image.uploaded || !image.tempId)) {
          setAba("imagens"); setDraftNotice("Reenvie ou remova as imagens pendentes antes de atualizar."); return;
        }
        const { patientPatch, tutorPatch } = montarAlteracoesCadastro();
        if (Object.keys(tutorPatch).length && !paciente?.tutor_id) {
          setDraftNotice("Vincule o tutor ao paciente no cadastro antes de atualizar os dados do tutor."); return;
        }
        await editorDraft.pause();
        const pending = { status: "pending" as const, laudoId: Number(laudoId) };
        setSubmission(pending);
        const saved = await editorDraft.flush({ ...captured, submission: pending });
        if (!saved) throw new Error("O rascunho não foi confirmado.");
        if (updateGeneration !== loadGeneration.current || readEditorOwner() !== draftUserId) return;
        const requestId = crypto.randomUUID();
        const body = {
          expected_editor_revision: captured.source!.editor_revision, request_id: requestId,
          editor_draft_id: saved.draft_id, expected_draft_revision: saved.revision,
          payload_laudo: payload,
          ...(Object.keys(patientPatch).length ? { paciente: patientPatch } : {}),
          ...(Object.keys(tutorPatch).length ? { tutor: { ...tutorPatch, id: paciente!.tutor_id } } : {}),
          imagens: echoEditorImageSelection(captured),
        };
        clinicalRequestStarted = true;
        const response = await api.put(`/laudos/${laudoId}/editor-update`, body, {
          timeout: 30_000, headers: { "X-Editor-Owner-Id": draftUserId } });
        if (updateGeneration !== loadGeneration.current || readEditorOwner() !== draftUserId) return;
        if (response.data?.id !== Number(laudoId) || response.data?.request_id !== requestId || response.data?.updated !== true) {
          throw new Error("A resposta da atualização não foi confirmada.");
        }
        applied = true;
        setSubmission({ status: "confirmed", laudoId: Number(laudoId) });
        try { editorDraft.acknowledgeApplied(response.data, requestId); }
        catch { setDraftNotice("Atualização confirmada; o encerramento da recuperação local precisa ser conferido."); }
        alert("Laudo atualizado com sucesso!");
        router.push(`/laudos/${laudoId}`);
        return;
      }
      if (imagens.length > 0) {
        await api.put(`/imagens/laudo/${laudoId}/configuracao`, {
          imagens: imagens.map((imagem, index) => ({
            id: imagem.id,
            ordem: index,
            incluir_no_pdf: imagem.incluir_no_pdf !== false,
            descricao: imagem.descricao || "",
          })),
        });
      }
      const novasImagensEnviadas = imagensTemp.filter((imagem) => imagem.uploaded && imagem.tempId);
      if (novasImagensEnviadas.length > 0) {
        await api.put(`/imagens/temp/session/${sessionId}/configuracao`, {
          imagens: novasImagensEnviadas.map((imagem) => ({
            id: imagem.tempId,
            ordem: imagem.ordem,
            incluir_no_pdf: imagem.incluirNoPdf ?? true,
            descricao: imagem.descricao || "",
          })),
        });
      }
      await api.put(`/laudos/${laudoId}`, payload);

      // 4. Associar novas imagens ao laudo se houver
      if (imagensTemp.length > 0 && imagensTemp.some(img => img.uploaded)) {
        try {
          await api.post(`/imagens/associar/${laudoId}?session_id=${sessionId}`);
        } catch (imgError) {
          console.error("Erro ao associar imagens:", imgError);
        }
      }

      alert("Laudo e dados do paciente salvos com sucesso!");
      router.push(`/laudos/${laudoId}`);
    } catch (error) {
      console.error("Erro ao salvar:", error);
      if (draftApplies) {
        const code = Number((error as any)?.response?.status);
        const detail = (error as any)?.response?.data?.detail;
        if (clinicalRequestStarted && ![400, 401, 403, 404, 409, 422, 429].includes(code)) {
          setDraftNotice("A resposta da atualização não foi confirmada. Confira o laudo oficial antes de qualquer nova tentativa.");
          return;
        }
        if (code === 409 && ["SOURCE_CHANGED", "IMAGES_CHANGED"].includes(detail?.code)) setSourceConflict(true);
        setSubmission(undefined);
        let retrySnapshot = captured;
        if (code === 409 && detail?.code === "TEMP_IMAGES_UNAVAILABLE" && captured) {
          const missing = imagensTemp.map((image) => ({ ...image, uploaded: false, requerReenvio: true }));
          setImagensTemp(missing); setAba("imagens");
          retrySnapshot = { ...captured, imagens: serializeDraftImages(missing), aba: "imagens" };
        }
        if (retrySnapshot) {
          try { await editorDraft.flush({ ...retrySnapshot, submission: undefined }); } catch { /* Preserve recovery. */ }
        }
        setDraftNotice(typeof detail === "string" ? detail : typeof detail?.message === "string" ? detail.message
          : "Não foi possível atualizar. O preenchimento foi preservado no rascunho.");
        return;
      }
      alert("Erro ao salvar. Verifique os dados e tente novamente.");
    } finally {
      updateInProgress.current = false;
      if (!applied) editorDraft.resume();
      setSalvando(false);
    }
  };

  const handleMedidaChange = (key: string, value: string) => {
    if (updateInProgress.current) return;
    setMedidas(prev => ECHO_OUTFLOW_KEYS.has(key)
      ? updateEchoOutflowMeasurement(prev, key, value)
      : updateFelineDiastolicMeasurement(prev, key, value, pacienteForm.especie));
  };

  const handleEchoAssistantApply = (patch: {
    fields: Record<string, string>;
    measurements: Record<string, string>;
    skipped: string[];
  }) => {
    if (updateInProgress.current || !isCurrentEditorContext() || sessionChanged || (draftApplies && (submission || editorDraft.blocked))) return;
    if (Object.keys(patch.measurements).length) {
      importarMedidas(patch.measurements);
    }
    if (Object.keys(patch.fields).length) {
      handleEcocardiogramaEstruturadoChange({
        ...ecocardiogramaEstruturado,
        usar_no_laudo: true,
        textos: {
          ...ecocardiogramaEstruturado.textos,
          ...patch.fields,
        },
        updated_at: new Date().toISOString(),
      });
    }
    setAba(Object.keys(patch.fields).length ? "qualitativa" : "medidas");
    setMensagemSucesso(
      patch.skipped.length
        ? `Sugestões aplicadas ao rascunho. ${patch.skipped.length} item(ns) permaneceram para revisão manual.`
        : "Sugestões selecionadas aplicadas ao rascunho. Revise antes de salvar."
    );
  };

  const leaveEditor = async (href: string) => {
    if (leaving || updateInProgress.current || loading) return;
    if (draftApplies && readEditorOwner() !== draftUserId) { setSessionChanged(true); return; }
    setLeaving(true);
    try {
      if (draftApplies && !submission && editorDraft.status !== "closed") await editorDraft.flush();
      if (draftApplies && (imageUploadActive || editorDraft.pendingImages > 0)
        && !window.confirm("Há imagens não recebidas que precisarão ser reenviadas ao retomar. Sair mesmo assim?")) return;
      router.push(href);
    } catch { setDraftNotice("Não foi possível confirmar o rascunho antes de sair. Mantenha esta tela aberta e tente novamente."); }
    finally { setLeaving(false); }
  };
  navigationHandler.current = leaveEditor;
  useEffect(() => {
    if (!imageUploadActive) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [imageUploadActive]);
  useEffect(() => {
    if (!draftApplies || loading || sessionChanged) return;
    const onLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin || url.href === window.location.href) return;
      event.preventDefault(); event.stopPropagation();
      void navigationHandler.current(`${url.pathname}${url.search}${url.hash}`);
    };
    document.addEventListener("click", onLink, true);
    return () => document.removeEventListener("click", onLink, true);
  }, [draftApplies, loading, sessionChanged]);

  if (sessionChanged) return <DashboardLayout><div role="alert" className="m-6 rounded border border-amber-300 p-4">
    A sessão do usuário mudou. Reabra o editor na conta correta. Nenhuma alteração será gravada nesta sessão.
  </div></DashboardLayout>;

  if (loading || (laudo && laudo.id !== Number(laudoId))) {
    return (
      <DashboardLayout>
        <div className="fc-report-editor-page">
          <div className="fc-report-loading"><span aria-hidden="true" />Carregando laudo...</div>
        </div>
      </DashboardLayout>
    );
  }

  if (!laudo) {
    return (
      <DashboardLayout>
        <div className="p-6 text-center">
          <h1 className="text-2xl font-bold text-gray-900">Laudo não encontrado</h1>
          <p className="text-gray-500 mt-2">O laudo solicitado não existe ou foi removido.</p>
          <button
            onClick={() => router.push("/laudos")}
            className="mt-4 px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700"
          >
            Voltar para Laudos
          </button>
        </div>
      </DashboardLayout>
    );
  }

  const textoParaConferencia = resolverTextoClinicoNaEdicao(
    serializarEcocardiogramaEstruturado(ecocardiogramaEstruturado),
    qualitativa,
    diagnostico,
    { qualitativa: qualitativaEstruturadaAplicada, conclusao: conclusaoEstruturadaAplicada },
  );
  const vistaIndice2D = medidas.VE_vista_2D === "eixo_curto" || medidas.VE_vista_2D === "eixo_longo"
    ? medidas.VE_vista_2D as Echo2DView : "";
  const pesoIndice2D = parsePesoKg(pacienteForm.peso);
  const indice2D = calculateCanine2DNormalizedLVIDd(
    echoLengthInMm(medidas, "DIVEd_2D"), pesoIndice2D, vistaIndice2D, pacienteForm.especie, pacienteForm.idade,
  );
  const faixaIndice2D = indice2D === null ? null : getCanine2DReference(
    "DIVEd_normalizado_2D", pesoIndice2D ?? undefined, vistaIndice2D, pacienteForm.idade,
  );

  return (
    <DashboardLayout>
      <div className="fc-report-editor-page">
        <header className="fc-report-editor-header">
          <div className="fc-report-editor-heading">
            <button
              type="button"
              onClick={() => { void leaveEditor(`/laudos/${laudoId}`); }}
              disabled={salvando || leaving}
              className="fc-report-editor-back"
              aria-label="Voltar para o laudo"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-report-editor-kicker">
                <Heart className="h-4 w-4" />
                Central diagnóstica
              </span>
              <h1>
                {laudoEhPressao ? "Editar Laudo de Pressao Arterial" : "Editar Laudo"}
              </h1>
              <p>
                {laudoEhPressao ? `${pacienteForm.nome} · fluxo dedicado de PA` : pacienteForm.nome}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
          {draftApplies && <button type="button" onClick={() => { void editorDraft.flush().catch(() => {}); }}
            disabled={salvando || leaving || editorDraft.blocked}
            className="rounded-lg border bg-white px-4 py-3 text-teal-900 disabled:opacity-50">Salvar rascunho</button>}
          <button
            type="button"
            onClick={handleSalvar}
            disabled={salvando || leaving || imageUploadActive || (draftApplies && (sourceConflict || Boolean(submission) || !editorDraft.canEmit))}
            className="fc-report-editor-save"
          >
            <Save className="w-4 h-4" />
            {salvando ? "Salvando..." : draftApplies ? "Atualizar laudo" : "Salvar Laudo"}
          </button>
          </div>
        </header>

        {draftApplies && <>
          <EchoDraftStatus draft={editorDraft} existing allowContinueFresh={!editorDraft.recovery?.snapshot.source
            || editorDraft.recovery.snapshot.source.editor_revision === laudo.editor_revision} />
          <p className="my-2 text-sm text-gray-600">As alterações ficam no rascunho privado até você atualizar o laudo. O PDF emitido permanece inalterado.</p>
          {(!draftUserId || !sourceRevision) && <p role="alert">Não foi possível confirmar a sessão e a versão oficial. Reabra o editor antes de atualizar.</p>}
          {(sourceConflict || (editorDraft.recovery?.snapshot.source
            && editorDraft.recovery.snapshot.source.editor_revision !== laudo.editor_revision)) && <p role="alert" className="my-3 rounded border border-amber-300 p-3">
            A versão oficial mudou desde o início deste rascunho. Sua cópia foi preservada; confira o laudo atual antes de resolver o conflito.
          </p>}
          {(sourceConflict || (editorDraft.recovery?.snapshot.source
            && editorDraft.recovery.snapshot.source.editor_revision !== laudo.editor_revision))
            && !submission && !editorDraft.recovery?.snapshot.submission && <button type="button"
              disabled={salvando || leaving || editorDraft.status === "saving"} className="my-2 underline" onClick={async () => {
                if (!isCurrentEditorContext()) return;
                if (!window.confirm("Descartar somente as alterações deste rascunho privado? O laudo oficial não será alterado. A próxima edição começará pela versão oficial atual.")) return;
                try { await editorDraft.discardExisting(); router.push(`/laudos/${laudoId}`); }
                catch { setDraftNotice("Não foi possível encerrar o rascunho privado. A cópia foi preservada para conferência."); }
              }}>Descartar alterações deste rascunho</button>}
          {editorDraft.closedRecovery && <p role="status" className="my-3 rounded border border-teal-300 p-3">
            {editorDraft.closedRecovery.result ? "O servidor confirmou a atualização deste laudo. Nenhuma nova atualização será enviada." : "Este rascunho foi encerrado. Confira o resultado no laudo oficial."}
            <button type="button" className="ml-4 underline" onClick={() => {
              if (readEditorOwner() !== draftUserId) { setSessionChanged(true); return; }
              if (window.confirm("Você conferiu o resultado no laudo oficial? A próxima edição começará pela versão oficial atual.")) {
                try { editorDraft.acknowledgeClosed(); router.push(`/laudos/${laudoId}`); }
                catch { setDraftNotice("Não foi possível concluir a recuperação. Mantenha esta tela aberta."); }
              }
            }}>Conferi o resultado; voltar ao laudo</button>
          </p>}
          {(submission || editorDraft.closedRecovery || sourceConflict) && <div role="status" className="my-3 rounded border border-amber-300 p-3">
            {submission?.status === "pending" && <p>Há uma tentativa de atualização sem resposta confirmada. Confira o laudo oficial antes de continuar.</p>}
            {submission?.status === "confirmed" && <p>Atualização confirmada. Confira o laudo oficial.</p>}
            <a href={`/laudos/${laudoId}`} target="_blank" rel="noreferrer" className="underline">Conferir laudo oficial</a>
            {submission?.status === "pending" && <button type="button" className="ml-4 underline" onClick={() => {
              if (window.confirm("Você conferiu o laudo oficial e confirmou que esta atualização não foi aplicada?")) {
                setSubmission(undefined); void editorDraft.flush({ ...snapshotRef.current, submission: undefined }).catch(() => {});
              }
            }}>Confirmei que não foi atualizado; retomar rascunho</button>}
          </div>}
          {draftNotice && <p role="alert" className="my-3 rounded border border-amber-300 p-3">{draftNotice}</p>}
        </>}
        {draftApplies && <EchoFinalReview
          snapshotKey={echoPreviewSnapshotKey(draftSnapshot)} scopeKey={`${draftUserId}:edit:${laudoId}`}
          disabled={salvando || leaving || imageUploadActive || sourceConflict || Boolean(submission) || !draftUserId || !editorDraft.canEmit}
          issues={buildEchoFinalReviewIssues({ measurements: medidas, species: pacienteForm.especie,
            qualitative: textoParaConferencia.qualitativa, conclusion: textoParaConferencia.conclusao,
            patientName: pacienteForm.nome, qualitativeApplied: ecocardiogramaEstruturado.usar_no_laudo,
            images: [...imagens.map((image) => ({ uploaded: true, included: image.incluir_no_pdf !== false })),
              ...imagensTemp.map((image) => ({ uploaded: image.uploaded, included: image.incluirNoPdf !== false }))] })}
          imageCount={imagens.filter((image) => image.incluir_no_pdf !== false).length
            + imagensTemp.filter((image) => image.uploaded && image.incluirNoPdf !== false).length}
          requestPreview={requestPdfPreview} onNavigate={(target) => navigateEchoFinalReview(target, setAba)} />}

        <fieldset disabled={salvando || leaving || (draftApplies && (!draftUserId || Boolean(submission)
          || ["loading", "recovery", "closed"].includes(editorDraft.status)))} className="min-w-0">
        <div className="fc-report-editor-layout">
          {/* Coluna Esquerda - Importadores */}
          <aside className="fc-report-editor-sidebar">
            {laudoEhPressao ? (
              <div className="fc-report-editor-side-card space-y-4">
                <h2 className="text-lg font-semibold mb-2 flex items-center gap-2">
                  <Heart className="w-5 h-5 text-teal-600" />
                  Fluxo de PA
                </h2>

                {mensagemSucesso && (
                  <div className="p-3 bg-green-100 border border-green-300 text-green-800 rounded-lg text-sm">
                    {mensagemSucesso}
                  </div>
                )}

                <div className="rounded-lg border border-teal-100 bg-teal-50 p-4 text-sm text-teal-900">
                  Este laudo esta configurado como exame dedicado de pressao arterial. A aba de pressao concentra o que voce precisa revisar.
                </div>
              </div>
            ) : (
              <>
                {laudoId && Number.isFinite(Number(laudoId)) ? (
                  <EchoVoiceAssistant
                    laudoId={Number(laudoId)}
                    currentFields={{
                      ...ecocardiogramaEstruturado.textos,
                      conclusao:
                        ecocardiogramaEstruturado.textos.conclusao || diagnostico,
                    }}
                    currentMeasurements={medidas}
                    onApply={handleEchoAssistantApply}
                  />
                ) : null}

                <div className="fc-report-editor-side-card">
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-teal-600" />
                    Importar Estudo (Imagem/PDF)
                  </h2>

                  <EcoStudyImportUploader onDadosImportados={handleDadosImportados} />

                  <div className="mt-4 rounded-lg bg-teal-50 p-3 text-sm text-teal-900">
                    Revise as medidas reconhecidas antes de aplica-las. Valores conflitantes permanecem fora do formulario.
                  </div>
                </div>

                <div className="fc-report-editor-side-card">
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Activity className="w-5 h-5 text-teal-600" />
                    Importar XML
                  </h2>

                  {mensagemSucesso && (
                    <div className="mb-4 p-3 bg-green-100 border border-green-300 text-green-800 rounded-lg text-sm">
                      {mensagemSucesso}
                    </div>
                  )}

                  <XmlUploader onDadosImportados={handleDadosImportados} />

                  <div className="mt-6 p-4 bg-blue-50 rounded-lg">
                    <p className="text-sm text-blue-800">
                      <strong>Dica:</strong> Arraste o arquivo XML exportado do aparelho de ecocardiograma para preencher automaticamente os dados e medidas.
                    </p>
                  </div>
                </div>

                <div className="fc-report-editor-side-card">
                  <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <ImageIcon className="w-5 h-5 text-teal-600" />
                    Importar Cabecalho (Imagem)
                  </h2>

                  <ImageHeaderUploader onDadosImportados={handleDadosImportados} />

                  <div className="mt-6 p-4 bg-blue-50 rounded-lg">
                    <p className="text-sm text-blue-800">
                      <strong>Dica:</strong> Envie a imagem gerada pelo equipamento para preencher automaticamente os campos de cabecalho.
                    </p>
                  </div>
                </div>
              </>
            )}
          </aside>

          {/* Coluna Direita - Abas */}
          <div className="fc-report-editor-main">
            <div className="fc-report-editor-workspace">
              {/* Abas */}
              <div className="fc-report-editor-tabs" role="tablist" aria-label="Seções do laudo">
                <button
                  onClick={() => setAba("paciente")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "paciente"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <User className="w-4 h-4" />
                  Paciente
                </button>
                <button
                  onClick={() => setAba("pressao")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "pressao"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <Heart className="w-4 h-4" />
                  Pressao
                </button>
                <button
                  onClick={() => setAba("medidas")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "medidas"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <Activity className="w-4 h-4" />
                  Medidas
                </button>
                <button
                  onClick={() => setAba("qualitativa")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "qualitativa"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <BookOpen className="w-4 h-4" />
                  Qualitativa
                </button>
                <button
                  onClick={() => setAba("biblioteca")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "biblioteca"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <FolderOpen className="w-4 h-4" />
                  Biblioteca
                </button>
                <button
                  onClick={() => setAba("imagens")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "imagens"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <ImageIcon className="w-4 h-4" />
                  Imagens
                </button>
                <button
                  onClick={() => setAba("referencias")}
                  className={`px-4 py-3 font-medium flex items-center gap-2 whitespace-nowrap ${
                    aba === "referencias"
                      ? "text-teal-600 border-b-2 border-teal-600"
                      : "text-gray-600 hover:text-gray-800"
                  }`}
                >
                  <BookOpen className="w-4 h-4" />
                  Referências
                </button>
              </div>

              {/* Conteúdo das Abas */}
              <div className="fc-report-editor-body">
                {aba === "paciente" && (
                  <div data-echo-review-target="patient" className="space-y-4">
                    <h3 className="font-medium text-gray-900 mb-4">Dados do Paciente</h3>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Nome do Paciente
                        </label>
                        <input
                          type="text"
                          value={pacienteForm.nome}
                          onChange={(e) => setPacienteForm({...pacienteForm, nome: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Tutor
                        </label>
                        <input
                          type="text"
                          value={pacienteForm.tutor}
                          onChange={(e) => setPacienteForm({...pacienteForm, tutor: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Espécie
                        </label>
                        <select
                          value={pacienteForm.especie}
                          onChange={(e) => {
                            const especie = e.target.value;
                            if (!isFelineEchoSpecies(especie) && temPresetDiastolicoFelinoAplicado(ecocardiogramaEstruturado)) {
                              if (!window.confirm("Este laudo contém uma descrição diastólica felina. Trocar a espécie removerá essa descrição; os demais achados serão preservados. Deseja continuar?")) return;
                              handleEcocardiogramaEstruturadoChange(removerPresetDiastolicoFelino(ecocardiogramaEstruturado));
                            }
                            setPacienteForm({ ...pacienteForm, especie, raca: "" });
                            setNovaRaca("");
                          }}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="Canina">Canina</option>
                          <option value="Felina">Felina</option>
                          {normalizeEchoSpecies(pacienteForm.especie) === "Canina" && pacienteForm.especie !== "Canina" && (
                            <option value={pacienteForm.especie}>{pacienteForm.especie} (canina)</option>
                          )}
                          {isFelineEchoSpecies(pacienteForm.especie) && pacienteForm.especie !== "Felina" && (
                            <option value={pacienteForm.especie}>{pacienteForm.especie} (felina)</option>
                          )}
                          <option value="Equina">Equina</option>
                          <option value="Outra">Outra</option>
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Raça
                        </label>
                        <select
                          value={pacienteForm.raca}
                          onChange={(e) => setPacienteForm({...pacienteForm, raca: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
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
                            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          />
                          <button
                            type="button"
                            onClick={handleAdicionarRaca}
                            disabled={!novaRaca.trim()}
                            className="px-3 py-2 rounded-lg border border-teal-200 text-teal-700 hover:bg-teal-50 disabled:opacity-50 disabled:cursor-not-allowed"
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
                          value={pacienteForm.sexo}
                          onChange={(e) => setPacienteForm({...pacienteForm, sexo: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="Macho">Macho</option>
                          <option value="Fêmea">Fêmea</option>
                        </select>
                      </div>

                      <PatientAgeFields value={pacienteForm} referenceDate={pacienteForm.data_exame} onChange={(patch) => setPacienteForm((prev) => ({ ...prev, ...patch }))} />

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Ritmo
                        </label>
                        <select
                          value={ecocardiogramaCabecalho.ritmo}
                          onChange={(e) =>
                            setEcocardiogramaCabecalho((prev) => ({
                              ...prev,
                              ritmo: e.target.value,
                            }))
                          }
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="">Selecione...</option>
                          {opcoesRitmoPaciente.map((ritmo) => (
                            <option key={ritmo} value={ritmo}>
                              {ritmo}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Estado do Paciente
                        </label>
                        <select
                          value={ecocardiogramaCabecalho.estado}
                          onChange={(e) =>
                            setEcocardiogramaCabecalho((prev) => ({
                              ...prev,
                              estado: e.target.value,
                            }))
                          }
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="">Selecione...</option>
                          {opcoesEstadoPaciente.map((estado) => (
                            <option key={estado} value={estado}>
                              {estado}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Peso (kg)
                        </label>
                        <input
                          type="text"
                          value={pacienteForm.peso}
                          onChange={(e) => setPacienteForm({...pacienteForm, peso: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          placeholder="Ex: 10.5"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Data do Exame
                        </label>
                        <input
                          type="date"
                          value={pacienteForm.data_exame}
                          onChange={(e) => setPacienteForm({...pacienteForm, data_exame: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>

                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Telefone
                        </label>
                        <input
                          type="text"
                          value={pacienteForm.telefone}
                          onChange={(e) => setPacienteForm({...pacienteForm, telefone: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          placeholder="(00) 00000-0000"
                        />
                      </div>
                    </div>

                    <div className="border-t pt-4 mt-4">
                      <h4 className="font-medium text-gray-900 mb-4">Informações da Clínica</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Clínica
                          </label>
                          <select
                            value={clinicaId}
                            onChange={(e) => {
                              const selectedId = e.target.value;
                              setClinicaId(selectedId);
                              const selectedClinica = clinicas.find(c => c.id.toString() === selectedId);
                              setClinicaNome(selectedClinica?.nome || "");
                            }}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">Selecione uma clínica</option>
                            {clinicas.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.nome}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Veterinário parceiro
                          </label>
                          <select
                            value={veterinarioParceiroId}
                            onChange={(e) => setVeterinarioParceiroId(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">Selecione o veterinário parceiro</option>
                            {parceirosVeterinarios.map((partner) => (
                              <option key={partner.id} value={partner.id}>
                                {partner.nome_exibicao}
                              </option>
                            ))}
                          </select>
                          <p className="mt-1 text-xs text-gray-500">
                            Use este campo para laudos prontos vindos de encaminhamento domiciliar ou volante.
                          </p>
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Veterinário Solicitante
                          </label>
                          <input
                            type="text"
                            value={medicoSolicitante}
                            onChange={(e) => setMedicoSolicitante(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          />
                        </div>
                      </div>
                    </div>

                    <div className="border-t pt-4 mt-4">
                      <h4 className="font-medium text-gray-900 mb-4">Informações do Laudo</h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Título
                          </label>
                          <input
                            type="text"
                            value={titulo}
                            onChange={(e) => setTitulo(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                            placeholder="Título do laudo"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Status
                          </label>
                          <select
                            value={status}
                            onChange={(e) => setStatus(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="Rascunho">Rascunho</option>
                            <option value="Finalizado">Finalizado</option>
                            <option value="Arquivado">Arquivado</option>
                            {!["Rascunho", "Finalizado", "Arquivado"].includes(status) && <option value={status}>{status}</option>}
                          </select>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {aba === "medidas" && (
                  <div className="space-y-6">
                    <div data-echo-review-target="units"><EchoUnitReview
                      measurements={medidas}
                      onConfirm={(key, unit) => handleMedidaChange(confirmedUnitKey(key), unit)}
                    /></div>
                    <div className="rounded-lg border border-teal-200 bg-teal-50 p-4">
                      <label className="block text-sm font-semibold text-gray-900">
                        Técnica do estudo do ventrículo esquerdo exibida no PDF
                      </label>
                      <select
                        data-echo-review-target="technique"
                        value={medidas["VE_tecnica_relatorio"] || ""}
                        onChange={(event) =>
                          handleMedidaChange("VE_tecnica_relatorio", event.target.value)
                        }
                        className="mt-2 w-full rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm text-gray-800 focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">Selecione quando houver medidas em M e 2D</option>
                        <option value="modo_m">Modo M</option>
                        <option value="2d">Modo 2D</option>
                      </select>
                      <p className="mt-2 text-xs text-teal-800">
                        Quando o estudo importado trouxer as duas técnicas, a escolha define qual bloco será levado ao PDF.
                      </p>
                    </div>

                    {/* Grid principal com 3 colunas */}
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                      {/* Coluna 1: VE - Modo M */}
                      <div className="space-y-4">
                        <h4 className="font-semibold text-gray-900 text-sm">VE - Modo M</h4>

                        <MedidaInput
                          label={echoLengthInputLabel("DIVEd (mm - Diâmetro interno do VE em diástole)", medidas, "DIVEd")}
                          value={medidas["DIVEd"] || ""}
                          onChange={(v) => handleMedidaChange("DIVEd", v)}
                        />
                        {normalizeEchoSpecies(pacienteForm.especie) === "Canina" && <MedidaInput
                          label="DIVEd normalizado (DIVEd [cm] / peso^0,294)"
                          value={medidas["DIVEd_normalizado"] || ""}
                          onChange={(v) => handleMedidaChange("DIVEd_normalizado", v)}
                          readOnly
                          reference={normalizeEchoSpecies(pacienteForm.especie) === "Canina" && (parsePesoKg(pacienteForm.peso) ?? 0) >= 2.2 && (parsePesoKg(pacienteForm.peso) ?? 0) <= 95
                            ? "Cornell 2004 (amostra de cães adultos, Modo M): 1,27–1,85"
                            : "Faixa aplicável não cadastrada"}
                        />}
                        <MedidaInput
                          label={echoLengthInputLabel("SIVd (mm - Septo interventricular em diástole)", medidas, "SIVd")}
                          value={medidas["SIVd"] || ""}
                          onChange={(v) => handleMedidaChange("SIVd", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("PLVEd (mm - Parede livre do VE em diástole)", medidas, "PLVEd")}
                          value={medidas["PLVEd"] || ""}
                          onChange={(v) => handleMedidaChange("PLVEd", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("DIVÉs (mm - Diâmetro interno do VE em sístole)", medidas, "DIVES")}
                          value={medidas["DIVES"] || ""}
                          onChange={(v) => handleMedidaChange("DIVES", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("SIVs (mm - Septo interventricular em sístole)", medidas, "SIVs")}
                          value={medidas["SIVs"] || ""}
                          onChange={(v) => handleMedidaChange("SIVs", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("PLVÉs (mm - Parede livre do VE em sístole)", medidas, "PLVES")}
                          value={medidas["PLVES"] || ""}
                          onChange={(v) => handleMedidaChange("PLVES", v)}
                        />
                        <MedidaInput
                          label="VDF (Teicholz, mL)"
                          value={medidas["VDF"] || ""}
                          onChange={(v) => handleMedidaChange("VDF", v)}
                        />
                        <MedidaInput
                          label="VSF (Teicholz, mL)"
                          value={medidas["VSF"] || ""}
                          onChange={(v) => handleMedidaChange("VSF", v)}
                        />
                        <MedidaInput
                          label="FE (Teicholz, %)"
                          value={medidas["FE_Teicholz"] || ""}
                          onChange={(v) => handleMedidaChange("FE_Teicholz", v)}
                        />
                        <MedidaInput
                          label="Delta D / FS (%)"
                          value={medidas["DeltaD_FS"] || ""}
                          onChange={(v) => handleMedidaChange("DeltaD_FS", v)}
                        />
                        <MedidaInput
                          label="TAPSE (mm - excursão sistólica do plano anular tricúspide)"
                          value={medidas["TAPSE"] || ""}
                          onChange={(v) => handleMedidaChange("TAPSE", v)}
                        />
                        <MedidaInput
                          label="MAPSE (mm - excursão sistólica do plano anular mitral)"
                          value={medidas["MAPSE"] || ""}
                          onChange={(v) => handleMedidaChange("MAPSE", v)}
                        />
                      </div>

                      {/* Coluna 2: Átrio esquerdo/Aorta e Diastólica */}
                      <div className="space-y-4">
                        <h4 className="font-semibold text-gray-900 text-sm">Átrio esquerdo/ Aorta</h4>

                        <MedidaInput
                          label={echoLengthInputLabel("Aorta (mm)", medidas, "Aorta")}
                          value={medidas["Aorta"] || ""}
                          onChange={(v) => handleMedidaChange("Aorta", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("Átrio esquerdo (mm)", medidas, "Atrio_esquerdo")}
                          value={medidas["Atrio_esquerdo"] || ""}
                          onChange={(v) => handleMedidaChange("Atrio_esquerdo", v)}
                        />
                        <MedidaInput
                          label="AE/Ao (Átrio esquerdo/Aorta, adimensional)"
                          value={medidas["AE_Ao"] || ""}
                          onChange={(v) => handleMedidaChange("AE_Ao", v)}
                          readOnly
                        />

                        {isFelineEchoSpecies(pacienteForm.especie) && (
                          <>
                            <MedidaInput
                              label={echoLengthInputLabel("AE diâmetro máximo (mm; preferir eixo curto, modo M guiado por 2D)", medidas, "AE_diametro_max")}
                              value={medidas["AE_diametro_max"] ?? ""}
                              onChange={(v) => handleMedidaChange("AE_diametro_max", v)}
                            />
                            <MedidaInput
                              label={echoLengthInputLabel("AE diâmetro mínimo (mm; mesma vista do máximo)", medidas, "AE_diametro_min")}
                              value={medidas["AE_diametro_min"] ?? ""}
                              onChange={(v) => handleMedidaChange("AE_diametro_min", v)}
                            />
                            <MedidaInput
                              label="Fração de encurtamento do AE (%) · calculada com os dois diâmetros"
                              value={medidas["Fracao_encurtamento_AE"] ?? ""}
                              onChange={(v) => handleMedidaChange("Fracao_encurtamento_AE", v)}
                              readOnly={calculateLeftAtrialFractionalShortening(medidas) !== null}
                            />
                            <MedidaInput
                              label="Velocidade máxima do apêndice atrial esquerdo (m/s, Doppler pulsado)"
                              value={medidas["Fluxo_auricular"] ?? ""}
                              onChange={(v) => handleMedidaChange("Fluxo_auricular", v)}
                            />
                            <p className="text-xs text-gray-600">Confirme que os diâmetros foram obtidos na mesma vista. Interprete função atrial e fluxo do apêndice com tamanho do AE, contraste espontâneo e trombo; sem corte diagnóstico automático.</p>
                          </>
                        )}

                        <hr className="border-gray-200 my-4" />

                        <h4 data-echo-review-target="diastolic" className="font-semibold text-gray-900 text-sm">Diastólica</h4>
                        <FelineWaveReview especie={pacienteForm.especie} medidas={medidas}
                          onMedidaChange={handleMedidaChange}
                          onDiscard={(kind) => setMedidas(prev => discardFelineFusedMeasurements(prev, pacienteForm.especie, kind))}
                        />
                        {!laudoEhPressao && <EchoNarrativeConsistencyNotice
                          species={pacienteForm.especie}
                          measurements={medidas}
                          qualitative={textoParaConferencia.qualitativa}
                          conclusion={textoParaConferencia.conclusao}
                        />}

                        <MedidaInput
                          label="Onda E (m/s)"
                          value={medidas["Onda_E"] || ""}
                          onChange={(v) => handleMedidaChange("Onda_E", v)}
                        />
                        <MedidaInput
                          label="Onda A (m/s)"
                          value={medidas["Onda_A"] || ""}
                          onChange={(v) => handleMedidaChange("Onda_A", v)}
                        />
                        <MedidaInput
                          label="E/A (relação adimensional)"
                          value={medidas["E_A"] || ""}
                          onChange={(v) => handleMedidaChange("E_A", v)}
                          readOnly={!isFelineEchoSpecies(pacienteForm.especie) || isEchoDiastolicRatioCalculated(medidas, pacienteForm.peso, pacienteForm.especie, "E_A")}
                        />
                        <MedidaInput
                          label="TD (tempo de desaceleração, ms)"
                          value={medidas["TD"] || ""}
                          onChange={(v) => handleMedidaChange("TD", v)}
                        />
                        <MedidaInput
                          label="TRIV (tempo de relaxamento isovolumétrico, ms)"
                          value={medidas["TRIV"] || ""}
                          onChange={(v) => handleMedidaChange("TRIV", v)}
                        />
                        <MedidaInput
                          label="E/TRIV (índice E [cm/s] / TRIV [ms])"
                          value={medidas["E_TRIV"] || ""}
                          onChange={(v) => handleMedidaChange("E_TRIV", v)}
                          readOnly={!isFelineEchoSpecies(pacienteForm.especie) || isEchoDiastolicRatioCalculated(medidas, pacienteForm.peso, pacienteForm.especie, "E_TRIV")}
                        />
                        <MedidaInput
                          label="MR dp/dt (mmHg/s)"
                          value={medidas["MR_dp_dt"] || ""}
                          onChange={(v) => handleMedidaChange("MR_dp_dt", v)}
                        />
                        <MedidaInput
                          label="e' (Doppler tecidual, m/s)"
                          value={medidas["e_doppler"] || ""}
                          onChange={(v) => handleMedidaChange("e_doppler", v)}
                        />
                        <MedidaInput
                          label="a' (Doppler tecidual, m/s)"
                          value={medidas["a_doppler"] || ""}
                          onChange={(v) => handleMedidaChange("a_doppler", v)}
                        />
                        <MedidaInput
                          label="Doppler tecidual (relação e'/a', adimensional)"
                          value={medidas["doppler_tecidual_relacao"] || ""}
                          onChange={(v) => handleMedidaChange("doppler_tecidual_relacao", v)}
                          readOnly={isFelineEchoSpecies(pacienteForm.especie) && isEchoDiastolicRatioCalculated(medidas, pacienteForm.peso, pacienteForm.especie, "doppler_tecidual_relacao")}
                        />
                        <MedidaInput
                          label="E/E' (adimensional)"
                          value={medidas["E_E_linha"] || ""}
                          onChange={(v) => handleMedidaChange("E_E_linha", v)}
                          readOnly={!isFelineEchoSpecies(pacienteForm.especie) || isEchoDiastolicRatioCalculated(medidas, pacienteForm.peso, pacienteForm.especie, "E_E_linha")}
                        />
                      </div>

                      {/* Coluna 3: Artéria pulmonar/Aorta e Regurgitações */}
                      <div className="space-y-4">
                        <h4 className="font-semibold text-gray-900 text-sm">Artéria pulmonar/ Aorta</h4>

                        <MedidaInput
                          label={echoLengthInputLabel("AP (mm - Artéria pulmonar)", medidas, "AP")}
                          value={medidas["AP"] || ""}
                          onChange={(v) => handleMedidaChange("AP", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("Ao (mm - Aorta - nível AP)", medidas, "Ao_nivel_AP")}
                          value={medidas["Ao_nivel_AP"] || ""}
                          onChange={(v) => handleMedidaChange("Ao_nivel_AP", v)}
                        />
                        <MedidaInput
                          label="AP/Ao (Artéria pulmonar/Aorta, adimensional)"
                          value={medidas["AP_Ao"] || ""}
                          onChange={(v) => handleMedidaChange("AP_Ao", v)}
                        />

                        <hr className="border-gray-200 my-4" />

                        <h4 className="font-semibold text-gray-900 text-sm">Regurgitações</h4>

                        <MedidaInput
                          label="IM (insuficiência mitral) Vmax (m/s)"
                          value={medidas["IM_Vmax"] || ""}
                          onChange={(v) => handleMedidaChange("IM_Vmax", v)}
                        />
                        <MedidaInput
                          label="Gradiente da insuficiência mitral (mmHg, 4 × V²)"
                          value={medidas["IM_Grad"] || ""}
                          onChange={(v) => handleMedidaChange("IM_Grad", v)}
                          readOnly
                        />
                        <MedidaInput
                          label="IT (insuficiência tricúspide) Vmax (m/s)"
                          value={medidas["IT_Vmax"] || ""}
                          onChange={(v) => handleMedidaChange("IT_Vmax", v)}
                        />
                        <MedidaInput
                          label="Gradiente da insuficiência tricúspide (mmHg, 4 × V²)"
                          value={medidas["IT_Grad"] || ""}
                          onChange={(v) => handleMedidaChange("IT_Grad", v)}
                          readOnly
                        />
                        <MedidaInput
                          label="IA (insuficiência aórtica) Vmax (m/s)"
                          value={medidas["IA_Vmax"] || ""}
                          onChange={(v) => handleMedidaChange("IA_Vmax", v)}
                        />
                        <MedidaInput
                          label="Gradiente da insuficiência aórtica (mmHg, 4 × V²)"
                          value={medidas["IA_Grad"] || ""}
                          onChange={(v) => handleMedidaChange("IA_Grad", v)}
                          readOnly
                        />
                        <MedidaInput
                          label="IP (insuficiência pulmonar) Vmax (m/s)"
                          value={medidas["IP_Vmax"] || ""}
                          onChange={(v) => handleMedidaChange("IP_Vmax", v)}
                        />
                        <MedidaInput
                          label="Gradiente da insuficiência pulmonar (mmHg, 4 × V²)"
                          value={medidas["IP_Grad"] || ""}
                          onChange={(v) => handleMedidaChange("IP_Grad", v)}
                          readOnly
                        />
                        <div className="space-y-1">
                          <label className="block text-xs leading-tight text-gray-600">
                            Remodelamento do átrio direito
                          </label>
                          <select
                            value={medidas["Remodelamento_AD"] || ""}
                            onChange={(event) =>
                              handleMedidaChange("Remodelamento_AD", event.target.value)
                            }
                            className="w-full rounded bg-blue-50 px-2 py-1.5 text-sm text-gray-700 focus:ring-1 focus:ring-teal-500"
                          >
                            <option value="">Selecione ou aplique a sugestão do ditado</option>
                            <option value="ausente">Ausente</option>
                            <option value="leve">Leve</option>
                            <option value="moderado">Moderado</option>
                            <option value="importante">Importante</option>
                          </select>
                        </div>
                        <MedidaInput
                          label="Pressão atrial direita estimada (mmHg)"
                          value={medidas["PAD_estimada"] || ""}
                          onChange={(v) => handleMedidaChange("PAD_estimada", v)}
                          readOnly
                        />
                        <MedidaInput
                          label="PSAP estimada (mmHg = gradiente IT + PAD estimada)"
                          value={medidas["PSAP"] || ""}
                          onChange={(v) => handleMedidaChange("PSAP", v)}
                          readOnly
                          reference="Estimativa ecocardiográfica; confirmar ausência de obstrução da via de saída do VD."
                        />
                      </div>
                    </div>

                    <div className="border-t pt-6">
                      <h4 className="mb-4 text-sm font-semibold text-gray-900">VE - Modo 2D</h4>
                      {isFelineEchoSpecies(pacienteForm.especie) && <p className="mb-3 text-xs text-gray-600">Verifique o ponto de maior espessura do septo e da parede livre nos eixos curto e longo; descreva hipertrofia focal na análise qualitativa.</p>}
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        <MedidaInput
                          label={echoLengthInputLabel("DIVEd 2D (mm - Diâmetro interno do VE em diástole)", medidas, "DIVEd_2D")}
                          value={medidas["DIVEd_2D"] || ""}
                          onChange={(v) => handleMedidaChange("DIVEd_2D", v)}
                        />
                        {faixaIndice2D && <MedidaInput
                          label="DIVEd normalizado 2D · Visser (DIVEd [cm] / peso^0,316)"
                          value={indice2D?.toFixed(2) || ""}
                          onChange={(v) => handleMedidaChange("DIVEd_normalizado_2D", v)}
                          readOnly
                          reference={`Visser et al. 2019: ${faixaIndice2D.min.toFixed(2)}–${faixaIndice2D.max.toFixed(2)}`}
                        />}
                        <MedidaInput
                          label={echoLengthInputLabel("SIVd 2D (mm)", medidas, "SIVd_2D")}
                          value={medidas["SIVd_2D"] || ""}
                          onChange={(v) => handleMedidaChange("SIVd_2D", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("PLVEd 2D (mm)", medidas, "PLVEd_2D")}
                          value={medidas["PLVEd_2D"] || ""}
                          onChange={(v) => handleMedidaChange("PLVEd_2D", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("DIVEs 2D (mm)", medidas, "DIVES_2D")}
                          value={medidas["DIVES_2D"] || ""}
                          onChange={(v) => handleMedidaChange("DIVES_2D", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("SIVs 2D (mm)", medidas, "SIVs_2D")}
                          value={medidas["SIVs_2D"] || ""}
                          onChange={(v) => handleMedidaChange("SIVs_2D", v)}
                        />
                        <MedidaInput
                          label={echoLengthInputLabel("PLVEs 2D (mm)", medidas, "PLVES_2D")}
                          value={medidas["PLVES_2D"] || ""}
                          onChange={(v) => handleMedidaChange("PLVES_2D", v)}
                        />
                        <MedidaInput
                          label="VDF 2D (Teicholz, mL)"
                          value={medidas["VDF_2D"] || ""}
                          onChange={(v) => handleMedidaChange("VDF_2D", v)}
                        />
                        <MedidaInput
                          label="VSF 2D (Teicholz, mL)"
                          value={medidas["VSF_2D"] || ""}
                          onChange={(v) => handleMedidaChange("VSF_2D", v)}
                        />
                        <MedidaInput
                          label="FE 2D (Teicholz, %)"
                          value={medidas["FE_Teicholz_2D"] || ""}
                          onChange={(v) => handleMedidaChange("FE_Teicholz_2D", v)}
                        />
                        <MedidaInput
                          label="Delta D / FS 2D (%)"
                          value={medidas["DeltaD_FS_2D"] || ""}
                          onChange={(v) => handleMedidaChange("DeltaD_FS_2D", v)}
                        />
                      </div>
                    </div>

                    <EchoOutflowMeasurements measurements={medidas} onChange={handleMedidaChange} />
                  </div>
                )}

                {aba === "qualitativa" && (
                  <div data-echo-review-target="qualitative" className="space-y-4">
                    {!laudoEhPressao && <EchoNarrativeConsistencyNotice
                      species={pacienteForm.especie}
                      measurements={medidas}
                      qualitative={textoParaConferencia.qualitativa}
                      conclusion={textoParaConferencia.conclusao}
                    />}
                    <div className="mb-4">
                      <h3 className="font-medium text-gray-900">Qualitativa Detalhada</h3>
                      <span className="text-sm text-gray-500">
                        O texto clinico salvo e preservado ao editar medidas e referencias. Edite os campos estruturados para atualizar a analise no laudo.
                      </span>
                    </div>

                    <EcocardiogramaEstruturadoEditor
                      value={ecocardiogramaEstruturado}
                      onChange={handleEcocardiogramaEstruturadoChange}
                      especie={pacienteForm.especie}
                    />

                    {ecocardiogramaEstruturado.usar_no_laudo ? (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        Para ajustar a conclusao oficial, edite o aspecto &quot;Conclusao&quot; no bloco estruturado acima.
                      </div>
                    ) : null}

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Conclusao
                      </label>
                      <textarea
                        value={diagnostico}
                        onChange={(e) => setDiagnostico(e.target.value)}
                        rows={4}
                        readOnly={ecocardiogramaEstruturado.usar_no_laudo}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500 read-only:bg-gray-50"
                        placeholder="Conclusao diagnostica..."
                      />
                    </div>
                  </div>
                )}

                {aba === "biblioteca" && (
                  <EcocardiogramaEstruturadoBiblioteca />
                )}

                {aba === "imagens" && (
                  <div data-echo-review-target="images" className="space-y-4">
                    <div className="flex justify-between items-center mb-4">
                      <h3 className="font-medium text-gray-900">Imagens do Exame</h3>
                      <span className="text-sm text-gray-500">
                        {imagens.length} imagem(ns) existente(s)
                      </span>
                    </div>

                    {imagens.length > 0 && (
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                        {imagens.map((img, idx) => (
                          <div
                            key={img.id}
                            draggable
                            onDragStart={(event) => {
                              setDraggedImagemIndex(idx);
                              event.dataTransfer.effectAllowed = "move";
                            }}
                            onDragEnd={() => setDraggedImagemIndex(null)}
                            onDragOver={(event) => {
                              event.preventDefault();
                              event.dataTransfer.dropEffect = "move";
                            }}
                            onDrop={(event) => {
                              event.preventDefault();
                              if (draggedImagemIndex !== null) moverImagemPersistida(draggedImagemIndex, idx);
                              setDraggedImagemIndex(null);
                            }}
                            className={`relative group border rounded-lg overflow-hidden ${
                              draggedImagemIndex === idx ? "opacity-50 ring-2 ring-teal-500" : ""
                            }`}
                          >
                            <img
                              src={img.dataUrl || img.url}
                              alt={img.nome}
                              className="w-full h-32 object-cover cursor-zoom-in"
                              onClick={() => setPreviewImagemIndex(idx)}
                              role="button"
                              tabIndex={0}
                              aria-label={`Ampliar ${img.nome}`}
                              draggable={false}
                              onKeyDown={(event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                  event.preventDefault();
                                  setPreviewImagemIndex(idx);
                                }
                              }}
                              onError={(e) => {
                                (e.target as HTMLImageElement).src = '/placeholder-image.png';
                              }}
                            />
                            <div className="absolute top-2 left-2 bg-teal-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
                              {idx + 1}
                            </div>
                            <div className="absolute bottom-14 left-2 rounded bg-black/65 p-1 text-white" title="Arraste para reordenar">
                              <GripVertical className="h-4 w-4" />
                            </div>
                            <button
                              onClick={async () => {
                                if (confirm("Deseja remover esta imagem?")) {
                                  try {
                                    if (draftApplies) {
                                      setImagensRemovidas((current) => [...new Set([...current, img.id])]);
                                    } else await api.delete(`/imagens/${img.id}`);
                                    const restantes = imagens
                                      .filter(i => i.id !== img.id)
                                      .map((imagem, index) => ({ ...imagem, ordem: index }));
                                    await salvarConfiguracaoImagens(restantes, restantes);
                                  } catch (e) {
                                    alert("Erro ao remover imagem");
                                  }
                                }
                              }}
                              className="absolute top-2 right-2 p-1 bg-red-500 text-white rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                              title="Remover"
                            >
                              <X className="h-4 w-4" />
                            </button>
                            <div className="p-2">
                              <p className="text-xs text-gray-600 truncate">{img.nome}</p>
                              <label className="mt-2 block text-xs font-medium text-gray-700">
                                Legenda opcional no PDF
                                <input
                                  type="text"
                                  value={img.descricao || ""}
                                  maxLength={160}
                                  onFocus={(event) => { event.currentTarget.dataset.initialValue = img.descricao || ""; }}
                                  onChange={(event) => setImagens(imagens.map((imagem) =>
                                    imagem.id === img.id ? { ...imagem, descricao: event.target.value } : imagem
                                  ))}
                                  onBlur={(event) => {
                                    const original = event.currentTarget.dataset.initialValue || "";
                                    const anteriores = imagens.map((imagem) =>
                                      imagem.id === img.id ? { ...imagem, descricao: original } : imagem
                                    );
                                    void salvarConfiguracaoImagens(imagens, anteriores);
                                  }}
                                  placeholder="Ex.: Doppler da regurgitação tricúspide"
                                  aria-label={`Legenda da imagem ${idx + 1}`}
                                  className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-xs text-gray-900"
                                />
                              </label>
                              <label className="mt-2 flex items-center gap-2 text-xs font-medium text-gray-700">
                                <input
                                  type="checkbox"
                                  checked={img.incluir_no_pdf !== false}
                                  onChange={() => alternarImagemNoPdf(idx)}
                                  className="h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
                                />
                                Incluir no PDF
                              </label>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <ImagePreviewModal
                      images={imagens.map((img) => ({
                        id: img.id,
                        nome: img.nome,
                        src: img.dataUrl || img.url,
                      }))}
                      selectedIndex={previewImagemIndex}
                      onSelectedIndexChange={setPreviewImagemIndex}
                    />

                    <div className="border-t pt-6">
                      <h4 className="font-medium text-gray-900 mb-4">Adicionar Novas Imagens</h4>
                      <ImageUploader
                        onImagensChange={(next) => { if (!updateInProgress.current && isCurrentEditorContext()) setImagensTemp(next); }}
                        onUploadStateChange={(active) => { if (isCurrentEditorContext()) setImageUploadActive(active); }}
                        sessionId={sessionId}
                        imagensIniciais={imagensTemp}
                      />
                    </div>

                    <div className="mt-4 p-4 bg-blue-50 rounded-lg">
                      <p className="text-sm text-blue-800">
                        <strong>Dica:</strong> Clique para ampliar, arraste para reordenar e desmarque as imagens que não devem entrar no PDF.
                      </p>
                    </div>
                  </div>
                )}

                {aba === "pressao" && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="font-medium text-gray-900">Pressao Arterial</h3>
                      <p className="text-sm text-gray-500 mt-1">
                        Edite as afericoes e observacoes da pressao arterial vinculadas a este laudo.
                      </p>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">1a afericao PAS (mmHg)</label>
                        <input
                          type="number"
                          min={0}
                          max={400}
                          step={1}
                          value={pressaoArterial.pas_1}
                          onChange={(e) => setPressaoArterial((prev) => ({ ...prev, pas_1: e.target.value }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">2a afericao PAS (mmHg)</label>
                        <input
                          type="number"
                          min={0}
                          max={400}
                          step={1}
                          value={pressaoArterial.pas_2}
                          onChange={(e) => setPressaoArterial((prev) => ({ ...prev, pas_2: e.target.value }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">3a afericao PAS (mmHg)</label>
                        <input
                          type="number"
                          min={0}
                          max={400}
                          step={1}
                          value={pressaoArterial.pas_3}
                          onChange={(e) => setPressaoArterial((prev) => ({ ...prev, pas_3: e.target.value }))}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">PA Sistolica Media (mmHg)</label>
                        <input
                          type="text"
                          readOnly
                          value={pasMediaCalculada ?? ""}
                          className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-700"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Metodo</label>
                        <input
                          type="text"
                          readOnly
                          value="Doppler"
                          className="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-gray-700"
                        />
                      </div>
                    </div>

                    <div className="border-t pt-4">
                      <h4 className="font-medium text-gray-900 mb-3">Observacoes do Procedimento</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Manguito</label>
                          <select
                            value={pressaoArterial.manguito_select}
                            onChange={(e) => setPressaoArterial((prev) => ({ ...prev, manguito_select: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            {OPCOES_MANGUITO.map((op) => (
                              <option key={op} value={op}>{op}</option>
                            ))}
                          </select>
                          {pressaoArterial.manguito_select === "Outro" && (
                            <input
                              type="text"
                              value={pressaoArterial.manguito_outro}
                              onChange={(e) => setPressaoArterial((prev) => ({ ...prev, manguito_outro: e.target.value }))}
                              placeholder="Especifique o manguito"
                              className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                            />
                          )}
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Membro</label>
                          <select
                            value={pressaoArterial.membro_select}
                            onChange={(e) => setPressaoArterial((prev) => ({ ...prev, membro_select: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            {OPCOES_MEMBRO.map((op) => (
                              <option key={op} value={op}>{op}</option>
                            ))}
                          </select>
                          {pressaoArterial.membro_select === "Outro" && (
                            <input
                              type="text"
                              value={pressaoArterial.membro_outro}
                              onChange={(e) => setPressaoArterial((prev) => ({ ...prev, membro_outro: e.target.value }))}
                              placeholder="Especifique o membro"
                              className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                            />
                          )}
                        </div>

                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Decubito</label>
                          <select
                            value={pressaoArterial.decubito_select}
                            onChange={(e) => setPressaoArterial((prev) => ({ ...prev, decubito_select: e.target.value }))}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          >
                            {OPCOES_DECUBITO.map((op) => (
                              <option key={op} value={op}>{op}</option>
                            ))}
                          </select>
                          {pressaoArterial.decubito_select === "Outro" && (
                            <input
                              type="text"
                              value={pressaoArterial.decubito_outro}
                              onChange={(e) => setPressaoArterial((prev) => ({ ...prev, decubito_outro: e.target.value }))}
                              placeholder="Especifique o decubito"
                              className="mt-2 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                            />
                          )}
                        </div>
                      </div>

                      <div className="mt-4">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Outras observacoes (opcional)</label>
                        <textarea
                          value={pressaoArterial.obs_extra}
                          onChange={(e) => setPressaoArterial((prev) => ({ ...prev, obs_extra: e.target.value }))}
                          rows={3}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          placeholder="Descreva detalhes adicionais da afericao..."
                        />
                      </div>
                    </div>

                    <div className="p-4 bg-green-50 border border-green-200 rounded-lg text-sm text-green-900 space-y-1">
                      <p><strong>Valores de referencia (PAS):</strong></p>
                      <p>Normal: 110 a 140 mmHg</p>
                      <p>Levemente elevada: 141 a 159 mmHg</p>
                      <p>Moderadamente elevada: 160 a 179 mmHg</p>
                      <p>Severamente elevada: &gt;= 180 mmHg</p>
                    </div>
                  </div>
                )}

                {aba === "referencias" && (
                  <div data-echo-review-target="references" className="space-y-4">
                    <div className="flex justify-between items-center mb-4">
                      <h3 className="font-medium text-gray-900">Tabelas de Referência</h3>
                      <a
                        href="/referencias-eco"
                        target="_blank"
                        className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 text-sm flex items-center gap-2"
                      >
                        <BookOpen className="w-4 h-4" />
                        Editar Tabelas
                      </a>
                    </div>

                    <div className="p-4 bg-blue-50 rounded-lg">
                      <p className="text-sm text-blue-800">
                        <strong>Nota:</strong> A comparação é numérica com as faixas cadastradas. Confirme a adequação
                        da faixa ao paciente e ao método de medida antes de interpretar. Use &quot;Editar Tabelas&quot; para gerenciar os limites.
                      </p>
                    </div>

                    <ReferenciaComparison
                      especie={pacienteForm.especie}
                      peso={parsePesoKg(pacienteForm.peso) ?? undefined}
                      idade={pacienteForm.idade}
                      medidas={medidas}
                      onMedidaChange={handleMedidaChange}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        </fieldset>
      </div>
    </DashboardLayout>
  );
}
