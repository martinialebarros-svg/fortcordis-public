"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  CircleStop,
  FileAudio,
  Loader2,
  Mic,
  Pause,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import api from "@/lib/axios";

interface EchoConfig {
  enabled: boolean;
  feature_flag_enabled: boolean;
  provider_configured: boolean;
  max_audio_bytes: number;
  max_audio_seconds: number;
  retention_hours: number;
}

interface EchoSuggestion {
  id: string;
  field_key: string;
  suggested_value: string;
  confidence: number;
  source_spans: string[];
  evidence_type: "fact" | "inference" | "diagnostic_suggestion";
  status: string;
}

interface EchoMeasurement {
  id: string;
  canonical_name: string;
  display_name: string;
  numeric_value: number | null;
  raw_value: string | null;
  unit: string | null;
  target_field_key: string | null;
  source_text: string;
  confidence: number;
  status: string;
}

interface EchoWarning {
  id: string;
  warning_type: string;
  severity: "info" | "warning" | "critical";
  message: string;
  related_fields: string[];
}

interface EchoSession {
  id: string;
  status:
    | "created"
    | "uploading"
    | "transcribing"
    | "structuring"
    | "awaiting_review"
    | "applied"
    | "rejected"
    | "failed";
  last_error?: { code: string; message: string } | null;
  audio?: {
    id: string;
    mime_type: string;
    duration_seconds: number | null;
    size_bytes: number;
    expires_at: string;
  } | null;
  transcript?: {
    id: string;
    raw_text: string;
    edited_text: string;
    language: string;
    confidence: number | null;
  } | null;
  field_suggestions: EchoSuggestion[];
  measurements: EchoMeasurement[];
  warnings: EchoWarning[];
  applications: Array<{
    id: string;
    mode: string;
    created_at: string;
    report_persisted: boolean;
  }>;
}

interface EchoPreferences {
  vocabulary: Array<{
    spoken_form: string;
    canonical_form: string;
    category: string;
    active: boolean;
  }>;
  phrases: Array<{
    field_key: string;
    phrase_text: string;
    tags: string[];
    active: boolean;
  }>;
}

interface EchoPatch {
  fields: Record<string, string>;
  measurements: Record<string, string>;
  skipped: string[];
}

interface EchoVoiceAssistantProps {
  laudoId?: number;
  resolveLaudoId?: () => Promise<number>;
  currentFields: Record<string, string>;
  currentMeasurements: Record<string, string>;
  onApply: (patch: EchoPatch) => void;
}

type RecorderState = "idle" | "recording" | "paused" | "ready";
type ApplyMode = "replace" | "append" | "empty_only";

const FIELD_LABELS: Record<string, string> = {
  valva_mitral: "Valva mitral",
  valva_aortica: "Valva aórtica",
  valva_tricuspide: "Valva tricúspide",
  valva_pulmonar: "Valva pulmonar",
  atrio_esquerdo: "Átrio esquerdo",
  ventriculo_esquerdo: "Ventrículo esquerdo",
  funcao_sistolica_ve: "Função sistólica do VE",
  funcao_diastolica: "Função diastólica",
  atrio_direito: "Átrio direito",
  ventriculo_direito: "Ventrículo direito",
  septos: "Septos",
  aorta: "Aorta",
  arteria_pulmonar: "Artéria pulmonar",
  pericardio: "Pericárdio",
  conclusao: "Conclusão",
};

const sleep = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

