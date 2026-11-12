import { describe, expect, it } from "vitest";

import type { VividIqStudy } from "./vivid-iq-dicom.mjs";
import {
  buildVividIqGrayscaleLut,
  resolveVividIqPlayback,
  vividIqCaptureLines,
} from "./vivid-iq-player";

function makeStudy(timestamps: number[]): Pick<VividIqStudy, "frames" | "frameCount"> {
  return {
    frameCount: timestamps.length,
    frames: timestamps.map((timestampSeconds, index) => ({
      timestampSeconds,
      offset: index,
      width: 1,
      height: 1,
      frameSize: 1,
    })),
  };
}

describe("buildVividIqGrayscaleLut", () => {
  it("mantém R=G=B e alfa opaco em todos os níveis de contraste e brilho da interface", () => {
    for (const brightness of [-100, 0, 100]) {
      for (let step = 10; step <= 40; step += 1) {
        const lut = buildVividIqGrayscaleLut(brightness, step / 20);
        expect(lut.length).toBe(256);
        for (const color of lut) {
          const red = color & 0xff;
          const green = (color >>> 8) & 0xff;
          const blue = (color >>> 16) & 0xff;
          expect(red).toBe(green);
          expect(red).toBe(blue);
          expect(color >>> 24).toBe(255);
        }
      }
    }
  });

  it("arredonda o cinza antes de empacotar e satura os extremos sem transbordar", () => {
    expect(buildVividIqGrayscaleLut(0, 1.05)[100]).toBe(0xff636363);
    expect(buildVividIqGrayscaleLut(0, 1.05)[64]).toBe(0xff3d3d3d);
    expect(buildVividIqGrayscaleLut(-100, 2)[0]).toBe(0xff000000);
    expect(buildVividIqGrayscaleLut(100, 2)[255]).toBe(0xffffffff);
  });

  it("restaura pixels originais e trata ajustes não finitos como valores padrão", () => {
    for (const lut of [buildVividIqGrayscaleLut(0, 1), buildVividIqGrayscaleLut(NaN, Infinity)]) {
      for (let source = 0; source < 256; source += 1) {
        expect(lut[source] & 0xff).toBe(source);
      }
    }
  });
});

