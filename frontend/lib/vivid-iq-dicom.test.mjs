import assert from "node:assert/strict";
import test from "node:test";

import {
  VividIqDicomError,
  createVividIqDisplayMap,
  detectVividIqPreviewAspectRatio,
  findVividIqFrameAtTimestamp,
  getVividIqFramePixels,
  getVividIqIdentification,
  getVividIqPreviewJpeg,
  parseVividIqDicom,
  VIVID_IQ_MAX_FRAMES,
} from "./vivid-iq-dicom.mjs";

const LONG_VRS = new Set(["OB", "OD", "OF", "OL", "OV", "OW", "SQ", "UC", "UR", "UT", "UN"]);

function concat(...parts) {
  return Buffer.concat(parts.map((part) => Buffer.from(part)));
}

function evenText(value, padding = 0x20) {
  const raw = Buffer.from(value, "ascii");
  return raw.length % 2 ? concat(raw, Buffer.from([padding])) : raw;
}

function element(group, tag, vr, value) {
  const payload = Buffer.from(value);
  const header = Buffer.alloc(LONG_VRS.has(vr) ? 12 : 8);
  header.writeUInt16LE(group, 0);
  header.writeUInt16LE(tag, 2);
  header.write(vr, 4, 2, "ascii");
  if (LONG_VRS.has(vr)) {
    header.writeUInt32LE(payload.length, 8);
  } else {
    header.writeUInt16LE(payload.length, 6);
  }
  return concat(header, payload);
}

function textElement(group, tag, vr, value) {
  return element(group, tag, vr, evenText(value, vr === "UI" ? 0 : 0x20));
}

function uint16Element(group, tag, value) {
  const payload = Buffer.alloc(2);
  payload.writeUInt16LE(value);
  return element(group, tag, "US", payload);
}

function uint32Element(group, tag, value) {
  const payload = Buffer.alloc(4);
  payload.writeUInt32LE(value);
  return element(group, tag, "UL", payload);
}

function int32x4Element(group, tag, values) {
  const payload = Buffer.alloc(16);
  values.forEach((value, index) => payload.writeInt32LE(value, index * 4));
  return element(group, tag, "SL", payload);
}

function item(value) {
  const payload = Buffer.from(value);
  const header = Buffer.alloc(8);
  header.writeUInt16LE(0xfffe, 0);
  header.writeUInt16LE(0xe000, 2);
  header.writeUInt32LE(payload.length, 4);
  return concat(header, payload);
}

function undefinedLengthElement(group, tag, vr, fragments) {
  const header = Buffer.alloc(12);
  header.writeUInt16LE(group, 0);
  header.writeUInt16LE(tag, 2);
  header.write(vr, 4, 2, "ascii");
  header.writeUInt32LE(0xffffffff, 8);
  const delimiter = Buffer.alloc(8);
  delimiter.writeUInt16LE(0xfffe, 0);
  delimiter.writeUInt16LE(0xe0dd, 2);
  return concat(header, ...fragments.map((fragment) => item(fragment)), delimiter);
}

function timestampsBuffer(values) {
  const timestamps = Buffer.alloc(values.length * 8);
  values.forEach((value, index) => timestamps.writeDoubleLE(value, index * 8));
  return timestamps;
}

function sequence(group, tag, ...items) {
  return element(group, tag, "SQ", concat(...items.map((value) => item(value))));
}

function asArrayBuffer(value) {
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength);
}

