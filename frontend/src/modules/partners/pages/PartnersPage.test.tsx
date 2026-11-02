import React from "react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import PartnersPage from "./PartnersPage";
import type { Partner } from "@/types";
import { toast } from "sonner";
import { signInWith, signOut } from "@/test/auth";

const partnerActions = vi.hoisted(() => ({
  deactivateOptions: null as { onSuccess?: () => void } | null,
  activateOptions: null as { onSuccess?: () => void } | null,
}));

// The page hides every action from an account that may not write, which is
// a different screen than these tests describe.
beforeEach(() => {
  signInWith(["partners:read", "partners:write"]);
});

afterEach(() => signOut());

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const makePartner = (id: string, name: string): Partner => ({
  purchase_order_count: 0,
  document_count: 0,
  id,
  organization_id: "org-1",
  name,
  code: `P-${id}`,
  type: "SUPPLIER",
  tax_id: null,
  is_consumer: false,
  email: null,
  phone: null,
  website: null,
  contact_person: null,
  address: null,
  notes: null,
  is_active: true,
  created_by: null,
  created_at: "2026-07-01T10:00:00Z",
  updated_at: "2026-07-01T10:00:00Z",
});

const PAGE_LIMIT = 25;
const manyPartners = Array.from({ length: 30 }, (_, i) =>
  makePartner(`p-${i + 1}`, `Partner ${i + 1}`),
);

let mockListParams: Record<string, unknown> | undefined;
let mockPartners: Partner[] = manyPartners;
let mockTotal = 30;
let mockDetailPartner: Partner | undefined;
let mockSearch = "";

// The test environment keeps window.location fixed, so the query a link
// carries is handed to the page here.
vi.mock("react-router-dom", async () => ({
  ...(await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  )),
  useSearchParams: () => [new URLSearchParams(mockSearch)],
}));

vi.mock("@/modules/partners/hooks/usePartners", () => ({
  usePartners: (params?: Record<string, unknown>) => {
    mockListParams = params;
    const offset = Number(params?.offset ?? 0);
    return {
      data: {
        items: mockPartners.slice(
          offset,
          offset + Number(params?.limit ?? PAGE_LIMIT),
        ),
        total: mockTotal,
      },
      isLoading: false,
    };
  },
  usePartner: () => ({ data: mockDetailPartner }),
  useDeactivatePartner: () => ({
    mutate: (_id: string, opts?: { onSuccess?: () => void }) => {
      partnerActions.deactivateOptions = opts ?? null;
      opts?.onSuccess?.();
    },
  }),
  useActivatePartner: () => ({
    mutate: (_id: string, opts?: { onSuccess?: () => void }) => {
      partnerActions.activateOptions = opts ?? null;
      opts?.onSuccess?.();
    },
  }),
}));

// exercises PartnersPage's own state, not the form: editing from the
// detail sheet must keep the sheet open underneath after save. The form is
// stubbed to a save button that just closes it, so the test focuses on the
// viewingPartner/editingPartner state transition.
vi.mock("@/modules/partners/components/PartnerFormModal", () => ({
  default: ({ onClose }: { onClose: () => void }) =>
    React.createElement("button", { type: "button", onClick: onClose }, "Save"),
}));

describe("PartnersPage pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListParams = undefined;
    mockPartners = manyPartners;
    mockTotal = 30;
  });

  it("requests limit 25 and offset 0 on first page", async () => {
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Partner 1")).toBeInTheDocument();
    });
    expect(mockListParams).toMatchObject({ limit: PAGE_LIMIT, offset: 0 });
    // Only the first page is rendered.
    expect(screen.queryByText("Partner 26")).not.toBeInTheDocument();
  });

  it("renders the pager when total exceeds the limit", async () => {
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("1 / 2")).toBeInTheDocument();
    });
  });

  it("does not render the pager when total fits one page", async () => {
    mockTotal = 1;
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Partner 1")).toBeInTheDocument();
    });
    expect(screen.queryByText(/\d+ \/ \d+/)).not.toBeInTheDocument();
  });

  it("advances to page 2 and requests offset 25", async () => {
    const user = userEvent.setup();
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("1 / 2")).toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => {
      expect(mockListParams).toMatchObject({ offset: PAGE_LIMIT });
    });
    expect(screen.getByText("Partner 26")).toBeInTheDocument();
  });
});

describe("PartnersPage empty state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListParams = undefined;
    mockPartners = [];
    mockTotal = 0;
  });

  it("renders the create action in the empty state", async () => {
    render(<PartnersPage />);
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /new partner/i }),
      ).toBeInTheDocument();
    });
  });
});

