const readDetailFromObject = (value: unknown): string | null => {
  if (!value || typeof value !== "object") return null;
  const detail = (value as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();

  if (Array.isArray(detail)) {
    const joined = detail
      .map((item) => (typeof item === "string" ? item.trim() : ""))
      .filter(Boolean)
      .join("; ");
    if (joined) return joined;
  }

  // Conflitos confirmaveis do backend chegam como objeto
  // ({ codigo, mensagem, confirmavel }) em vez de string.
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const detalhe = detail as { mensagem?: unknown; message?: unknown };
    if (typeof detalhe.mensagem === "string" && detalhe.mensagem.trim()) {
      return detalhe.mensagem.trim();
    }
    if (typeof detalhe.message === "string" && detalhe.message.trim()) {
      return detalhe.message.trim();
    }
  }

  const message = (value as { message?: unknown }).message;
  if (typeof message === "string" && message.trim()) return message.trim();

  return null;
};

export const extractApiErrorMessageSync = (error: unknown, fallback: string): string => {
  const responseData = (error as { response?: { data?: unknown } } | undefined)?.response?.data;
  const fromObject = readDetailFromObject(responseData);
  if (fromObject) return fromObject;

  if (typeof responseData === "string" && responseData.trim()) {
    try {
      const parsed = JSON.parse(responseData);
      const fromParsed = readDetailFromObject(parsed);
      if (fromParsed) return fromParsed;
      return responseData.trim();
    } catch {
      return responseData.trim();
    }
  }

  const topLevelMessage = (error as { message?: unknown } | undefined)?.message;
  if (typeof topLevelMessage === "string" && topLevelMessage.trim()) {
    return topLevelMessage.trim();
  }

  return fallback;
};

export const extractApiErrorMessage = async (error: unknown, fallback: string): Promise<string> => {
  const syncMessage = extractApiErrorMessageSync(error, "");
  if (syncMessage) return syncMessage;

  const responseData = (error as { response?: { data?: unknown } } | undefined)?.response?.data;
  if (typeof Blob !== "undefined" && responseData instanceof Blob) {
    try {
      const text = (await responseData.text()).trim();
      if (!text) return fallback;
      try {
        const parsed = JSON.parse(text);
        const fromParsed = readDetailFromObject(parsed);
        return fromParsed || text;
      } catch {
        return text;
      }
    } catch {
      return fallback;
    }
  }

  return fallback;
};
