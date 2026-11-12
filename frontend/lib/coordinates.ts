const EPSILON_COORDENADA = 0.000001;

export const normalizarCoordenadaOpcional = (
  valor?: number | string | null
): number | null => {
  if (valor === null || valor === undefined) return null;

  if (typeof valor === "string") {
    const texto = valor.trim();
    if (!texto) return null;
    const numero = Number(texto);
    return Number.isFinite(numero) ? numero : null;
  }

  return Number.isFinite(valor) ? valor : null;
};

export const coordenadasSaoConfiaveis = (
  latitude?: number | string | null,
  longitude?: number | string | null
): boolean => {
  const lat = normalizarCoordenadaOpcional(latitude);
  const lng = normalizarCoordenadaOpcional(longitude);

  if (lat === null || lng === null) return false;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
  if (Math.abs(lat) < EPSILON_COORDENADA && Math.abs(lng) < EPSILON_COORDENADA) return false;

  return true;
};
