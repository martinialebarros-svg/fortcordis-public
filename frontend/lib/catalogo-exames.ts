type CatalogoExameOrdenavel = {
  id: number;
  nome: string;
};

export const ordenarCatalogoExames = <T extends CatalogoExameOrdenavel>(items: T[]): T[] =>
  [...items].sort((left, right) => {
    const byName = left.nome.localeCompare(right.nome, "pt-BR", { sensitivity: "base" });
    return byName || left.id - right.id;
  });

export const upsertCatalogoExame = <T extends CatalogoExameOrdenavel>(items: T[], item: T): T[] =>
  ordenarCatalogoExames([...items.filter((current) => current.id !== item.id), item]);

export const removeCatalogoExame = <T extends CatalogoExameOrdenavel>(items: T[], itemId: number): T[] =>
  items.filter((item) => item.id !== itemId);

export const parseCatalogoExameSinonimos = (value: string): string[] => {
  const seen = new Set<string>();
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase("pt-BR");
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
};
