"use client";

import { PatientAgeFields } from "@/components/pacientes/PatientAgeFields";
import { calcularIdadeComFonte, patientAgeForm, importedPatientAge, type PatientAgeValue } from "@/lib/paciente-idade";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import DashboardLayout from "../../layout-dashboard";
import api from "@/lib/axios";
import {
  addRacaCustomPorEspecie,
  getRacaOptions,
  loadRacasCustomPorEspecie,
  saveRacasCustomPorEspecie,
} from "@/lib/racas";
import XmlUploader from "../components/XmlUploader";
import ImageHeaderUploader from "../components/ImageHeaderUploader";
import ImageUploader from "../components/ImageUploader";
import EchoFinalReview from "../components/EchoFinalReview";
import { buildEchoFinalReviewIssues } from "@/lib/echo-final-review";
import { echoEditorImageSelection, echoPreviewSnapshotKey, navigateEchoFinalReview } from "@/lib/echo-preview-request";
import EcoStudyImportUploader from "../components/EcoStudyImportUploader";
import EcocardiogramaEstruturadoEditor from "../components/EcocardiogramaEstruturadoEditor";
import EcocardiogramaEstruturadoBiblioteca from "../components/EcocardiogramaEstruturadoBiblioteca";
import EchoVoiceAssistant from "../components/EchoVoiceAssistant";
import EchoUnitReview from "../components/EchoUnitReview";
import EchoNarrativeConsistencyNotice from "../components/EchoNarrativeConsistencyNotice";
import EchoOutflowMeasurements from "../components/EchoOutflowMeasurements";
import EchoPulmonaryHypertension from "../components/EchoPulmonaryHypertension";
import { mapImportedEchoMeasurements, updateEchoOutflowMeasurement } from "@/lib/echo-outflow-editor";
import { ECHO_OUTFLOW_KEYS } from "@/lib/echo-outflow";
import FelineWaveReview from "../components/FelineWaveReview";
import { discardFelineFusedMeasurements, isEchoDiastolicRatioCalculated, updateFelineDiastolicMeasurement } from "@/lib/echo-feline-wave-review";
import { calculateCanine2DNormalizedLVIDd, getCanine2DReference, type Echo2DView } from "@/lib/echo-2d-reference";
import { Save, ArrowLeft, Heart, User, Activity, BookOpen, Settings, Image as ImageIcon, Minus, Plus, FolderOpen } from "lucide-react";
import { ReferenciaComparison } from "../components/ReferenciaComparison";
import {
  criarEcocardiogramaEstruturadoInicial,
  derivarLegadoDeEcocardiogramaEstruturado,
  qualitativaEcoLegadaIgual,
  removerPresetDiastolicoFelino,
  serializarEcocardiogramaEstruturado,
  temPresetDiastolicoFelinoAplicado,
} from "@/lib/ecocardiograma-estruturado";
import { listarTodasClinicas } from "@/lib/clinicas";
import { TIPO_LAUDO_PRESSAO_ARTERIAL } from "@/lib/laudos";
import { extrairIdadePaciente, normalizarSexoPaciente, parsePesoKg } from "@/lib/paciente";
import {
  calculateLeftAtrialFractionalShortening,
  deriveAutomaticEchoMeasurements,
  hasAnyMeasurement,
  LV_2D_KEYS,
  LV_M_MODE_KEYS,
} from "@/lib/echo-derived-measurements";
import { criarMensagemAlertaSalvamentoEcocardiograma } from "@/lib/ecocardiograma-save-alert";
import { calendarDateInput, operationalTodayDateInput } from "@/lib/calendar-date";
import { confirmedUnitKey, echoLengthInMm, echoLengthInputLabel } from "@/lib/echo-unit-provenance";
import { isCanineEchoSpecies, isFelineEchoSpecies, normalizeEchoSpecies } from "@/lib/echo-species";
import { useEchoMeasurements } from "../hooks/useEchoMeasurements";
import { NEW_REPORT_PROTOCOL_KEYS } from "@/lib/echo-new-report-defaults";
import { useEchoEditorDraft } from "../hooks/useEchoEditorDraft";
import EchoDraftStatus from "../components/EchoDraftStatus";
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

const parseInteiroPositivo = (valor?: string): number | null => {
  if (!valor) return null;
  const numero = Number(valor.toString().replace(",", ".").trim());
  if (!Number.isFinite(numero)) return null;
  const inteiro = Math.round(numero);
  return inteiro > 0 ? inteiro : null;
};

const formatar2Casas = (valor: number): string => valor.toFixed(2);

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

interface DadosPaciente extends PatientAgeValue {
  id?: number;
  nome: string;
  tutor: string;
  raca: string;
  especie: string;
  peso: string;
  idade: string;
  sexo: string;
  telefone: string;
  data_exame: string;
}

interface Clinica {
  id: number;
  nome: string;
}

