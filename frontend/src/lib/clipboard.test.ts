import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText, copyTextOrExplain, manualCopyStore } from "./clipboard";

/**
 * The clipboard answers three ways and only one of them is a copy. The other
 * two must not be an unhandled rejection behind a button that never changes
 * state — which is how an API key shown once, or an invitation link in an
 * organization that sends no mail, would go nowhere with nothing said.
 */

const stubClipboard = (clipboard: unknown) => {
  vi.stubGlobal("navigator", { clipboard });
};

afterEach(() => {
  manualCopyStore.dismiss();
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
  it("hands the text over to be shown when the clipboard is not there", async () => {
    stubClipboard(undefined);

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(false);

    expect(manualCopyStore.get()).toEqual({
      text: "value",
      message: "select it and copy it by hand",
    });
  });

  it("hands the text over to be shown when the clipboard refuses", async () => {
    stubClipboard({
      writeText: vi.fn().mockRejectedValue(new Error("NotAllowedError")),
    });

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(false);

    expect(manualCopyStore.get()?.text).toBe("value");
  });

  it("leaves the success notice to the caller", async () => {
    stubClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });

    await expect(
      copyTextOrExplain("value", "select it and copy it by hand"),
    ).resolves.toBe(true);

    expect(manualCopyStore.get()).toBeNull();
  });
});
