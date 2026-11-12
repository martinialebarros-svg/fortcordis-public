const DICOM_MAGIC_OFFSET = 128;
const DICOM_DATASET_OFFSET = 132;
const UNDEFINED_LENGTH = 0xffffffff;
const ITEM_GROUP = 0xfffe;
const ITEM_TAG = 0xe000;
const ITEM_DELIMITATION_TAG = 0xe00d;
const SEQUENCE_DELIMITATION_TAG = 0xe0dd;
const PRIVATE_GROUP = 0x7fe1;
const PRIVATE_CREATOR = "GEMS_Ultrasound_MovieGroup_001";
const MAX_FILE_BYTES = 512 * 1024 * 1024;
const MAX_ELEMENTS = 100_000;
const MAX_DEPTH = 48;
const MAX_FRAMES = 100_000;

const LONG_VALUE_REPRESENTATIONS = new Set([
  "OB",
  "OD",
  "OF",
  "OL",
  "OV",
  "OW",
  "SQ",
  "UC",
  "UR",
  "UT",
  "UN",
]);

export class VividIqDicomError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "VividIqDicomError";
    this.code = code;
  }
}

function fail(code, message) {
  throw new VividIqDicomError(code, message);
}

function assertBounds(offset, length, end, message) {
  if (
    !Number.isSafeInteger(offset)
    || !Number.isSafeInteger(length)
    || offset < 0
    || length < 0
    || offset + length > end
  ) {
    fail("INVALID_DICOM", message);
  }
}

function readAscii(view, offset, length) {
  assertBounds(offset, length, view.byteLength, "Texto DICOM ultrapassa o tamanho do arquivo.");
  let value = "";
  for (let index = 0; index < length; index += 1) {
    value += String.fromCharCode(view.getUint8(offset + index));
  }
  return value.replace(/[\0 ]+$/g, "");
}

function tagMatches(header, group, element) {
  return header.group === group && header.element === element;
}

function readElementHeader(view, offset, end) {
  assertBounds(offset, 8, end, "Cabecalho de elemento DICOM incompleto.");
  const group = view.getUint16(offset, true);
  const element = view.getUint16(offset + 2, true);

  if (group === ITEM_GROUP) {
    return {
      group,
      element,
      valueRepresentation: null,
      valueLength: view.getUint32(offset + 4, true),
      valueOffset: offset + 8,
      headerOffset: offset,
    };
  }

  const valueRepresentation = String.fromCharCode(
    view.getUint8(offset + 4),
    view.getUint8(offset + 5),
  );
  if (!/^[A-Z]{2}$/.test(valueRepresentation)) {
    fail(
      "INVALID_DICOM",
      "O conjunto de dados nao usa Explicit VR Little Endian ou esta corrompido.",
    );
  }

  let valueLength;
  let valueOffset;
  if (LONG_VALUE_REPRESENTATIONS.has(valueRepresentation)) {
    assertBounds(offset, 12, end, "Cabecalho DICOM longo incompleto.");
    valueLength = view.getUint32(offset + 8, true);
    valueOffset = offset + 12;
  } else {
    valueLength = view.getUint16(offset + 6, true);
    valueOffset = offset + 8;
  }

  if (valueLength !== UNDEFINED_LENGTH) {
    assertBounds(valueOffset, valueLength, end, "Valor DICOM ultrapassa o tamanho do arquivo.");
  }

  return {
    group,
    element,
    valueRepresentation,
    valueLength,
    valueOffset,
    headerOffset: offset,
  };
}

