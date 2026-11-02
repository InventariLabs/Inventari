import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { useEquipmentForm } from "../hooks/useEquipmentForm";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function renderForm() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return renderHook(() => useEquipmentForm(undefined, {}), { wrapper });
}

describe("useEquipmentForm — the category list did not arrive", () => {
  it("keeps the category required instead of concluding there is none to pick", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderForm();

    await waitFor(() => expect(result.current.categoryRequired).toBe(true));
  });

  it("leaves it optional when the list arrived empty", async () => {
    server.use(
      http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    );
    const { result } = renderForm();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current.categoryRequired).toBe(false);
  });
});
