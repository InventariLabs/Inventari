import { afterEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { copyText, copyTextOrExplain } from "./clipboard";

/**
 * The clipboard answers three ways and only one of them is a copy. The other
 * two used to be an unhandled rejection behind a button that never changed
 * state — which is how an API key shown once, or an invitation link in an
 * organization that sends no mail, went nowhere with nothing said.
 */

const stubClipboard = (clipboard: unknown) => {
  vi.stubGlobal("navigator", { clipboard });
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("copyText", () => {
  it("answers that there is no clipboard instead of throwing", async () => {
    stubClipboard(undefined);

    await expect(copyText("value")).resolves.toBe("no-clipboard");
  });

  it("reports a refusal rather than letting the rejection escape", async () => {
    stubClipboard({
      writeText: vi.fn().mockRejectedValue(new Error("NotAllowedError")),
    });

    await expect(copyText("value")).resolves.toBe("error");
  });

  it("says copied when the text landed", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard({ writeText });

    await expect(copyText("value")).resolves.toBe("copied");
    expect(writeText).toHaveBeenCalledWith("value");
  });
});

describe("copyTextOrExplain", () => {
  it("says what to do instead when the clipboard is not there", async () => {
    stubClipboard(undefined);
    const error = vi.spyOn(toast, "error").mockImplementation(() => "");

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(false);

    expect(error).toHaveBeenCalledWith("select it and copy it by hand");
  });

  it("says what to do instead when the clipboard refuses", async () => {
    stubClipboard({
      writeText: vi.fn().mockRejectedValue(new Error("NotAllowedError")),
    });
    const error = vi.spyOn(toast, "error").mockImplementation(() => "");

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(false);

    expect(error).toHaveBeenCalledWith("select it and copy it by hand");
  });

  it("leaves the success notice to the caller", async () => {
    stubClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
    const error = vi.spyOn(toast, "error").mockImplementation(() => "");

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(true);

    expect(error).not.toHaveBeenCalled();
  });
});
