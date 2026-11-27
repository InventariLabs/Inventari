import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { validateFileSize } from "./fileValidation";

describe("validateFileSize", () => {
  const fileOfSize = (bytes: number) => {
    const file = new File(["x"], "sheet.csv");
    Object.defineProperty(file, "size", { value: bytes });
    return file;
  };

  it("passes a file within the limit without a toast", () => {
    const shown = vi.spyOn(toast, "error").mockImplementation(() => "");

    expect(validateFileSize(fileOfSize(10 * 1024 * 1024))).toBe(true);
    expect(shown).not.toHaveBeenCalled();
  });

  it("refuses a file above the limit with one toast that names it", () => {
    const shown = vi.spyOn(toast, "error").mockImplementation(() => "");

    expect(validateFileSize(fileOfSize(10 * 1024 * 1024 + 1))).toBe(false);
    expect(shown).toHaveBeenCalledTimes(1);
    expect(shown).toHaveBeenCalledWith("File too large. Maximum size: 10 MB");
  });

  it("names the limit it was given, not the default", () => {
    const shown = vi.spyOn(toast, "error").mockImplementation(() => "");

    expect(validateFileSize(fileOfSize(3 * 1024 * 1024), 2 * 1024 * 1024)).toBe(
      false,
    );
    expect(shown).toHaveBeenCalledWith("File too large. Maximum size: 2 MB");
  });
});