function buildSyntheticVividIqDicom({
  includePrivateMovie = true,
  includeUltrasoundRegion = true,
  includeCurvedSurface = false,
  includePreview = false,
  imageSizes = [[2, 2]],
  metadata = textElement(0x0010, 0x0010, "PN", "PACIENTE^NAO_EXIBIR"),
  voxelGroupSpecs,
  rawPixels,
} = {}) {
  const preamble = Buffer.alloc(128);
  const magic = Buffer.from("DICM", "ascii");
  const meta = concat(
    textElement(0x0002, 0x0010, "UI", "1.2.840.10008.1.2.4.50"),
  );
  const ultrasoundRegion = includeUltrasoundRegion
    ? sequence(
        0x0018,
        0x6011,
        concat(
          uint16Element(0x0018, 0x6012, 1),
          uint32Element(0x0018, 0x6018, 10),
          uint32Element(0x0018, 0x601a, 20),
          uint32Element(0x0018, 0x601c, 209),
          uint32Element(0x0018, 0x601e, 119),
        ),
      )
    : Buffer.alloc(0);
  const preview = includePreview
    ? undefinedLengthElement(0x7fe0, 0x0010, "OB", [
        Buffer.alloc(4),
        Buffer.from([0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9]),
      ])
    : Buffer.alloc(0);
  const safeDataset = concat(
    textElement(0x0008, 0x0060, "CS", "US"),
    textElement(0x0008, 0x0070, "LO", "GE Vingmed Ultrasound"),
    textElement(0x0008, 0x1090, "LO", "Vivid iq"),
    metadata,
    ultrasoundRegion,
    uint16Element(0x0028, 0x0010, 708),
    uint16Element(0x0028, 0x0011, 1016),
    preview,
  );

  if (!includePrivateMovie) {
    return asArrayBuffer(concat(preamble, magic, meta, safeDataset));
  }

  const defaultPixels = rawPixels || Buffer.from([
    0, 64, 128, 255,
    255, 128, 64, 0,
  ]);
  const groups = voxelGroupSpecs || [{
    timestamps: [1, 1.1],
    pixels: defaultPixels,
  }];

  const imageDescription = sequence(
    0x7fe1,
    0x1026,
    concat(
      textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
      includeCurvedSurface
        ? textElement(0x7fe1, 0x1057, "LT", "CurvedSurface")
        : Buffer.alloc(0),
      ...imageSizes.map(([width, height]) => (
        int32x4Element(0x7fe1, 0x1086, [width, height, 0, 2])
      )),
    ),
  );
  const voxelGroups = sequence(
    0x7fe1,
    0x1036,
    ...groups.map((group) => concat(
      textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
      uint32Element(0x7fe1, 0x1037, group.declaredFrames ?? group.timestamps?.length ?? 0),
      group.timestamps === null
        ? Buffer.alloc(0)
        : element(0x7fe1, 0x1043, "OB", group.rawTimestamps || timestampsBuffer(group.timestamps)),
      element(0x7fe1, 0x1060, "OB", group.pixels),
    )),
  );
  const levelTwo = sequence(
    0x7fe1,
    0x1020,
    concat(
      textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
      imageDescription,
      voxelGroups,
    ),
  );
  const levelOne = sequence(
    0x7fe1,
    0x1010,
    concat(
      textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
      levelTwo,
    ),
  );
  const movie = concat(
    textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
    sequence(
      0x7fe1,
      0x1001,
      concat(
        textElement(0x7fe1, 0x0010, "LO", "GEMS_Ultrasound_MovieGroup_001"),
        textElement(0x7fe1, 0x1002, "LO", "2D+Trace"),
        levelOne,
      ),
    ),
  );

  return asArrayBuffer(concat(preamble, magic, meta, safeDataset, movie));
}

test("extrai cine GE sintetico sem expor metadados do paciente", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom(), "SEMEXTENSAO");

  assert.equal(study.fileName, "SEMEXTENSAO");
  assert.equal(study.model, "Vivid iq");
  assert.equal(study.cineType, "2D+Trace");
  assert.equal(study.width, 2);
  assert.equal(study.height, 2);
  assert.equal(study.displayWidth, 200);
  assert.equal(study.displayHeight, 100);
  assert.equal(study.displayAspectRatio, 2);
  assert.equal(study.displayAspectRatioSource, "ultrasound-region");
  assert.equal(study.frameCount, 2);
  assert.ok(Math.abs(study.durationSeconds - 0.1) < 0.0001);
  assert.ok(Math.abs(study.frameRate - 10) < 0.0001);
  assert.deepEqual([...getVividIqFramePixels(study, 0)], [0, 64, 128, 255]);
  assert.deepEqual([...getVividIqFramePixels(study, 1)], [255, 128, 64, 0]);
  assert.equal(findVividIqFrameAtTimestamp(study, 1.05), 0);
  assert.equal(findVividIqFrameAtTimestamp(study, 1.1), 1);
  assert.equal(JSON.stringify(study).includes("PACIENTE"), false);
});

