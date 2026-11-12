"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apagarAudioBackup, lerAudioBackup, salvarAudioBackup, type AtendimentoAudioBackup } from "./atendimento-audio-backup";
import { ASSISTENTE_AUDIO_MAX_BYTES, ASSISTENTE_AUDIO_MAX_SECONDS, escolherMimeGravacao, extensaoAudio, limiteAudioAssistente, validarAudioParaTranscricao } from "./atendimento-assistente-ia";
import { apagarAudioAssistenteMemoria, guardarAudioAssistenteMemoria, lerRascunhoAssistenteMemoria, observarAudioAssistenteMemoria } from "./atendimento-assistente-memory";

export function useAtendimentoAudio(atendimentoId: number, usuarioId: number | null, pacienteId: number) {
  const [audio, setAudio] = useState<File | null>(null);
  const [gravando, setGravando] = useState(false);
  const [iniciando, setIniciando] = useState(false);
  const [carregandoBackup, setCarregandoBackup] = useState(true);
  const [identidadeCarregada, setIdentidadeCarregada] = useState("");
  const chaveIdentidade = `${usuarioId || ""}:${atendimentoId}:${pacienteId}`;
  const [seconds, setSeconds] = useState(0);
  const [nivel, setNivel] = useState(0);
  const [aviso, setAviso] = useState("");
  const [erro, setErro] = useState("");
  const [manterCopia, setManterCopiaState] = useState(false);
  const alive = useRef(true);
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audioContext = useRef<AudioContext | null>(null);
  const frame = useRef<number | null>(null);
  const secondsRef = useRef(0);
  const manterCopiaRef = useRef(false);
  const backupPendente = useRef(false);
  const escrevendoMemoria = useRef(false);
  const storageQueue = useRef(Promise.resolve());
  const maxBytesRef = useRef(ASSISTENTE_AUDIO_MAX_BYTES);

  const guardar = useCallback((value: AtendimentoAudioBackup) => {
    if (!usuarioId || !pacienteId) return;
    escrevendoMemoria.current = true;
    guardarAudioAssistenteMemoria({ ...value, copiaDispositivo: manterCopiaRef.current });
    escrevendoMemoria.current = false;
    if (!manterCopiaRef.current) return;
    backupPendente.current = true;
    storageQueue.current = storageQueue.current.then(() => salvarAudioBackup(value)).catch(() => {
      if (alive.current) setAviso("Não foi possível salvar a cópia neste dispositivo. Mantenha esta tela aberta e baixe o áudio ao terminar.");
    });
  }, [usuarioId, pacienteId]);

  const liberarMicrofone = useCallback(() => {
    stream.current?.getTracks().forEach((track) => { track.onended = null; track.stop(); });
    stream.current = null;
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    void audioContext.current?.close().catch(() => {});
    audioContext.current = null;
    if (alive.current) setNivel(0);
  }, []);

  const parar = useCallback(() => {
    const current = recorder.current;
    if (current && current.state !== "inactive") current.stop();
    liberarMicrofone();
    // Keep the UI busy until onstop receives the final media chunk.
  }, [liberarMicrofone]);

  useEffect(() => {
    alive.current = true;
    let cancelled = false;
    setCarregandoBackup(Boolean(usuarioId));
    const identity = { usuarioId: usuarioId || 0, atendimentoId, pacienteId };
    const restaurar = (saved: AtendimentoAudioBackup | null, persistido: boolean) => {
      if (cancelled || !saved || saved.pacienteId !== pacienteId || saved.usuarioId !== usuarioId || saved.atendimentoId !== atendimentoId) return;
      setAudio(saved.blob instanceof File ? saved.blob : new File([saved.blob], saved.filename, { type: saved.blob.type }));
      setSeconds(saved.seconds);
      secondsRef.current = saved.seconds;
      if (persistido || saved.copiaDispositivo) {
        setManterCopiaState(true);
        manterCopiaRef.current = true;
        backupPendente.current = true;
      }
      setAviso(saved.finalizado
        ? persistido ? "Áudio recuperado deste atendimento. Ouça e confira antes de transcrever." : "Áudio recuperado nesta aba para este paciente e atendimento. Baixe o original para guardá-lo."
        : "Gravação interrompida recuperada. O final pode estar incompleto; confira se o áudio reproduz antes de transcrever.");
    };
    const memoria = usuarioId ? lerRascunhoAssistenteMemoria(identity)?.audio : null;
    const desobservar = usuarioId ? observarAudioAssistenteMemoria(identity, (saved) => {
      if (cancelled || escrevendoMemoria.current || recorder.current?.state === "recording") return;
      if (saved) restaurar(saved, false);
      else setAudio(null);
    }) : () => {};
    if (memoria) {
      restaurar(memoria, false);
      setCarregandoBackup(false); setIdentidadeCarregada(chaveIdentidade);
    } else if (usuarioId) void lerAudioBackup(usuarioId, atendimentoId, pacienteId).then((saved) => {
      // A final recorder chunk can arrive during the IndexedDB read after SPA unmount.
      const recente = lerRascunhoAssistenteMemoria(identity)?.audio;
      restaurar(recente || saved, !recente);
    }).catch(() => {}).finally(() => { if (!cancelled) { setCarregandoBackup(false); setIdentidadeCarregada(chaveIdentidade); } });
    return () => {
      cancelled = true;
      desobservar();
      alive.current = false;
      parar();
    };
  }, [atendimentoId, usuarioId, pacienteId, chaveIdentidade, parar]);

  useEffect(() => {
    if (!gravando) return;
    const started = Date.now();
    const interval = window.setInterval(() => {
      const value = Math.floor((Date.now() - started) / 1000);
      secondsRef.current = value;
      setSeconds(value);
      if (value >= ASSISTENTE_AUDIO_MAX_SECONDS) {
        setAviso("A gravação atingiu 30 minutos e foi encerrada. Transcreva este trecho antes de iniciar outro.");
        parar();
      }
    }, 500);
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const visibility = () => {
      if (document.hidden) setAviso("A tela ficou em segundo plano. Alguns dispositivos interrompem o microfone; confira o áudio ao retornar.");
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      clearInterval(interval);
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [gravando, parar]);

  const iniciar = async (maxBytes = ASSISTENTE_AUDIO_MAX_BYTES) => {
    if (iniciando || gravando || audio || carregandoBackup) return;
    setErro("");
    setAviso("");
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setErro("Este navegador não oferece gravação. Abra em uma conexão HTTPS ou carregue um arquivo de áudio.");
      return;
    }
    setIniciando(true);
    maxBytesRef.current = limiteAudioAssistente(maxBytes);
    try {
      const captured = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
      if (!alive.current) { captured.getTracks().forEach((track) => track.stop()); return; }
      stream.current = captured;
      const mime = escolherMimeGravacao((value) => MediaRecorder.isTypeSupported(value));
      const current = new MediaRecorder(captured, { ...(mime ? { mimeType: mime } : {}), audioBitsPerSecond: 96000 });
      recorder.current = current;
      const chunks: Blob[] = [];
      let total = 0;
      const recordingMime = () => current.mimeType || chunks.find((chunk) => chunk.type)?.type || mime || "application/octet-stream";
      const filename = () => `atendimento-${atendimentoId}-${recordingStartedAt}.${extensaoAudio(recordingMime())}`;
      const recordingStartedAt = Date.now();
      const buildBackup = (finalizado: boolean): AtendimentoAudioBackup => ({
        atendimentoId, usuarioId: usuarioId || 0, pacienteId, blob: new Blob(chunks, { type: recordingMime() }), filename: filename(),
        seconds: secondsRef.current, finalizado, atualizadoEm: Date.now(),
      });
      current.ondataavailable = (event) => {
        if (!event.data.size) return;
        chunks.push(event.data);
        total += event.data.size;
        guardar(buildBackup(false));
        if (total >= maxBytesRef.current - 256 * 1024 && current.state !== "inactive") {
          if (alive.current) setAviso("A gravação foi encerrada ao se aproximar do limite. O arquivo final será conferido antes de permitir a transcrição.");
          parar();
        }
      };
      current.onstop = () => {
        const backup = buildBackup(true);
        if (backup.blob.size) {
          const file = new File([backup.blob], backup.filename, { type: backup.blob.type });
          guardar({ ...backup, blob: file });
          if (alive.current) {
            setAudio(file);
            setErro(validarAudioParaTranscricao(file, maxBytesRef.current) || "");
          }
        } else if (alive.current) setErro("Nenhum áudio foi capturado. Verifique o microfone e tente novamente.");
        // Release recorder closures so discarding the resulting File also releases
        // the raw chunks instead of leaving them reachable through recorder.current.
        chunks.length = 0;
        current.ondataavailable = null;
        current.onstop = null;
        current.onerror = null;
        if (recorder.current === current) recorder.current = null;
        if (alive.current) setGravando(false);
        liberarMicrofone();
      };
      current.onerror = () => {
        if (alive.current) setErro("A gravação foi interrompida. Confira o trecho recuperado antes de continuar.");
        parar();
      };
      captured.getAudioTracks().forEach((track) => {
        track.onended = () => {
          if (alive.current) setAviso("O microfone foi desconectado. A gravação foi encerrada; confira o trecho capturado.");
          parar();
        };
      });
      // Every stored blob includes the first media header and all fragments in order.
      // Individual MediaRecorder fragments must never be sent as standalone files.
      secondsRef.current = 0;
      setSeconds(0);
      current.start(5000);
      setGravando(true);
      try {
        const Context = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
        if (Context) {
          const context = new Context();
          audioContext.current = context;
          void context.resume();
          const analyser = context.createAnalyser();
          analyser.fftSize = 256;
          context.createMediaStreamSource(captured).connect(analyser);
          const data = new Uint8Array(analyser.fftSize);
          const measure = () => {
            if (!alive.current || current.state === "inactive") return;
            analyser.getByteTimeDomainData(data);
            const rms = Math.sqrt(data.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / data.length);
            setNivel(Math.min(100, Math.round(rms * 400)));
            frame.current = requestAnimationFrame(measure);
          };
          measure();
        }
      } catch { setAviso("Medidor de volume indisponível. Faça um teste curto e ouça a gravação."); }
    } catch (error) {
      liberarMicrofone();
      if (alive.current) setErro(error instanceof DOMException && error.name === "NotAllowedError"
        ? "Permita o acesso ao microfone nas configurações do navegador e tente novamente."
        : "Não foi possível iniciar a gravação. Verifique se outro aplicativo está usando o microfone.");
    } finally { if (alive.current) setIniciando(false); }
  };

  const importar = (file: File, maxBytes = ASSISTENTE_AUDIO_MAX_BYTES) => {
    if (gravando || iniciando) return;
    if (!/\.(webm|mp3|m4a|mp4|wav|mpeg|mpga)$/i.test(file.name) || !file.size) {
      setErro("Selecione um áudio não vazio em MP3, MP4/M4A, MPEG/MPGA, WAV ou WebM.");
      return;
    }
    setErro(validarAudioParaTranscricao(file, maxBytes) || ""); setAviso(""); setAudio(file); setSeconds(0); secondsRef.current = 0;
    guardar({ atendimentoId, usuarioId: usuarioId || 0, pacienteId, blob: file, filename: file.name, seconds: 0, finalizado: true, atualizadoEm: Date.now() });
  };

  const descartar = async () => {
    if (gravando || iniciando) return;
    try {
      await storageQueue.current;
      if (usuarioId && backupPendente.current) await apagarAudioBackup(usuarioId, atendimentoId, pacienteId);
      backupPendente.current = false;
      if (usuarioId) apagarAudioAssistenteMemoria({ usuarioId, atendimentoId, pacienteId });
      setAudio(null); setSeconds(0); secondsRef.current = 0; setAviso(""); setErro("");
    } catch {
      // Never claim deletion if persistent storage could still contain the recording.
      setErro("Não foi possível apagar a cópia local. Tente novamente ou limpe os dados deste site no navegador.");
    }
  };

  const setManterCopia = async (enabled: boolean) => {
    if (enabled && (!usuarioId || !pacienteId)) return;
    manterCopiaRef.current = enabled;
    setManterCopiaState(enabled);
    if (enabled && audio) guardar({ atendimentoId, usuarioId: usuarioId || 0, pacienteId, blob: audio, filename: audio.name, seconds, finalizado: true, atualizadoEm: Date.now() });
    if (!enabled) {
      try {
        await storageQueue.current;
        if (usuarioId && backupPendente.current) await apagarAudioBackup(usuarioId, atendimentoId, pacienteId);
        backupPendente.current = false;
        if (usuarioId) {
          const saved = lerRascunhoAssistenteMemoria({ usuarioId, atendimentoId, pacienteId })?.audio;
          if (saved) {
            escrevendoMemoria.current = true;
            guardarAudioAssistenteMemoria({ ...saved, copiaDispositivo: false });
            escrevendoMemoria.current = false;
          }
        }
      }
      catch { setErro("Não foi possível apagar a cópia local. Limpe os dados deste site ao encerrar."); }
    }
  };

  return { audio, gravando, iniciando, carregandoBackup: carregandoBackup || Boolean(usuarioId && identidadeCarregada !== chaveIdentidade), seconds, nivel, aviso, erro, manterCopia, setManterCopia, iniciar, parar, importar, descartar };
}
