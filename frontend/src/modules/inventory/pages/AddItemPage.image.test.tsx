import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import AddItemPage from "./AddItemPage";

import { signInWith } from "@/test/auth";

// The page asks whether this account may write before it renders the
// form at all; rendering it signed out tests the denial instead.
beforeEach(() => {
  signInWith(["items:write"]);
});

/**
 * The page rendered the photo picker but never wired its callback, so
 * choosing a file produced a preview and nothing else — the same action
 * worked or not depending on whether the user came in through the modal.
 */
const manualTabProps: Record<string, unknown> = {};

vi.mock("../components/quick-add/ManualTab", () => ({
  ManualTab: (props: Record<string, unknown>) => {
    Object.assign(manualTabProps, props);
    return <div data-testid="manual-tab" />;
  },
}));

const createQueryClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false } } });

describe("AddItemPage — product photo", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createQueryClient();
    manualTabProps.onImageSelect = undefined;
  });

  it("gives the form somewhere to send a chosen photo", async () => {
    render(
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

    // The form is what the page opens on, and where `vision` is off — as it
    // is here — there is no tab to click at all.
    await screen.findByTestId("manual-tab");

    expect(typeof manualTabProps.onImageSelect).toBe("function");

    // …and it is wired to the page's state, not to an empty stub: choosing a
    // file has to reach the preview the form renders.
    const onImageSelect = manualTabProps.onImageSelect as (file: File) => void;
    await act(async () => {
      onImageSelect(new File(["photo"], "jam.jpg", { type: "image/jpeg" }));
    });

    await waitFor(() =>
      expect(manualTabProps.imagePreview).toEqual(expect.any(String)),
    );
  });
});
