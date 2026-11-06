import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ExistingProductSuggestions from "./ExistingProductSuggestions";
import { productTemplatesApi } from "@/lib/api/productTemplates";

vi.mock("@/lib/api/productTemplates", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/productTemplates")>()),
  productTemplatesApi: { search: vi.fn() },
}));

const product = (id: string, name: string) =>
  ({ id, name }) as Awaited<ReturnType<typeof productTemplatesApi.search>>[0];

function renderIt(name: string, onPick = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ExistingProductSuggestions name={name} onPick={onPick} />
    </QueryClientProvider>,
  );
  return onPick;
}

describe("ExistingProductSuggestions", () => {
  beforeEach(() => vi.clearAllMocks());

  it("offers the product a typed fragment belongs to, and picking writes its exact name", async () => {
    vi.mocked(productTemplatesApi.search).mockResolvedValue([
      product("1", "Soy wax"),
    ]);
    const onPick = renderIt("wax");

    fireEvent.click(await screen.findByRole("button", { name: "Soy wax" }));

    expect(productTemplatesApi.search).toHaveBeenCalledWith("wax", 5);
    expect(onPick).toHaveBeenCalledWith("Soy wax");
  });

  it("offers nothing for the exact name, which the save already matches", async () => {
    vi.mocked(productTemplatesApi.search).mockResolvedValue([
      product("1", "Soy wax"),
    ]);
    renderIt("soy wax");

    await waitFor(() => expect(productTemplatesApi.search).toHaveBeenCalled());
    expect(screen.queryByTestId("items-existing-products")).toBeNull();
  });

  it("does not ask for a single letter", () => {
    renderIt("w");

    expect(productTemplatesApi.search).not.toHaveBeenCalled();
  });
});
