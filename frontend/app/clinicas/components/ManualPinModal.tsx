"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Coordenadas = {
  lat: number;
  lng: number;
};

type ManualPinModalProps = {
  isOpen: boolean;
  initialLat: number | null;
  initialLng: number | null;
  onClose: () => void;
  onConfirm: (coords: Coordenadas) => void;
};

declare global {
  interface Window {
    L?: any;
    __leafletLoaderPromise?: Promise<any>;
  }
}

const DEFAULT_CENTER: Coordenadas = {
  lat: -3.7318616,
  lng: -38.5266704,
};

const LEAFLET_CSS_ID = "leaflet-css-cdn";
const LEAFLET_SCRIPT_ID = "leaflet-js-cdn";
const LEAFLET_CSS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
const LEAFLET_JS_URL = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";

async function loadLeaflet(): Promise<any> {
  if (typeof window === "undefined") {
    throw new Error("Leaflet indisponivel no servidor.");
  }
  if (window.L) {
    return window.L;
  }
  if (window.__leafletLoaderPromise) {
    return window.__leafletLoaderPromise;
  }

  window.__leafletLoaderPromise = new Promise((resolve, reject) => {
    if (!document.getElementById(LEAFLET_CSS_ID)) {
      const css = document.createElement("link");
      css.id = LEAFLET_CSS_ID;
      css.rel = "stylesheet";
      css.href = LEAFLET_CSS_URL;
      css.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
      css.crossOrigin = "";
      document.head.appendChild(css);
    }

    const finish = () => {
      if (window.L) {
        resolve(window.L);
      } else {
        reject(new Error("Leaflet nao carregou."));
      }
    };

    const existingScript = document.getElementById(LEAFLET_SCRIPT_ID) as HTMLScriptElement | null;
    if (existingScript) {
      if (window.L) {
        finish();
        return;
      }
      existingScript.addEventListener("load", finish, { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Falha ao carregar Leaflet.")), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.id = LEAFLET_SCRIPT_ID;
    script.src = LEAFLET_JS_URL;
    script.async = true;
    script.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
    script.crossOrigin = "";
    script.onload = finish;
    script.onerror = () => reject(new Error("Falha ao carregar Leaflet."));
    document.body.appendChild(script);
  });

  return window.__leafletLoaderPromise;
}

export default function ManualPinModal({
  isOpen,
  initialLat,
  initialLng,
  onClose,
  onConfirm,
}: ManualPinModalProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const [carregandoMapa, setCarregandoMapa] = useState(false);
  const [erroMapa, setErroMapa] = useState("");
  const [coordenadas, setCoordenadas] = useState<Coordenadas | null>(null);
  const [inputLat, setInputLat] = useState("");
  const [inputLng, setInputLng] = useState("");

  const centroInicial = useMemo<Coordenadas>(() => {
    const latValida = Number.isFinite(Number(initialLat));
    const lngValida = Number.isFinite(Number(initialLng));
    if (latValida && lngValida) {
      return { lat: Number(initialLat), lng: Number(initialLng) };
    }
    return DEFAULT_CENTER;
  }, [initialLat, initialLng]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    let canceled = false;
    setErroMapa("");
    setCarregandoMapa(true);
    setCoordenadas(centroInicial);
    setInputLat(centroInicial.lat.toFixed(9));
    setInputLng(centroInicial.lng.toFixed(9));

    const initMap = async () => {
      try {
        const L = await loadLeaflet();
        if (canceled || !containerRef.current) return;

        if (mapRef.current) {
          mapRef.current.remove();
        }

        const map = L.map(containerRef.current).setView([centroInicial.lat, centroInicial.lng], 16);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19,
        }).addTo(map);

        const marker = L.marker([centroInicial.lat, centroInicial.lng], { draggable: true }).addTo(map);

        const atualizarPonto = (lat: number, lng: number) => {
          setCoordenadas({ lat, lng });
          setInputLat(lat.toFixed(9));
          setInputLng(lng.toFixed(9));
        };

        map.on("click", (evt: any) => {
          const lat = Number(evt?.latlng?.lat);
          const lng = Number(evt?.latlng?.lng);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          marker.setLatLng([lat, lng]);
          atualizarPonto(lat, lng);
        });

        marker.on("dragend", () => {
          const pos = marker.getLatLng();
          const lat = Number(pos?.lat);
          const lng = Number(pos?.lng);
          if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
          atualizarPonto(lat, lng);
        });

        mapRef.current = map;
        markerRef.current = marker;
        setTimeout(() => map.invalidateSize(), 0);
      } catch (err: any) {
        setErroMapa(err?.message || "Falha ao carregar mapa.");
      } finally {
        if (!canceled) {
          setCarregandoMapa(false);
        }
      }
    };

    initMap();

    return () => {
      canceled = true;
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
      markerRef.current = null;
    };
  }, [isOpen, centroInicial]);

  if (!isOpen) return null;

  const aplicarCoordenadasDigitadas = () => {
    const lat = Number(inputLat.replace(",", "."));
    const lng = Number(inputLng.replace(",", "."));

    if (!Number.isFinite(lat) || !Number.isFinite(lng) || lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setErroMapa("Coordenadas invalidas. Use latitude/longitude numericas.");
      return;
    }

    setErroMapa("");
    setCoordenadas({ lat, lng });
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lng]);
    }
    if (mapRef.current) {
      const zoom = Number(mapRef.current.getZoom?.() || 16);
      mapRef.current.setView([lat, lng], zoom);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="w-full max-w-4xl bg-white rounded-xl shadow-2xl border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Ajustar pin manual</h3>
            <p className="text-sm text-gray-500">Clique no ponto correto ou arraste o marcador.</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Fechar
          </button>
        </div>

        <div className="p-5 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-2">
            <input
              type="text"
              value={inputLat}
              onChange={(e) => setInputLat(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="Latitude"
            />
            <input
              type="text"
              value={inputLng}
              onChange={(e) => setInputLng(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              placeholder="Longitude"
            />
            <button
              type="button"
              onClick={aplicarCoordenadasDigitadas}
              className="px-3 py-2 rounded-lg border border-indigo-300 text-indigo-700 hover:bg-indigo-50"
            >
              Aplicar coordenadas
            </button>
          </div>

          <div className="h-[420px] rounded-lg border border-gray-300 overflow-hidden bg-gray-100">
            <div ref={containerRef} className="h-full w-full" />
          </div>

          {carregandoMapa && <p className="text-sm text-gray-600">Carregando mapa...</p>}
          {erroMapa && <p className="text-sm text-red-600">{erroMapa}</p>}
          {coordenadas && (
            <p className="text-sm text-gray-700">
              Coordenadas selecionadas: <strong>{coordenadas.lat.toFixed(9)}</strong>,{" "}
              <strong>{coordenadas.lng.toFixed(9)}</strong>
            </p>
          )}
        </div>

        <div className="px-5 py-4 border-t border-gray-200 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={() => coordenadas && onConfirm(coordenadas)}
            disabled={!coordenadas}
            className="px-4 py-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Confirmar pin
          </button>
        </div>
      </div>
    </div>
  );
}
