export const TIPO_LAUDO_ECOCARDIOGRAMA = "ecocardiograma";
export const TIPO_LAUDO_ELETROCARDIOGRAMA = "eletrocardiograma";
export const TIPO_LAUDO_PRESSAO_ARTERIAL = "pressao_arterial";
export const TIPO_LAUDO_ULTRASSOM_ABDOMINAL = "ultrassonografia_abdominal";

export function getTipoLaudoLabel(tipo?: string): string {
  const mapa: Record<string, string> = {
    [TIPO_LAUDO_ECOCARDIOGRAMA]: "Ecocardiograma",
    [TIPO_LAUDO_ELETROCARDIOGRAMA]: "Eletrocardiograma",
    [TIPO_LAUDO_PRESSAO_ARTERIAL]: "Pressao Arterial",
    [TIPO_LAUDO_ULTRASSOM_ABDOMINAL]: "Ultrassonografia Abdominal",
  };

  return mapa[tipo || ""] || (tipo || "Laudo");
}

export function getLaudoBasePath(tipo?: string): string {
  return tipo === TIPO_LAUDO_ULTRASSOM_ABDOMINAL
    ? "/ultrassonografia-abdominal"
    : "/laudos";
}

export function getLaudoViewPath(id: string | number, tipo?: string): string {
  return `${getLaudoBasePath(tipo)}/${id}`;
}

export function getLaudoEditPath(id: string | number, tipo?: string): string {
  if (tipo === TIPO_LAUDO_ELETROCARDIOGRAMA) {
    return getLaudoViewPath(id, tipo);
  }
  return `${getLaudoBasePath(tipo)}/${id}/editar`;
}
