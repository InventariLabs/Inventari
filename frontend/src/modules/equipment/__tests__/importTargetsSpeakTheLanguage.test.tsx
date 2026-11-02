import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import { ModulesProvider } from "@/contexts/ModulesContext";
import ImportEquipmentModal from "../components/ImportEquipmentModal";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter>{children}</MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
};

/**
 * This is the screen that teaches the import to read Polish column headers,
 * and it named its own targets in English while doing it. It also answered
 * "what can I import?" only after a file had already been uploaded.
 */
describe("the import modal before a file is chosen", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("lists the columns it understands", () => {
    render(<ImportEquipmentModal onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    expect(
      screen.getByText("Columns this import understands"),
    ).toBeInTheDocument();
    expect(screen.getByText("Serial number")).toBeInTheDocument();
    expect(screen.getByText("Warranty until")).toBeInTheDocument();
  });

  it("offers a sample file", () => {
    render(<ImportEquipmentModal onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });

    expect(
      screen.getByRole("button", { name: /Download a sample file/ }),
    ).toBeInTheDocument();
  });

  it("names those columns in the reader's language", async () => {
    await withLanguage("pl", () => {
      render(<ImportEquipmentModal onClose={vi.fn()} />, {
        wrapper: createWrapper(),
      });

      expect(screen.getByText("Numer seryjny")).toBeInTheDocument();
      expect(screen.getByText("Gwarancja do")).toBeInTheDocument();
      expect(screen.queryByText("Serial number")).not.toBeInTheDocument();
    });
  });
});