describe("PartnersPage document stats", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListParams = undefined;
    mockTotal = 1;
  });

  it("labels a mixed-currency partner instead of summing currencies", async () => {
    mockPartners = [
      {
        ...makePartner("p-mixed", "Mixed Currency Co"),
        document_count: 2,
        total_amount: null,
        last_activity_at: "2026-07-02T10:00:00Z",
      },
    ];
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Mixed Currency Co")).toBeInTheDocument();
    });
    expect(screen.getByText("Multiple currencies")).toBeInTheDocument();
    expect(screen.queryByText(/120\.50/)).not.toBeInTheDocument();
  });

  it("renders a single-currency amount with its currency code", async () => {
    mockPartners = [
      {
        ...makePartner("p-single", "Single Currency Co"),
        document_count: 1,
        total_amount: "120.50",
        turnover_currency: "EUR",
        last_activity_at: "2026-07-01T10:00:00Z",
      },
    ];
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Single Currency Co")).toBeInTheDocument();
    });
    // the API names the total's currency, so the amount prints
    // with its currency symbol instead of a bare number.
    expect(screen.getByText(/120\.50/)).toBeInTheDocument();
    expect(screen.getByText(/€/)).toBeInTheDocument();
  });

  it("renders a single-currency amount without a currency when none is named", async () => {
    mockPartners = [
      {
        ...makePartner("p-single", "Unlabeled Currency Co"),
        document_count: 1,
        total_amount: "120.50",
        last_activity_at: "2026-07-01T10:00:00Z",
      },
    ];
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Unlabeled Currency Co")).toBeInTheDocument();
    });
    // formatMoney with no currency appends " ?" rather than the
    // organization's currency symbol.
    expect(screen.getByText(/120\.50/)).toBeInTheDocument();
  });
});

describe("PartnersPage edit-from-sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListParams = undefined;
    mockPartners = [makePartner("p1", "Original Co")];
    mockTotal = 1;
    // Simulate the background refetch returning updated contact details.
    mockDetailPartner = {
      ...makePartner("p1", "Original Co"),
      name: "Refreshed Co",
    };
  });

  it("keeps the sheet open and refreshed after editing from it", async () => {
    const user = userEvent.setup();
    render(<PartnersPage />);

    // Open the detail sheet from the list row.
    await user.click(screen.getByText("Original Co"));
    const dialog = await screen.findByRole("dialog");
    // The sheet shows the refetched name, not the stale list item.
    expect(within(dialog).getByText("Refreshed Co")).toBeInTheDocument();

    // Edit from the sheet: the sheet closes and the (stubbed) form opens.
    await user.click(within(dialog).getByRole("button", { name: /edit/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();

    // Save: the form closes and the sheet re-opens with the refreshed data.
    await user.click(screen.getByRole("button", { name: /save/i }));
    const reopened = await screen.findByRole("dialog");
    expect(within(reopened).getByText("Refreshed Co")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /save/i }),
    ).not.toBeInTheDocument();
  });
});

describe("PartnersPage — a finished action is confirmed in the past tense", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPartners = manyPartners;
    mockTotal = 30;
  });

  it("says the partner was deactivated, not the button's own label", async () => {
    // "Deactivate" over a partner already deactivated reads as the next
    // thing to do, not as what just happened.
    const user = userEvent.setup();
    render(<PartnersPage />);
    await waitFor(() => {
      expect(screen.getByText("Partner 1")).toBeInTheDocument();
    });

    await user.click(screen.getAllByRole("button", { name: "Deactivate" })[0]);
    const dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Deactivate" }),
    );

    await waitFor(() => {
      expect(vi.mocked(toast.success)).toHaveBeenCalledWith(
        "Partner deactivated",
      );
    });
  });
});

describe("PartnersPage opened from a link", () => {
  afterEach(() => {
    mockSearch = "";
    mockDetailPartner = undefined;
  });

  it("opens the form of the partner the link names", async () => {
    mockPartners = manyPartners;
    mockDetailPartner = makePartner("p-1", "Partner 1");
    mockSearch = "?edit=p-1";
    render(<PartnersPage />);
    await screen.findByText("Partner 1");
    expect(
      await screen.findByRole("button", { name: "Save" }),
    ).toBeInTheDocument();
  });

  it("opens no form when the link names nobody", async () => {
    mockPartners = manyPartners;
    mockDetailPartner = makePartner("p-1", "Partner 1");
    render(<PartnersPage />);
    await screen.findByText("Partner 1");
    expect(
      screen.queryByRole("button", { name: "Save" }),
    ).not.toBeInTheDocument();
  });
});
