/**
 * The client gate refuses at the server's number, not above it.
 *
 * The browser-side limit and the route's limit are two constants in two
 * languages, hand-synced on purpose — it was decided that there is no
 * API for them (the same call was made for vision). What keeps the pair
 * honest is the backend pin on its side and this test on ours: a file the
 * route would refuse must never reach the network, because the user only
 * learns the limit after the bytes have been paid for.
 *
 * Seven megabytes was the measured case that opened this gap: a photo a
 * phone takes happily, above the old server cap of five, below the old
 * client default of ten — it sailed through the gate and came back as a
 * 413. The agreement settled both sides at ten, so seven now uploads
 * legitimately; what the gate owes the route is the file above ten.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  api: { post: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

import { toast } from "sonner";
import { api } from "./client";
import { itemsApi } from "./items";
import { organizationsApi } from "./organizations";
import { extractApiError } from "@/lib/errors";
import { prepareImageUpload } from "@/lib/imageUtils";
import { recipesCoreApi } from "@/modules/recipes/api/recipes_core";
import { IMAGE_UPLOAD_MAX_BYTES } from "@/utils/fileValidation";

vi.mock("@/lib/imageUtils", () => ({
  prepareImageUpload: vi.fn(async (f: File) => f),
}));

const fileOfMB = (mb: number) =>
  new File([new Uint8Array(mb * 1024 * 1024)], "photo.jpg", {
    type: "image/jpeg",
  });

describe("an upload the route would refuse", () => {
  beforeEach(() => {
    vi.mocked(api.post).mockClear();
  });

  it("never leaves the browser: an oversized product photo", async () => {
    await expect(itemsApi.uploadImage("id-1", fileOfMB(11))).rejects.toThrow(
      "File too large",
    );
    expect(api.post).not.toHaveBeenCalled();
  });

  it("never leaves the browser: an oversized logo", async () => {
    await expect(organizationsApi.uploadLogo(fileOfMB(11))).rejects.toThrow(
      "File too large",
    );
    expect(api.post).not.toHaveBeenCalled();
  });

  it("draws the line exactly where the backend pin does", () => {
    expect(IMAGE_UPLOAD_MAX_BYTES).toBe(10 * 1024 * 1024);
  });

  it("lets a file inside the agreement through to the route", async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { image_url: "/x" } });
    await expect(itemsApi.uploadImage("id-1", fileOfMB(9))).resolves.toEqual({
      image_url: "/x",
    });
    expect(api.post).toHaveBeenCalled();
  });
});

describe("a phone photo above the cap", () => {
  it("is shrunk first, so it goes through instead of being refused", async () => {
    const small = new File([new Uint8Array(300 * 1024)], "photo.jpg", {
      type: "image/jpeg",
    });
    vi.mocked(prepareImageUpload).mockResolvedValueOnce(small);
    vi.mocked(api.post).mockResolvedValue({ data: { image_url: "/x" } });

    await itemsApi.uploadImage("id-1", fileOfMB(12));

    const form = vi.mocked(api.post).mock.calls.at(-1)?.[1] as FormData;
    expect((form.get("image") as File).size).toBe(300 * 1024);
  });
});

/**
 * The gate used to toast its sentence and then throw a bare "File too large",
 * which every caller's catch turned into its own generic toast on top: two
 * toasts, and the one with the limit hidden under the one without. The
 * refusal now travels as the error itself, so the caller's single toast —
 * `extractApiError(error, fallback)`, the way each of them reads a failure —
 * is the one that says the limit.
 */
describe("an oversized image is refused in one toast, the one with the limit", () => {
  const uploads = {
    "the product photo": () => itemsApi.uploadImage("id-1", fileOfMB(11)),
    "the logo": () => organizationsApi.uploadLogo(fileOfMB(11)),
    "the recipe cover": () => recipesCoreApi.uploadImage("r-1", fileOfMB(11)),
  };

  for (const [name, upload] of Object.entries(uploads)) {
    it(name, async () => {
      vi.mocked(toast.error).mockClear();
      try {
        await upload();
      } catch (error) {
        toast.error(extractApiError(error, "Failed to upload file"));
      }
      expect(toast.error).toHaveBeenCalledTimes(1);
      expect(toast.error).toHaveBeenCalledWith(
        "File too large. Maximum size: 10 MB",
      );
      expect(api.post).not.toHaveBeenCalled();
    });
  }
});
