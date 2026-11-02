import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { runWithToast } from "@/lib/api/runWithToast";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("runWithToast", () => {
  it("resolves the fn result and shows success toast", async () => {
    const result = await runWithToast(() => Promise.resolve(42), {
      success: "Done",
      errorFallback: "Failed",
    });
    expect(result).toBe(42);
    expect(toast.success).toHaveBeenCalledWith("Done");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("omits success toast when no success message given", async () => {
    const result = await runWithToast(() => Promise.resolve("ok"), {
      errorFallback: "Failed",
    });
    expect(result).toBe("ok");
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("returns undefined and shows error toast on failure", async () => {
    const err = new Error("boom");
    const result = await runWithToast(() => Promise.reject(err), {
      errorFallback: "Failed",
    });
    expect(result).toBeUndefined();
    // Non-axios errors fall back to the fallback message (extractApiError contract).
    expect(toast.error).toHaveBeenCalledWith("Failed");
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("falls back to errorFallback when error has no useful message", async () => {
    const result = await runWithToast(() => Promise.reject(new Error("")), {
      errorFallback: "Failed",
    });
    expect(result).toBeUndefined();
    expect(toast.error).toHaveBeenCalledWith("Failed");
  });
});
