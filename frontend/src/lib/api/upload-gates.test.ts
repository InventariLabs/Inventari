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
 * The gate shows no toast of its own: its sentence travels as the error, so
 * the caller's single toast — `extractApiError(error, fallback)`, the way
 * each of them reads a failure — is the one that says the limit. A gate that
 * toasted too would put a second toast on the caller's. The callers' own
 * tests count that toast: the quick add's photo, the logo in the organization
 * settings and the cover on the recipe page.
 */
describe("an oversized image is refused with the limit as its error, and no toast of the gate's own", () => {
  const uploads = {
    "the product photo": () => itemsApi.uploadImage("id-1", fileOfMB(11)),
    "the logo": () => organizationsApi.uploadLogo(fileOfMB(11)),
    "the recipe cover": () => recipesCoreApi.uploadImage("r-1", fileOfMB(11)),
  };

  for (const [name, upload] of Object.entries(uploads)) {
    it(name, async () => {
      const shown = vi.spyOn(toast, "error").mockImplementation(() => "");
      try {
        const refusal = await upload().catch((error: unknown) => error);

        expect(extractApiError(refusal, "Failed to upload file")).toBe(
          "File too large. Maximum size: 10 MB",
        );
        expect(shown).not.toHaveBeenCalled();
        expect(api.post).not.toHaveBeenCalled();
      } finally {
        shown.mockRestore();
      }
    });
  }
});