function collectElement(state, context, header) {
  const { view } = state;

  if (tagMatches(header, 0x0008, 0x0060)) {
    state.modality = readAscii(view, header.valueOffset, header.valueLength);
    return;
  }
  if (tagMatches(header, 0x0008, 0x0070)) {
    state.manufacturer = readAscii(view, header.valueOffset, header.valueLength);
    return;
  }
  if (tagMatches(header, 0x0008, 0x1090)) {
    state.model = readAscii(view, header.valueOffset, header.valueLength);
    return;
  }
  if (tagMatches(header, 0x0028, 0x0010) && header.valueLength >= 2) {
    state.previewHeight = view.getUint16(header.valueOffset, true);
    return;
  }
  if (tagMatches(header, 0x0028, 0x0011) && header.valueLength >= 2) {
    state.previewWidth = view.getUint16(header.valueOffset, true);
    return;
  }

  if (context.ultrasoundRegion) {
    if (tagMatches(header, 0x0018, 0x6012) && header.valueLength >= 2) {
      context.ultrasoundRegion.spatialFormat = view.getUint16(header.valueOffset, true);
      return;
    }
    if (tagMatches(header, 0x0018, 0x6018) && header.valueLength >= 4) {
      context.ultrasoundRegion.minX = view.getUint32(header.valueOffset, true);
      return;
    }
    if (tagMatches(header, 0x0018, 0x601a) && header.valueLength >= 4) {
      context.ultrasoundRegion.minY = view.getUint32(header.valueOffset, true);
      return;
    }
    if (tagMatches(header, 0x0018, 0x601c) && header.valueLength >= 4) {
      context.ultrasoundRegion.maxX = view.getUint32(header.valueOffset, true);
      return;
    }
    if (tagMatches(header, 0x0018, 0x601e) && header.valueLength >= 4) {
      context.ultrasoundRegion.maxY = view.getUint32(header.valueOffset, true);
      return;
    }
  }

  if (tagMatches(header, PRIVATE_GROUP, 0x0010)) {
    const creator = readAscii(view, header.valueOffset, header.valueLength);
    if (creator === PRIVATE_CREATOR) {
      state.privateCreatorFound = true;
    }
    return;
  }
  if (tagMatches(header, PRIVATE_GROUP, 0x1002)) {
    const cineType = readAscii(view, header.valueOffset, header.valueLength);
    if (!state.cineType || cineType.includes("2D")) {
      state.cineType = cineType;
    }
    return;
  }
  if (tagMatches(header, PRIVATE_GROUP, 0x1057)) {
    if (readAscii(view, header.valueOffset, header.valueLength) === "CurvedSurface") {
      state.curvedSurfaceFound = true;
    }
    return;
  }
  if (tagMatches(header, PRIVATE_GROUP, 0x1086) && header.valueLength >= 16) {
    state.imageSizeCandidates.push({
      width: view.getInt32(header.valueOffset, true),
      height: view.getInt32(header.valueOffset + 4, true),
      component: view.getInt32(header.valueOffset + 8, true),
      kind: view.getInt32(header.valueOffset + 12, true),
    });
    return;
  }

  if (!context.voxelGroup) {
    return;
  }

  if (tagMatches(header, PRIVATE_GROUP, 0x1037) && header.valueLength >= 4) {
    context.voxelGroup.declaredFrames = view.getUint32(header.valueOffset, true);
    return;
  }
  if (tagMatches(header, PRIVATE_GROUP, 0x1043)) {
    context.voxelGroup.timestampsOffset = header.valueOffset;
    context.voxelGroup.timestampsLength = header.valueLength;
    return;
  }
  if (tagMatches(header, PRIVATE_GROUP, 0x1060)) {
    context.voxelGroup.voxelsOffset = header.valueOffset;
    context.voxelGroup.voxelsLength = header.valueLength;
  }
}

function collectEncapsulatedPreview(state, header, end) {
  let position = header.valueOffset;
  let fragmentIndex = 0;

  while (position + 8 <= end) {
    const item = readElementHeader(state.view, position, end);
    if (item.group !== ITEM_GROUP) {
      return;
    }
    if (item.element === SEQUENCE_DELIMITATION_TAG) {
      return;
    }
    if (item.element !== ITEM_TAG || item.valueLength === UNDEFINED_LENGTH) {
      return;
    }
    if (
      fragmentIndex > 0
      && item.valueLength >= 4
      && state.view.getUint8(item.valueOffset) === 0xff
      && state.view.getUint8(item.valueOffset + 1) === 0xd8
    ) {
      state.previewJpegOffset = item.valueOffset;
      state.previewJpegLength = item.valueLength;
      return;
    }
    fragmentIndex += 1;
    position = item.valueOffset + item.valueLength;
  }
}

function skipUndefinedBinary(state, valueOffset, end) {
  const { view } = state;
  let position = valueOffset;
  while (position + 8 <= end) {
    const item = readElementHeader(view, position, end);
    if (item.group !== ITEM_GROUP) {
      fail("INVALID_DICOM", "Item encapsulado DICOM invalido.");
    }
    if (item.element === SEQUENCE_DELIMITATION_TAG) {
      return item.valueOffset;
    }
    if (item.element !== ITEM_TAG || item.valueLength === UNDEFINED_LENGTH) {
      fail("INVALID_DICOM", "Fragmento encapsulado DICOM invalido.");
    }
    position = item.valueOffset + item.valueLength;
  }
  fail("INVALID_DICOM", "Sequencia encapsulada sem delimitador.");
}

function parseSequence(state, header, context, depth, end) {
  if (depth > MAX_DEPTH) {
    fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de sequencias aninhadas.");
  }

  const { view } = state;
  const sequenceEnd = header.valueLength === UNDEFINED_LENGTH
    ? end
    : header.valueOffset + header.valueLength;
  const isVoxelGroupSequence = tagMatches(header, PRIVATE_GROUP, 0x1036);
  const isUltrasoundRegionSequence = tagMatches(header, 0x0018, 0x6011);
  let position = header.valueOffset;

  while (position + 8 <= sequenceEnd) {
    const item = readElementHeader(view, position, sequenceEnd);
    if (item.group !== ITEM_GROUP) {
      fail("INVALID_DICOM", "Sequencia DICOM contem um item invalido.");
    }
    if (item.element === SEQUENCE_DELIMITATION_TAG) {
      return item.valueOffset;
    }
    if (item.element !== ITEM_TAG) {
      fail("INVALID_DICOM", "Delimitador inesperado dentro de sequencia DICOM.");
    }

    const itemEnd = item.valueLength === UNDEFINED_LENGTH
      ? sequenceEnd
      : item.valueOffset + item.valueLength;
    const voxelGroup = isVoxelGroupSequence
      ? {
          declaredFrames: null,
          timestampsOffset: null,
          timestampsLength: 0,
          voxelsOffset: null,
          voxelsLength: 0,
        }
      : context.voxelGroup;
    const ultrasoundRegion = isUltrasoundRegionSequence
      ? {
          spatialFormat: null,
          minX: null,
          minY: null,
          maxX: null,
          maxY: null,
        }
      : context.ultrasoundRegion;

    if (isVoxelGroupSequence) {
      state.voxelGroups.push(voxelGroup);
    }
    if (isUltrasoundRegionSequence) {
      state.ultrasoundRegions.push(ultrasoundRegion);
    }

    const parsed = parseDataset(
      state,
      item.valueOffset,
      itemEnd,
      { voxelGroup, ultrasoundRegion },
      depth + 1,
    );

    if (item.valueLength === UNDEFINED_LENGTH) {
      if (parsed.delimiter !== ITEM_DELIMITATION_TAG) {
        fail("INVALID_DICOM", "Item DICOM indefinido sem delimitador.");
      }
      position = parsed.position + 8;
    } else {
      position = itemEnd;
    }
  }

  if (header.valueLength === UNDEFINED_LENGTH) {
    fail("INVALID_DICOM", "Sequencia DICOM indefinida sem delimitador.");
  }
  return sequenceEnd;
}