test("usa proporcao nativa quando a regiao 2D do equipamento nao existe", () => {
  const study = parseVividIqDicom(
    buildSyntheticVividIqDicom({ includeUltrasoundRegion: false }),
  );

  assert.equal(study.displayWidth, 2);
  assert.equal(study.displayHeight, 2);
  assert.equal(study.displayAspectRatio, 1);
  assert.equal(study.displayAspectRatioSource, "native-pixels");
});

test("preserva dimensoes por bloco quando o equipamento muda a geometria no mesmo cine", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({
    includeUltrasoundRegion: false,
    imageSizes: [[2, 2], [3, 2]],
    voxelGroupSpecs: [
      {
        timestamps: [1, 1.1],
        pixels: Buffer.from([1, 2, 3, 4, 5, 6, 7, 8]),
      },
      {
        timestamps: [1.2],
        pixels: Buffer.from([9, 10, 11, 12, 13, 14]),
      },
    ],
  }));

  assert.equal(study.frameCount, 3);
  assert.deepEqual(study.frameDimensions, [
    { width: 2, height: 2, frameCount: 2 },
    { width: 3, height: 2, frameCount: 1 },
  ]);
  assert.deepEqual(
    study.frames.map(({ width, height, frameSize }) => ({ width, height, frameSize })),
    [
      { width: 2, height: 2, frameSize: 4 },
      { width: 2, height: 2, frameSize: 4 },
      { width: 3, height: 2, frameSize: 6 },
    ],
  );
  assert.deepEqual([...getVividIqFramePixels(study, 2)], [9, 10, 11, 12, 13, 14]);
  assert.ok(Math.abs(study.frameRate - 10) < 0.0001);
});

test("extrai a previa JPEG local sem interpretar seus metadados visuais", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({ includePreview: true }));
  assert.deepEqual(
    [...getVividIqPreviewJpeg(study)],
    [0xff, 0xd8, 0x01, 0x02, 0xff, 0xd9],
  );
});

test("orienta a varredura curva como setor com profundidade vertical", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({
    includeCurvedSurface: true,
    includeUltrasoundRegion: false,
  }));
  const mapping = createVividIqDisplayMap(5, 3, 5, 5, true, true);

  assert.equal(study.scanConversion, true);
  assert.equal(study.displayAspectRatioSource, "estimated-sector");
  assert.equal(mapping.length, 25);
  assert.ok(mapping.some((sourceIndex) => sourceIndex >= 0));
  assert.equal(mapping[2], 5);
  assert.equal(mapping[4], -1);
});

test("estima a proporcao da maior regiao neutra da previa", () => {
  const width = 120;
  const height = 100;
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let y = 20; y < 90; y += 1) {
    const halfWidth = Math.round((y - 20) * 0.6);
    for (let x = 60 - halfWidth; x <= 60 + halfWidth; x += 1) {
      const offset = (y * width + x) * 4;
      pixels[offset] = 90;
      pixels[offset + 1] = 90;
      pixels[offset + 2] = 90;
      pixels[offset + 3] = 255;
    }
  }

  const aspectRatio = detectVividIqPreviewAspectRatio(pixels, width, height, 4);
  assert.ok(aspectRatio > 1 && aspectRatio < 1.4);
});