function formatTime(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function confidenceLabel(confidence: number): string {
  if (confidence < 0.65) return "Baixa confiança";
  if (confidence < 0.8) return "Revisar";
  return `${Math.round(confidence * 100)}%`;
}

function errorMessage(error: any, fallback: string): string {
  return (
    error?.userMessage ||
    error?.response?.data?.detail ||
    error?.message ||
    fallback
  );
}

function extensionForMimeType(mimeType: string): string {
  if (mimeType.includes("mp4")) return "m4a";
  if (mimeType.includes("mpeg")) return "mp3";
  if (mimeType.includes("wav")) return "wav";
  return "webm";
}

export default function EchoVoiceAssistant({
  laudoId,
  resolveLaudoId,
  currentFields,
  currentMeasurements,
  onApply,
}: EchoVoiceAssistantProps) {
  const [config, setConfig] = useState<EchoConfig | null>(null);
  const [open, setOpen] = useState(false);
  const [session, setSession] = useState<EchoSession | null>(null);
  const [recorderState, setRecorderState] = useState<RecorderState>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioName, setAudioName] = useState("ditado-ecocardiograma.webm");
  const [audioUrl, setAudioUrl] = useState("");
  const [editedTranscript, setEditedTranscript] = useState("");
  const [editedSuggestionTexts, setEditedSuggestionTexts] = useState<Record<string, string>>({});
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<string>>(new Set());
  const [selectedMeasurements, setSelectedMeasurements] = useState<Set<string>>(new Set());
  const [applyMode, setApplyMode] = useState<ApplyMode>("replace");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [preferencesOpen, setPreferencesOpen] = useState(false);
  const [vocabularyText, setVocabularyText] = useState("");
  const [phrasesText, setPhrasesText] = useState("");
  const [preferencesLoading, setPreferencesLoading] = useState(false);
  const [resolvedLaudoId, setResolvedLaudoId] = useState<number | null>(
    laudoId ?? null
  );

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (laudoId) setResolvedLaudoId(laudoId);
  }, [laudoId]);

  useEffect(() => {
    let mounted = true;
    api
      .get<EchoConfig>("/ai/echo-sessions/config")
      .then((response) => {
        if (mounted) setConfig(response.data);
      })
      .catch(() => {
        if (mounted) setConfig(null);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const openAssistant = async () => {
    setError("");
    if (resolvedLaudoId) {
      setOpen(true);
      return;
    }
    if (!resolveLaudoId) {
      setError("Não foi possível preparar o rascunho para o ditado.");
      return;
    }
    setBusy(true);
    try {
      const nextLaudoId = await resolveLaudoId();
      setResolvedLaudoId(nextLaudoId);
      setOpen(true);
    } catch (draftError) {
      setError(
        errorMessage(
          draftError,
          "Preencha os dados mínimos do paciente para iniciar o ditado."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      mediaRecorderRef.current?.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  const processing =
    busy || session?.status === "transcribing" || session?.status === "structuring";
  const hasSuggestions = Boolean(
    session?.field_suggestions?.length || session?.measurements?.length
  );
  const selectableMeasurements = useMemo(
    () =>
      (session?.measurements || []).filter(
        (item) => item.target_field_key && item.status === "pending"
      ),
    [session?.measurements]
  );

  const clearRecording = () => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl("");
    setAudioBlob(null);
    setAudioName("ditado-ecocardiograma.webm");
    setElapsedSeconds(0);
    setRecorderState("idle");
  };

  const resetDictationState = () => {
    clearRecording();
    setSession(null);
    setEditedTranscript("");
    setEditedSuggestionTexts({});
    setSelectedSuggestions(new Set());
    setSelectedMeasurements(new Set());
  };

  const stopTracks = () => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  };

  const stopTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const startRecording = async () => {
    setError("");
    setNotice("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Este navegador não oferece gravação de áudio. Envie um arquivo já gravado.");
      return;
    }
    try {
      clearRecording();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
      ];
      const mimeType = candidates.find((item) => MediaRecorder.isTypeSupported(item));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stopTimer();
        stopTracks();
        const recordedType = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: recordedType });
        const url = URL.createObjectURL(blob);
        setAudioBlob(blob);
        setAudioUrl(url);
        setAudioName(`ditado-ecocardiograma.${extensionForMimeType(recordedType)}`);
        setRecorderState("ready");
      };
      mediaRecorderRef.current = recorder;
      recorder.start(250);
      setRecorderState("recording");
      setElapsedSeconds(0);
      timerRef.current = setInterval(() => {
        setElapsedSeconds((previous) => {
          const next = previous + 1;
          if (next >= (config?.max_audio_seconds || 600)) {
            mediaRecorderRef.current?.stop();
          }
          return next;
        });
      }, 1000);
    } catch (recordingError: any) {
      stopTracks();
      const denied =
        recordingError?.name === "NotAllowedError" ||
        recordingError?.name === "PermissionDeniedError";
      setError(
        denied
          ? "Permissão do microfone negada. Autorize o acesso ou envie um arquivo de áudio."
          : "Não foi possível acessar o microfone. Verifique o dispositivo e tente novamente."
      );
    }
  };

  const pauseOrResume = () => {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    if (recorder.state === "recording") {
      recorder.pause();
      stopTimer();
      setRecorderState("paused");
    } else if (recorder.state === "paused") {
      recorder.resume();
      timerRef.current = setInterval(
        () => setElapsedSeconds((previous) => previous + 1),
        1000
      );
      setRecorderState("recording");
    }
  };

  const stopRecording = () => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  };

  const selectAudioFile = (file: File | null) => {
    if (!file) return;
    setError("");
    if (config && file.size > config.max_audio_bytes) {
      setError("O arquivo excede o limite de tamanho permitido.");
      return;
    }
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioBlob(file);
    setAudioName(file.name);
    setAudioUrl(URL.createObjectURL(file));
    setElapsedSeconds(0);
    setRecorderState("ready");
  };

  const pollSession = async (
    sessionId: string,
    ready: (next: EchoSession) => boolean
  ): Promise<EchoSession> => {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await api.get<EchoSession>(`/ai/echo-sessions/${sessionId}`);
      const next = response.data;
      setSession(next);
      if (next.status === "failed") {
        throw new Error(next.last_error?.message || "O processamento falhou.");
      }
      if (ready(next)) return next;
      await sleep(1000);
    }
    throw new Error("O processamento está demorando mais que o esperado. Tente novamente.");
  };

  const transcribeAudio = async () => {
    if (!audioBlob) {
      setError("Grave ou selecione um áudio antes de processar.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("Enviando áudio com proteção temporária...");
    try {
      if (!resolvedLaudoId) {
        throw new Error("O rascunho do laudo ainda não foi preparado.");
      }
      const created = await api.post<EchoSession>("/ai/echo-sessions", {
        laudo_id: resolvedLaudoId,
      });
      const sessionId = created.data.id;
      setSession(created.data);
      const formData = new FormData();
      formData.append("file", audioBlob, audioName);
      if (elapsedSeconds > 0) {
        formData.append("duration_seconds", String(elapsedSeconds));
      }
      await api.post(`/ai/echo-sessions/${sessionId}/audio`, formData);
      await api.post(`/ai/echo-sessions/${sessionId}/transcribe`);
      setNotice("Transcrevendo. Você pode continuar preenchendo o laudo.");
      const next = await pollSession(
        sessionId,
        (item) => item.status === "awaiting_review" && Boolean(item.transcript)
      );
      setEditedTranscript(next.transcript?.edited_text || "");
      setNotice("Transcrição pronta. Revise o texto antes de gerar sugestões.");
    } catch (processingError) {
      setError(errorMessage(processingError, "Não foi possível transcrever o áudio."));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const structureTranscript = async () => {
    if (!session?.id || !editedTranscript.trim()) return;
    setBusy(true);
    setError("");
    setNotice("Organizando achados no esquema clínico do FortCordis...");
    try {
      await api.post(`/ai/echo-sessions/${session.id}/structure`, {
        edited_transcript: editedTranscript,
        current_measurements: currentMeasurements,
      });
      const next = await pollSession(
        session.id,
        (item) => item.status === "awaiting_review"
      );
      setSelectedSuggestions(new Set());
      setSelectedMeasurements(new Set());
      setEditedSuggestionTexts(
        Object.fromEntries(
          next.field_suggestions.map((item) => [item.id, item.suggested_value])
        )
      );
      setNotice("Sugestões prontas. Nada foi aplicado ao laudo.");
      setSession(next);
    } catch (processingError) {
      setError(errorMessage(processingError, "Não foi possível estruturar a transcrição."));
      setNotice("");
    } finally {
      setBusy(false);
    }
  };

  const selectAll = () => {
    setSelectedSuggestions(
      new Set(
        (session?.field_suggestions || [])
          .filter((item) => item.status === "pending")
          .map((item) => item.id)
      )
    );
    setSelectedMeasurements(new Set(selectableMeasurements.map((item) => item.id)));
  };

  const applySelected = async () => {
    if (!session) return;
    if (!selectedSuggestions.size && !selectedMeasurements.size) {
      setError("Selecione ao menos uma sugestão ou medida.");
      return;
    }
    const replacesExisting =
      applyMode === "replace" &&
      [
        ...(session.field_suggestions || [])
          .filter((item) => selectedSuggestions.has(item.id))
          .map((item) => currentFields[item.field_key]),
        ...selectableMeasurements
          .filter((item) => selectedMeasurements.has(item.id))
          .map((item) =>
            item.target_field_key
              ? currentMeasurements[item.target_field_key]
              : ""
          ),
      ].some((value) => String(value || "").trim());
    if (
      replacesExisting &&
      !window.confirm(
        "Há campos preenchidos entre os selecionados. Confirmar a substituição no formulário?"
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await api.post<{
        patch: EchoPatch;
        report_persisted: boolean;
        requires_normal_save: boolean;
      }>(`/ai/echo-sessions/${session.id}/apply`, {
        confirmed: true,
        accepted_suggestion_ids: Array.from(selectedSuggestions),
        accepted_measurement_ids: Array.from(selectedMeasurements),
        suggestion_overrides: Object.fromEntries(
          (session.field_suggestions || [])
            .filter((item) => selectedSuggestions.has(item.id))
            .map((item) => [
              item.id,
              editedSuggestionTexts[item.id] || item.suggested_value,
            ])
        ),
        mode: applyMode,
        current_fields: currentFields,
        current_measurements: currentMeasurements,
      });
      onApply(response.data.patch);
      setSession((previous) => (previous ? { ...previous, status: "applied" } : previous));
      setNotice(
        "Sugestões aplicadas ao formulário como rascunho. Revise e use “Salvar Laudo” no fluxo normal."
      );
    } catch (applyError) {
      setError(errorMessage(applyError, "Não foi possível aplicar as sugestões."));
    } finally {
      setBusy(false);
    }
  };

  const rejectSuggestion = async (suggestion: EchoSuggestion) => {
    if (!session || suggestion.status !== "pending") return;
    setBusy(true);
    setError("");
    try {
      await api.post(`/ai/echo-sessions/${session.id}/feedback`, {
        feedback_type: "rejected",
        suggestion_id: suggestion.id,
      });
      setSelectedSuggestions((previous) => {
        const next = new Set(previous);
        next.delete(suggestion.id);
        return next;
      });
      setSession((previous) =>
        previous
          ? {
              ...previous,
              field_suggestions: previous.field_suggestions.map((item) =>
                item.id === suggestion.id ? { ...item, status: "rejected" } : item
              ),
            }
          : previous
      );
      setNotice(`Sugestão de ${FIELD_LABELS[suggestion.field_key] || suggestion.field_key} rejeitada.`);
    } catch (rejectError) {
      setError(errorMessage(rejectError, "Não foi possível rejeitar a sugestão."));
    } finally {
      setBusy(false);
    }
  };

  const rejectSession = async () => {
    if (!session) {
      setOpen(false);
      return;
    }
    try {
      await api.post(`/ai/echo-sessions/${session.id}/feedback`, {
        feedback_type: "reject_session",
      });
      setSession((previous) => (previous ? { ...previous, status: "rejected" } : previous));
      setNotice("Sugestões rejeitadas. Nenhum campo do laudo foi alterado.");
    } catch (rejectError) {
      setError(errorMessage(rejectError, "Não foi possível registrar a rejeição."));
    }
  };

  const discardCurrentDictation = async (successNotice: string) => {
    if (!session) {
      resetDictationState();
      setNotice(successNotice);
      return;
    }
    if (processing) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api.post(`/ai/echo-sessions/${session.id}/feedback`, {
        feedback_type: "reject_session",
      });
      if (session.audio) {
        await api.delete(`/ai/echo-sessions/${session.id}/audio`);
      }
      resetDictationState();
      setNotice(successNotice);
    } catch (restartError) {
      setError(
        errorMessage(
          restartError,
          "Não foi possível descartar o ditado atual. Tente novamente."
        )
      );
    } finally {
      setBusy(false);
    }
  };

  const removeAudio = async () => {
    await discardCurrentDictation(
      session
        ? "Áudio e tentativa anteriores descartados. Grave um novo áudio."
        : "Áudio excluído. Grave um novo áudio."
    );
  };

  const startNewDictation = async () => {
    await discardCurrentDictation(
      "Sugestões anteriores descartadas. Grave um novo áudio para gerar outras sugestões."
    );
  };

  const loadPreferences = async () => {
    setPreferencesLoading(true);
    setError("");
    try {
      const response = await api.get<EchoPreferences>("/ai/echo-sessions/preferences");
      setVocabularyText(
        response.data.vocabulary
          .filter((item) => item.active)
          .map((item) => `${item.spoken_form} = ${item.canonical_form}`)
          .join("\n")
      );
      setPhrasesText(
        response.data.phrases
          .filter((item) => item.active)
          .map((item) => `${item.field_key} | ${item.phrase_text}`)
          .join("\n")
      );
    } catch (preferencesError) {
      setError(errorMessage(preferencesError, "Não foi possível carregar as preferências."));
    } finally {
      setPreferencesLoading(false);
    }
  };

  const togglePreferences = () => {
    const next = !preferencesOpen;
    setPreferencesOpen(next);
    if (next) void loadPreferences();
  };

  const savePreferences = async () => {
    setPreferencesLoading(true);
    setError("");
    try {
      const vocabulary = vocabularyText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const [spoken, ...canonicalParts] = line.split("=");
          return {
            spoken_form: spoken.trim(),
            canonical_form: canonicalParts.join("=").trim(),
            category: "clinical",
            active: true,
          };
        })
        .filter((item) => item.spoken_form && item.canonical_form);
      const phrases = phrasesText
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const [fieldKey, ...textParts] = line.split("|");
          return {
            field_key: fieldKey.trim(),
            phrase_text: textParts.join("|").trim(),
            tags: ["personalizado"],
            active: true,
          };
        })
        .filter((item) => FIELD_LABELS[item.field_key] && item.phrase_text);
      await api.put("/ai/echo-sessions/preferences", { vocabulary, phrases });
      setNotice("Vocabulário e frases preferidas atualizados.");
    } catch (preferencesError) {
      setError(errorMessage(preferencesError, "Não foi possível salvar as preferências."));
    } finally {
      setPreferencesLoading(false);
    }
  };

  if (!config?.enabled) return null;

  return (
    <>
      <div className="fc-report-editor-side-card">
        <h2 className="mb-2 flex items-center gap-2 text-lg font-semibold">
          <Mic className="h-5 w-5 text-teal-600" />
          Assistente de laudo
        </h2>
        <p className="mb-4 text-sm text-gray-600">
          Dite achados do ecocardiograma e revise cada sugestão antes de levar ao formulário.
        </p>
        <button
          type="button"
          onClick={openAssistant}
          disabled={busy}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-teal-600 px-4 py-3 font-semibold text-white hover:bg-teal-700 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:ring-offset-2"
        >
          <Mic className="h-5 w-5" />
          {busy ? "Preparando rascunho..." : "Ditado assistido por IA"}
        </button>
        {error && !open ? (
          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error}
          </div>
        ) : null}
        <div className="mt-3 flex items-start gap-2 text-xs text-gray-500">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-teal-600" />
          Nunca assina, finaliza ou publica o laudo.
        </div>
      </div>

      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/60 p-3 sm:p-6"
          role="dialog"
          aria-modal="true"
          aria-labelledby="echo-assistant-title"
        >
          <div className="my-auto w-full max-w-6xl overflow-hidden rounded-2xl bg-white shadow-2xl">
            <header className="flex items-start justify-between gap-4 border-b border-gray-200 px-4 py-4 sm:px-6">
              <div>
                <h2 id="echo-assistant-title" className="text-xl font-semibold text-gray-950">
                  Ditado assistido por IA
                </h2>
                <p className="mt-1 text-sm text-gray-600">
                  O áudio será processado por um serviço de inteligência artificial.
                  Evite ditar nomes, contatos, documentos ou endereços.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-lg p-2 text-gray-500 hover:bg-gray-100"
                aria-label="Fechar assistente"
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="max-h-[82vh] space-y-5 overflow-y-auto p-4 sm:p-6">
              {error ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                  {error}
                </div>
              ) : null}
              {notice ? (
                <div className="rounded-xl border border-teal-200 bg-teal-50 p-3 text-sm text-teal-800">
                  {notice}
                </div>
              ) : null}

              {!session?.transcript ? (
                <section className="rounded-xl border border-gray-200 p-4">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <h3 className="font-semibold text-gray-900">1. Gravar ou enviar áudio</h3>
                      <p className="text-sm text-gray-600">
                        Limite: {Math.round(config.max_audio_bytes / 1024 / 1024)} MB e{" "}
                        {Math.round(config.max_audio_seconds / 60)} minutos.
                      </p>
                    </div>
                    <div className="rounded-full bg-gray-950 px-4 py-2 font-mono text-lg text-white">
                      {formatTime(elapsedSeconds)}
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    {recorderState === "idle" || recorderState === "ready" ? (
                      <button
                        type="button"
                        onClick={startRecording}
                        disabled={processing}
                        className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-red-600 px-5 py-3 font-semibold text-white hover:bg-red-700 disabled:opacity-50"
                      >
                        <Mic className="h-5 w-5" />
                        Iniciar gravação
                      </button>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={pauseOrResume}
                          className="inline-flex min-h-12 items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 font-medium text-amber-800"
                        >
                          {recorderState === "paused" ? (
                            <Play className="h-5 w-5" />
                          ) : (
                            <Pause className="h-5 w-5" />
                          )}
                          {recorderState === "paused" ? "Continuar" : "Pausar"}
                        </button>
                        <button
                          type="button"
                          onClick={stopRecording}
                          className="inline-flex min-h-12 items-center gap-2 rounded-xl bg-gray-950 px-4 py-3 font-medium text-white"
                        >
                          <CircleStop className="h-5 w-5" />
                          Parar
                        </button>
                      </>
                    )}
                    <label className="inline-flex min-h-12 cursor-pointer items-center gap-2 rounded-xl border border-gray-300 bg-white px-4 py-3 font-medium text-gray-700 hover:bg-gray-50">
                      <FileAudio className="h-5 w-5" />
                      Enviar arquivo
                      <input
                        type="file"
                        accept=".webm,.mp3,.mp4,.m4a,.mpeg,.mpga,.wav,audio/*"
                        className="sr-only"
                        onChange={(event) => selectAudioFile(event.target.files?.[0] || null)}
                      />
                    </label>
                  </div>

                  {audioUrl ? (
                    <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-3">
                      <audio controls src={audioUrl} className="w-full" />
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={removeAudio}
                          disabled={processing}
                          className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm text-red-700"
                        >
                          <Trash2 className="h-4 w-4" />
                          Excluir
                        </button>
                        <button
                          type="button"
                          onClick={clearRecording}
                          disabled={processing}
                          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700"
                        >
                          <RotateCcw className="h-4 w-4" />
                          Gravar novamente
                        </button>
                        <button
                          type="button"
                          onClick={transcribeAudio}
                          disabled={processing}
                          className="ml-auto inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                        >
                          {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                          Confirmar e transcrever
                        </button>
                      </div>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {session?.transcript ? (
                <section className="rounded-xl border border-gray-200 p-4">
                  <h3 className="font-semibold text-gray-900">2. Revisar transcrição</h3>
                  <div className="mt-3 grid gap-4 lg:grid-cols-2">
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Transcrição original
                      </label>
                      <div className="min-h-40 whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
                        {session.transcript.raw_text}
                      </div>
                    </div>
                    <div>
                      <label className="mb-1 block text-sm font-medium text-gray-700">
                        Transcrição editável
                      </label>
                      <textarea
                        value={editedTranscript}
                        onChange={(event) => setEditedTranscript(event.target.value)}
                        rows={8}
                        disabled={processing || hasSuggestions}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:ring-2 focus:ring-teal-500 disabled:bg-gray-50"
                      />
                    </div>
                  </div>
                  {!hasSuggestions ? (
                    <div className="mt-3 flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={removeAudio}
                        disabled={processing}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 px-3 py-2 text-sm text-red-700"
                      >
                        <RotateCcw className="h-4 w-4" />
                        Excluir e gravar novamente
                      </button>
                      <button
                        type="button"
                        onClick={structureTranscript}
                        disabled={processing || !editedTranscript.trim()}
                        className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 font-semibold text-white disabled:opacity-50"
                      >
                        {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                        Gerar sugestões
                      </button>
                    </div>
                  ) : null}
                </section>
              ) : null}

              {session?.warnings?.length ? (
                <section className="rounded-xl border border-amber-300 bg-amber-50 p-4">
                  <h3 className="flex items-center gap-2 font-semibold text-amber-950">
                    <AlertTriangle className="h-5 w-5" />
                    Alertas para revisão
                  </h3>
                  <ul className="mt-2 space-y-2 text-sm text-amber-900">
                    {session.warnings.map((warning) => (
                      <li key={warning.id} className="rounded-lg bg-white/70 p-2">
                        <span className="font-medium uppercase">{warning.severity}:</span>{" "}
                        {warning.message}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {hasSuggestions ? (
                <section className="space-y-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <h3 className="font-semibold text-gray-900">3. Revisar sugestões por campo</h3>
                      <p className="text-sm text-gray-600">
                        Selecione somente o que deseja levar ao formulário.
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => void startNewDictation()}
                        disabled={processing}
                        className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 disabled:opacity-50"
                      >
                        <RotateCcw className="h-4 w-4" />
                        Gravar novo áudio
                      </button>
                      <button
                        type="button"
                        onClick={selectAll}
                        disabled={processing}
                        className="rounded-lg border border-teal-300 bg-teal-50 px-3 py-2 text-sm font-medium text-teal-800 disabled:opacity-50"
                      >
                        Aceitar todas
                      </button>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {(session?.field_suggestions || []).map((suggestion) => {
                      const selected = selectedSuggestions.has(suggestion.id);
                      const lowConfidence = suggestion.confidence < 0.8;
                      const rejected = suggestion.status === "rejected";
                      return (
                        <article
                          key={suggestion.id}
                          className={`rounded-xl border p-4 ${
                            lowConfidence
                              ? "border-amber-300 bg-amber-50/50"
                              : "border-gray-200 bg-white"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <h4 className="font-semibold text-gray-900">
                              {FIELD_LABELS[suggestion.field_key] || suggestion.field_key}
                            </h4>
                            <span
                              className={`rounded-full px-2 py-1 text-xs font-medium ${
                                lowConfidence
                                  ? "bg-amber-100 text-amber-800"
                                  : "bg-green-100 text-green-800"
                              }`}
                            >
                              {confidenceLabel(suggestion.confidence)}
                            </span>
                          </div>
                          <div className="mt-3 grid gap-3 lg:grid-cols-2">
                            <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                              <div className="mb-1 text-xs font-semibold uppercase text-gray-500">
                                Texto atual
                              </div>
                              <div className="whitespace-pre-wrap text-sm text-gray-700">
                                {currentFields[suggestion.field_key] || "Campo vazio"}
                              </div>
                            </div>
                            <div className="rounded-lg border border-teal-200 bg-teal-50 p-3">
                              <div className="mb-1 text-xs font-semibold uppercase text-teal-700">
                                Texto sugerido editável
                              </div>
                              <textarea
                                value={
                                  editedSuggestionTexts[suggestion.id] ??
                                  suggestion.suggested_value
                                }
                                onChange={(event) =>
                                  setEditedSuggestionTexts((previous) => ({
                                    ...previous,
                                    [suggestion.id]: event.target.value,
                                  }))
                                }
                                disabled={rejected || busy}
                                rows={4}
                                className="w-full rounded-lg border border-teal-200 bg-white px-3 py-2 text-sm text-gray-900 disabled:bg-gray-100"
                              />
                            </div>
                          </div>
                          {suggestion.source_spans?.length ? (
                            <p className="mt-2 text-xs text-gray-500">
                              Origem: {suggestion.source_spans.join(" · ")}
                            </p>
                          ) : null}
                          <div className="mt-3 flex flex-wrap gap-2">
                            <button
                              type="button"
                              disabled={rejected || busy}
                              onClick={() =>
                                setSelectedSuggestions((previous) => {
                                  const next = new Set(previous);
                                  if (next.has(suggestion.id)) next.delete(suggestion.id);
                                  else next.add(suggestion.id);
                                  return next;
                                })
                              }
                              className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium disabled:opacity-50 ${
                                selected
                                  ? "bg-teal-600 text-white"
                                  : "border border-gray-300 bg-white text-gray-700"
                              }`}
                            >
                              <Check className="h-4 w-4" />
                              {selected ? "Selecionado" : "Aceitar este campo"}
                            </button>
                            <button
                              type="button"
                              disabled={rejected || busy}
                              onClick={() => void rejectSuggestion(suggestion)}
                              className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-700 disabled:opacity-50"
                            >
                              <X className="h-4 w-4" />
                              {rejected ? "Rejeitada" : "Rejeitar este campo"}
                            </button>
                          </div>
                        </article>
                      );
                    })}
                  </div>

                  {(session?.measurements || []).length ? (
                    <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4">
                      <h4 className="font-semibold text-gray-900">Medidas estruturadas</h4>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {(session?.measurements || []).map((measurement) => {
                          const selected = selectedMeasurements.has(measurement.id);
                          return (
                            <label
                              key={measurement.id}
                              className={`rounded-lg border p-3 ${
                                measurement.target_field_key
                                  ? "cursor-pointer border-blue-200 bg-white"
                                  : "border-amber-200 bg-amber-50"
                              }`}
                            >
                              <div className="flex items-start gap-3">
                                {measurement.target_field_key ? (
                                  <input
                                    type="checkbox"
                                    checked={selected}
                                    onChange={() =>
                                      setSelectedMeasurements((previous) => {
                                        const next = new Set(previous);
                                        if (next.has(measurement.id)) next.delete(measurement.id);
                                        else next.add(measurement.id);
                                        return next;
                                      })
                                    }
                                    className="mt-1 h-4 w-4 rounded border-gray-300 text-teal-600"
                                  />
                                ) : (
                                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                                )}
                                <span className="min-w-0">
                                  <span className="block font-medium text-gray-900">
                                    {measurement.display_name}:{" "}
                                    {measurement.raw_value ?? measurement.numeric_value ?? "—"}{" "}
                                    {measurement.unit || ""}
                                  </span>
                                  <span className="block text-xs text-gray-500">
                                    {measurement.source_text}
                                  </span>
                                  {!measurement.target_field_key ? (
                                    <span className="mt-1 block text-xs font-medium text-amber-700">
                                      Sem campo equivalente no formulário; revisar manualmente.
                                    </span>
                                  ) : null}
                                </span>
                              </div>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}

                  <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                    <label className="block text-sm font-medium text-gray-700">
                      Como aplicar em campos já preenchidos
                    </label>
                    <select
                      value={applyMode}
                      onChange={(event) => setApplyMode(event.target.value as ApplyMode)}
                      className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 sm:max-w-md"
                    >
                      <option value="replace">Substituir após confirmação</option>
                      <option value="append">Inserir abaixo do texto atual</option>
                      <option value="empty_only">Aceitar apenas campos vazios</option>
                    </select>
                    <div className="mt-4 flex flex-wrap justify-end gap-2">
                      <button
                        type="button"
                        onClick={rejectSession}
                        disabled={busy}
                        className="rounded-lg border border-red-200 bg-white px-4 py-2 text-red-700"
                      >
                        Rejeitar
                      </button>
                      <button
                        type="button"
                        onClick={applySelected}
                        disabled={
                          busy ||
                          session?.status !== "awaiting_review" ||
                          (!selectedSuggestions.size && !selectedMeasurements.size)
                        }
                        className="inline-flex items-center gap-2 rounded-lg bg-teal-600 px-4 py-2 font-semibold text-white disabled:opacity-50"
                      >
                        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                        Aplicar selecionados ao rascunho
                      </button>
                    </div>
                  </div>
                </section>
              ) : null}

              <section className="rounded-xl border border-gray-200">
                <button
                  type="button"
                  onClick={togglePreferences}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                >
                  <span className="flex items-center gap-2 font-medium text-gray-900">
                    <Settings2 className="h-4 w-4" />
                    Vocabulário e frases preferidas
                  </span>
                  {preferencesLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                </button>
                {preferencesOpen ? (
                  <div className="grid gap-4 border-t border-gray-200 p-4 lg:grid-cols-2">
                    <div>
                      <label className="block text-sm font-medium text-gray-700">
                        Vocabulário personalizado
                      </label>
                      <p className="mb-2 text-xs text-gray-500">
                        Uma entrada por linha: forma falada = forma canônica
                      </p>
                      <textarea
                        value={vocabularyText}
                        onChange={(event) => setVocabularyText(event.target.value)}
                        rows={6}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                        placeholder="a e sobre ao = AE/Ao"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700">
                        Frases preferidas
                      </label>
                      <p className="mb-2 text-xs text-gray-500">
                        Uma entrada por linha: chave do campo | frase
                      </p>
                      <textarea
                        value={phrasesText}
                        onChange={(event) => setPhrasesText(event.target.value)}
                        rows={6}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                        placeholder="valva_mitral | Refluxo de grau leve."
                      />
                    </div>
                    <div className="lg:col-span-2 flex justify-end">
                      <button
                        type="button"
                        onClick={savePreferences}
                        disabled={preferencesLoading}
                        className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                      >
                        Salvar preferências
                      </button>
                    </div>
                  </div>
                ) : null}
              </section>

              {session?.status === "applied" ? (
                <div className="flex flex-col gap-3 rounded-xl border border-green-200 bg-green-50 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <p className="text-sm text-green-900">
                    O formulário recebeu o rascunho selecionado. O laudo ainda não foi salvo,
                    finalizado, assinado ou publicado.
                  </p>
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-lg bg-green-700 px-4 py-2 font-medium text-white"
                  >
                    Voltar ao laudo
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
