import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock browser-image-compression before importing the module
vi.mock("browser-image-compression", () => ({
  default: vi.fn(),
}));

import imageCompression from "browser-image-compression";
import { readableErrorMessage } from "@/lib/errors";
import { compressImage, prepareImageUpload } from "./imageUtils";

const mockCompress = vi.mocked(imageCompression);

const createFakeFile = (name = "test.jpg", size = 1024) => {
  return new File(["a".repeat(size)], name, { type: "image/jpeg" });
};

describe("compressImage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns compressed file on success", async () => {
    const original = createFakeFile();
    const compressed = createFakeFile("compressed.jpg", 512);
    mockCompress.mockResolvedValueOnce(compressed);

    const result = await compressImage(original);

    expect(mockCompress).toHaveBeenCalledWith(
      original,
      expect.objectContaining({
        maxSizeMB: 0.8,
        maxWidthOrHeight: 1024,
        useWebWorker: true,
        initialQuality: 0.8,
        fileType: "image/jpeg",
      }),
    );
    expect(result).toBe(compressed);
  });

  it("accepts custom maxWidth and quality", async () => {
    const original = createFakeFile();
    const compressed = createFakeFile("compressed.jpg", 256);
    mockCompress.mockResolvedValueOnce(compressed);

    await compressImage(original, 800, 0.6);

    expect(mockCompress).toHaveBeenCalledWith(
      original,
      expect.objectContaining({ maxWidthOrHeight: 800, initialQuality: 0.6 }),
    );
  });

  it("returns original file when compression fails", async () => {
    const original = createFakeFile();
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockCompress.mockRejectedValueOnce(new Error("Compression error"));

    const result = await compressImage(original);

    consoleSpy.mockRestore();
    expect(result).toBe(original);
  });
});

describe("prepareImageUpload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("refuses a HEIC picture with the shared sentence", async () => {
    const heic = new File(["x"], "IMG.heic", { type: "image/heic" });
    const error = await prepareImageUpload(heic).catch((e: unknown) => e);
    // A sentence the caller's error path shows as it is — not a toast here
    // plus each screen's own generic fallback.
    expect(readableErrorMessage(error)).toBeTruthy();
    expect(mockCompress).not.toHaveBeenCalled();
  });

  it("keeps the picture's own file name on the shrunk file", async () => {
    const original = createFakeFile("IMG_0001.jpg", 4096);
    mockCompress.mockResolvedValueOnce(
      new Blob(["a"], { type: "image/jpeg" }) as File,
    );
    const result = await prepareImageUpload(original);
    expect(result).toBeInstanceOf(File);
    expect(result.name).toBe("IMG_0001.jpg");
    expect(result.size).toBeLessThan(original.size);
  });

  it("leaves a document on an attachment endpoint alone", async () => {
    const pdf = new File(["x"], "a.pdf", { type: "application/pdf" });
    expect(await prepareImageUpload(pdf, { imageOnly: false })).toBe(pdf);
  });
});