interface DadosExame {
  paciente: DadosPaciente;
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


// Parâmetros ecocardiográficos
const PARAMETROS_MEDIDAS = [
  { key: "Ao", label: "Ao (mm)", categoria: "Câmaras" },
  { key: "LA", label: "LA (mm)", categoria: "Câmaras" },
  { key: "LA_Ao", label: "LA/Ao", categoria: "Razões" },
  { key: "IVSd", label: "IVSd (mm)", categoria: "Paredes" },
  { key: "LVIDd", label: "LVIDd (mm)", categoria: "Câmaras" },
  { key: "LVPWd", label: "LVPWd (mm)", categoria: "Paredes" },
  { key: "IVSs", label: "IVSs (mm)", categoria: "Paredes" },
  { key: "LVIDs", label: "LVIDs (mm)", categoria: "Câmaras" },
  { key: "LVPWs", label: "LVPWs (mm)", categoria: "Paredes" },
  { key: "EDV", label: "EDV (ml)", categoria: "Volumes" },
  { key: "ESV", label: "ESV (ml)", categoria: "Volumes" },
  { key: "EF", label: "EF (%)", categoria: "Função" },
  { key: "FS", label: "FS (%)", categoria: "Função" },
  { key: "MAPSE", label: "MAPSE (mm)", categoria: "Função" },
  { key: "TAPSE", label: "TAPSE (mm)", categoria: "Função" },
  { key: "Vmax_Ao", label: "Vmax Ao (m/s)", categoria: "Fluxos" },
  { key: "Grad_Ao", label: "Grad Ao (mmHg)", categoria: "Gradientes" },
  { key: "Vmax_Pulm", label: "Vmax Pulm (m/s)", categoria: "Fluxos" },
  { key: "Grad_Pulm", label: "Grad Pulm (mmHg)", categoria: "Gradientes" },
  { key: "MV_E", label: "MV E (m/s)", categoria: "Mitral" },
  { key: "MV_A", label: "MV A (m/s)", categoria: "Mitral" },
  { key: "MV_E_A", label: "MV E/A", categoria: "Mitral" },
  { key: "MV_E_TRIV", label: "MV E/TRIV", categoria: "Mitral" },
  { key: "MV_DT", label: "MV DT (ms)", categoria: "Mitral" },
  { key: "IVRT", label: "IVRT (ms)", categoria: "Tempos" },
  { key: "MR_Vmax", label: "MR Vmax (m/s)", categoria: "Regurgitação" },
  { key: "TR_Vmax", label: "TR Vmax (m/s)", categoria: "Regurgitação" },
];

// Subcampos para o layout detalhado
const SUBCAMPOS_DETALHADO: Record<string, { key: string; label: string }[]> = {
  valvas: [
    { key: "mitral", label: "Mitral" },
    { key: "tricuspide", label: "Tricúspide" },
    { key: "aortica", label: "Aórtica" },
    { key: "pulmonar", label: "Pulmonar" },
  ],
  camaras: [
    { key: "ae", label: "Átrio Esquerdo" },
    { key: "ad", label: "Átrio Direito" },
    { key: "ve", label: "Ventrículo Esquerdo" },
    { key: "vd", label: "Ventrículo Direito" },
  ],
  funcao: [
    { key: "sistolica_ve", label: "Sistólica VE" },
    { key: "sistolica_vd", label: "Sistólica VD" },
    { key: "diastolica", label: "Diastólica" },
    { key: "sincronia", label: "Sincronia" },
  ],
  pericardio: [
    { key: "efusao", label: "Efusão" },
    { key: "espessamento", label: "Espessamento" },
    { key: "tamponamento", label: "Tamponamento" },
  ],
  vasos: [
    { key: "aorta", label: "Aorta" },
    { key: "art_pulmonar", label: "Art. Pulmonar" },
    { key: "veias_pulmonares", label: "Veias Pulmonares" },
    { key: "cava_hepaticas", label: "Cava/Hepáticas" },
  ],
};

type DetalhadoState = Record<string, Record<string, string>>;

export default function NovoLaudoPage() {
  const router = useRouter();
  const [entradaPressao, setEntradaPressao] = useState(false);
  const [loading, setLoading] = useState(false);
  const [aba, setAba] = useState<"paciente" | "medidas" | "qualitativa" | "biblioteca" | "imagens" | "pressao" | "referencias">("paciente");
  
  // Dados do paciente
  const [paciente, setPaciente] = useState({
    id: undefined as number | undefined,
    nome: "",
    tutor: "",
    raca: "",
    especie: "Canina",
    peso: "",
    ...patientAgeForm(),
    sexo: "Macho",
    telefone: "",
    data_exame: "",
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
  
  // Medidas
  const { measurements: medidas, setMeasurements: setMedidas, importMeasurements: importarMedidas, setProtocolMeasurement, exportState, restoreState } = useEchoMeasurements({ newReportSpecies: paciente.especie });
  
  // Qualitativa
  const [qualitativa, setQualitativa] = useState({
    valvas: "",
    camaras: "",
    funcao: "",
    pericardio: "",
    vasos: "",
    ad_vd: "",
  });
  const [ecocardiogramaCabecalho, setEcocardiogramaCabecalho] = useState<EcocardiogramaCabecalho>({
    ritmo: "",
    estado: "",
    fc: "",
  });
  
  // Conteúdo do laudo
  const [conteudo, setConteudo] = useState({
    descricao: "",
    conclusao: "",
    observacoes: "",
  });
  const [ecocardiogramaEstruturado, setEcocardiogramaEstruturado] = useState(
    criarEcocardiogramaEstruturadoInicial()
  );

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
    salvar_como_laudo_pressao: false,
  });
  
  // Clinica
  const [clinicaId, setClinicaId] = useState<string>("");
  const [clinicaNome, setClinicaNome] = useState<string>("");
  const [clinicas, setClinicas] = useState<Clinica[]>([]);
  const [veterinario, setVeterinario] = useState("");
  const [agendamentoVinculadoId, setAgendamentoVinculadoId] = useState<number | null>(null);
  
  // Mensagem de sucesso
  const [mensagemSucesso, setMensagemSucesso] = useState<string | null>(null);
  
  // Imagens do laudo
  const [imagens, setImagens] = useState<any[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [draftLaudoId, setDraftLaudoId] = useState<number | null>(null);
  const draftPromiseRef = useRef<Promise<number> | null>(null);
  const [contextReady, setContextReady] = useState(false);
  const [draftUserId, setDraftUserId] = useState<number | null>(null);
  const firstDraftUserId = useRef<number | null>(null);
  const [draftSessionChanged, setDraftSessionChanged] = useState(false);
  const [draftContextKey, setDraftContextKey] = useState("");
  const [draftImageNotice, setDraftImageNotice] = useState<string | null>(null);
  const [draftNavigationNotice, setDraftNavigationNotice] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);
  const navigationInProgress = useRef(false);
  const navigationHandler = useRef<(href: string) => Promise<void>>(async () => {});
  const [submission, setSubmission] = useState<EchoEditorDraftSnapshot["submission"]>(undefined);
  const emissionInProgress = useRef(false);
  const voiceDraftIdRef = useRef<number | null>(null);
  const restoreGeneration = useRef(0);
  useEffect(() => {
    restoreGeneration.current += 1;
    return () => { restoreGeneration.current += 1; };
  }, [draftUserId, draftContextKey]);
  const opcoesRitmoPaciente = incluirOpcaoAtual(OPCOES_RITMO, ecocardiogramaCabecalho.ritmo);
  const opcoesEstadoPaciente = incluirOpcaoAtual(
    OPCOES_ESTADO_PACIENTE,
    ecocardiogramaCabecalho.estado,
  );

  const draftSnapshot = useMemo<EchoEditorDraftSnapshot>(() => ({
    schema_version: 1,
    editor: "new-echo",
    paciente,
    measurementState: exportState(),
    qualitativa,
    conteudo,
    ecocardiogramaCabecalho,
    ecocardiogramaEstruturado,
    pressaoArterial,
    clinicaId,
    clinicaNome,
    veterinario,
    agendamentoVinculadoId,
    sessionId,
    draftLaudoId,
    imagens: serializeDraftImages(imagens),
    aba,
    submission,
  }), [paciente, medidas, exportState, qualitativa, conteudo, ecocardiogramaCabecalho,
    ecocardiogramaEstruturado, pressaoArterial, clinicaId, clinicaNome, veterinario,
    agendamentoVinculadoId, sessionId, draftLaudoId, imagens, aba, submission]);
  const draftSnapshotRef = useRef(draftSnapshot);
  draftSnapshotRef.current = draftSnapshot;

  const restoreDraft = async (snapshot: EchoEditorDraftSnapshot) => {
    const generation = restoreGeneration.current;
    const owner = draftUserId;
    // Verify temporary images before showing an old uploaded flag as received.
    // Files that never finished uploading cannot be reconstructed from JSON.
    const uploaded = snapshot.imagens.filter((image) => image.uploaded && image.tempId);
    const available = uploaded.length
      ? (await api.get(`/imagens/temp/session/${encodeURIComponent(snapshot.sessionId)}`)).data.items || []
      : [];
    const availableIds = new Set(available.map((image: { id: number }) => image.id));
    const restoredImages = await Promise.all(snapshot.imagens.map(async (image) => {
      if (!image.uploaded || !image.tempId || !availableIds.has(image.tempId)) {
        return { ...image, dataUrl: "", uploaded: false, tempId: undefined, requerReenvio: true };
      }
      let dataUrl = "";
      try {
        const response = await api.get(`/imagens/temp/${image.tempId}`, { responseType: "blob", timeout: 10_000 });
        dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(new Error("Prévia indisponível"));
          reader.readAsDataURL(response.data);
        });
      } catch { /* Image is present on the server; only its preview failed. */ }
      return { ...image, dataUrl, requerReenvio: false };
    }));
    let currentOwner: number | null = null;
    try {
      const user = JSON.parse(localStorage.getItem("user") || "null");
      currentOwner = Number(user?.id ?? user?.user_id) || null;
    } catch { /* The owner must still be confirmed before applying patient data. */ }
    if (generation !== restoreGeneration.current || owner !== currentOwner) {
      throw new Error("A sessão mudou durante a recuperação. Reabra o formulário para continuar.");
    }
    setPaciente(snapshot.paciente as typeof paciente);
    restoreState(snapshot.measurementState, String(snapshot.paciente.especie || ""));
    setQualitativa(snapshot.qualitativa as typeof qualitativa);
    setConteudo(snapshot.conteudo as typeof conteudo);
    setEcocardiogramaCabecalho(snapshot.ecocardiogramaCabecalho as typeof ecocardiogramaCabecalho);
    setEcocardiogramaEstruturado(snapshot.ecocardiogramaEstruturado as typeof ecocardiogramaEstruturado);
    setPressaoArterial(snapshot.pressaoArterial as typeof pressaoArterial);
    setClinicaId(snapshot.clinicaId);
    setClinicaNome(snapshot.clinicaNome);
    setVeterinario(snapshot.veterinario);
    setAgendamentoVinculadoId(snapshot.agendamentoVinculadoId);
    setSessionId(snapshot.sessionId);
    setDraftLaudoId(snapshot.draftLaudoId);
    setSubmission(snapshot.submission);
    voiceDraftIdRef.current = snapshot.draftLaudoId;
    setImagens(restoredImages);
    const missing = restoredImages.filter((image) => image.requerReenvio).length;
    setDraftImageNotice(missing
      ? `${missing} imagem(ns) não puderam ser recuperadas. Reenvie os arquivos antes de emitir.`
      : null);
    if (["paciente", "medidas", "qualitativa", "biblioteca", "imagens", "pressao", "referencias"].includes(snapshot.aba || "")) {
      setAba(snapshot.aba as typeof aba);
    }
    return { ...snapshot, imagens: serializeDraftImages(restoredImages) };
  };

  const editorDraft = useEchoEditorDraft({
    enabled: contextReady && !draftSessionChanged && !entradaPressao && !pressaoArterial.salvar_como_laudo_pressao,
    userId: draftUserId,
    contextKey: draftContextKey,
    snapshot: draftSnapshot,
    onRestore: restoreDraft,
  });
  const draftApplies = !entradaPressao && !pressaoArterial.salvar_como_laudo_pressao;

  useEffect(() => {
    const readUser = () => {
      let id: number | null = null;
      try {
        const user = JSON.parse(localStorage.getItem("user") || "null");
        const candidate = Number(user?.id ?? user?.user_id);
        id = Number.isSafeInteger(candidate) && candidate > 0 ? candidate : null;
      } catch { /* A lost owner must never reassign an open editor. */ }
      if (firstDraftUserId.current !== null && firstDraftUserId.current !== id) {
        setDraftSessionChanged(true);
        return;
      }
      if (id !== null) firstDraftUserId.current = id;
      setDraftUserId(id);
    };
    readUser();
    window.addEventListener("storage", readUser);
    window.addEventListener("focus", readUser);
    return () => {
      window.removeEventListener("storage", readUser);
      window.removeEventListener("focus", readUser);
    };
  }, []);

  useEffect(() => {
    if (!draftApplies || !draftUserId || draftSessionChanged) return;
    // Next Links do not trigger beforeunload. Save before the shell's normal
    // same-tab links navigate, including the sidebar outside this page.
    const onLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
      const destination = new URL(anchor.href, window.location.href);
      if (destination.origin !== window.location.origin || (destination.pathname === window.location.pathname && destination.search === window.location.search)) return;
      event.preventDefault();
      event.stopPropagation();
      void navigationHandler.current(`${destination.pathname}${destination.search}${destination.hash}`);
    };
    document.addEventListener("click", onLink, true);
    return () => document.removeEventListener("click", onLink, true);
  }, [draftApplies, draftUserId, draftSessionChanged]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setEntradaPressao(params.get("tipo") === TIPO_LAUDO_PRESSAO_ARTERIAL);
  }, []);

  useEffect(() => {
    if (!entradaPressao) return;
    setAba("pressao");
    setPressaoArterial((prev) =>
      prev.salvar_como_laudo_pressao ? prev : { ...prev, salvar_como_laudo_pressao: true }
    );
  }, [entradaPressao]);

  useEffect(() => {
    setRacasCustomPorEspecie(loadRacasCustomPorEspecie());
    setRacasLoaded(true);
  }, []);

  useEffect(() => {
    if (!racasLoaded) return;
    saveRacasCustomPorEspecie(racasCustomPorEspecie);
  }, [racasLoaded, racasCustomPorEspecie]);

  useEffect(() => {
    if (!ecocardiogramaEstruturado.usar_no_laudo) return;
    const legado = derivarLegadoDeEcocardiogramaEstruturado(ecocardiogramaEstruturado);
    setQualitativa((prev) =>
      qualitativaEcoLegadaIgual(prev, legado.qualitativa) ? prev : legado.qualitativa
    );
    if (legado.conclusao) {
      setConteudo((prev) =>
        prev.conclusao === legado.conclusao
          ? prev
          : { ...prev, conclusao: legado.conclusao }
      );
    }
  }, [ecocardiogramaEstruturado]);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      router.push("/");
      return;
    }
    // Inicializar valores dinâmicos no cliente para evitar hydration mismatch
    setPaciente(prev => ({ ...prev, data_exame: prev.data_exame || operationalTodayDateInput() }));
    setSessionId(Math.random().toString(36).substring(2, 15));
    carregarClinicas();
  }, [router]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const positiveId = (key: string) => {
      const value = Number(params.get(key));
      return Number.isSafeInteger(value) && value > 0 ? value : null;
    };
    const atendimentoId = positiveId("atendimento_id");
    const agendamentoId = positiveId("agendamento_id");
    const pacienteId = positiveId("paciente_id");
    setDraftContextKey(atendimentoId ? `new:atendimento:${atendimentoId}`
      : agendamentoId ? `new:agendamento:${agendamentoId}`
      : pacienteId ? `new:paciente:${pacienteId}` : "new:manual");
    let active = true;
    const initialize = async () => {
      if (!localStorage.getItem("token")) return;
      const clinicaParam = positiveId("clinica_id");
      if (clinicaParam) setClinicaId(String(clinicaParam));
      if (atendimentoId) await preencherDadosDoAtendimento(atendimentoId);
      else if (agendamentoId) {
        setAgendamentoVinculadoId(agendamentoId);
        await preencherDadosDoAgendamento(agendamentoId);
      } else if (pacienteId) await preencherDadosDoPaciente(pacienteId);
    };
    void initialize().finally(() => { if (active) setContextReady(true); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const aoNivelAp = echoLengthInMm(medidas, "Ao_nivel_AP");
    const arteriaPulmonar = echoLengthInMm(medidas, "AP");
    const divedMm = echoLengthInMm(medidas, "DIVEd");
    const peso = parsePesoKg(paciente.peso);

    const apAoCalculado =
      aoNivelAp !== null && aoNivelAp > 0 && arteriaPulmonar !== null && arteriaPulmonar > 0
        ? formatar2Casas(arteriaPulmonar / aoNivelAp)
        : null;

    const divedNormalizadoCalculado =
      isCanineEchoSpecies(paciente.especie) && divedMm !== null && divedMm > 0 && peso !== null && peso > 0
        ? formatar2Casas((divedMm / 10.0) / Math.pow(peso, 0.294))
        : null;

    const atualizacoes: Record<string, string> = {};
    if (apAoCalculado !== null && medidas["AP_Ao"] !== apAoCalculado) {
      atualizacoes.AP_Ao = apAoCalculado;
    }
    if (divedNormalizadoCalculado !== null && medidas["DIVEd_normalizado"] !== divedNormalizadoCalculado) {
      atualizacoes.DIVEd_normalizado = divedNormalizadoCalculado;
    }
    const automaticas = deriveAutomaticEchoMeasurements(medidas, paciente.peso, paciente.especie, paciente.idade);
    Object.entries(automaticas).forEach(([key, value]) => {
      if (medidas[key] !== value) atualizacoes[key] = value;
    });

    if (Object.keys(atualizacoes).length > 0) {
      setMedidas((prev) => ({
        ...prev,
        ...atualizacoes,
      }));
    }
  }, [medidas, paciente.peso, paciente.especie, paciente.idade]);

  useEffect(() => {
    const resolved = calcularIdadeComFonte(paciente, paciente.data_exame);
    if (resolved !== null && resolved !== paciente.idade) {
      setPaciente((prev) => ({ ...prev, idade: resolved }));
    }
  }, [paciente.idade_fonte, paciente.idade_informada, paciente.idade_referencia, paciente.data_nascimento, paciente.data_exame]);

  const carregarClinicas = async () => {
    try {
      const items = await listarTodasClinicas<Clinica>();
      setClinicas(items);
    } catch (error) {
      console.error("Erro ao carregar clínicas:", error);
    }
  };

  const preencherDadosDoAtendimento = async (atendimentoId: number) => {
    try {
      const respAtendimento = await api.get(`/atendimentos/${atendimentoId}`);
      const atendimento = respAtendimento.data || {};

      if (atendimento.paciente_id) {
        await preencherDadosDoPaciente(Number(atendimento.paciente_id));
      }

      if (atendimento.clinica_id) {
        setClinicaId(String(atendimento.clinica_id));
      }
      if (atendimento.clinica_nome) {
        setClinicaNome(atendimento.clinica_nome);
      }

      if (atendimento.agendamento_id) {
        setAgendamentoVinculadoId(Number(atendimento.agendamento_id));
      }

      if (atendimento.observacoes || atendimento.dados_clinicos || atendimento.diagnostico) {
        setConteudo((prev) => ({
          ...prev,
          descricao: prev.descricao || atendimento.dados_clinicos || "",
          conclusao: prev.conclusao || atendimento.diagnostico || "",
          observacoes: prev.observacoes || atendimento.observacoes || "",
        }));
      }

      setMensagemSucesso(`Atendimento #${atendimentoId} vinculado ao laudo.`);
      setTimeout(() => setMensagemSucesso(null), 4000);
    } catch (error) {
      console.error("Erro ao carregar atendimento para laudo:", error);
    }
  };

  const preencherDadosDoAgendamento = async (agendamentoId: number) => {
    try {
      const respAgendamento = await api.get(`/agenda/${agendamentoId}`);
      const agendamento = respAgendamento.data || {};

      let dadosPaciente: any = null;
      if (agendamento.paciente_id) {
        try {
          const respPaciente = await api.get(`/pacientes/${agendamento.paciente_id}`);
          dadosPaciente = respPaciente.data;
        } catch (error) {
          console.warn("Nao foi possivel carregar detalhes do paciente vinculado:", error);
        }
      }

      setPaciente((prev) => ({
        ...prev,
        id: agendamento.paciente_id || prev.id,
        nome: dadosPaciente?.nome || agendamento.paciente || prev.nome,
        tutor: dadosPaciente?.tutor || agendamento.tutor || prev.tutor,
        raca: dadosPaciente?.raca || prev.raca,
        especie: dadosPaciente?.especie || prev.especie || "Canina",
        peso:
          dadosPaciente?.peso_kg !== null && dadosPaciente?.peso_kg !== undefined
            ? String(dadosPaciente.peso_kg)
            : prev.peso,
        ...patientAgeForm(dadosPaciente || {}),
        idade: extrairIdadePaciente(dadosPaciente || {}),
        sexo: normalizarSexoPaciente(dadosPaciente?.sexo || prev.sexo || "Macho") || "Macho",
        telefone: agendamento.telefone || prev.telefone,
        data_exame:
          calendarDateInput(agendamento.data || agendamento.inicio) ||
          prev.data_exame ||
          operationalTodayDateInput(),
      }));

      if (agendamento.clinica_id) {
        setClinicaId(String(agendamento.clinica_id));
      }
      if (agendamento.clinica) {
        setClinicaNome(agendamento.clinica);
      }

      if (agendamento.observacoes) {
        setConteudo((prev) => ({
          ...prev,
          observacoes: prev.observacoes || agendamento.observacoes,
        }));
      }

      setMensagemSucesso(`Agendamento #${agendamentoId} vinculado ao laudo.`);
      setTimeout(() => setMensagemSucesso(null), 4000);
    } catch (error) {
      console.error("Erro ao carregar agendamento para laudo:", error);
    }
  };

  const preencherDadosDoPaciente = async (pacienteId: number) => {
    try {
      const respPaciente = await api.get(`/pacientes/${pacienteId}`);
      const dadosPaciente = respPaciente.data || {};

      setPaciente((prev) => ({
        ...prev,
        id: pacienteId,
        nome: dadosPaciente?.nome || prev.nome,
        tutor: dadosPaciente?.tutor || prev.tutor,
        raca: dadosPaciente?.raca || prev.raca,
        especie: dadosPaciente?.especie || prev.especie || "Canina",
        peso:
          dadosPaciente?.peso_kg !== null && dadosPaciente?.peso_kg !== undefined
            ? String(dadosPaciente.peso_kg)
            : prev.peso,
        ...patientAgeForm(dadosPaciente || {}),
        idade: extrairIdadePaciente(dadosPaciente || {}),
        sexo: normalizarSexoPaciente(dadosPaciente?.sexo || prev.sexo || "Macho") || "Macho",
        data_exame: prev.data_exame || operationalTodayDateInput(),
      }));

      setMensagemSucesso(`Paciente #${pacienteId} carregado para novo laudo.`);
      setTimeout(() => setMensagemSucesso(null), 4000);
    } catch (error) {
      console.error("Erro ao carregar paciente para laudo:", error);
    }
  };

  const handleDadosImportados = (dados: DadosExame) => {
    
    if (dados.paciente) {
      const pesoImportado = parsePesoKg(dados.paciente.peso);
      setPaciente((anterior) => ({
        ...anterior,
        id: dados.paciente.id ?? anterior.id,
        nome: dados.paciente.nome || anterior.nome || "",
        tutor: dados.paciente.tutor || anterior.tutor || "",
        raca: dados.paciente.raca || anterior.raca || "",
        especie: dados.paciente.especie || anterior.especie || "Canina",
        peso: pesoImportado !== null ? String(pesoImportado) : anterior.peso || "",
        ...importedPatientAge(anterior, dados.paciente, dados.paciente.data_exame?.substring(0, 10) || anterior.data_exame),
        sexo: normalizarSexoPaciente(dados.paciente.sexo || anterior.sexo || "Macho") || "Macho",
        telefone: dados.paciente.telefone || anterior.telefone || "",
        data_exame: dados.paciente.data_exame
          ? dados.paciente.data_exame.substring(0, 10)
          : anterior.data_exame || operationalTodayDateInput(),
      }));
    }
    
    if (dados.medidas) {
      const medidasFormatadas = mapImportedEchoMeasurements(dados.medidas);
      importarMedidas(medidasFormatadas);
    } else {
    }

    if (dados.fc) {
      setEcocardiogramaCabecalho((prev) => ({
        ...prev,
        fc: String(dados.fc || "").trim(),
      }));
    }
    
    if (dados.clinica) {
      // Se vier como string, usa direto; se vier como objeto, extrai o id
      if (typeof dados.clinica === 'string') {
        // Buscar clínica pelo nome
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
    
    setMensagemSucesso("Dados importados com sucesso!");
    setTimeout(() => setMensagemSucesso(null), 5000);
  };

  const pasValores = [
    parseInteiroPositivo(pressaoArterial.pas_1),
    parseInteiroPositivo(pressaoArterial.pas_2),
    parseInteiroPositivo(pressaoArterial.pas_3),
  ].filter((v): v is number => v !== null);

  const pasMediaCalculada = pasValores.length
    ? Math.round(pasValores.reduce((acc, item) => acc + item, 0) / pasValores.length)
    : null;

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

  const pressaoPreenchida = Boolean(
    pasValores.length || (pasMediaCalculada !== null && pasMediaCalculada > 0)
  );

  const montarPayloadPressao = () => {
    if (!pressaoPreenchida) return null;
    return {
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
  };

  // Keep serialization metadata stable while the clinical snapshot is unchanged,
  // so the optional preview and the explicit emission share the same intent.
  const estruturaParaPayload = useMemo(() => serializarEcocardiogramaEstruturado(ecocardiogramaEstruturado), [ecocardiogramaEstruturado]);

  const montarPayloadEcocardiograma = (status = "Finalizado") => {
    const medidasPayload = {
      ...medidas,
      ...deriveAutomaticEchoMeasurements(medidas, paciente.peso, paciente.especie, paciente.idade),
    };
    const clinicaPayload = clinicaId
      ? { id: parseInt(clinicaId), nome: clinicaNome }
      : clinicaNome;
    const ecoEstruturadoPayload =
      estruturaParaPayload;
    const legadoEco = ecoEstruturadoPayload?.usar_no_laudo
      ? derivarLegadoDeEcocardiogramaEstruturado(ecoEstruturadoPayload)
      : null;
    const qualitativaPayload = legadoEco?.qualitativa || qualitativa;
    const conteudoPayload =
      ecoEstruturadoPayload?.usar_no_laudo && legadoEco
        ? {
            ...conteudo,
            conclusao: legadoEco.conclusao || conteudo.conclusao,
          }
        : conteudo;

    return {
      paciente,
      medidas: medidasPayload,
      qualitativa: qualitativaPayload,
      conteudo: conteudoPayload,
      agendamento_id: agendamentoVinculadoId,
      clinica: clinicaPayload,
      veterinario: { nome: veterinario },
      data_exame: paciente.data_exame,
      tipo_laudo: "ecocardiograma",
      status,
      pressao_arterial: montarPayloadPressao(),
      ecocardiograma_cabecalho: ecocardiogramaCabecalho,
      ecocardiograma_estruturado: ecoEstruturadoPayload,
    };
  };

  const requestPdfPreview = async (signal: AbortSignal): Promise<Blob> => {
    if (!ensureDraftOwner() || !draftUserId || !editorDraft.canEmit || submission || emissionInProgress.current) {
      throw new Error("Conclua a recuperação e confira a sessão antes de gerar a prévia.");
    }
    if (!paciente.nome.trim()) throw new Error("Preencha o nome do paciente antes de gerar a prévia.");
    const captured = cloneEchoEditorDraftSnapshot(draftSnapshotRef.current);
    const key = echoPreviewSnapshotKey(captured);
    if (captured.imagens.some((image) => !image.uploaded || !image.tempId)) {
      throw new Error("Reenvie ou remova as imagens pendentes antes de gerar a prévia.");
    }
    const payload = montarPayloadEcocardiograma("Finalizado");
    const assertCurrent = () => {
      if (signal.aborted || !ensureDraftOwner() || echoPreviewSnapshotKey(draftSnapshotRef.current) !== key) {
        throw new DOMException("O conteúdo da prévia mudou.", "AbortError");
      }
    };
    const saved = await editorDraft.flush(captured);
    assertCurrent();
    if (!saved) throw new Error("O rascunho não foi confirmado para a prévia.");
    const response = await api.post(`/laudos/editor-drafts/${saved.draft_id}/preview`, {
      expected_revision: saved.revision, payload_laudo: payload, imagens: echoEditorImageSelection(captured),
    }, { signal, responseType: "blob", timeout: 30_000, headers: { "X-Editor-Owner-Id": draftUserId } });
    assertCurrent();
    return response.data;
  };

  const ensureDraftOwner = () => {
    if (draftSessionChanged) return false;
    if (firstDraftUserId.current === null) return !draftApplies;
    let currentOwner: number | null = null;
    try {
      const user = JSON.parse(localStorage.getItem("user") || "null");
      currentOwner = Number(user?.id ?? user?.user_id) || null;
    } catch { /* Preserve the original owner of this mounted form. */ }
    if (currentOwner !== firstDraftUserId.current) {
      setDraftSessionChanged(true);
      return false;
    }
    return true;
  };

  const garantirRascunhoParaDitado = async (): Promise<number> => {
    if (!ensureDraftOwner() || !contextReady || submission || (draftApplies && !editorDraft.canEmit)) {
      throw new Error("Resolva a recuperação ou o salvamento do rascunho antes de iniciar o ditado.");
    }
    if (voiceDraftIdRef.current) return voiceDraftIdRef.current;
    if (!(paciente.nome || "").trim()) {
      throw new Error("Informe ou selecione o paciente antes de iniciar o ditado.");
    }
    if (draftPromiseRef.current) return draftPromiseRef.current;

    const promise = (async () => {
      let started = false;
      try {
        // Dictation is also an explicit clinical creation. Preserve its pending
        // intent before POST so an unknown response cannot create a second draft.
        await editorDraft.flush({ ...draftSnapshotRef.current, submission: { status: "pending", laudoId: null } });
        setSubmission({ status: "pending", laudoId: null });
        started = true;
        const response = await api.post("/laudos", montarPayloadEcocardiograma("Rascunho"));
        const id = Number(response.data?.id);
        if (!Number.isSafeInteger(id) || id <= 0) {
          throw new Error("O rascunho do laudo não foi criado.");
        }
        if (!ensureDraftOwner()) throw new Error("A sessão mudou durante a preparação do ditado. Confira a central de laudos.");
        voiceDraftIdRef.current = id;
        setDraftLaudoId(id);
        // Keep this editor's recovery context until explicit issue. A refresh
        // must recover all later edits, not just the first dictation seed.
        await editorDraft.flush({ ...draftSnapshotRef.current, draftLaudoId: id, submission: undefined });
        setSubmission(undefined);
        setMensagemSucesso(
          "Rascunho preparado. Faça o ditado e revise as sugestões antes de salvar."
        );
        return id;
      } catch (error) {
        const httpStatus = Number((error as any)?.response?.status);
        if (!started || [400, 401, 403, 404, 409, 422, 429].includes(httpStatus)) {
          setSubmission(undefined);
          try { await editorDraft.flush({ ...draftSnapshotRef.current, submission: undefined }); } catch { /* Preserve the last confirmed recovery copy. */ }
        }
        throw error;
      } finally {
        draftPromiseRef.current = null;
      }
    })();
    draftPromiseRef.current = promise;
    return promise;
  };

  const handleEchoAssistantApply = (patch: {
    fields: Record<string, string>;
    measurements: Record<string, string>;
    skipped: string[];
  }) => {
    if (Object.keys(patch.measurements).length) {
      importarMedidas(patch.measurements);
    }
    if (Object.keys(patch.fields).length) {
      setEcocardiogramaEstruturado((previous) => ({
        ...previous,
        usar_no_laudo: true,
        textos: {
          ...previous.textos,
          ...patch.fields,
        },
        updated_at: new Date().toISOString(),
      }));
    }
    setAba(Object.keys(patch.fields).length ? "qualitativa" : "medidas");
    setMensagemSucesso(
      patch.skipped.length
        ? `Sugestões aplicadas ao rascunho. ${patch.skipped.length} item(ns) permaneceram para revisão manual.`
        : "Sugestões aplicadas ao rascunho. Revise antes de salvar."
    );
  };

  const handleSalvar = async () => {
    if (!ensureDraftOwner() || navigationInProgress.current || emissionInProgress.current || submission || !contextReady || (draftApplies && !editorDraft.canEmit)) return;
    emissionInProgress.current = true;
    let clinicalRequestStarted = false;
    let confirmedLaudoId: number | null = null;
    setLoading(true);
    try {
      if (
        hasAnyMeasurement(medidas, LV_M_MODE_KEYS) &&
        hasAnyMeasurement(medidas, LV_2D_KEYS) &&
        !medidas["VE_tecnica_relatorio"]
      ) {
        alert("Escolha se o PDF deve usar as medidas do VE em Modo M ou Modo 2D.");
        setAba("medidas");
        return;
      }
      const pacienteNome = (paciente.nome || "").trim();
      if (!pacienteNome) {
        alert("Nome do paciente é obrigatório.");
        return;
      }

      const pressaoPayload = montarPayloadPressao();
      const tipoLaudo = draftLaudoId
        ? "ecocardiograma"
        : pressaoArterial.salvar_como_laudo_pressao
          ? "pressao_arterial"
          : "ecocardiograma";
      if (tipoLaudo === "pressao_arterial" && !pressaoPayload) {
        alert("Preencha pelo menos uma afericao de pressao para salvar como laudo de pressao arterial.");
        return;
      }

      if (tipoLaudo === "ecocardiograma") {
        if (imagens.some((imagem) => !imagem.uploaded)) {
          setAba("imagens");
          setDraftImageNotice("Há imagens com envio pendente. Reenvie ou remova esses arquivos antes de emitir.");
          return;
        }
        const mensagemAlerta = criarMensagemAlertaSalvamentoEcocardiograma({
          analiseQualitativaAplicada: ecocardiogramaEstruturado.usar_no_laudo,
          imagensCarregadas: imagens.some((imagem) => imagem.uploaded),
        });
        if (mensagemAlerta && !window.confirm(mensagemAlerta)) {
          setAba(
            ecocardiogramaEstruturado.usar_no_laudo ? "imagens" : "qualitativa"
          );
          return;
        }
        // Autosave writes only the private workspace. Drain and pause that
        // queue before the existing, explicit clinical save begins.
        if (draftApplies) await editorDraft.pause();
      }

      // Garante que legendas e ordem opcionais cheguem ao PDF mesmo quando
      // o usuário salva imediatamente após editar uma imagem.
      const imagensEnviadas = imagens.filter((imagem) => imagem.uploaded && imagem.tempId);
      if (imagensEnviadas.length > 0) {
        if (tipoLaudo === "ecocardiograma" && draftApplies) {
          const response = await api.get(`/imagens/temp/session/${encodeURIComponent(sessionId)}`);
          const received = new Set((response.data.items || []).map((image: { id: number }) => image.id));
          const missing = imagensEnviadas.filter((image) => !received.has(image.tempId));
          if (missing.length) {
            const missingIds = new Set(missing.map((image) => image.id));
            setImagens((previous) => previous.map((image) => missingIds.has(image.id)
              ? { ...image, uploaded: false, tempId: undefined, requerReenvio: true } : image));
            setAba("imagens");
            setDraftImageNotice("Algumas imagens temporárias expiraram. Reenvie ou remova esses arquivos antes de emitir.");
            return;
          }
        }
        await api.put(`/imagens/temp/session/${sessionId}/configuracao`, {
          imagens: imagensEnviadas.map((imagem) => ({
            id: imagem.tempId,
            ordem: imagem.ordem,
            incluir_no_pdf: imagem.incluirNoPdf ?? true,
            descricao: imagem.descricao || "",
          })),
        });
      }

      const payload =
        tipoLaudo === "ecocardiograma"
          ? montarPayloadEcocardiograma("Finalizado")
          : {
              paciente,
              medidas,
              qualitativa,
              conteudo,
              agendamento_id: agendamentoVinculadoId,
              clinica: clinicaId
                ? { id: parseInt(clinicaId), nome: clinicaNome }
                : clinicaNome,
              veterinario: { nome: veterinario },
              data_exame: paciente.data_exame,
              tipo_laudo: tipoLaudo,
              pressao_arterial: pressaoPayload,
              ecocardiograma_cabecalho: null,
              ecocardiograma_estruturado: null,
            };

      const preparedVoiceId = voiceDraftIdRef.current || (draftPromiseRef.current ? await draftPromiseRef.current : null);
      if (tipoLaudo === "ecocardiograma" && draftApplies) {
        const pending = { status: "pending" as const, laudoId: null };
        await editorDraft.flush({ ...draftSnapshotRef.current, submission: pending });
        setSubmission(pending);
      }
      clinicalRequestStarted = true;
      const response =
        tipoLaudo === "ecocardiograma" && preparedVoiceId
          ? await api.put(`/laudos/${preparedVoiceId}`, payload)
          : await api.post("/laudos", payload);
      const laudoId = response.data.id;
      if (!Number.isSafeInteger(laudoId) || laudoId <= 0) throw new Error("A emissão precisa ser conferida na central de laudos.");
      confirmedLaudoId = laudoId;
      if (tipoLaudo === "ecocardiograma" && draftApplies) {
        const confirmed = { status: "confirmed" as const, laudoId };
        setSubmission(confirmed);
        try { await editorDraft.flush({ ...draftSnapshotRef.current, submission: confirmed }); }
        catch { /* Never retry clinical creation after its ID was confirmed. */ }
      }
      
      // Associar imagens ao laudo se houver imagens enviadas
      if (imagens.length > 0 && imagens.some(img => img.uploaded)) {
        try {
          await api.post(`/imagens/associar/${laudoId}?session_id=${sessionId}`);
          if (tipoLaudo === "ecocardiograma" && draftApplies) {
            const associated = (await api.get(`/imagens/laudo/${laudoId}`)).data.items;
            if (!Array.isArray(associated)) throw new Error("A associação das imagens não foi confirmada.");
            const remaining = [...associated];
            for (const expected of imagensEnviadas) {
              const index = remaining.findIndex((image) => image.nome === expected.nome
                && image.tamanho === expected.tamanho && (image.descricao || "") === (expected.descricao || "")
                && Boolean(image.incluir_no_pdf) === (expected.incluirNoPdf ?? true));
              if (index < 0) throw new Error("A associação das imagens não foi confirmada.");
              remaining.splice(index, 1);
            }
          }
        } catch (imgError) {
          console.error("Erro ao associar imagens:", imgError);
          setDraftImageNotice(`O laudo #${laudoId} foi emitido, mas a associação das imagens não foi confirmada. Confira o laudo antes de qualquer nova emissão.`);
          return;
        }
      }

      if (tipoLaudo === "ecocardiograma" && draftApplies) {
        // Failure to retire a workspace cannot turn a confirmed emission into
        // an apparent clinical failure that invites a duplicate submission.
        try { await editorDraft.close(); }
        catch { setMensagemSucesso("Laudo emitido. O encerramento do rascunho precisa ser conferido."); }
      }
      
      alert("Laudo salvo com sucesso!");
      router.push("/laudos");
    } catch (error) {
      console.error("Erro ao salvar laudo:", error);
      const detail = (error as any)?.response?.data?.detail;
      const httpStatus = Number((error as any)?.response?.status);
      if (clinicalRequestStarted && !confirmedLaudoId && ![400, 401, 403, 404, 409, 422, 429].includes(httpStatus)) {
        setSubmission({ status: "pending", laudoId: null });
        alert("A resposta da emissão não foi confirmada. Confira a central de laudos antes de tentar novamente; seu rascunho foi preservado.");
        return;
      }
      if (!confirmedLaudoId) {
        setSubmission(undefined);
        try { await editorDraft.flush({ ...draftSnapshotRef.current, submission: undefined }); } catch { /* Keep the recovery copy. */ }
      }
      alert(typeof detail === "string" && detail.trim() ? detail : "Erro ao salvar laudo");
    } finally {
      emissionInProgress.current = false;
      editorDraft.resume();
      setLoading(false);
    }
  };

  const leaveEditor = async (href: string) => {
    if (!ensureDraftOwner() || !contextReady || emissionInProgress.current || navigationInProgress.current) return;
    navigationInProgress.current = true;
    setLeaving(true);
    setDraftNavigationNotice(null);
    try {
      if (draftPromiseRef.current) await draftPromiseRef.current;
      if (draftApplies && !submission) {
        await editorDraft.flush();
        if (editorDraft.pendingImages > 0 && !window.confirm("Há arquivos ainda não recebidos que precisarão ser reenviados ao retomar. Sair mesmo assim?")) return;
      }
      router.push(href);
    } catch {
      setDraftNavigationNotice("Não foi possível confirmar o rascunho antes de sair. Mantenha esta tela aberta e tente salvar novamente.");
    } finally {
      navigationInProgress.current = false;
      setLeaving(false);
    }
  };
  navigationHandler.current = leaveEditor;

  const handleMedidaChange = (key: string, value: string) => {
    if (normalizeEchoSpecies(paciente.especie) === "Canina" && NEW_REPORT_PROTOCOL_KEYS.includes(key)) {
      setProtocolMeasurement(key, value);
      return;
    }
    setMedidas(prev => ECHO_OUTFLOW_KEYS.has(key)
      ? updateEchoOutflowMeasurement(prev, key, value)
      : updateFelineDiastolicMeasurement(prev, key, value, paciente.especie));
  };

  const estruturadoParaConferencia = serializarEcocardiogramaEstruturado(ecocardiogramaEstruturado);
  const legadoParaConferencia = estruturadoParaConferencia?.usar_no_laudo
    ? derivarLegadoDeEcocardiogramaEstruturado(estruturadoParaConferencia) : null;
  const qualitativaParaConferencia = legadoParaConferencia?.qualitativa || qualitativa;
  const conclusaoParaConferencia = estruturadoParaConferencia?.usar_no_laudo && legadoParaConferencia
    ? legadoParaConferencia.conclusao || conteudo.conclusao : conteudo.conclusao;
  const vistaIndice2D = medidas.VE_vista_2D === "eixo_curto" || medidas.VE_vista_2D === "eixo_longo"
    ? medidas.VE_vista_2D as Echo2DView : "";
  const pesoIndice2D = parsePesoKg(paciente.peso);
  const indice2D = calculateCanine2DNormalizedLVIDd(
    echoLengthInMm(medidas, "DIVEd_2D"), pesoIndice2D, vistaIndice2D, paciente.especie, paciente.idade,
  );
  const faixaIndice2D = indice2D === null ? null : getCanine2DReference(
    "DIVEd_normalizado_2D", pesoIndice2D ?? undefined, vistaIndice2D, paciente.idade,
  );

  if (draftSessionChanged) return <DashboardLayout>
    <div role="alert" className="m-6 rounded-lg border border-amber-300 bg-amber-50 p-5 text-amber-900">
      <p className="font-semibold">A sessão do usuário mudou.</p>
      <p className="mt-2">Reabra o formulário na conta correta para recuperar o rascunho. Este preenchimento não será gravado em outra conta.</p>
      <Link className="mt-3 inline-block font-semibold underline" href="/laudos">Abrir central de laudos</Link>
    </div>
  </DashboardLayout>;

  return (
    <DashboardLayout>
      <div className="fc-report-editor-page">
        <header className="fc-report-editor-header">
          <div className="fc-report-editor-heading">
            <button
              type="button"
              onClick={() => { void leaveEditor("/laudos"); }}
              disabled={loading || leaving || !contextReady}
              className="fc-report-editor-back"
              aria-label="Voltar para laudos"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div>
              <span className="fc-report-editor-kicker">
                <Heart className="h-4 w-4" />
                Central diagnóstica
              </span>
              <h1>
                {entradaPressao ? "Novo Laudo de Pressao Arterial" : "Novo Laudo"}
              </h1>
              <p>
                {entradaPressao
                  ? "Fluxo rapido para afericoes manuais e PDF dedicado"
                  : "Importe XML ou preencha manualmente"}
              </p>
              {agendamentoVinculadoId && (
                <p className="text-sm text-teal-700 font-medium mt-1">
                  Agendamento vinculado: #{agendamentoVinculadoId}
                </p>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
          {!entradaPressao && !pressaoArterial.salvar_como_laudo_pressao && (
            <button type="button" onClick={() => { void editorDraft.flush().catch(() => {}); }}
              disabled={loading || leaving || !contextReady || editorDraft.blocked || !draftUserId}
              className="rounded-lg border border-white/60 bg-white/95 px-4 py-3 text-sm font-semibold text-teal-900 disabled:opacity-50">
              Salvar rascunho
            </button>
          )}
          <button
            type="button"
            onClick={handleSalvar}
            disabled={loading || leaving || Boolean(submission) || !contextReady || (draftApplies && !editorDraft.canEmit)}
            className="fc-report-editor-save"
          >
            <Save className="w-4 h-4" />
            {loading ? "Salvando..." : entradaPressao ? "Salvar Laudo de PA" : "Emitir laudo"}
          </button>
          </div>
        </header>

        {!entradaPressao && !pressaoArterial.salvar_como_laudo_pressao && <EchoDraftStatus draft={editorDraft} />}
        {contextReady && draftApplies && !draftUserId && <div role="alert" className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Não foi possível identificar o usuário do rascunho. Reabra o sistema na conta correta antes de iniciar o ditado ou emitir.
        </div>}
        {draftNavigationNotice && <div role="alert" className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">{draftNavigationNotice}</div>}
        {submission && <div role="status" className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          <p>{submission.laudoId ? `Laudo #${submission.laudoId} já emitido. Confira o documento e as imagens.`
            : "Há uma tentativa de salvamento sem resposta confirmada. Confira a central antes de salvar novamente."}</p>
          <a className="mt-2 inline-block font-semibold underline" target="_blank" rel="noreferrer"
            href={submission.laudoId ? `/laudos/${submission.laudoId}` : "/laudos"}>Conferir na central de laudos</a>
          {!submission.laudoId && <button type="button" className="ml-4 font-semibold underline" onClick={() => {
            if (window.confirm("Você conferiu a central e confirmou que nenhum laudo foi emitido nesta tentativa?")) {
              setSubmission(undefined);
              void editorDraft.flush({ ...draftSnapshotRef.current, submission: undefined }).catch(() => {});
            }
          }}>Confirmei que não foi emitido; retomar rascunho</button>}
        </div>}
        {draftImageNotice && <div role="status" className="my-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">{draftImageNotice}</div>}

        {draftApplies && <EchoFinalReview
          snapshotKey={echoPreviewSnapshotKey(draftSnapshot)} scopeKey={`${draftUserId}:${draftContextKey}`}
          disabled={loading || leaving || !contextReady || Boolean(submission) || !draftUserId || !editorDraft.canEmit}
          issues={buildEchoFinalReviewIssues({ measurements: medidas, species: paciente.especie,
            qualitative: qualitativaParaConferencia, conclusion: conclusaoParaConferencia,
            patientName: paciente.nome, qualitativeApplied: ecocardiogramaEstruturado.usar_no_laudo,
            images: imagens.map((image) => ({ uploaded: image.uploaded, included: image.incluirNoPdf !== false })) })}
          imageCount={imagens.filter((image) => image.uploaded && image.incluirNoPdf !== false).length}
          requestPreview={requestPdfPreview} onNavigate={(target) => navigateEchoFinalReview(target, setAba)} />}

        <fieldset disabled={loading || leaving || !contextReady || (draftApplies && ["loading", "recovery"].includes(editorDraft.status))} className="min-w-0">
        <div className="fc-report-editor-layout">
          {/* Coluna Esquerda - Importadores */}
          <aside className="fc-report-editor-sidebar">
            {entradaPressao ? (
              <div className="fc-report-editor-side-card space-y-4">
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  <Heart className="w-5 h-5 text-teal-600" />
                  Fluxo de PA
                </h2>

                {mensagemSucesso && (
                  <div className="p-3 bg-green-100 border border-green-300 text-green-800 rounded-lg text-sm">
                    {mensagemSucesso}
                  </div>
                )}

                <div className="rounded-lg border border-teal-100 bg-teal-50 p-4 text-sm text-teal-900">
                  <p className="font-semibold">Entrada dedicada para pressao arterial</p>
                  <p className="mt-2">
                    Use este fluxo quando o exame principal do atendimento for a afericao de pressao arterial.
                  </p>
                </div>

                <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                  <p className="font-semibold">Como preencher</p>
                  <ul className="mt-2 list-disc space-y-1 pl-5">
                    <li>Informe as 3 afericoes de PAS, quando disponiveis.</li>
                    <li>Registre manguito, membro e decubito usados no exame.</li>
                    <li>Revise a opcao para salvar como laudo de pressao arterial antes de concluir.</li>
                  </ul>
                </div>

                <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                  Se quiser manter a PA dentro de um laudo ecocardiografico, voce pode desmarcar a opcao de laudo dedicado na aba
                  de pressao e seguir usando o restante do editor.
                </div>
              </div>
            ) : (
              <>
                <EchoVoiceAssistant
                  laudoId={draftLaudoId ?? undefined}
                  resolveLaudoId={garantirRascunhoParaDitado}
                  currentFields={{
                    ...ecocardiogramaEstruturado.textos,
                    conclusao:
                      ecocardiogramaEstruturado.textos.conclusao ||
                      conteudo.conclusao,
                  }}
                  currentMeasurements={medidas}
                  onApply={handleEchoAssistantApply}
                />

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
                      <strong>Dica:</strong> Arraste o arquivo XML exportado do aparelho de ecocardiograma (Vivid IQ) para preencher automaticamente os dados do paciente e medidas.
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
                      <strong>Dica:</strong> Envie a imagem/PDF convertido em imagem gerado pelo equipamento para preencher automaticamente campos do cabecalho (paciente, tutor, especie, raca, sexo, idade e data).
                    </p>
                  </div>
                </div>
              </>
            )}

          </aside>

          {/* Coluna Direita - Formulário */}
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
                          value={paciente.nome}
                          onChange={(e) => setPaciente({...paciente, nome: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                      
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Tutor
                        </label>
                        <input
                          type="text"
                          value={paciente.tutor}
                          onChange={(e) => setPaciente({...paciente, tutor: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                      
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">
                          Espécie
                        </label>
                        <select
                          value={paciente.especie}
                          onChange={(e) => {
                            const especie = e.target.value;
                            if (!isFelineEchoSpecies(especie) && temPresetDiastolicoFelinoAplicado(ecocardiogramaEstruturado)) {
                              if (!window.confirm("Este laudo contém uma descrição diastólica felina. Trocar a espécie removerá essa descrição; os demais achados serão preservados. Deseja continuar?")) return;
                              setEcocardiogramaEstruturado(removerPresetDiastolicoFelino(ecocardiogramaEstruturado));
                            }
                            setPaciente({ ...paciente, especie, raca: "" });
                            setNovaRaca("");
                          }}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="Canina">Canina</option>
                          <option value="Felina">Felina</option>
                          {isCanineEchoSpecies(paciente.especie) && paciente.especie !== "Canina" && (
                            <option value={paciente.especie}>{paciente.especie} (canina)</option>
                          )}
                          {isFelineEchoSpecies(paciente.especie) && paciente.especie !== "Felina" && (
                            <option value={paciente.especie}>{paciente.especie} (felina)</option>
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
                          value={paciente.raca}
                          onChange={(e) => setPaciente({...paciente, raca: e.target.value})}
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
                          value={paciente.sexo}
                          onChange={(e) => setPaciente({...paciente, sexo: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="Macho">Macho</option>
                          <option value="Fêmea">Fêmea</option>
                        </select>
                      </div>
                      
                      <PatientAgeFields value={paciente} referenceDate={paciente.data_exame} onChange={(patch) => setPaciente((prev) => ({ ...prev, ...patch }))} />

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
                          value={paciente.peso}
                          onChange={(e) => setPaciente({...paciente, peso: e.target.value})}
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
                          value={paciente.data_exame}
                          onChange={(e) => setPaciente({...paciente, data_exame: e.target.value})}
                          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                        />
                      </div>
                    </div>

                    <div className="border-t pt-4 mt-4">
                      <h4 className="font-medium text-gray-900 mb-4">Informações da Clínica</h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
                            Veterinário Solicitante
                          </label>
                          <input
                            type="text"
                            value={veterinario}
                            onChange={(e) => setVeterinario(e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500"
                          />
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
                        {isCanineEchoSpecies(paciente.especie) && <MedidaInput
                          label="DIVEd normalizado (DIVEd [cm] / peso^0,294)"
                          value={medidas["DIVEd_normalizado"] || ""}
                          onChange={(v) => handleMedidaChange("DIVEd_normalizado", v)}
                          readOnly
                          reference={isCanineEchoSpecies(paciente.especie) && (parsePesoKg(paciente.peso) ?? 0) >= 2.2 && (parsePesoKg(paciente.peso) ?? 0) <= 95
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

                        {isFelineEchoSpecies(paciente.especie) && (
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
                        <FelineWaveReview especie={paciente.especie} medidas={medidas}
                          onMedidaChange={handleMedidaChange}
                          onDiscard={(kind) => setMedidas(prev => discardFelineFusedMeasurements(prev, paciente.especie, kind))}
                        />
                        <EchoNarrativeConsistencyNotice
                          species={paciente.especie}
                          measurements={medidas}
                          qualitative={qualitativaParaConferencia}
                          conclusion={conclusaoParaConferencia}
                        />
                        
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
                          readOnly={!isFelineEchoSpecies(paciente.especie) || isEchoDiastolicRatioCalculated(medidas, paciente.peso, paciente.especie, "E_A")}
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
                          readOnly={!isFelineEchoSpecies(paciente.especie) || isEchoDiastolicRatioCalculated(medidas, paciente.peso, paciente.especie, "E_TRIV")}
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
                          readOnly={isFelineEchoSpecies(paciente.especie) && isEchoDiastolicRatioCalculated(medidas, paciente.peso, paciente.especie, "doppler_tecidual_relacao")}
                        />
                        <MedidaInput 
                          label="E/E' (adimensional)"
                          value={medidas["E_E_linha"] || ""}
                          onChange={(v) => handleMedidaChange("E_E_linha", v)}
                          readOnly={!isFelineEchoSpecies(paciente.especie) || isEchoDiastolicRatioCalculated(medidas, paciente.peso, paciente.especie, "E_E_linha")}
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
                          reference="Estimativa complementar; revisar a avaliação de HP e confirmar ausência de obstrução da via de saída do VD. Não gradua a probabilidade de HP."
                        />
                      </div>
                    </div>

                    <div data-echo-review-target="pulmonary"><EchoPulmonaryHypertension species={paciente.especie} measurements={medidas}
                      onPatch={(patch) => setMedidas((previous) => ({ ...previous, ...patch }))} /></div>

                    <div className="border-t pt-6">
                      <h4 className="mb-4 text-sm font-semibold text-gray-900">VE - Modo 2D</h4>
                      {isFelineEchoSpecies(paciente.especie) && <p className="mb-3 text-xs text-gray-600">Verifique o ponto de maior espessura do septo e da parede livre nos eixos curto e longo; descreva hipertrofia focal na análise qualitativa.</p>}
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
                    <EchoNarrativeConsistencyNotice
                      species={paciente.especie}
                      measurements={medidas}
                      qualitative={qualitativaParaConferencia}
                      conclusion={conclusaoParaConferencia}
                    />
                    <div className="mb-4">
                      <div>
                        <h3 className="font-medium text-gray-900">Qualitativa Detalhada</h3>
                        <span className="text-sm text-gray-500">
                          Use o editor estruturado como fonte principal. O bloco qualitativo legado eh gerado automaticamente ao salvar para compatibilidade do PDF.
                        </span>
                      </div>
                    </div>

                    <EcocardiogramaEstruturadoEditor
                      value={ecocardiogramaEstruturado}
                      onChange={setEcocardiogramaEstruturado}
                      especie={paciente.especie}
                    />

                    {ecocardiogramaEstruturado.usar_no_laudo ? (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        Para ajustar a conclusao oficial, edite o aspecto &quot;Conclusao&quot; no bloco estruturado acima.
                      </div>
                    ) : null}

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Conclusão
                      </label>
                      <textarea
                        value={conteudo.conclusao}
                        onChange={(e) => setConteudo({ ...conteudo, conclusao: e.target.value })}
                        rows={4}
                        readOnly={ecocardiogramaEstruturado.usar_no_laudo}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-teal-500 read-only:bg-gray-50"
                        placeholder="Conclusão diagnóstica..."
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
                        {imagens.length} imagem(ns)
                      </span>
                    </div>
                    
                    <ImageUploader 
                      onImagensChange={setImagens}
                      sessionId={sessionId}
                      imagensIniciais={imagens}
                    />
                    
                    <div className="mt-4 p-4 bg-blue-50 rounded-lg">
                      <p className="text-sm text-blue-800">
                        <strong>Dica:</strong> Clique em uma imagem para ampliá-la. As imagens serão inseridas automaticamente no PDF do laudo.
                        Arraste para reordenar, desmarque as que não devem entrar no PDF ou clique no X para remover.
                      </p>
                    </div>
                  </div>
                )}

                {aba === "pressao" && (
                  <div className="space-y-6">
                    <div>
                      <h3 className="font-medium text-gray-900">Laudo de Pressao Arterial</h3>
                      <p className="text-sm text-gray-500 mt-1">
                        Preencha as afericoes manualmente. Se marcar a opcao abaixo, o laudo sera salvo como
                        &quot;pressao arterial&quot; e o PDF sera gerado no formato dedicado.
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

                    <label className="flex items-start gap-3 p-3 border border-gray-200 rounded-lg">
                      <input
                        type="checkbox"
                        checked={pressaoArterial.salvar_como_laudo_pressao}
                        onChange={(e) =>
                          setPressaoArterial((prev) => ({
                            ...prev,
                            salvar_como_laudo_pressao: e.target.checked,
                          }))
                        }
                        className="mt-1 h-4 w-4 text-teal-600 border-gray-300 rounded"
                      />
                      <span className="text-sm text-gray-700">
                        Salvar como <strong>laudo de pressao arterial</strong> (PDF dedicado). Se desmarcado,
                        os dados de pressao ficam anexados ao laudo ecocardiografico.
                      </span>
                    </label>
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
                      especie={paciente.especie}
                      peso={parsePesoKg(paciente.peso) ?? undefined}
                      idade={paciente.idade}
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
