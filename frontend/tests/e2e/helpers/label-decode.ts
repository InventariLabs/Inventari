import { fileURLToPath } from "node:url";
import { type Page } from "@playwright/test";

/** The decoder the app's own camera screens use, run on a downloaded label. */
const DECODER = fileURLToPath(
  new URL(
    "../../../node_modules/html5-qrcode/html5-qrcode.min.js",
    import.meta.url,
  ),
);

/**
 * What a reader finds in a label image: the Code 128 bars (what a USB 1D
 * scanner reads) or the QR (what a phone camera reads). Decoded in the page
 * with the library the camera screens ship, from the very bytes the download
 * gave, so the file is checked and not only the request that asked for it.
 */
export async function decodeLabel(
  page: Page,
  png: Buffer,
  kind: "bars" | "qr",
  /** The part of the width to read, left to right: a scanner is aimed at one symbol. */
  aim: [number, number] = [0, 1],
): Promise<string | null> {
  if (!(await page.evaluate(() => "Html5Qrcode" in window))) {
    await page.addScriptTag({ path: DECODER });
  }
  return page.evaluate(
    async ({ base64, kind, aim }) => {
      const lib = window as unknown as {
        Html5Qrcode: new (
          id: string,
          config: object,
        ) => {
          scanFile(file: File, show: boolean): Promise<string>;
          clear(): void;
        };
        Html5QrcodeSupportedFormats: Record<string, number>;
      };
      const host = document.createElement("div");
      host.id = "label-decoder";
      document.body.appendChild(host);
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      // The sheet is drawn at 12 px to the millimetre; with a QR beside them
      // the bars are about two pixels a module, which the decoder wants
      // larger. Enlarging by whole pixels (no smoothing) adds nothing the
      // file does not hold.
      const bitmap = await createImageBitmap(new Blob([bytes]));
      const canvas = document.createElement("canvas");
      const left = Math.round(bitmap.width * aim[0]);
      const width = Math.round(bitmap.width * aim[1]) - left;
      canvas.width = width * 2;
      canvas.height = bitmap.height * 2;
      const context = canvas.getContext("2d")!;
      context.imageSmoothingEnabled = false;
      context.drawImage(
        bitmap,
        left,
        0,
        width,
        bitmap.height,
        0,
        0,
        canvas.width,
        canvas.height,
      );
      const enlarged = await new Promise<Blob>((resolve) =>
        canvas.toBlob((blob) => resolve(blob!), "image/png"),
      );
      const file = new File([enlarged], "label.png", { type: "image/png" });
      const reader = new lib.Html5Qrcode("label-decoder", {
        formatsToSupport: [
          kind === "bars"
            ? lib.Html5QrcodeSupportedFormats.CODE_128
            : lib.Html5QrcodeSupportedFormats.QR_CODE,
        ],
        useBarCodeDetectorIfSupported: false,
        verbose: false,
      });
      try {
        return await reader.scanFile(file, false);
      } catch {
        return null;
      } finally {
        reader.clear();
        host.remove();
      }
    },
    { base64: png.toString("base64"), kind, aim },
  );
}

export async function download(page: Page, button: () => Promise<void>) {
  const pending = page.waitForEvent("download");
  await button();
  const file = await pending;
  const chunks: Buffer[] = [];
  for await (const chunk of await file.createReadStream()) {
    chunks.push(chunk as Buffer);
  }
  return { name: file.suggestedFilename(), bytes: Buffer.concat(chunks) };
}