describe("resolveVividIqPlayback", () => {
  const study = makeStudy([10, 10.1, 10.3, 10.35, 10.6, 10.9]);

  it("respeita timestamps irregulares e a velocidade sem sair do intervalo inclusivo", () => {
    expect(resolveVividIqPlayback(study, 1, 0.09, 2, 1, 4, false))
      .toEqual({ frameIndex: 1, ended: false });
    expect(resolveVividIqPlayback(study, 1, 0.1, 2, 1, 4, false))
      .toEqual({ frameIndex: 2, ended: false });
    expect(resolveVividIqPlayback(study, 2, 0.1, 0.5, 1, 4, false))
      .toEqual({ frameIndex: 3, ended: false });
    expect(resolveVividIqPlayback(study, 1, 1, 1, 1, 4, false))
      .toEqual({ frameIndex: 4, ended: true });
  });

  it("encerra sem loop no último timestamp do segmento, mesmo antes do fim do arquivo", () => {
    expect(resolveVividIqPlayback(study, 1, 0.25, 1, 1, 3, false))
      .toEqual({ frameIndex: 3, ended: true });
    expect(resolveVividIqPlayback(study, 1, 0.249, 1, 1, 3, false))
      .toEqual({ frameIndex: 2, ended: false });
  });

  it("mantém o último quadro pelo delta final antes de repetir, inclusive após vários ciclos", () => {
    expect(resolveVividIqPlayback(study, 1, 0.275, 1, 1, 3, true))
      .toEqual({ frameIndex: 3, ended: false });
    expect(resolveVividIqPlayback(study, 1, 0.3, 1, 1, 3, true))
      .toEqual({ frameIndex: 1, ended: false });
    expect(resolveVividIqPlayback(study, 1, 0.85, 1, 1, 3, true))
      .toEqual({ frameIndex: 3, ended: false });
    expect(resolveVividIqPlayback(study, 3, 0.05, 1, 1, 3, true))
      .toEqual({ frameIndex: 1, ended: false });
  });

  it("usa o delta inicial ou 30 fps quando o último delta não é positivo", () => {
    const repeated = makeStudy([0, 0.1, 0.1]);
    expect(resolveVividIqPlayback(repeated, 0, 0.15, 1, 0, 2, true))
      .toEqual({ frameIndex: 2, ended: false });
    expect(resolveVividIqPlayback(repeated, 0, 0.2, 1, 0, 2, true))
      .toEqual({ frameIndex: 0, ended: false });
    expect(resolveVividIqPlayback(makeStudy([4, 4]), 0, 1, 1, 0, 1, true))
      .toEqual({ frameIndex: 1, ended: false });
  });

  it("normaliza intervalos invertidos e limita índices e âncora aos quadros disponíveis", () => {
    expect(resolveVividIqPlayback(study, 0, 0, 1, 3, 1, false))
      .toEqual({ frameIndex: 1, ended: false });
    expect(resolveVividIqPlayback(study, 100, 0, 1, -20, 100, false))
      .toEqual({ frameIndex: 5, ended: true });
    expect(resolveVividIqPlayback({ ...study, frameCount: 100 }, 0, 20, 1, 0, 99, false))
      .toEqual({ frameIndex: 5, ended: true });
  });

  it("mantém um quadro no loop e encerra imediatamente um segmento sem duração sem loop", () => {
    expect(resolveVividIqPlayback(study, 3, 100, 2, 3, 3, true))
      .toEqual({ frameIndex: 3, ended: false });
    expect(resolveVividIqPlayback(study, 3, 0, 1, 3, 3, false))
      .toEqual({ frameIndex: 3, ended: true });
    expect(resolveVividIqPlayback(makeStudy([0]), 0, 0.2, 1, 0, 0, true))
      .toEqual({ frameIndex: 0, ended: false });
    expect(resolveVividIqPlayback(makeStudy([]), 0, 1, 1, 0, 0, true))
      .toEqual({ frameIndex: 0, ended: true });
  });

  it("trata relógio e velocidade inválidos sem produzir um índice inexistente", () => {
    expect(resolveVividIqPlayback(study, 1, -2, 1, 1, 3, false))
      .toEqual({ frameIndex: 1, ended: false });
    expect(resolveVividIqPlayback(study, 1, 0.2, 0, 1, 3, false))
      .toEqual({ frameIndex: 2, ended: false });
    expect(resolveVividIqPlayback(study, NaN, Infinity, NaN, NaN, NaN, true))
      .toEqual({ frameIndex: 0, ended: false });
  });
});

describe("vividIqCaptureLines", () => {
  it("identifica derivação, tempo, ajustes e inversão sem metadados de paciente", () => {
    expect(vividIqCaptureLines({
      frameIndex: 9,
      frameCount: 100,
      currentSeconds: 1.234,
      brightness: 10,
      contrast: 1.05,
      lateralInverted: true,
    })).toEqual([
      "Captura derivada — não calibrada · Vivid IQ",
      "Quadro 10 de 100 · 1,23 s",
      "Brilho +10 · Contraste 1,05x · Inversão lateral: sim",
    ]);
  });

  it("torna explícito quando a captura não tem inversão lateral e mantém brilho negativo", () => {
    const lines = vividIqCaptureLines({
      frameIndex: 0,
      frameCount: 1,
      currentSeconds: 0,
      brightness: -20,
      contrast: 1,
      lateralInverted: false,
    });
    expect(lines[2]).toBe("Brilho -20 · Contraste 1,00x · Inversão lateral: não");
  });
});
