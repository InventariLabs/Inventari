import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApprovalStageStepper } from "@/modules/approvals/components/ApprovalStageStepper";
import type { StageDefinition } from "@/modules/approvals/api/approvals";
import { withLanguage } from "./mocks/i18n";

/**
 * Polish has three plural categories where English has two, so a string that
 * reads correctly for one count can be wrong for the next. Nothing in the unit
 * suite rendered a non-English interface before, which is how shipped:
 * "Przypisano {{count}} akceptant(ów)" for every count.
 */

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
  >
    {children}
  </QueryClientProvider>
);

function stagesWithApprovers(count: number): StageDefinition[] {
  return [
    {
      order: 1,
      label: "Akceptacja kierownika",
      approver_user_ids: Array.from({ length: count }, (_, i) => `u-${i}`),
    },
    {
      order: 2,
      label: "Akceptacja dyrektora",
      approver_user_ids: [],
    },
  ];
}

function renderStepper(approverCount: number) {
  return render(
    <ApprovalStageStepper
      stages={stagesWithApprovers(approverCount)}
      currentStage={1}
      totalStages={2}
      status="PENDING"
      decisions={[]}
    />,
    { wrapper: Wrapper },
  );
}

describe("Polish plural forms", () => {
  it.each([
    [1, "Przypisano 1 akceptanta"],
    [2, "Przypisano 2 akceptantów"],
    [5, "Przypisano 5 akceptantów"],
  ])("renders %i assigned approvers as %s", async (count, expected) => {
    await withLanguage("pl", () => {
      renderStepper(count);
      expect(screen.getByText(expected)).toBeInTheDocument();
    });
  });

  it("uses the English forms by default", () => {
    renderStepper(2);
    expect(screen.getByText("2 approvers assigned")).toBeInTheDocument();
  });

  it("puts the interface back to English after a Polish block", async () => {
    await withLanguage("pl", () => {
      const polish = renderStepper(1);
      expect(screen.getByText("Przypisano 1 akceptanta")).toBeInTheDocument();
      // Unmounted here: react-i18next re-renders live components on
      // changeLanguage, so a tree left mounted would flip to English and
      // make the assertion below ambiguous.
      polish.unmount();
    });

    renderStepper(1);
    expect(screen.getByText("1 approver assigned")).toBeInTheDocument();
  });
});
