import assert from "assert";
import { spawnSync } from "child_process";
import ffmpegPath from "ffmpeg-static";
import { transcodeOggOpusToMp3 } from "../src/services/whatsappService";

function buildSyntheticOggOpus(): Buffer {
  if (!ffmpegPath) {
    throw new Error("ffmpeg-static binary not available in this environment");
  }
  const result = spawnSync(ffmpegPath, [
    "-f", "lavfi",
    "-i", "anullsrc=r=16000:cl=mono",
    "-t", "1",
    "-c:a", "libopus",
    "-f", "ogg",
    "pipe:1"
  ]);
  if (result.status !== 0 || !result.stdout || result.stdout.length === 0) {
    throw new Error(`Failed to build synthetic ogg/opus fixture: ${result.stderr?.toString().slice(-500)}`);
  }
  return result.stdout;
}

async function run(): Promise<void> {
  const oggBuffer = buildSyntheticOggOpus();
  assert.ok(oggBuffer.length > 0, "synthetic ogg fixture should not be empty");

  const mp3Buffer = await transcodeOggOpusToMp3(oggBuffer);
  assert.ok(mp3Buffer.length > 0, "transcoded mp3 buffer should not be empty");

  // Assinatura de MP3: "ID3" (tag) ou frame sync 0xFFFB/0xFFFA no header.
  const header = mp3Buffer.subarray(0, 3).toString("ascii");
  const looksLikeId3 = header === "ID3";
  const looksLikeMpegFrame = mp3Buffer[0] === 0xff && (mp3Buffer[1] & 0xe0) === 0xe0;
  assert.ok(looksLikeId3 || looksLikeMpegFrame, "output does not look like a valid mp3 file");

  await assert.rejects(
    transcodeOggOpusToMp3(Buffer.from("isto nao e audio valido")),
    /ffmpeg exited with code/,
    "entrada invalida deveria rejeitar com erro do ffmpeg, nao travar"
  );

  console.log("Audio transcode contract tests passed.");
}

void run().catch((error) => {
  console.error("Audio transcode test failed:", error);
  process.exit(1);
});