test("rejeita arquivo sem assinatura DICM", () => {
  assert.throws(
    () => parseVividIqDicom(new ArrayBuffer(256)),
    (error) => error instanceof VividIqDicomError && error.code === "INVALID_DICOM",
  );
});

test("rejeita DICOM sem MovieGroup privado", () => {
  assert.throws(
    () => parseVividIqDicom(buildSyntheticVividIqDicom({ includePrivateMovie: false })),
    (error) => error instanceof VividIqDicomError && error.code === "UNSUPPORTED_GE_MOVIE",
  );
});

test("rejeita MovieGroup sem um quadro completo", () => {
  assert.throws(
    () => parseVividIqDicom(buildSyntheticVividIqDicom({ rawPixels: Buffer.from([1, 2, 3]) })),
    (error) => error instanceof VividIqDicomError && error.code === "INVALID_MOVIE",
  );
});

test("explicita quadros completos sem timestamps correspondentes", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({
    voxelGroupSpecs: [{ declaredFrames: 3, timestamps: [1, 1.1], pixels: Buffer.alloc(12) }],
  }));
  assert.equal(study.frameCount, 2);
  assert.deepEqual(study.frames.map((frame) => frame.timestampSeconds), [1, 1.1]);
  assert.equal(study.warnings.length, 1);
  assert.match(study.warnings[0], /3 declarados, 3 quadros completos nos pixels, 2 timestamps/);
  assert.match(study.warnings[0], /1 quadros sem timestamp correspondente nao foram exibidos/);
});

test("preserva quadros temporizados quando a declaracao e menor que os pixels", () => {
  for (const declaredFrames of [0, 2]) {
    const study = parseVividIqDicom(buildSyntheticVividIqDicom({
      voxelGroupSpecs: [{ declaredFrames, timestamps: [1, 1.1, 1.2], pixels: Buffer.alloc(12) }],
    }));
    assert.equal(study.frameCount, 3);
    assert.deepEqual(study.frames.map((frame) => frame.timestampSeconds), [1, 1.1, 1.2]);
    assert.ok(study.warnings[0].includes(`${declaredFrames} declarados, 3 quadros completos nos pixels, 3 timestamps`));
  }
});

test("nao le timestamps incompletos nem cria quadros a partir de contagem maior", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({
    voxelGroupSpecs: [{
      declaredFrames: 3,
      timestamps: [1, 1.1],
      rawTimestamps: concat(timestampsBuffer([1, 1.1]), Buffer.from([255, 255])),
      pixels: Buffer.alloc(8),
    }],
  }));
  assert.equal(study.frameCount, 2);
  assert.match(study.warnings[0], /3 declarados, 2 quadros completos nos pixels, 2 timestamps/);
  assert.match(study.warnings[0], /bytes incompletos/);
});

test("informa falta de timestamps e usa estimativa sem ler o bloco seguinte", () => {
  for (const timestamps of [null, []]) {
    const study = parseVividIqDicom(buildSyntheticVividIqDicom({
      voxelGroupSpecs: [{ declaredFrames: 2, timestamps, pixels: Buffer.alloc(8) }],
    }));
    assert.equal(study.frameCount, 2);
    assert.deepEqual(study.frames.map((frame) => frame.timestampSeconds), [0, 1 / 30]);
    assert.ok(study.warnings.some((warning) => warning.includes("0 timestamps")));
    assert.ok(study.warnings.some((warning) => warning.includes("30 fps estimados")));
  }
});

test("ignora componentes sem geometria 2D resolvida sem gerar aviso de quadros", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({
    voxelGroupSpecs: [
      { declaredFrames: 2, timestamps: [1, 1.1], pixels: Buffer.alloc(8) },
      { declaredFrames: 2, timestamps: [1.2, 1.3], pixels: Buffer.alloc(5) },
    ],
  }));
  assert.equal(study.frameCount, 2);
  assert.deepEqual(study.warnings, []);
});

