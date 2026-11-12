"use client";

import { useEffect, useRef, useState } from "react";

export interface AgendaRealtimePayload {
  type?: string;
  action?: string;
  agendamento_id?: number;
  data?: Record<string, unknown>;
  timestamp?: string;
}

interface UseAgendaRealtimeResult {
  conectado: boolean;
  ultimoEvento: string;
}

export function useAgendaRealtime(
  enabled: boolean,
  onAgendaUpdate: (payload: AgendaRealtimePayload) => void
): UseAgendaRealtimeResult {
  const [conectado, setConectado] = useState(false);
  const [ultimoEvento, setUltimoEvento] = useState("");
  const [paginaVisivel, setPaginaVisivel] = useState(() => {
    if (typeof document === "undefined") {
      return true;
    }
    return document.visibilityState === "visible";
  });
  const callbackRef = useRef(onAgendaUpdate);

  useEffect(() => {
    callbackRef.current = onAgendaUpdate;
  }, [onAgendaUpdate]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }

    const handleVisibilityChange = () => {
      setPaginaVisivel(document.visibilityState === "visible");
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || !paginaVisivel) {
      setConectado(false);
      return;
    }

    let cancelado = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let abortController: AbortController | null = null;
    let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    let reconnectDelayMs = 3000;

    const parseEventBlock = (rawBlock: string) => {
      if (!rawBlock.trim()) return;

      const linhas = rawBlock.replace(/\r/g, "").split("\n");
      let eventType = "message";
      const dataChunks: string[] = [];

      for (const linha of linhas) {
        if (linha.startsWith("event:")) {
          eventType = linha.slice(6).trim();
          continue;
        }
        if (linha.startsWith("data:")) {
          dataChunks.push(linha.slice(5).trim());
        }
      }

      if (eventType !== "agenda_update" && eventType !== "connected") {
        return;
      }

      const rawData = dataChunks.join("\n");
      if (!rawData) {
        return;
      }

      try {
        const payload = JSON.parse(rawData) as AgendaRealtimePayload;
        if (eventType === "connected") {
          setUltimoEvento("connected");
        } else if (payload.action) {
          setUltimoEvento(payload.action);
        }
        callbackRef.current(payload);
      } catch (error) {
        console.error("Erro ao parsear evento SSE de agenda:", error);
      }
    };

    const connect = async () => {
      while (!cancelado) {
        abortController = new AbortController();
        activeReader = null;

        try {
          const response = await fetch("/api/v1/agenda/stream", {
            method: "GET",
            headers: {
              Accept: "text/event-stream",
              "Cache-Control": "no-cache",
            },
            signal: abortController.signal,
            cache: "no-store",
            credentials: "include",
          });

          if (!response.ok || !response.body) {
            throw new Error(`Falha no stream de agenda (HTTP ${response.status}).`);
          }

          setConectado(true);
          reconnectDelayMs = 3000;
          const reader = response.body.getReader();
          activeReader = reader;
          const decoder = new TextDecoder("utf-8");
          let buffer = "";

          while (!cancelado) {
            const { done, value } = await reader.read();
            if (done) {
              break;
            }

            buffer += decoder.decode(value, { stream: true });
            let boundary = buffer.indexOf("\n\n");
            while (boundary !== -1) {
              const rawBlock = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              parseEventBlock(rawBlock);
              boundary = buffer.indexOf("\n\n");
            }
          }
        } catch (error: any) {
          if (!cancelado && error?.name !== "AbortError") {
            console.error("Stream de agenda desconectado:", error);
          }
        } finally {
          setConectado(false);
          if (activeReader) {
            try {
              await activeReader.cancel();
            } catch {
              // ignore
            }
            activeReader = null;
          }
        }

        if (cancelado) {
          break;
        }

        await new Promise<void>((resolve) => {
          reconnectTimer = setTimeout(() => resolve(), reconnectDelayMs);
        });
        reconnectDelayMs = Math.min(reconnectDelayMs + 2000, 15000);
      }
    };

    void connect();

    return () => {
      cancelado = true;
      setConectado(false);
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      if (abortController) {
        abortController.abort();
      }
      if (activeReader) {
        activeReader.cancel().catch(() => undefined);
      }
    };
  }, [enabled, paginaVisivel]);

  return { conectado, ultimoEvento };
}