function parseDataset(
  state,
  start,
  end,
  context = { voxelGroup: null, ultrasoundRegion: null },
  depth = 0,
) {
  if (depth > MAX_DEPTH) {
    fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de profundidade.");
  }

  let position = start;
  while (position + 8 <= end) {
    const header = readElementHeader(state.view, position, end);
    if (header.group === ITEM_GROUP) {
      return { position, delimiter: header.element };
    }

    state.elementCount += 1;
    if (state.elementCount > MAX_ELEMENTS) {
      fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de elementos.");
    }

    collectElement(state, context, header);

    if (header.valueRepresentation === "SQ") {
      position = parseSequence(state, header, context, depth + 1, end);
    } else if (header.valueLength === UNDEFINED_LENGTH) {
      if (tagMatches(header, 0x7fe0, 0x0010)) {
        collectEncapsulatedPreview(state, header, end);
      }
      position = skipUndefinedBinary(state, header.valueOffset, end);
    } else {
      position = header.valueOffset + header.valueLength;
    }
  }

  return { position, delimiter: null };
}

function parseMetaHeader(state) {
  let position = DICOM_DATASET_OFFSET;
  while (position + 8 <= state.view.byteLength) {
    const group = state.view.getUint16(position, true);
    if (group !== 0x0002) {
      break;
    }
    const header = readElementHeader(state.view, position, state.view.byteLength);
    if (tagMatches(header, 0x0002, 0x0010)) {
      state.transferSyntax = readAscii(
        state.view,
        header.valueOffset,
        header.valueLength,
      );
    }
    state.elementCount += 1;
    if (state.elementCount > MAX_ELEMENTS) {
      fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de elementos.");
    }
    position = header.valueOffset + header.valueLength;
  }
  return position;
}

function validateTransferSyntax(transferSyntax) {
  if (!transferSyntax) {
    fail("INVALID_DICOM", "O DICOM nao informa a sintaxe de transferencia.");
  }
  if (
    transferSyntax === "1.2.840.10008.1.2"
    || transferSyntax === "1.2.840.10008.1.2.2"
  ) {
    fail(
      "UNSUPPORTED_TRANSFER_SYNTAX",
      "Esta versao aceita apenas conjuntos de dados Explicit VR Little Endian.",
    );
  }
}

function listValidImageSizes(candidates) {
  return candidates.filter(({ width, height }) => (
    Number.isInteger(width)
    && Number.isInteger(height)
    && width > 0
    && height > 0
    && width <= 8192
    && height <= 8192
  )).map((candidate) => ({
    ...candidate,
    frameSize: candidate.width * candidate.height,
  }));
}

function chooseImageSize(imageSizes, groups) {
  const ranked = imageSizes.map((candidate) => {
    let exactGroups = 0;
    let compatibleGroups = 0;
    for (const group of groups) {
      if (!group.voxelsLength || group.voxelsLength < candidate.frameSize) {
        continue;
      }
      const availableFrames = Math.floor(group.voxelsLength / candidate.frameSize);
      if (availableFrames > 0) {
        compatibleGroups += 1;
      }
      if (
        group.declaredFrames
        && availableFrames === group.declaredFrames
        && group.voxelsLength % candidate.frameSize === 0
      ) {
        exactGroups += 1;
      }
    }
    return {
      ...candidate,
      exactGroups,
      compatibleGroups,
    };
  });

  ranked.sort((left, right) => (
    right.exactGroups - left.exactGroups
    || right.compatibleGroups - left.compatibleGroups
    || right.frameSize - left.frameSize
  ));

  const selected = ranked[0];
  if (!selected || selected.compatibleGroups === 0) {
    fail("INVALID_MOVIE", "Nao foi possivel determinar as dimensoes do cine GE.");
  }
  return selected;
}

