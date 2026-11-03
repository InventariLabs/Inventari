import React, { useState } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { act, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import PutawayRulesPage from "./PutawayRulesPage";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

// This screen hides its actions from an account that cannot use them,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  signInWith(["warehouse:read", "warehouse:write"]);
});

afterEach(() => {
  signOut();
});

const createMutateMock = vi.hoisted(() => vi.fn());
const updateMutateMock = vi.hoisted(() => vi.fn());
const deleteMutateMock = vi.hoisted(() => vi.fn());
const dialogSubmitRef = vi.hoisted<{
  current: ((data: unknown) => void) | null;
}>(() => ({ current: null }));

const putawayRulesFixture = vi.hoisted(() => ({ data: [] as unknown[] }));

vi.mock("@/modules/warehouse/hooks/usePutawayRules", () => ({
  usePutawayRules: () => ({
    data: putawayRulesFixture.data,
    isLoading: false,
  }),
  useCreatePutawayRule: () => ({
    mutate: createMutateMock,
    isPending: false,
  }),
  useUpdatePutawayRule: () => ({
    mutate: updateMutateMock,
    isPending: false,
  }),
  useDeletePutawayRule: () => ({
    mutate: deleteMutateMock,
    isPending: false,
  }),
}));

vi.mock("@/modules/warehouse/components/SilencedHomeShelves", () => ({
  SilencedHomeShelves: () => null,
}));

vi.mock("@/hooks/useConfirm", () => ({
  useConfirm: () => ({ confirm: vi.fn(), confirmDialogProps: {} }),
}));

interface DialogStubProps {
  open: boolean;
  rule?: unknown;
  onClose: () => void;
  onSubmit: (data: unknown) => void;
  isPending: boolean;
  serverError?: string | null;
}

vi.mock("@/modules/warehouse/components/PutawayRuleEditorDialog", () => ({
  PutawayRuleEditorDialog: (props: DialogStubProps) => {
    dialogSubmitRef.current = props.onSubmit;
    return props.open ? (
      <div data-testid="putaway-dialog">
        {props.serverError ?? "no-server-error"}
      </div>
    ) : null;
  },
}));

function HeaderHarness({ children }: { children: React.ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});

  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.actions ? <div>{headerData.actions}</div> : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

async function renderWithHeader(ui: React.ReactElement) {
  let result: ReturnType<typeof render> | undefined;
  await act(async () => {
    result = render(<HeaderHarness>{ui}</HeaderHarness>);
  });
  return result!;
}

const validPayload = {
  product_template_id: null,
  category_id: null,
  context_tag: "cold_xyz",
  location_type_code: null,
  target_location_id: "loc-1",
  priority: 100,
  is_active: true,
};

const structuredError = {
  isAxiosError: true,
  response: {
    data: {
      detail: {
        code: "VALIDATION_ERROR",
        message:
          "Unknown context tag 'nope' — it must match a context_tag defined on an existing category",
      },
    },
  },
};

describe("PutawayRulesPage server error surfacing", () => {
  beforeEach(() => {
    createMutateMock.mockReset();
    updateMutateMock.mockReset();
    deleteMutateMock.mockReset();
    dialogSubmitRef.current = null;
  });

  it("keeps the dialog open and shows the 400 message when the backend rejects the rule", async () => {
    createMutateMock.mockImplementation(
      (_data: unknown, opts: { onError?: (e: unknown) => void }) => {
        opts.onError?.(structuredError);
      },
    );

    await renderWithHeader(<PutawayRulesPage />);

    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    expect(screen.getByTestId("putaway-dialog")).toBeInTheDocument();

    await act(async () => {
      dialogSubmitRef.current?.(validPayload);
    });

    await waitFor(() =>
      expect(
        screen.getByText(/Unknown context tag 'nope'/),
      ).toBeInTheDocument(),
    );
  });

  it("closes the dialog and clears the error on a successful save", async () => {
    createMutateMock.mockImplementation(
      (_data: unknown, opts: { onSuccess?: () => void }) => {
        opts.onSuccess?.();
      },
    );

    await renderWithHeader(<PutawayRulesPage />);

    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));

    await act(async () => {
      dialogSubmitRef.current?.(validPayload);
    });

    await waitFor(() =>
      expect(screen.queryByTestId("putaway-dialog")).not.toBeInTheDocument(),
    );
  });

  it("reads the locations through the module-data policy, not the raw list", async () => {
    // Every location this organization has belongs to a module. With the
    // policy off the scoped query comes back empty, and the honest answer is
    // "your locations are hidden by the policy" — not a rules table over a
    // dead form.
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const scoped =
          new URL(request.url).searchParams.get("exclude_module_contexts") ===
          "true";
        return HttpResponse.json(
          onePage(
            scoped
              ? []
              : [
                  {
                    id: "loc-rack",
                    name: "Server Rack",
                    context_tag: "equipment",
                  },
                ],
          ),
        );
      }),
    );

    await renderWithHeader(<PutawayRulesPage />);

    // StorageRequired's settled state: scoped came back empty while the raw
    // list has locations the policy keeps out of view.
    expect(
      await screen.findByText("Some locations are hidden"),
    ).toBeInTheDocument();
  });
});

describe("PutawayRulesPage — inactive target mark", () => {
  it("marks a rule whose target can no longer take goods", async () => {
    putawayRulesFixture.data = [
      {
        id: "r1",
        organization_id: "o1",
        product_template_id: null,
        category_id: "c1",
        context_tag: null,
        location_type_code: null,
        target_location_id: "loc-1",
        priority: 10,
        is_active: true,
        created_at: "2026-09-15T10:00:00Z",
        category_name: "Paints",
        target_location_name: "Old Shelf",
        target_location_active: false,
      },
      {
        id: "r2",
        organization_id: "o1",
        product_template_id: null,
        category_id: "c2",
        context_tag: null,
        location_type_code: null,
        target_location_id: "loc-2",
        priority: 10,
        is_active: true,
        created_at: "2026-09-15T10:00:00Z",
        category_name: "Glues",
        target_location_name: "Live Shelf",
        target_location_active: true,
      },
    ];
    await renderWithHeader(<PutawayRulesPage />);

    // The parked rule says so next to its target; the live one stays clean.
    const marks = await screen.findAllByText("Target inactive");
    expect(marks).toHaveLength(1);
  });

  it("says a rule reaches further than the shelf it names", async () => {
    // The row prints the head of the rule's list. Without a word about the
    // rest, a rule with one shelf and a rule with three read identically,
    // and the whole point of the list is invisible from the page that
    // manages it.
    putawayRulesFixture.data = [
      {
        id: "r1",
        organization_id: "o1",
        product_template_id: null,
        category_id: "c1",
        context_tag: null,
        location_type_code: null,
        target_location_id: "loc-1",
        priority: 10,
        is_active: true,
        created_at: "2026-09-15T10:00:00Z",
        category_name: "Paints",
        target_location_name: "First Shelf",
        target_location_active: true,
        locations: [
          { location_id: "loc-1", position: 0, location_name: "First Shelf" },
          { location_id: "loc-2", position: 1, location_name: "Second Shelf" },
          { location_id: "loc-3", position: 2, location_name: "Third Shelf" },
        ],
      },
    ];
    await renderWithHeader(<PutawayRulesPage />);

    expect(
      await screen.findByText(/\+2 more shelves if it is full/),
    ).toBeInTheDocument();
  });
});
