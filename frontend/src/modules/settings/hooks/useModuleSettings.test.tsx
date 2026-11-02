import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import {
  useModuleSettings,
  useUpdateModuleSettings,
} from "./useModuleSettings";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/**
 * A module's settings are read and written under that module's own path, and
 * a page that saves several things at once can mute the per-save toast.
 */
describe("module settings hooks", () => {
  beforeEach(() => vi.clearAllMocks());

  it("stays idle until a module is named", () => {
    const { result } = renderHook(() => useModuleSettings(undefined), {
      wrapper: QueryWrapper,
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("reads the settings of the named module", async () => {
    server.use(
      http.get("/api/v1/modules/maker/settings", () =>
        HttpResponse.json({ currency: "EUR" }),
      ),
    );
    const { result } = renderHook(() => useModuleSettings("maker"), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ currency: "EUR" });
  });

  it("saves the whole settings object and announces it", async () => {
    let body: unknown;
    server.use(
      http.put("/api/v1/modules/maker/settings", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ status: "ok" });
      }),
    );
    const { result } = renderHook(() => useUpdateModuleSettings("maker"), {
      wrapper: QueryWrapper,
    });
    await act(() => result.current.mutateAsync({ currency: "PLN" }));
    expect(body).toEqual({ currency: "PLN" });
    expect(toast.success).toHaveBeenCalledWith("Saved maker settings");
  });

  it("stays silent when the page confirms the save itself", async () => {
    server.use(
      http.put("/api/v1/modules/maker/settings", () =>
        HttpResponse.json({ status: "ok" }),
      ),
    );
    const { result } = renderHook(
      () => useUpdateModuleSettings("maker", { quiet: true }),
      { wrapper: QueryWrapper },
    );
    await act(() => result.current.mutateAsync({ currency: "PLN" }));
    expect(toast.success).not.toHaveBeenCalled();
  });
});