function chooseDisplayGeometry(regions, imageSize, scanConversion) {
  const validTwoDimensionalRegions = regions
    .filter((region) => (
      region.spatialFormat === 1
      && Number.isInteger(region.minX)
      && Number.isInteger(region.minY)
      && Number.isInteger(region.maxX)
      && Number.isInteger(region.maxY)
      && region.maxX >= region.minX
      && region.maxY >= region.minY
    ))
    .map((region) => ({
      width: region.maxX - region.minX + 1,
      height: region.maxY - region.minY + 1,
    }))
    .filter(({ width, height }) => (
      width > 0
      && height > 0
      && width <= 8192
      && height <= 8192
      && width / height >= 0.2
      && width / height <= 5
    ));

  validTwoDimensionalRegions.sort((left, right) => (
    Math.abs(Math.log(left.width / imageSize.width))
    - Math.abs(Math.log(right.width / imageSize.width))
  ));

  const selected = validTwoDimensionalRegions[0];
  if (!selected) {
    if (scanConversion) {
      return {
        displayWidth: 1,
        displayHeight: 1,
        displayAspectRatio: 1,
        displayAspectRatioSource: "estimated-sector",
      };
    }
    return {
      displayWidth: imageSize.width,
      displayHeight: imageSize.height,
      displayAspectRatio: imageSize.width / imageSize.height,
      displayAspectRatioSource: "native-pixels",
    };
  }

  return {
    displayWidth: selected.width,
    displayHeight: selected.height,
    displayAspectRatio: selected.width / selected.height,
    displayAspectRatioSource: "ultrasound-region",
  };
}

function chooseGroupImageSize(group, imageSizes) {
  const timestampCount = group.timestampsOffset === null
    ? 0
    : Math.floor(group.timestampsLength / 8);
  const expectedFrameCounts = [group.declaredFrames, timestampCount]
    .filter((value) => Number.isInteger(value) && value > 0);

  const exact = imageSizes.filter((candidate) => expectedFrameCounts.some(
    (frameCount) => candidate.frameSize * frameCount === group.voxelsLength,
  ));
  if (exact.length) {
    exact.sort((left, right) => (
      Number(right.kind === 2) - Number(left.kind === 2)
      || Number(right.component === 0) - Number(left.component === 0)
      || right.frameSize - left.frameSize
    ));
    return exact[0];
  }

  if (!expectedFrameCounts.length) {
    const divisible = imageSizes.filter((candidate) => (
      group.voxelsLength >= candidate.frameSize
      && group.voxelsLength % candidate.frameSize === 0
    ));
    divisible.sort((left, right) => right.frameSize - left.frameSize);
    return divisible[0] || null;
  }
  return null;
}

function buildFrames(state, imageSizes) {
  const frames = [];
  const warnings = [];

  for (const [groupIndex, group] of state.voxelGroups.entries()) {
    if (group.voxelsOffset === null || !group.voxelsLength) {
      continue;
    }

    const imageSize = chooseGroupImageSize(group, imageSizes);
    if (!imageSize) {
      continue;
    }

    const availableFrames = Math.floor(group.voxelsLength / imageSize.frameSize);
    const declaredFrames = Number.isInteger(group.declaredFrames) && group.declaredFrames >= 0
      ? group.declaredFrames
      : null;
    const timestampCount = group.timestampsOffset === null
      ? 0
      : Math.floor(group.timestampsLength / 8);
    let frameCount = availableFrames;
    if (timestampCount > 0) {
      frameCount = Math.min(frameCount, timestampCount);
    }

    if (
      declaredFrames !== availableFrames
      || timestampCount !== availableFrames
      || group.timestampsLength % 8 !== 0
    ) {
      const omittedFrames = availableFrames - frameCount;
      warnings.push(
        `Bloco ${groupIndex + 1}: contagens divergentes (${declaredFrames ?? "nao informados"} declarados, ${availableFrames} quadros completos nos pixels, ${timestampCount} timestamps); ${frameCount} quadros exibidos.`
        + (omittedFrames > 0 ? ` ${omittedFrames} quadros sem timestamp correspondente nao foram exibidos.` : "")
        + (group.timestampsLength % 8 !== 0 ? " O registro de timestamps possui bytes incompletos." : ""),
      );
    }

    if (frames.length + frameCount > MAX_FRAMES) {
      fail("RESOURCE_LIMIT", "O cine excede o limite local de 100.000 quadros.");
    }

    if (frameCount <= 0) {
      continue;
    }
    for (let frameIndex = 0; frameIndex < frameCount; frameIndex += 1) {
      const timestampSeconds = group.timestampsOffset === null || frameIndex >= timestampCount
        ? Number.NaN
        : state.view.getFloat64(group.timestampsOffset + frameIndex * 8, true);
      frames.push({
        offset: group.voxelsOffset + frameIndex * imageSize.frameSize,
        timestampSeconds,
        width: imageSize.width,
        height: imageSize.height,
        frameSize: imageSize.frameSize,
      });
    }
  }

  if (!frames.length) {
    fail("INVALID_MOVIE", "O MovieGroup foi encontrado, mas nao contem quadros 2D completos.");
  }

  let timestampsAreMonotonic = true;
  for (let index = 0; index < frames.length; index += 1) {
    if (!Number.isFinite(frames[index].timestampSeconds)) {
      timestampsAreMonotonic = false;
      break;
    }
    if (
      index > 0
      && frames[index].timestampSeconds <= frames[index - 1].timestampSeconds
    ) {
      timestampsAreMonotonic = false;
      break;
    }
  }

  if (!timestampsAreMonotonic) {
    for (let index = 0; index < frames.length; index += 1) {
      frames[index].timestampSeconds = index / 30;
    }
    warnings.push("Os timestamps privados estavam ausentes ou fora de ordem; a reproducao usa 30 fps estimados.");
  }

  const firstTimestamp = frames[0].timestampSeconds;
  const lastTimestamp = frames[frames.length - 1].timestampSeconds;
  const durationSeconds = Math.max(0, lastTimestamp - firstTimestamp);
  const frameRate = durationSeconds > 0 && frames.length > 1
    ? (frames.length - 1) / durationSeconds
    : 30;
  const dimensions = new Map();
  let maxFrameWidth = 0;
  for (const frame of frames) {
    maxFrameWidth = Math.max(maxFrameWidth, frame.width);
    const key = `${frame.width}x${frame.height}`;
    const current = dimensions.get(key) || {
      width: frame.width,
      height: frame.height,
      frameCount: 0,
    };
    current.frameCount += 1;
    dimensions.set(key, current);
  }

  return {
    frames,
    warnings: [...new Set(warnings)],
    frameRate,
    firstTimestamp,
    durationSeconds,
    frameDimensions: [...dimensions.values()],
    maxFrameWidth,
  };
}

