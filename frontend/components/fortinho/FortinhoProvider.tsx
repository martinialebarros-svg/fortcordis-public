"use client";

import dynamic from "next/dynamic";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { type FortinhoGesture, type FortinhoMood } from "@/components/FortinhoMascot";

interface FortinhoNotifyOptions {
  title?: string;
  message: string;
  mood?: FortinhoMood;
  gesture?: FortinhoGesture;
  durationMs?: number;
  sticky?: boolean;
}

interface FortinhoConfirmOptions {
  title?: string;
  message: string;
  mood?: FortinhoMood;
  gesture?: FortinhoGesture;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface FortinhoContextValue {
  notify: (options: FortinhoNotifyOptions) => void;
  confirm: (options: FortinhoConfirmOptions) => Promise<boolean>;
  dismissCurrent: () => void;
}

type FortinhoQueueBase = {
  id: number;
  title: string;
  message: string;
  mood: FortinhoMood;
  gesture: FortinhoGesture;
};

type FortinhoNoticeItem = FortinhoQueueBase & {
  kind: "notice";
  durationMs: number;
  sticky: boolean;
};

type FortinhoConfirmItem = FortinhoQueueBase & {
  kind: "confirm";
  confirmLabel: string;
  cancelLabel: string;
  resolve: (value: boolean) => void;
};

type FortinhoQueueItem = FortinhoNoticeItem | FortinhoConfirmItem;

const FALLBACK_CONTEXT: FortinhoContextValue = {
  notify: ({ title, message }) => {
    if (typeof window === "undefined") return;
    const texto = title ? `${title}\n\n${message}` : message;
    window.alert(texto);
  },
  confirm: async ({ title, message, confirmLabel, cancelLabel }) => {
    if (typeof window === "undefined") return false;
    const rodape =
      confirmLabel || cancelLabel
        ? `\n\n${confirmLabel || "Confirmar"} / ${cancelLabel || "Cancelar"}`
        : "";
    const texto = title ? `${title}\n\n${message}${rodape}` : `${message}${rodape}`;
    return window.confirm(texto);
  },
  dismissCurrent: () => {},
};

const FortinhoContext = createContext<FortinhoContextValue>(FALLBACK_CONTEXT);
const FortinhoOverlay = dynamic(() => import("@/components/fortinho/FortinhoOverlay"), {
  ssr: false,
});

export function useFortinho(): FortinhoContextValue {
  return useContext(FortinhoContext);
}

export function FortinhoProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<FortinhoQueueItem[]>([]);
  const [oculto, setOculto] = useState(false);
  const sequenceRef = useRef(0);

  const shiftQueue = useCallback((confirmResult = false) => {
    setQueue((prev) => {
      if (prev.length === 0) return prev;
      const [itemAtual, ...restante] = prev;
      if (itemAtual.kind === "confirm") {
        queueMicrotask(() => itemAtual.resolve(confirmResult));
      }
      return restante;
    });
  }, []);

  const notify = useCallback((options: FortinhoNotifyOptions) => {
    const id = ++sequenceRef.current;
    const item: FortinhoNoticeItem = {
      id,
      kind: "notice",
      title: options.title?.trim() || "Fortinho",
      message: options.message,
      mood: options.mood ?? "happy",
      gesture: options.gesture ?? "wave",
      durationMs: Math.max(2000, options.durationMs ?? 6000),
      sticky: Boolean(options.sticky),
    };
    setQueue((prev) => [...prev, item]);
  }, []);

  const confirm = useCallback((options: FortinhoConfirmOptions) => {
    return new Promise<boolean>((resolve) => {
      // Uma confirmacao requer uma resposta, mesmo se o mascote foi ocultado.
      setOculto(false);
      const id = ++sequenceRef.current;
      const item: FortinhoConfirmItem = {
        id,
        kind: "confirm",
        title: options.title?.trim() || "Fortinho precisa de confirmacao",
        message: options.message,
        mood: options.mood ?? "alert",
        gesture: options.gesture ?? "open-arms",
        confirmLabel: options.confirmLabel?.trim() || "Confirmar",
        cancelLabel: options.cancelLabel?.trim() || "Cancelar",
        resolve,
      };
      // Confirmacoes interrompem avisos (inclusive os persistentes), que
      // voltam a ser exibidos depois da resposta. Confirmacoes pendentes
      // continuam na ordem em que foram solicitadas.
      setQueue((prev) => {
        const primeiroAviso = prev.findIndex((pendente) => pendente.kind === "notice");
        if (primeiroAviso === -1) return [...prev, item];
        return [
          ...prev.slice(0, primeiroAviso),
          item,
          ...prev.slice(primeiroAviso),
        ];
      });
    });
  }, []);

  const dismissCurrent = useCallback(() => {
    shiftQueue(false);
  }, [shiftQueue]);

  const current = queue[0] ?? null;

  useEffect(() => {
    if (!current || current.kind !== "notice" || current.sticky) return;
    const timeout = window.setTimeout(() => {
      shiftQueue(false);
    }, current.durationMs);
    return () => window.clearTimeout(timeout);
  }, [current, shiftQueue]);

  const contextValue = useMemo<FortinhoContextValue>(
    () => ({
      notify,
      confirm,
      dismissCurrent,
    }),
    [notify, confirm, dismissCurrent]
  );

  const mensagemAtual = current
    ? `${current.title}: ${current.message}`
    : "Estou por aqui para deixar os avisos mais humanos.";
  const moodAtual = current?.mood ?? "happy";
  const gestoAtual = current?.gesture ?? "wave";

  return (
    <FortinhoContext.Provider value={contextValue}>
      {children}

      <FortinhoOverlay
        hidden={oculto}
        message={mensagemAtual}
        mood={moodAtual}
        gesture={gestoAtual}
        confirmState={
          current?.kind === "confirm"
            ? {
                confirmLabel: current.confirmLabel,
                cancelLabel: current.cancelLabel,
              }
            : null
        }
        stickyNotice={current?.kind === "notice" && current.sticky}
        onHide={() => setOculto(true)}
        onShow={() => setOculto(false)}
        onDismiss={() => shiftQueue(false)}
        onConfirm={() => shiftQueue(true)}
      />
    </FortinhoContext.Provider>
  );
}
