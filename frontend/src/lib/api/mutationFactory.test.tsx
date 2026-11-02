import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { AxiosError } from "axios";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import "@/test/mocks/i18n";
import { useAppMutation } from "./mutationFactory";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

/** A rejection shaped like the ones the API client produces. */
function apiError(detail?: string, status = 400): AxiosError {
  return new AxiosError(
    `Request failed with status code ${status}`,
    "ERR_BAD_REQUEST",
    undefined,
    undefined,
    {
      status,
      statusText: status === 409 ? "Conflict" : "Bad Request",
      headers: {},
      config: { headers: {} } as never,
      data: detail === undefined ? {} : { detail },
    },
  );
}

const noInvalidation = () => {};

describe("useAppMutation failure reporting", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
  });

  it("says why the request failed, in the API's own words", async () => {
    const { result } = renderHook(
      () =>
        useAppMutation(
          () => Promise.reject(apiError("No active assignments found")),
          noInvalidation,
        ),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("No active assignments found"),
    );
  });

  it("falls back to a general sentence when the API sends no reason", async () => {
    const { result } = renderHook(
      () => useAppMutation(() => Promise.reject(apiError()), noInvalidation),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The action could not be completed.",
      ),
    );
  });

  it("prefers the caller's own fallback over the general sentence", async () => {
    const { result } = renderHook(
      () =>
        useAppMutation(() => Promise.reject(apiError()), noInvalidation, {
          errorFallback: "The campaign could not be launched.",
        }),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "The campaign could not be launched.",
      ),
    );
  });

  it("stands aside when the call site handles the error itself", async () => {
    const handled = vi.fn();
    const { result } = renderHook(
      () =>
        useAppMutation(() => Promise.reject(apiError("nope")), noInvalidation),
      { wrapper },
    );

    result.current.mutate(undefined, { onError: handled });

    await waitFor(() => expect(handled).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("stands aside when the hook itself was given an onError", async () => {
    const handled = vi.fn();
    const { result } = renderHook(
      () =>
        useAppMutation(() => Promise.reject(apiError("nope")), noInvalidation, {
          onError: handled,
        }),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() => expect(handled).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("says nothing when silence was asked for explicitly", async () => {
    const { result } = renderHook(
      () =>
        useAppMutation(() => Promise.reject(apiError("nope")), noInvalidation, {
          silentError: true,
        }),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("leaves mutateAsync to the caller that awaited it", async () => {
    const { result } = renderHook(
      () =>
        useAppMutation(() => Promise.reject(apiError("nope")), noInvalidation),
      { wrapper },
    );

    await expect(result.current.mutateAsync(undefined)).rejects.toThrow();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("still invalidates on success and stays quiet", async () => {
    const invalidate = vi.fn();
    const { result } = renderHook(
      () => useAppMutation(() => Promise.resolve("done"), invalidate),
      { wrapper },
    );

    result.current.mutate(undefined);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("keeps mutate referentially stable across renders", async () => {
    const { result, rerender } = renderHook(
      () => useAppMutation(() => Promise.resolve("done"), noInvalidation),
      { wrapper },
    );

    const first = result.current.mutate;
    result.current.mutate(undefined);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    rerender();

    expect(result.current.mutate).toBe(first);
  });
});

describe("useAppMutation conflicts (409)", () => {
  beforeEach(() => {
    vi.mocked(toast.error).mockClear();
  });

  function conflictHarness() {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const Wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { Wrapper };
  }

  it("refetches the entity a conflict refused, as a success would", async () => {
    const { Wrapper } = conflictHarness();
    const queryFn = vi.fn().mockResolvedValue({ id: "a1" });
    renderHook(() => useQuery({ queryKey: ["asset", "a1"], queryFn }), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));

    const successContinuation = vi.fn();
    const { result } = renderHook(
      () =>
        useAppMutation<unknown, { id: string }>(
          () => Promise.reject(apiError("Assignment already checked in", 409)),
          successContinuation,
        ),
      { wrapper: Wrapper },
    );

    result.current.mutate({ id: "a1" });

    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
    // The success continuation is not replayed: it may upload a file,
    // open a download or patch a cache with a body a refusal never sent.
    expect(successContinuation).not.toHaveBeenCalled();
  });

  it("refreshes even when the call site handles the refusal itself", async () => {
    const { Wrapper } = conflictHarness();
    const queryFn = vi.fn().mockResolvedValue({ id: "a2" });
    renderHook(() => useQuery({ queryKey: ["asset", "a2"], queryFn }), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));

    const handled = vi.fn();
    const { result } = renderHook(
      () =>
        useAppMutation<unknown, { id: string }>(
          () => Promise.reject(apiError("nope", 409)),
          (qc, _data, vars) => {
            qc.invalidateQueries({ queryKey: ["asset", vars.id] });
          },
        ),
      { wrapper: Wrapper },
    );

    result.current.mutate({ id: "a2" }, { onError: handled });

    await waitFor(() => expect(handled).toHaveBeenCalled());
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(2));
  });

  it("leaves other refusals alone — only a stale view is refetched", async () => {
    const { Wrapper } = conflictHarness();
    const queryFn = vi.fn().mockResolvedValue({ id: "a3" });
    renderHook(() => useQuery({ queryKey: ["asset", "a3"], queryFn }), {
      wrapper: Wrapper,
    });
    await waitFor(() => expect(queryFn).toHaveBeenCalledTimes(1));

    const { result } = renderHook(
      () =>
        useAppMutation<unknown, { id: string }>(
          () => Promise.reject(apiError("bad input")),
          (qc, _data, vars) => {
            qc.invalidateQueries({ queryKey: ["asset", vars.id] });
          },
        ),
      { wrapper: Wrapper },
    );

    result.current.mutate({ id: "a3" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(queryFn).toHaveBeenCalledTimes(1);
  });
});