test("aplica limite acumulado de quadros antes de expandir um cine excessivo", () => {
  const limit = VIVID_IQ_MAX_FRAMES;
  const block = { declaredFrames: limit, timestamps: null, pixels: Buffer.alloc(limit * 4) };
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({ voxelGroupSpecs: [block] }));
  assert.equal(study.frameCount, limit);
  assert.equal(study.maxFrameWidth, 2);
  assert.throws(
    () => parseVividIqDicom(buildSyntheticVividIqDicom({
      voxelGroupSpecs: [block, { declaredFrames: 1, timestamps: null, pixels: Buffer.alloc(4) }],
    })),
    (error) => error instanceof VividIqDicomError && error.code === "RESOURCE_LIMIT",
  );
});

test("identificacao opt-in formata campos top-level sem anexar dados ao study", () => {
  const study = parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
    textElement(0x0010, 0x0010, "PN", "FAMILIA^PACIENTE^^Dra.^Jr"),
    textElement(0x0008, 0x0020, "DA", "20240229"),
    textElement(0x0008, 0x0030, "TM", "230102.123"),
    textElement(0x0008, 0x002a, "DT", "20240301000102.12-0300"),
    textElement(0x0008, 0x0023, "DA", "20240301"),
    textElement(0x0008, 0x0033, "TM", "000203"),
    textElement(0x0008, 0x0201, "SH", "+0530"),
  ) }));
  const before = JSON.stringify(study);
  assert.deepEqual(getVividIqIdentification(study), {
    patientName: "FAMILIA PACIENTE Dra. Jr",
    patientNameRaw: "FAMILIA^PACIENTE^^Dra.^Jr",
    studyDate: "29/02/2024",
    studyTime: "23:01:02.123",
    acquisitionDateTime: "01/03/2024 00:01:02.12 UTC-03:00",
    contentDate: "01/03/2024",
    contentTime: "00:02:03",
    timezoneOffset: "UTC+05:30",
    warnings: [],
  });
  assert.equal(JSON.stringify(study), before);
  assert.equal(before.includes("FAMILIA"), false);
  assert.equal(before.includes("20240229"), false);
});

test("identificacao aceita Latin-1 e UTF-8 declarados sem adivinhar codificacao", () => {
  for (const [charset, encoding, raw, display] of [
    ["ISO_IR 100", "latin1", "Gonçalves^Cão", "Gonçalves Cão"],
    ["ISO_IR 192", "utf8", "Família^猫", "Família 猫"],
  ]) {
    const payload = Buffer.from(raw, encoding);
    const study = parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
      textElement(0x0008, 0x0005, "CS", charset),
      element(0x0010, 0x0010, "PN", payload.length % 2 ? concat(payload, Buffer.from([32])) : payload),
    ) }));
    const identification = getVividIqIdentification(study);
    assert.equal(identification.patientName, display);
    assert.equal(identification.patientNameRaw, raw);
    assert.deepEqual(identification.warnings, []);
  }
});

test("identificacao rejeita charset nao suportado, UTF-8 invalido e ASCII estendido", () => {
  for (const [charset, bytes] of [
    ["ISO 2022 IR 87", Buffer.from("NOME^TESTE")],
    ["ISO_IR 192", Buffer.from([0xc3, 0x28])],
    ["", Buffer.from([0xe7, 0x20])],
  ]) {
    const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
      textElement(0x0008, 0x0005, "CS", charset),
      element(0x0010, 0x0010, "PN", bytes),
      textElement(0x0008, 0x0020, "DA", "20240102"),
    ) })));
    assert.equal(identification.patientName, null);
    assert.equal(identification.patientNameRaw, null);
    assert.equal(identification.studyDate, "02/01/2024");
    assert.ok(identification.warnings.length > 0);
  }
});

test("charset repetido nao permite interpretar nome como ASCII por omissao", () => {
  const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
    textElement(0x0008, 0x0005, "CS", "ISO_IR 192"),
    textElement(0x0008, 0x0005, "CS", "ISO_IR 100"),
    textElement(0x0010, 0x0010, "PN", "NOME^SINTETICO"),
  ) })));
  assert.equal(identification.patientNameRaw, null);
  assert.equal(identification.patientName, null);
  assert.match(identification.warnings.join(" "), /campo repetido/);
});