export function parseVividIqDicom(buffer, fileName = "arquivo DICOM") {
  if (!(buffer instanceof ArrayBuffer)) {
    fail("INVALID_INPUT", "O visualizador recebeu um arquivo invalido.");
  }
  if (buffer.byteLength > MAX_FILE_BYTES) {
    fail("RESOURCE_LIMIT", "O arquivo excede o limite local de 512 MB.");
  }
  if (buffer.byteLength < DICOM_DATASET_OFFSET) {
    fail("INVALID_DICOM", "O arquivo e pequeno demais para ser um DICOM Part 10.");
  }

  const view = new DataView(buffer);
  if (readAscii(view, DICOM_MAGIC_OFFSET, 4) !== "DICM") {
    fail("INVALID_DICOM", "Assinatura DICM nao encontrada. Selecione o arquivo original exportado pelo equipamento.");
  }

  const state = {
    view,
    elementCount: 0,
    transferSyntax: "",
    modality: "",
    manufacturer: "",
    model: "",
    cineType: "",
    previewWidth: null,
    previewHeight: null,
    previewJpegOffset: null,
    previewJpegLength: 0,
    privateCreatorFound: false,
    curvedSurfaceFound: false,
    imageSizeCandidates: [],
    voxelGroups: [],
    ultrasoundRegions: [],
  };

  const datasetOffset = parseMetaHeader(state);
  validateTransferSyntax(state.transferSyntax);
  parseDataset(state, datasetOffset, buffer.byteLength);

  if (!state.privateCreatorFound) {
    fail(
      "UNSUPPORTED_GE_MOVIE",
      "Este DICOM nao contem GEMS_Ultrasound_MovieGroup_001 e nao e suportado por este visualizador.",
    );
  }
  if (!state.voxelGroups.some((group) => group.voxelsOffset !== null)) {
    fail(
      "UNSUPPORTED_GE_MOVIE",
      "O arquivo possui metadados GE, mas nao contem um cine 2D no formato MovieGroup conhecido.",
    );
  }

  const imageSizes = listValidImageSizes(state.imageSizeCandidates);
  const imageSize = chooseImageSize(imageSizes, state.voxelGroups);
  const timeline = buildFrames(state, imageSizes);
  const scanConversion = state.curvedSurfaceFound && state.cineType.includes("2D");
  const displayGeometry = chooseDisplayGeometry(
    state.ultrasoundRegions,
    imageSize,
    scanConversion,
  );
  const equipment = [state.manufacturer, state.model].filter(Boolean).join(" · ");

  return {
    fileName,
    fileSize: buffer.byteLength,
    transferSyntax: state.transferSyntax,
    modality: state.modality || "US",
    manufacturer: state.manufacturer || "GE Ultrasound",
    model: state.model || "Vivid iq",
    equipment: equipment || "GE Vivid iq",
    cineType: state.cineType || "2D",
    previewWidth: state.previewWidth,
    previewHeight: state.previewHeight,
    width: imageSize.width,
    height: imageSize.height,
    ...displayGeometry,
    frameSize: imageSize.frameSize,
    frameDimensions: timeline.frameDimensions,
    maxFrameWidth: timeline.maxFrameWidth,
    scanConversion,
    previewJpegOffset: state.previewJpegOffset,
    previewJpegLength: state.previewJpegLength,
    frameCount: timeline.frames.length,
    frameRate: timeline.frameRate,
    durationSeconds: timeline.durationSeconds,
    firstTimestamp: timeline.firstTimestamp,
    frames: timeline.frames,
    warnings: timeline.warnings,
    sourceBuffer: buffer,
  };
}

export function getVividIqFramePixels(study, frameIndex) {
  if (!Number.isInteger(frameIndex) || frameIndex < 0 || frameIndex >= study.frameCount) {
    fail("INVALID_FRAME", "Quadro solicitado fora da sequencia.");
  }
  const frame = study.frames[frameIndex];
  return new Uint8Array(study.sourceBuffer, frame.offset, frame.frameSize);
}

