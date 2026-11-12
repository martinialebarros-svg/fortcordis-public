import api from "@/lib/axios";
import { loadStableCatalog } from "@/lib/stable-catalog-cache";

type PaginatedApiResponse<T> = {
  items?: T[];
  total?: number;
};

const CLINICAS_PAGE_SIZE = 500;

export async function listarTodasClinicas<T>(): Promise<T[]> {
  return loadStableCatalog({
    catalog: "clinicas",
    variant: "all-paginated",
    load: async () => {
      const clinicas: T[] = [];
      let skip = 0;
      let total = 0;

      while (true) {
        const response = await api.get<PaginatedApiResponse<T>>("/clinicas", {
          params: {
            skip,
            limit: CLINICAS_PAGE_SIZE,
          },
        });

        const pagina = Array.isArray(response.data?.items) ? response.data.items : [];
        const totalResposta = Number(response.data?.total);

        if (Number.isFinite(totalResposta) && totalResposta >= 0) {
          total = totalResposta;
        }

        clinicas.push(...pagina);

        if (
          pagina.length === 0 ||
          pagina.length < CLINICAS_PAGE_SIZE ||
          (total > 0 && clinicas.length >= total)
        ) {
          break;
        }

        skip += pagina.length;
      }

      return clinicas;
    },
  });
}
