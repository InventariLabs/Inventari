import React from "react";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { useStorageEditForm } from "./useStorageEditForm";
import type { StorageLocation } from "@/types";
import { makeStorageSummary } from "@/test/factories/storage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const storage = {
  id: "s1",
  user_id: "u1",
  location_type_id: null,
  parent_id: null,
  name: "Cold Storage",
  description: null,
  location_details: null,
  settings: null,
  created_at: "2026-01-01T00:00:00Z",
  context_schema: [],
  behavior_mode: "STOCK",
  field_definitions: [],
  context_tag: null,
} as unknown as StorageLocation;

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

const renderForm = () =>
  renderHook(
    () =>
      useStorageEditForm(
        true,
        storage,
        makeStorageSummary({ id: storage.id, name: storage.name }),
        vi.fn(),
        vi.fn(),
      ),
    { wrapper },
  );

const failWith = (status: number, code: string, message: string) =>
  server.use(
    http.put("/api/v1/locations/:id", () =>
      HttpResponse.json({ detail: { code, message } }, { status }),
    ),
  );

/**
 * The same collision used to arrive as 400 from one endpoint and 409 from
 * another, and the screen relayed whichever English sentence came with it.
 * A status code and a machine-readable code are what let it say something
 * in the reader's own language instead.
 */
describe("a name already in use is a conflict, not a sentence to relay", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("says the name is taken, in the reader's language", async () => {
    failWith(
      409,
      "STORAGE_CONFLICT",
      'A storage location named "Cold Storage" already exists at this level.',
    );
    const { result } = renderForm();

    act(() => result.current.handleSave());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith(
      'A location named "Cold Storage" already exists here.',
    );
  });

  it("tells a code collision apart from a name collision", async () => {
    failWith(
      409,
      "STORAGE_SHORT_CODE_CONFLICT",
      "Short code 'LOC-9' is already in use by another location.",
    );
    const { result } = renderForm();

    act(() => result.current.handleSave());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith(
      "That location code is already used by another location.",
    );
  });

  it("leaves an ordinary failure to the generic path", async () => {
    failWith(400, "VALIDATION_ERROR", "Something else is wrong.");
    const { result } = renderForm();

    act(() => result.current.handleSave());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledWith("Something else is wrong.");
  });
});