const IDENTIFICATION_FIELDS = new Map([
  [0x00080005, { key: "characterSet", vr: "CS", label: "Conjunto de caracteres" }],
  [0x00100010, { key: "patientName", vr: "PN", label: "Nome do paciente" }],
  [0x00080020, { key: "studyDate", vr: "DA", label: "Data do estudo" }],
  [0x00080030, { key: "studyTime", vr: "TM", label: "Hora do estudo" }],
  [0x0008002a, { key: "acquisitionDateTime", vr: "DT", label: "Data/hora da aquisicao" }],
  [0x00080022, { key: "acquisitionDate", vr: "DA", label: "Data da aquisicao" }],
  [0x00080032, { key: "acquisitionTime", vr: "TM", label: "Hora da aquisicao" }],
  [0x00080023, { key: "contentDate", vr: "DA", label: "Data do conteudo" }],
  [0x00080033, { key: "contentTime", vr: "TM", label: "Hora do conteudo" }],
  [0x00080201, { key: "timezoneOffset", vr: "SH", label: "Fuso horario" }],
]);

function readIdentificationHeaders(state, start, end, depth = 0, delimiter = null) {
  if (depth > MAX_DEPTH) {
    fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de profundidade.");
  }
  let position = start;
  while (position + 8 <= end) {
    const header = readElementHeader(state.view, position, end);
    state.elementCount += 1;
    if (state.elementCount > MAX_ELEMENTS) {
      fail("RESOURCE_LIMIT", "O DICOM excede o limite seguro de elementos.");
    }
    if (header.group === ITEM_GROUP && header.element !== ITEM_TAG) {
      if (header.element !== delimiter || header.valueLength !== 0) {
        fail("INVALID_DICOM", "Delimitador DICOM inesperado na leitura da identificacao.");
      }
      return header.valueOffset;
    }
    if (depth === 0) {
      const descriptor = IDENTIFICATION_FIELDS.get(header.group * 0x10000 + header.element);
      if (descriptor) {
        if (state.fields.has(descriptor.key)) {
          state.fields.set(descriptor.key, null);
          state.warnings.add(`${descriptor.label}: campo repetido; valor nao exibido.`);
        } else if (header.valueRepresentation !== descriptor.vr || header.valueLength > 1024) {
          state.fields.set(descriptor.key, null);
          state.warnings.add(`${descriptor.label}: formato ou tamanho invalido; valor nao exibido.`);
        } else {
          state.fields.set(descriptor.key, header);
        }
      }
    }
    if (header.valueLength === UNDEFINED_LENGTH) {
      position = readIdentificationHeaders(
        state,
        header.valueOffset,
        end,
        depth + 1,
        header.group === ITEM_GROUP ? ITEM_DELIMITATION_TAG : SEQUENCE_DELIMITATION_TAG,
      );
    } else {
      position = header.valueOffset + header.valueLength;
    }
  }
  if (delimiter !== null || position !== end) {
    fail("INVALID_DICOM", "Estrutura DICOM incompleta na leitura da identificacao.");
  }
  return position;
}

function formatDicomDate(value) {
  if (!/^\d{8}$/.test(value)) {
    return null;
  }
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1]) {
    return null;
  }
  return `${value.slice(6, 8)}/${value.slice(4, 6)}/${value.slice(0, 4)}`;
}

function formatDicomTime(value) {
  const match = /^(\d{2})(?:(\d{2})(?:(\d{2})(\.\d{1,6})?)?)?$/.exec(value);
  if (!match || Number(match[1]) > 23 || Number(match[2] || 0) > 59 || Number(match[3] || 0) > 60) {
    return null;
  }
  return [match[1], match[2], match[3]].filter((part) => part !== undefined).join(":") + (match[4] || "");
}

function formatDicomOffset(value) {
  if (!/^[+-]\d{4}$/.test(value) || value === "-0000") {
    return null;
  }
  const hours = Number(value.slice(1, 3));
  const minutes = Number(value.slice(3, 5));
  const limit = value[0] === "-" ? 12 : 14;
  if (hours > limit || minutes > 59 || (hours === limit && minutes !== 0)) {
    return null;
  }
  return `UTC${value[0]}${value.slice(1, 3)}:${value.slice(3, 5)}`;
}

function formatDicomDateTime(value, defaultOffset) {
  const match = /^(\d{8})(\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,6})?)?)?)?([+-]\d{4})?$/.exec(value);
  if (!match) {
    return null;
  }
  const date = formatDicomDate(match[1]);
  const time = match[2] ? formatDicomTime(match[2]) : null;
  const offset = match[3] ? formatDicomOffset(match[3]) : defaultOffset;
  if (!date || (match[2] && !time) || (match[3] && !offset)) {
    return null;
  }
  return [date, time, offset].filter(Boolean).join(" ");
}

function readIdentificationText(state, key) {
  const header = state.fields.get(key);
  if (!header || header.valueLength === 0) {
    return null;
  }
  const bytes = new Uint8Array(state.view.buffer, header.valueOffset, header.valueLength);
  return Array.from(bytes, (value) => String.fromCharCode(value)).join("").replace(/ +$/g, "") || null;
}

