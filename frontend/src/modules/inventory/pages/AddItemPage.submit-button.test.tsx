import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AddItemPage from "./AddItemPage";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";

import { signInWith } from "@/test/auth";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["items:write"]);
});

const mutateMock = vi.fn();
const submitMock = vi.fn(() => {
  mutateMock();
});

// The unit question is a state the page has to render, not just receive: the
// test turns it on, and the page must show the dialog — without it the save
// button is dead with nobody to answer.
const quickAddStub = vi.hoisted(() => ({}) as Record<string, unknown>);

vi.mock("@/modules/inventory/hooks/useQuickAdd", () => ({
  useQuickAdd: () => ({
    activeTab: "manual",
    setActiveTab: vi.fn(),
    formData: {
      name: "Test Item",
      location_id: "loc-1",
      category_id: "",
      brand: "",
      quantity: "1",
    },
    errors: {},
    fieldDefinitions: [],
    handleInputChange: vi.fn(),
    submit: submitMock,
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
    assignMutation: { mutate: mutateMock, isPending: false },
    handleFileSelect: vi.fn(),
    ...quickAddStub,
  }),
}));

const renderPage = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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
};

describe("AddItemPage — submit button", () => {
  beforeEach(() => {
    mutateMock.mockClear();
    delete quickAddStub.pendingUnitChoice;
    delete quickAddStub.resolveUnitChoice;
  });

  it("triggers mutation when Add Product button is clicked (not only Enter)", async () => {
    const user = userEvent.setup();
    renderPage();

    const submitBtn = await screen.findByRole("button", {
      name: /Add Product/i,
    });
    expect(submitBtn).not.toBeDisabled();

    await user.click(submitBtn);

    await waitFor(() => expect(mutateMock).toHaveBeenCalledTimes(1));
  });

  it("keeps the footer in view: sticky above the phone nav, on a page that sets no height of its own", async () => {
    renderPage();

    const submitBtn = await screen.findByRole("button", {
      name: /Add Product/i,
    });
    const footer = submitBtn.parentElement?.parentElement;
    expect(footer?.className).toContain("sticky");
    // On a phone the bottom navigation is fixed over the page: the footer
    // pins above it, and from md up, where there is none, to the window edge.
    expect(footer?.className).toContain("md:bottom-0");
    expect(footer?.className).toContain("--mobile-nav-height");

    // A height written as "viewport minus some rem" guessed the chrome above
    // the form and pushed the footer 170px below the fold at 1440x1000.
    const page = footer?.parentElement;
    expect(page?.className).not.toMatch(/\bh-\[calc\(100dvh/);
    expect(page?.className).not.toContain("overflow-hidden");
  });

  it("asks about a unit the matched template does not keep", async () => {
    const resolveUnitChoice = vi.fn();
    quickAddStub.pendingUnitChoice = {
      template: {
        uomId: "kg-1",
        uomSymbol: "kg",
        uomName: "Kilogram",
        productName: "Mąka pszenna",
      },
      chosenUomId: "pcs-1",
      chosenSymbol: "pcs",
      chosenName: "Piece",
    };
    quickAddStub.resolveUnitChoice = resolveUnitChoice;

    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText(/in another unit/i)).toBeInTheDocument();

    await user.click(
      await screen.findByRole("button", { name: /enter in pcs/i }),
    );

    // Exactly one answer, and it is the confirmation: toHaveBeenCalledWith
    // also passes when the click resolves [[true], [false]] — the answer
    // followed by the refusal, which is the defect this test stands over.
    expect(resolveUnitChoice.mock.calls).toEqual([[true]]);
    expect(mutateMock).not.toHaveBeenCalled();
  });
});