test("identificacao ignora paciente e datas de sequencias aninhadas", () => {
  const nested = concat(
    textElement(0x0010, 0x0010, "PN", "NESTED^PATIENT"),
    textElement(0x0008, 0x0020, "DA", "20240101"),
    textElement(0x0008, 0x0005, "CS", "UNSUPPORTED"),
  );
  const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
    sequence(0x0008, 0x1110, nested),
    undefinedLengthElement(0x0008, 0x1115, "SQ", [nested]),
    textElement(0x0010, 0x0010, "PN", "TOP^LEVEL"),
    textElement(0x0008, 0x0020, "DA", "20240202"),
  ) })));
  assert.equal(identification.patientName, "TOP LEVEL");
  assert.equal(identification.studyDate, "02/02/2024");
  assert.deepEqual(identification.warnings, []);
});

test("campos ausentes ficam null e par DA/TM de aquisicao conserva precisao e fuso", () => {
  const empty = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: Buffer.alloc(0) })));
  assert.ok(Object.entries(empty).every(([key, value]) => key === "warnings" || value === null));
  assert.deepEqual(empty.warnings, []);
  const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
    textElement(0x0008, 0x0022, "DA", "20251022"),
    textElement(0x0008, 0x0032, "TM", "1411"),
    textElement(0x0008, 0x0030, "TM", "14"),
    textElement(0x0008, 0x0201, "SH", "-0300"),
  ) })));
  assert.equal(identification.acquisitionDateTime, "22/10/2025 14:11 UTC-03:00");
  assert.equal(identification.studyTime, "14");
  assert.deepEqual(identification.warnings, []);
});

test("identificacao omite valores invalidos, repetidos ou ambiguos com aviso sem PII", () => {
  const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata: concat(
    textElement(0x0010, 0x0010, "PN", "SEGREDO^UM"),
    textElement(0x0010, 0x0010, "PN", "SEGREDO^DOIS"),
    textElement(0x0008, 0x0020, "DA", "20230229"),
    textElement(0x0008, 0x0030, "TM", "240000"),
    textElement(0x0008, 0x002a, "DT", "202401"),
    textElement(0x0008, 0x0023, "DA", "20240431"),
    textElement(0x0008, 0x0033, "TM", "120000.1234567"),
    textElement(0x0008, 0x0201, "SH", "+1460"),
  ) })));
  assert.ok(Object.entries(identification).every(([key, value]) => key === "warnings" || value === null));
  assert.equal(identification.warnings.length, 7);
  assert.equal(JSON.stringify(identification).includes("SEGREDO"), false);
});

test("identificacao rejeita nome malformado, VR inesperado e leitura fora do buffer", () => {
  for (const raw of ["UM^DOIS^TRES^QUATRO^CINCO^SEIS", "UM\\DOIS", "NOME\u0000", "N".repeat(1026)]) {
    const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata:
      textElement(0x0010, 0x0010, "PN", raw),
    })));
    assert.equal(identification.patientName, null);
    assert.equal(identification.patientNameRaw, null);
    assert.ok(identification.warnings.length > 0);
  }
  const identification = getVividIqIdentification(parseVividIqDicom(buildSyntheticVividIqDicom({ metadata:
    textElement(0x0008, 0x0020, "LO", "20240101"),
  })));
  assert.equal(identification.studyDate, null);
  assert.match(identification.warnings[0], /formato ou tamanho invalido/);
  const original = buildSyntheticVividIqDicom();
  assert.throws(
    () => getVividIqIdentification({ sourceBuffer: original.slice(0, original.byteLength - 1) }),
    (error) => error instanceof VividIqDicomError && error.code === "INVALID_DICOM",
  );
});