function readPatientName(state, characterSet) {
  const header = state.fields.get("patientName");
  if (!header || header.valueLength === 0) {
    return null;
  }
  const bytes = new Uint8Array(state.view.buffer, header.valueOffset, header.valueLength);
  let decoded;
  try {
    if (characterSet === "ISO_IR 192") {
      decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } else if (characterSet === "ISO_IR 100") {
      decoded = Array.from(bytes, (value) => String.fromCharCode(value)).join("");
    } else if (characterSet === "" || characterSet === "ISO_IR 6") {
      if (bytes.some((value) => value > 0x7f)) {
        throw new Error("invalid ASCII");
      }
      decoded = Array.from(bytes, (value) => String.fromCharCode(value)).join("");
    } else {
      state.warnings.add("Conjunto de caracteres nao suportado; nome do paciente nao exibido.");
      return null;
    }
  } catch {
    state.warnings.add("Nome do paciente: codificacao invalida; valor nao exibido.");
    return null;
  }
  const raw = decoded.replace(/ +$/g, "");
  const representations = raw.split("=");
  if (
    /[\p{Cc}\p{Cf}\\]/u.test(raw)
    || representations.length > 3
    || representations.some((value) => [...value].length > 64 || value.split("^").length > 5)
  ) {
    state.warnings.add("Nome do paciente: formato invalido; valor nao exibido.");
    return null;
  }
  const display = representations
    .map((value) => value.split("^").map((part) => part.trim()).filter(Boolean).join(" "))
    .filter(Boolean)
    .join(" / ");
  return display ? { raw, display } : null;
}

// Identification is deliberately decoded only on an explicit UI request and is
// never attached to the technical study, cached, or written to persistent storage.
export function getVividIqIdentification(study) {
  const buffer = study?.sourceBuffer;
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < DICOM_DATASET_OFFSET) {
    fail("INVALID_INPUT", "O visualizador recebeu um arquivo invalido.");
  }
  if (buffer.byteLength > MAX_FILE_BYTES) {
    fail("RESOURCE_LIMIT", "O arquivo excede o limite local de 512 MB.");
  }
  const view = new DataView(buffer);
  if (readAscii(view, DICOM_MAGIC_OFFSET, 4) !== "DICM") {
    fail("INVALID_DICOM", "Assinatura DICM nao encontrada.");
  }
  const state = { view, fields: new Map(), warnings: new Set(), elementCount: 0, transferSyntax: "" };
  const datasetOffset = parseMetaHeader(state);
  validateTransferSyntax(state.transferSyntax);
  readIdentificationHeaders(state, datasetOffset, buffer.byteLength);

  const characterSet = state.fields.has("characterSet") && state.fields.get("characterSet") === null
    ? "unsupported"
    : (readIdentificationText(state, "characterSet") || "").trim();
  const patientName = readPatientName(state, characterSet);
  const formatted = (key, formatter) => {
    const raw = readIdentificationText(state, key);
    if (raw === null) {
      return null;
    }
    const result = formatter(raw);
    if (result === null) {
      const descriptor = [...IDENTIFICATION_FIELDS.values()].find((field) => field.key === key);
      state.warnings.add(`${descriptor.label}: valor invalido ou incompleto; nao exibido.`);
    }
    return result;
  };
  const timezoneOffset = formatted("timezoneOffset", formatDicomOffset);
  let acquisitionDateTime = formatted("acquisitionDateTime", (value) => formatDicomDateTime(value, timezoneOffset));
  if (!state.fields.has("acquisitionDateTime")) {
    const date = formatted("acquisitionDate", formatDicomDate);
    const time = formatted("acquisitionTime", formatDicomTime);
    if (date && time) {
      acquisitionDateTime = [date, time, timezoneOffset].filter(Boolean).join(" ");
    } else if (date || time) {
      state.warnings.add("Data/hora da aquisicao: par de data e hora incompleto; nao exibido.");
    }
  }
  return {
    patientName: patientName?.display || null,
    patientNameRaw: patientName?.raw || null,
    studyDate: formatted("studyDate", formatDicomDate),
    studyTime: formatted("studyTime", formatDicomTime),
    acquisitionDateTime,
    contentDate: formatted("contentDate", formatDicomDate),
    contentTime: formatted("contentTime", formatDicomTime),
    timezoneOffset,
    warnings: [...state.warnings],
  };
}

export function getVividIqPreviewJpeg(study) {
  if (
    !Number.isInteger(study.previewJpegOffset)
    || study.previewJpegOffset < 0
    || !Number.isInteger(study.previewJpegLength)
    || study.previewJpegLength <= 0
  ) {
    return null;
  }
  return new Uint8Array(
    study.sourceBuffer,
    study.previewJpegOffset,
    study.previewJpegLength,
  );
}

export function createVividIqDisplayMap(
  sourceWidth,
  sourceHeight,
  outputWidth,
  outputHeight,
  scanConversion = true,
  lateralFlip = true,
) {
  for (const dimension of [sourceWidth, sourceHeight, outputWidth, outputHeight]) {
    if (!Number.isInteger(dimension) || dimension <= 0 || dimension > 8192) {
      fail("INVALID_GEOMETRY", "Dimensao invalida para orientar o quadro do cine.");
    }
  }

  const mapping = new Int32Array(outputWidth * outputHeight);
  mapping.fill(-1);
  if (!scanConversion) {
    for (let y = 0; y < outputHeight; y += 1) {
      const sourceX = Math.min(
        sourceWidth - 1,
        Math.round((y / Math.max(1, outputHeight - 1)) * (sourceWidth - 1)),
      );
      for (let x = 0; x < outputWidth; x += 1) {
        const normalized = x / Math.max(1, outputWidth - 1);
        const sourceY = Math.min(
          sourceHeight - 1,
          Math.round((lateralFlip ? 1 - normalized : normalized) * (sourceHeight - 1)),
        );
        mapping[y * outputWidth + x] = sourceY * sourceWidth + sourceX;
      }
    }
    return mapping;
  }

  const aspectRatio = outputWidth / outputHeight;
  const halfAngle = Math.asin(Math.min(0.98, aspectRatio / 2));
  const centerX = (outputWidth - 1) / 2;
  const outerRadius = Math.max(1, outputHeight - 1);
  for (let y = 0; y < outputHeight; y += 1) {
    for (let x = 0; x < outputWidth; x += 1) {
      const deltaX = x - centerX;
      const radius = Math.hypot(deltaX, y);
      const angle = Math.atan2(deltaX, y);
      if (radius > outerRadius || Math.abs(angle) > halfAngle) {
        continue;
      }
      const sourceX = Math.min(
        sourceWidth - 1,
        Math.round((radius / outerRadius) * (sourceWidth - 1)),
      );
      const beamPosition = 0.5 + angle / (2 * halfAngle);
      const sourceY = Math.min(
        sourceHeight - 1,
        Math.max(
          0,
          Math.round(
            (lateralFlip ? 1 - beamPosition : beamPosition) * (sourceHeight - 1),
          ),
        ),
      );
      mapping[y * outputWidth + x] = sourceY * sourceWidth + sourceX;
    }
  }
  return mapping;
}

