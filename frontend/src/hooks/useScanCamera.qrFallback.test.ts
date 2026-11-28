import { describe, expect, it, vi } from "vitest";
import { decodeQrFallback } from "./useScanCamera";

// The camera hook imports the library the app's camera screens use; this
// test exercises only the second decoder on a frame it is handed.
vi.mock("html5-qrcode", () => ({
  Html5Qrcode: class {},
  Html5QrcodeSupportedFormats: {},
}));

/**
 * One printed label's QR, as python-qrcode drew it: error correction M, a
 * two-module quiet zone on each side, the payload below. It is one of the
 * labels the bundled zxing port's locator rejects — a clean 37 x 37 matrix
 * at six pixels a module fails with NotFoundException, as it does at eight —
 * while jsQR reads the same pixels. The rows are the matrix itself, quiet
 * zone included, so the test needs no encoder of its own.
 */
const PAYLOAD = "https://inventari.example.com/s/LBL-L67T8G";
const MATRIX = [
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
  "0000111111101111101101000011111110000",
  "0000100000100010001010001010000010000",
  "0000101110101111111101110010111010000",
  "0000101110100101110101110010111010000",
  "0000101110100010110010100010111010000",
  "0000100000101000111000101010000010000",
  "0000111111101010101010101011111110000",
  "0000000000000110100010000000000000000",
  "0000101000110110101010011001001010000",
  "0000101101011011001010011011000110000",
  "0000101000101010100111011000111010000",
  "0000101010011110001100100011010000000",
  "0000001010100000110110100011000010000",
  "0000011000011101101011011111000110000",
  "0000100000101101010110010011000010000",
  "0000101001010110000010001001000000000",
  "0000100010100101001010011010000010000",
  "0000010011011100111010011011001110000",
  "0000110011101111111100111111010010000",
  "0000001011010010000110111101100000000",
  "0000111101100011010010001111110100000",
  "0000000000001010000101001000111010000",
  "0000111111101100000100001010100010000",
  "0000100000100001001100101000100010000",
  "0000101110100100011100011111110100000",
  "0000101110100100110111010100111010000",
  "0000101110101110101101010000100110000",
  "0000100000100001110110101001010000000",
  "0000111111101011100010101101010010000",
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
  "0000000000000000000000000000000000000",
];

/** The matrix at `unit` pixels a module, on white, as the camera delivers it. */
function frame(unit: number): ImageData {
  const size = MATRIX.length * unit;
  const data = new Uint8ClampedArray(size * size * 4).fill(255);
  MATRIX.forEach((row, r) => {
    for (let c = 0; c < row.length; c++) {
      if (row[c] !== "1") continue;
      for (let y = r * unit; y < (r + 1) * unit; y++) {
        for (let x = c * unit; x < (c + 1) * unit; x++) {
          const i = (y * size + x) * 4;
          data[i] = data[i + 1] = data[i + 2] = 0;
        }
      }
    }
  });
  return { width: size, height: size, data } as unknown as ImageData;
}

describe("decodeQrFallback", () => {
  it("reads a label's QR the bundled decoder's locator rejects", () => {
    expect(decodeQrFallback(frame(6))).toBe(PAYLOAD);
  });

  it("says nothing about a frame with no code in it", () => {
    const data = new Uint8ClampedArray(40 * 40 * 4).fill(255);
    expect(
      decodeQrFallback({ width: 40, height: 40, data } as unknown as ImageData),
    ).toBeNull();
  });
});
