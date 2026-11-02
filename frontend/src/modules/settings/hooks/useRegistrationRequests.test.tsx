import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { QueryWrapper } from "@/test/queryWrapper";
import {
  useApproveRegistrationRequest,
  useRegistrationRequests,
  useRejectRegistrationRequest,
} from "./useRegistrationRequests";

/**
 * An approval or a rejection goes to its own endpoint for the request it was
 * given. Swapping the two would approve what the administrator refused.
 */
describe("registration request hooks", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the pending requests", async () => {
    server.use(
      http.get("/api/v1/auth/registration-requests", () =>
        HttpResponse.json(onePage([{ id: "q1", email: "a@b.c" }])),
      ),
    );
    const { result } = renderHook(() => useRegistrationRequests(), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([{ id: "q1", email: "a@b.c" }]);
  });

  it("approves through the approve endpoint only", async () => {
    const approve = vi.fn();
    const reject = vi.fn();
    server.use(
      http.post("/api/v1/auth/registration-requests/q1/approve", () => {
        approve();
        return HttpResponse.json({ message: "ok", email_sent: true });
      }),
      http.post("/api/v1/auth/registration-requests/q1/reject", () => {
        reject();
        return HttpResponse.json({ message: "no" });
      }),
    );
    const { result } = renderHook(() => useApproveRegistrationRequest(), {
      wrapper: QueryWrapper,
    });
    await act(() => result.current.mutateAsync("q1"));
    expect(approve).toHaveBeenCalledTimes(1);
    expect(reject).not.toHaveBeenCalled();
  });

  it("rejects through the reject endpoint only", async () => {
    const approve = vi.fn();
    const reject = vi.fn();
    server.use(
      http.post("/api/v1/auth/registration-requests/q1/approve", () => {
        approve();
        return HttpResponse.json({ message: "ok" });
      }),
      http.post("/api/v1/auth/registration-requests/q1/reject", () => {
        reject();
        return HttpResponse.json({ message: "no" });
      }),
    );
    const { result } = renderHook(() => useRejectRegistrationRequest(), {
      wrapper: QueryWrapper,
    });
    await act(() => result.current.mutateAsync("q1"));
    expect(reject).toHaveBeenCalledTimes(1);
    expect(approve).not.toHaveBeenCalled();
  });
});