export function detectVividIqPreviewAspectRatio(
  pixels,
  width,
  height,
  channels = 4,
) {
  if (
    !pixels
    || !Number.isInteger(width)
    || !Number.isInteger(height)
    || !Number.isInteger(channels)
    || width <= 0
    || height <= 0
    || channels < 3
    || pixels.length < width * height * channels
  ) {
    return null;
  }

  const blockSize = Math.max(4, Math.round(Math.min(width, height) / 118));
  const gridWidth = Math.floor(width / blockSize);
  const gridHeight = Math.floor(height / blockSize);
  if (gridWidth < 3 || gridHeight < 3) {
    return null;
  }
  const active = new Uint8Array(gridWidth * gridHeight);
  const minimumActivePixels = Math.ceil(blockSize * blockSize * 0.12);
  for (let gridY = 0; gridY < gridHeight; gridY += 1) {
    for (let gridX = 0; gridX < gridWidth; gridX += 1) {
      let activePixels = 0;
      for (let y = 0; y < blockSize; y += 1) {
        for (let x = 0; x < blockSize; x += 1) {
          const pixelOffset = (
            (gridY * blockSize + y) * width
            + gridX * blockSize
            + x
          ) * channels;
          const red = pixels[pixelOffset];
          const green = pixels[pixelOffset + 1];
          const blue = pixels[pixelOffset + 2];
          const maximum = Math.max(red, green, blue);
          const minimum = Math.min(red, green, blue);
          if (maximum > 12 && maximum - minimum < 15) {
            activePixels += 1;
          }
        }
      }
      if (activePixels >= minimumActivePixels) {
        active[gridY * gridWidth + gridX] = 1;
      }
    }
  }

  const visited = new Uint8Array(active.length);
  let largest = null;
  for (let start = 0; start < active.length; start += 1) {
    if (!active[start] || visited[start]) {
      continue;
    }
    const queue = [start];
    let head = 0;
    let count = 0;
    let minX = gridWidth;
    let minY = gridHeight;
    let maxX = 0;
    let maxY = 0;
    visited[start] = 1;
    while (head < queue.length) {
      const index = queue[head];
      head += 1;
      const x = index % gridWidth;
      const y = Math.floor(index / gridWidth);
      count += 1;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
      for (let adjacentY = Math.max(0, y - 1); adjacentY <= Math.min(gridHeight - 1, y + 1); adjacentY += 1) {
        for (let adjacentX = Math.max(0, x - 1); adjacentX <= Math.min(gridWidth - 1, x + 1); adjacentX += 1) {
          const adjacent = adjacentY * gridWidth + adjacentX;
          if (active[adjacent] && !visited[adjacent]) {
            visited[adjacent] = 1;
            queue.push(adjacent);
          }
        }
      }
    }
    if (!largest || count > largest.count) {
      largest = { count, minX, minY, maxX, maxY };
    }
  }

  if (!largest || largest.count < gridWidth * gridHeight * 0.03) {
    return null;
  }
  const componentWidth = (largest.maxX - largest.minX + 1) * blockSize;
  const componentHeight = (largest.maxY - largest.minY + 1) * blockSize;
  const aspectRatio = componentWidth / componentHeight;
  if (
    componentWidth < width * 0.15
    || componentHeight < height * 0.15
    || aspectRatio < 0.45
    || aspectRatio > 1.95
  ) {
    return null;
  }
  return aspectRatio;
}

export function findVividIqFrameAtTimestamp(study, timestampSeconds) {
  if (!study.frames.length) {
    return 0;
  }
  if (timestampSeconds <= study.frames[0].timestampSeconds) {
    return 0;
  }
  const lastIndex = study.frames.length - 1;
  if (timestampSeconds >= study.frames[lastIndex].timestampSeconds) {
    return lastIndex;
  }

  let low = 0;
  let high = lastIndex;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (study.frames[middle].timestampSeconds <= timestampSeconds) {
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return Math.max(0, low - 1);
}

export const VIVID_IQ_MAX_FILE_BYTES = MAX_FILE_BYTES;
export const VIVID_IQ_MAX_FRAMES = MAX_FRAMES;
