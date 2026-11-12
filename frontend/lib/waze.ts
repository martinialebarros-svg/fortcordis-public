export interface WazeDestinoLocal {
  latitude?: number | string | null;
  longitude?: number | string | null;
  endereco_normalizado?: string | null;
  endereco?: string | null;
  numero?: string | null;
  bairro?: string | null;
  cidade?: string | null;
  estado?: string | null;
  cep?: string | null;
}

export type WazeDestinoClinica = WazeDestinoLocal;

interface Coordenadas {
  lat: number;
  lng: number;
}

export interface WazeDestinoUrl {
  appUrl: string;
  webUrl: string;
  tipo: "coordenadas" | "endereco";
}

const texto = (valor?: string | number | null) => String(valor ?? "").trim();

const coordenadasValidas = (destino?: WazeDestinoLocal | null): Coordenadas | null => {
  const lat = Number(destino?.latitude);
  const lng = Number(destino?.longitude);

  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  if (Math.abs(lat) < 0.000001 && Math.abs(lng) < 0.000001) return null;

  return { lat, lng };
};

const formatarCoordenada = (valor: number) => valor.toFixed(7);

export const montarEnderecoDestinoWaze = (destino?: WazeDestinoLocal | null): string => {
  const enderecoNormalizado = texto(destino?.endereco_normalizado);
  if (enderecoNormalizado) return enderecoNormalizado;

  const endereco = texto(destino?.endereco);
  const numero = texto(destino?.numero);
  const linhaEndereco = [endereco, numero].filter(Boolean).join(", ");

  return [
    linhaEndereco,
    texto(destino?.bairro),
    texto(destino?.cidade),
    texto(destino?.estado),
    texto(destino?.cep),
  ]
    .filter(Boolean)
    .join(", ");
};

export const montarWazeDestinoLocal = (
  destino?: WazeDestinoLocal | null
): WazeDestinoUrl | null => {
  const coordenadas = coordenadasValidas(destino);
  if (coordenadas) {
    const ll = `${formatarCoordenada(coordenadas.lat)},${formatarCoordenada(coordenadas.lng)}`;
    return {
      appUrl: `waze://?ll=${ll}&navigate=yes`,
      webUrl: `https://waze.com/ul?ll=${ll}&navigate=yes`,
      tipo: "coordenadas",
    };
  }

  const endereco = montarEnderecoDestinoWaze(destino);
  if (!endereco) return null;

  const query = encodeURIComponent(endereco);
  return {
    appUrl: `waze://?q=${query}&navigate=yes`,
    webUrl: `https://waze.com/ul?q=${query}&navigate=yes`,
    tipo: "endereco",
  };
};

export const montarGoogleMapsDestinoLocal = (
  destino?: WazeDestinoLocal | null
): string | null => {
  const coordenadas = coordenadasValidas(destino);
  if (coordenadas) {
    const destino = `${formatarCoordenada(coordenadas.lat)},${formatarCoordenada(coordenadas.lng)}`;
    return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destino)}`;
  }

  const endereco = montarEnderecoDestinoWaze(destino);
  if (!endereco) return null;

  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(endereco)}`;
};

export const montarEnderecoClinicaWaze = (clinica?: WazeDestinoClinica | null): string => {
  return montarEnderecoDestinoWaze(clinica);
};

export const montarWazeDestinoClinica = (clinica?: WazeDestinoClinica | null): WazeDestinoUrl | null => {
  return montarWazeDestinoLocal(clinica);
};

export const montarGoogleMapsDestinoClinica = (clinica?: WazeDestinoClinica | null): string | null => {
  return montarGoogleMapsDestinoLocal(clinica);
};
