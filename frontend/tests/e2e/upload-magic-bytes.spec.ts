import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * Magic-bytes upload validation.
 *
 * The backend rejects uploads whose declared Content-Type does not match
 * the file's actual signature. This test exercises that defence at the
 * API layer (the endpoint that wires up ``validate_signature``).
 */
test.describe("Upload — magic-bytes validation", () => {
  test("rejects a text file uploaded with image/png content type", async ({
    playwright,
    baseURL,
  }) => {
    const apiCtx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(apiCtx);
    const { access_token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);

    const itemId = process.env.E2E_ITEM_EXPIRING_ID;
    if (!itemId) throw new Error("E2E_ITEM_EXPIRING_ID not set by globalSetup");

    // Plain text bytes claiming to be a PNG. The signature check looks for
    // the PNG magic bytes \x89PNG\r\n\x1a\n at the start of the file.
    const evilBytes = Buffer.from(
      "this is not a PNG, just plain ASCII text pretending to be one\n",
      "utf-8",
    );

    const res = await apiCtx.post(`/api/v1/items/${itemId}/attachments`, {
      multipart: {
        file: {
          name: "evil.png",
          mimeType: "image/png",
          buffer: evilBytes,
        },
      },
      headers: { Authorization: `Bearer ${access_token}` },
    });

    expect(res.status()).toBe(400);
    const body = await res.json();
    // The backend should return a structured error explaining the mismatch.
    expect(JSON.stringify(body)).toMatch(/signature|invalid|magic|file_must/i);
  });

  test("rejects a JPEG file uploaded with image/png content type", async ({
    playwright,
    baseURL,
  }) => {
    const apiCtx = await playwright.request.newContext({ baseURL });
    const api = new ApiHelper(apiCtx);
    const { access_token } = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);

    const itemId = process.env.E2E_ITEM_EXPIRING_ID;
    if (!itemId) throw new Error("E2E_ITEM_EXPIRING_ID not set by globalSetup");

    // Real JPEG signature \xff\xd8\xff\xe0 followed by padding.
    const jpegBytes = Buffer.concat([
      Buffer.from([0xff, 0xd8, 0xff, 0xe0]),
      Buffer.alloc(200, 0),
    ]);

    const res = await apiCtx.post(`/api/v1/items/${itemId}/attachments`, {
      multipart: {
        file: {
          name: "actually.jpg",
          mimeType: "image/png",
          buffer: jpegBytes,
        },
      },
      headers: { Authorization: `Bearer ${access_token}` },
    });

    expect(res.status()).toBe(400);
  });
});
