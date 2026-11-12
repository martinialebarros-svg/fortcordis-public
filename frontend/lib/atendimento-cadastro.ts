export const PRESCRICAO_PRESETS_STORAGE_KEY = "fortcordis:atendimento:prescricao-presets:v1";
export const ATENDIMENTOS_LIST_LIMIT = 30;

export const normalizarCep = (valor: string) => valor.replace(/\D/g, "").slice(0, 8);

export const formatarCepVisual = (valor: string) => {
  const cep = normalizarCep(valor);
  if (cep.length <= 5) return cep;
  return `${cep.slice(0, 5)}-${cep.slice(5)}`;
};

export const normalizarCpf = (valor: string) => valor.replace(/\D/g, "").slice(0, 11);

export const formatarCpfVisual = (valor: string) => {
  const cpf = normalizarCpf(valor);
  if (cpf.length <= 3) return cpf;
  if (cpf.length <= 6) return `${cpf.slice(0, 3)}.${cpf.slice(3)}`;
  if (cpf.length <= 9) return `${cpf.slice(0, 3)}.${cpf.slice(3, 6)}.${cpf.slice(6)}`;
  return `${cpf.slice(0, 3)}.${cpf.slice(3, 6)}.${cpf.slice(6, 9)}-${cpf.slice(9)}`;
};

export const normalizarCnpj = (valor: string) => valor.replace(/\D/g, "").slice(0, 14);

export const formatarCnpjVisual = (valor: string) => {
  const cnpj = normalizarCnpj(valor);
  if (cnpj.length <= 2) return cnpj;
  if (cnpj.length <= 5) return `${cnpj.slice(0, 2)}.${cnpj.slice(2)}`;
  if (cnpj.length <= 8) return `${cnpj.slice(0, 2)}.${cnpj.slice(2, 5)}.${cnpj.slice(5)}`;
  if (cnpj.length <= 12) {
    return `${cnpj.slice(0, 2)}.${cnpj.slice(2, 5)}.${cnpj.slice(5, 8)}/${cnpj.slice(8)}`;
  }
  return `${cnpj.slice(0, 2)}.${cnpj.slice(2, 5)}.${cnpj.slice(5, 8)}/${cnpj.slice(8, 12)}-${cnpj.slice(12)}`;
};

export const normalizarTelefone = (valor: string) => valor.replace(/\D/g, "").slice(0, 11);

export const formatarTelefoneVisual = (valor: string) => {
  const telefone = normalizarTelefone(valor);
  if (telefone.length <= 2) return telefone;
  if (telefone.length <= 6) return `(${telefone.slice(0, 2)}) ${telefone.slice(2)}`;
  if (telefone.length <= 10) return `(${telefone.slice(0, 2)}) ${telefone.slice(2, 6)}-${telefone.slice(6)}`;
  return `(${telefone.slice(0, 2)}) ${telefone.slice(2, 7)}-${telefone.slice(7)}`;
};

export const parseIdadeInformadaParaMeses = (valor: string): number | null => {
  const texto = String(valor || "").trim();
  if (!texto) return null;

  const normalizado = texto
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(",", ".")
    .replace(/\s+/g, " ");

  const numeroIsolado = /^(\d+(?:\.\d+)?)$/.exec(normalizado);
  if (numeroIsolado) {
    const anos = Number(numeroIsolado[1]);
    if (!Number.isFinite(anos) || anos < 0) return null;
    return Math.max(0, Math.round(anos * 12));
  }

  let mesesTotais = 0;
  let encontrouAlgum = false;

  const anosRegex = /(\d+(?:\.\d+)?)\s*(?:a|ano|anos)\b/g;
  for (const match of normalizado.matchAll(anosRegex)) {
    const anos = Number(match[1]);
    if (!Number.isFinite(anos) || anos < 0) continue;
    mesesTotais += Math.round(anos * 12);
    encontrouAlgum = true;
  }

  const mesesRegex = /(\d+(?:\.\d+)?)\s*(?:m|mes|meses)\b/g;
  for (const match of normalizado.matchAll(mesesRegex)) {
    const meses = Number(match[1]);
    if (!Number.isFinite(meses) || meses < 0) continue;
    mesesTotais += Math.round(meses);
    encontrouAlgum = true;
  }

  if (!encontrouAlgum) return null;
  return Math.max(0, mesesTotais);
};
