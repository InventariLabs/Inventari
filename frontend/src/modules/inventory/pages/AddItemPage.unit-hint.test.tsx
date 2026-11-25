import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AddItemPage from "./AddItemPage";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith } from "@/test/auth";

beforeEach(() => {
  signInWith(["items:write"]);
});

const quickAddStub = vi.hoisted(() => ({}) as Record<string, unknown>);

vi.mock("@/modules/inventory/hooks/useQuickAdd", () => ({
  useQuickAdd: () => ({
    activeTab: "manual",
    setActiveTab: vi.fn(),
    formData: { name: "QA look Flour", location_id: "loc-1" },
    errors: {},
    fieldDefinitions: [],
    handleInputChange: vi.fn(),
    submit: vi.fn(),
    isAnalyzing: false,
    imagePreview: null,
    setImagePreview: vi.fn(),
    handleVisionAI: vi.fn(),
    storages: [
      {
        id: "loc-1",
        name: "Fridge",
        is_leaf: true,
        location_type: { icon: "Package" },
      },
    ],
    categories: [],
    assignMutation: { mutate: vi.fn(), isPending: false },
    handleFileSelect: vi.fn(),
    ...quickAddStub,
  }),
}));

// The form itself is covered elsewhere; this pins what the page hands it.
vi.mock("../components/quick-add/ManualTab", () => ({
  ManualTab: ({
    templateUnit,
  }: {
    templateUnit?: { productName: string; uomSymbol: string } | null;
  }) => (
    <p data-testid="unit-from-catalogue">
      {templateUnit
        ? `${templateUnit.productName} in ${templateUnit.uomSymbol}`
        : "no catalogue unit"}
    </p>
  ),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ModulesProvider>
            <AddItemPage />
          </ModulesProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </PageHeaderContext.Provider>,
  );
}

describe("AddItemPage — where the unit comes from", () => {
  it("hands the form the catalogue's unit, so the page can say where it comes from", async () => {
    quickAddStub.templateUnit = {
      uomSymbol: "pcs",
      uomName: "Piece",
      productName: "QA look Flour",
    };
    renderPage();

    expect(await screen.findByTestId("unit-from-catalogue")).toHaveTextContent(
      "QA look Flour in pcs",
    );
  });
});
