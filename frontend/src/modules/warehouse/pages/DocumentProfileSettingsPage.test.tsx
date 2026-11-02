import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { toast } from "sonner";
import { useFormGuardStore } from "@/store/formGuardStore";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import DocumentProfileSettingsPage from "./DocumentProfileSettingsPage";
import { onePage } from "@/test/mocks/page";

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse"],
    hiddenModules: [],
    focusModule: null,
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

const authState = {
  user: { role: "admin", is_superuser: true, permissions: [] as string[] },
  isAuthenticated: true,
  isLoading: false,
};

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof authState) => unknown) =>
    selector ? selector(authState) : authState,
}));

const confirmMock = vi.fn();
vi.mock("@/hooks/useConfirm", () => ({
  useConfirm: () => ({
    confirm: confirmMock,
    confirmDialogProps: { open: false },
  }),
}));

const profile = {
  name: "default",
  value_tracking_enabled: false,
  tax_handling: "NONE",
  default_tax_rate: null,
  require_partner_tax_id: false,
  require_unit_price: false,
  confirm_shelf_by_scan: false,
  numbering_format: "{TYPE}/{YEAR}/{SEQ:03d}",
  number_padding: 3,
  type_labels: { IN: "PZ", OUT: "WZ" },
  default_currency: "PLN",
  default_unit: "pcs",
  print_template: "standard",
  visible_line_fields: [] as string[],
  approval_threshold: null,
  approval_required_for_types: [] as string[],
  pick_order_strategy: null,
};

/** What the pick-order registry holds: the default, and a module's own. */
const pickOrders = [
  {
    name: "location_sequence",
    module: "warehouse",
    label_key: "warehouse:pickOrderStrategies.location_sequence",
    is_default: true,
  },
  {
    name: "certified_first",
    module: "lot_certificates",
    label_key: "lot_certificates:pickOrderStrategies.certified_first",
    is_default: false,
  },
];

function GuardHarness({ onNavigate }: { onNavigate: () => void }) {
  const { guardNavigate } = useNavLeaveGuard();
  return (
    <button type="button" onClick={() => guardNavigate(onNavigate)}>
      leave
    </button>
  );
}

function renderPage(onNavigate: () => void = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DocumentProfileSettingsPage />
        <GuardHarness onNavigate={onNavigate} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The page shows one section at a time; the others stay mounted but hidden. */
async function openSection(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name }));
}

const saveButton = () => screen.findByRole("button", { name: "Save" });

beforeEach(() => {
  vi.clearAllMocks();
  useFormGuardStore.getState().setDirtyForm(null);
  confirmMock.mockResolvedValue(true);
  server.use(
    http.get("*/warehouse/profile", () => HttpResponse.json(profile)),
    http.get("*/warehouse/profile/presets", () => HttpResponse.json([])),
    http.get("*/warehouse/profile/pick-order-strategies", () =>
      HttpResponse.json(pickOrders),
    ),
    http.put("*/warehouse/profile", () => HttpResponse.json(profile)),
    http.get("*/warehouse/templates", () => HttpResponse.json([])),
    http.get("*/uoms", () => HttpResponse.json(onePage([]))),
    http.get("*/modules/warehouse/settings", () =>
      HttpResponse.json({
        settings: { over_receipt_tolerance_pct: 0 },
        settings_schema: {
          type: "object",
          properties: {
            over_receipt_tolerance_pct: {
              type: "number",
              title: "Over-receipt tolerance (%)",
              default: 0,
            },
          },
        },
      }),
    ),
  );
});

describe("DocumentProfileSettingsPage — a preset list that failed", () => {
  it("says so instead of offering an empty list of presets", async () => {
    server.use(
      http.get(
        "*/warehouse/profile/presets",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderPage();
    await openSection("Ready-made setup");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });
});

describe("DocumentProfileSettingsPage — one Settings screen", () => {
  // The module's own options used to be a second tab, "Module settings",
  // whose only other content was a link back to this screen.
  it("opens on receiving, which holds the module's own options", async () => {
    renderPage();

    expect(await screen.findByText("Over-receipt tolerance (%)")).toBeVisible();
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(
      "Receiving and scanning",
    );
  });

  it("splits the settings into sections a person is setting up", async () => {
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    for (const section of [
      "Receiving and scanning",
      "Putaway",
      "Printouts",
      "Numbering and prices",
      "Approvals",
      "Work on the floor",
      "Tracking links",
      "Ready-made setup",
    ]) {
      expect(screen.getByRole("tab", { name: section })).toBeInTheDocument();
    }

    // Only the open section is on screen.
    expect(
      screen.queryByRole("combobox", { name: "Picking order" }),
    ).toBeNull();
    await openSection("Work on the floor");
    expect(
      screen.getByRole("combobox", { name: "Picking order" }),
    ).toBeVisible();
  });

  it("keeps the links to other screens apart from the fields", async () => {
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    await openSection("Putaway");
    // How each top-level location receives is chosen here, under Putaway.
    expect(
      await screen.findByRole("combobox", { name: "How Home receives" }),
    ).toHaveValue("one");
    const related = screen.getByRole("navigation", { name: "Related screens" });
    expect(
      within(related).getByRole("link", { name: /Putaway rules/i }),
    ).toHaveAttribute("href", "/warehouse/putaway-rules");
    expect(
      within(related).getByRole("link", { name: "Codes and labels" }),
    ).toHaveAttribute("href", "/warehouse/location-settings");

    await openSection("Printouts");
    expect(
      screen.getByRole("link", { name: /Print templates/i }),
    ).toHaveAttribute("href", "/warehouse/templates");
  });

  it("puts the rarely changed numbering format under Advanced", async () => {
    renderPage();
    const format = await screen.findByDisplayValue(profile.numbering_format);

    expect(format.closest("details")).not.toBeNull();
    expect(format.closest("details")).not.toHaveAttribute("open");
  });
});

describe("DocumentProfileSettingsPage — one Save for the whole page", () => {
  it("shows no Save until something changed, then a single one", async () => {
    renderPage();
    const format = await screen.findByDisplayValue(profile.numbering_format);
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();

    fireEvent.change(format, { target: { value: "{TYPE}/{SEQ:03d}" } });

    expect(
      await screen.findAllByRole("button", { name: /save/i }),
    ).toHaveLength(1);
    expect(screen.getByText("You have unsaved changes")).toBeInTheDocument();
  });

  it("an edit in one section survives a visit to another and is saved with it", async () => {
    const puts: Array<Record<string, unknown>> = [];
    // The server keeps what each request wrote, so a later answer still
    // carries the earlier ones.
    let stored: Record<string, unknown> = { ...profile };
    server.use(
      http.put("*/warehouse/profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        puts.push(body);
        stored = { ...stored, ...body };
        return HttpResponse.json(stored);
      }),
    );
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    await openSection("Work on the floor");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Picking order" }),
      "certified_first",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /confirm the location by scan/i }),
    );
    await openSection("Tracking links");
    await userEvent.click(
      screen.getByRole("button", { name: "Add a carrier" }),
    );
    await userEvent.type(screen.getByLabelText("Carrier"), "Acme");
    // `{` opens a key name in userEvent.type, so the token is set directly.
    fireEvent.change(screen.getByLabelText("Tracking link"), {
      target: { value: "https://acme.test/{tracking_number}" },
    });
    await openSection("Receiving and scanning");

    await userEvent.click(await saveButton());

    // The profile form and the two sections that keep their own state each
    // write their field; nothing is written before Save.
    await waitFor(() => expect(puts.length).toBeGreaterThanOrEqual(3));
    expect(puts).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ confirm_shelf_by_scan: true }),
        expect.objectContaining({ pick_order_strategy: "certified_first" }),
        expect.objectContaining({
          tracking_url_templates: {
            Acme: "https://acme.test/{tracking_number}",
          },
        }),
      ]),
    );
    await waitFor(() =>
      expect(screen.queryByText("You have unsaved changes")).toBeNull(),
    );
  });

  it("keeps the Save and says why when a request is refused", async () => {
    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    server.use(
      http.put("*/warehouse/profile", () =>
        HttpResponse.json(
          { detail: "Numbering format needs {SEQ}" },
          { status: 422 },
        ),
      ),
    );
    renderPage();
    const format = await screen.findByDisplayValue(profile.numbering_format);
    fireEvent.change(format, { target: { value: "{TYPE}" } });

    await userEvent.click(await saveButton());

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Numbering format needs {SEQ}"),
    );
    expect(screen.getByText("You have unsaved changes")).toBeInTheDocument();
  });

  it("does not write anything while the reader only picks", async () => {
    const puts: unknown[] = [];
    server.use(
      http.put("*/warehouse/profile", async ({ request }) => {
        puts.push(await request.json());
        return HttpResponse.json(profile);
      }),
    );
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    await openSection("Work on the floor");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Picking order" }),
      "certified_first",
    );
    await openSection("Printouts");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Print layout" }),
      "pl_pz",
    );

    expect(puts).toHaveLength(0);
    expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
  });
});

describe("DocumentProfileSettingsPage — the navigation gate knows about unsaved work", () => {
  it("reports a format field's unsaved work to the gate", async () => {
    renderPage();

    const format = await screen.findByDisplayValue(profile.numbering_format);
    expect(useFormGuardStore.getState().dirtyForm).toBeNull();

    fireEvent.change(format, { target: { value: "{TYPE}/{SEQ:03d}" } });

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });
    expect(useFormGuardStore.getState().dirtyForm).toContain("document");
  });

  it("disarms the gate when the typed value goes back to the saved one", async () => {
    renderPage();

    const format = await screen.findByDisplayValue(profile.numbering_format);
    fireEvent.change(format, { target: { value: "{TYPE}/{SEQ:03d}" } });
    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });

    fireEvent.change(format, { target: { value: profile.numbering_format } });

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();
    });
  });

  it("declining the leave question keeps the typed values", async () => {
    confirmMock.mockResolvedValue(false);
    const onNavigate = vi.fn();
    renderPage(onNavigate);

    const format = await screen.findByDisplayValue(profile.numbering_format);
    fireEvent.change(format, { target: { value: "{TYPE}/{SEQ:03d}" } });
    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });

    await userEvent.click(screen.getByRole("button", { name: "leave" }));

    await waitFor(() => {
      expect(confirmMock).toHaveBeenCalled();
    });
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue("{TYPE}/{SEQ:03d}")).toBeInTheDocument();
    expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
  });

  // The reachable state the disabled checkbox exists for: a row that holds
  // the unit-price requirement while value tracking is off — saved by older
  // code, or by an update that never touched the pair. The screen gates the
  // box to unchecked+disabled, so there is no edit to leave over, and the
  // gate must not hear one.
  it("a row holding the unit-price requirement with value tracking off loads clean", async () => {
    server.use(
      http.get("*/warehouse/profile", () =>
        HttpResponse.json({ ...profile, require_unit_price: true }),
      ),
    );
    renderPage();

    await screen.findByDisplayValue(profile.numbering_format);
    await openSection("Numbering and prices");
    expect(
      screen.getByRole("checkbox", { name: /require unit price/i }),
    ).toBeDisabled();

    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeNull();
    });
  });

  it("accepting the leave question lets the navigation through", async () => {
    confirmMock.mockResolvedValue(true);
    const onNavigate = vi.fn();
    renderPage(onNavigate);

    const format = await screen.findByDisplayValue(profile.numbering_format);
    fireEvent.change(format, { target: { value: "{TYPE}/{SEQ:03d}" } });
    await waitFor(() => {
      expect(useFormGuardStore.getState().dirtyForm).toBeTruthy();
    });

    await userEvent.click(screen.getByRole("button", { name: "leave" }));

    await waitFor(() => {
      expect(onNavigate).toHaveBeenCalled();
    });
  });
});

describe("DocumentProfileSettingsPage — every setting reaches Save and comes back", () => {
  const puts: Array<Record<string, unknown>> = [];

  function useCapturingProfile() {
    puts.length = 0;
    server.use(
      http.get("*/warehouse/profile", () => HttpResponse.json(profile)),
      http.get("*/warehouse/profile/presets", () => HttpResponse.json([])),
      http.put("*/warehouse/profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        puts.push(body);
        return HttpResponse.json({ ...profile, ...body });
      }),
      http.get("*/warehouse/templates", () => HttpResponse.json([])),
      http.get("*/uoms", () => HttpResponse.json(onePage([]))),
    );
  }

  it("sends every field it shows, set and then cleared", async () => {
    useCapturingProfile();
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    // ---- set everything the page holds a control for ----
    await openSection("Numbering and prices");
    await userEvent.click(
      screen.getByRole("checkbox", { name: /enable value tracking/i }),
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Tax Handling"),
      "SIMPLE_RATE",
    );
    await userEvent.type(screen.getByLabelText("Default Tax Rate (%)"), "23");
    await userEvent.selectOptions(
      screen.getByLabelText("Default Currency (ISO 4217)"),
      "EUR",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /require partner tax id/i }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /require unit price/i }),
    );
    fireEvent.change(screen.getByLabelText("Document Number Format"), {
      target: { value: "{TYPE}/{YEAR}/{SEQ:05d}" },
    });
    await userEvent.clear(screen.getByLabelText("Label for Receipt"));
    await userEvent.type(screen.getByLabelText("Label for Receipt"), "PZ2");
    await userEvent.type(screen.getByLabelText("Label for Adjustment"), "ADJ");
    await userEvent.clear(
      screen.getByLabelText("Approval Threshold (net value)"),
    );
    await userEvent.type(
      screen.getByLabelText("Approval Threshold (net value)"),
      "100",
    );
    await openSection("Work on the floor");
    await userEvent.click(
      screen.getByRole("checkbox", { name: /confirm the location by scan/i }),
    );
    await openSection("Approvals");
    await userEvent.click(screen.getByRole("checkbox", { name: "Receipt" }));

    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(1));

    expect(puts[0]).toMatchObject({
      value_tracking_enabled: true,
      tax_handling: "SIMPLE_RATE",
      default_tax_rate: "23",
      default_currency: "EUR",
      require_partner_tax_id: true,
      require_unit_price: true,
      confirm_shelf_by_scan: true,
      numbering_format: "{TYPE}/{YEAR}/{SEQ:05d}",
      number_padding: 5,
      type_labels: { IN: "PZ2", OUT: "WZ", ADJUSTMENT: "ADJ" },
      approval_threshold: "100",
      approval_required_for_types: ["IN"],
    });

    // ---- clear them all, the same way a reader would ----
    // The tax rate and the currency live inside value tracking, so they go
    // first — switching it off takes them off the screen.
    await userEvent.clear(screen.getByLabelText("Default Tax Rate (%)"));
    await userEvent.selectOptions(
      screen.getByLabelText("Default Currency (ISO 4217)"),
      "",
    );
    await openSection("Numbering and prices");
    await userEvent.click(
      screen.getByRole("checkbox", { name: /enable value tracking/i }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /require partner tax id/i }),
    );
    fireEvent.change(screen.getByLabelText("Document Number Format"), {
      target: { value: "{TYPE}/{YEAR}/{SEQ:03d}" },
    });
    await userEvent.clear(screen.getByLabelText("Label for Receipt"));
    await userEvent.clear(screen.getByLabelText("Label for Delivery"));
    await userEvent.clear(screen.getByLabelText("Label for Adjustment"));
    await openSection("Work on the floor");
    await userEvent.click(
      screen.getByRole("checkbox", { name: /confirm the location by scan/i }),
    );
    await openSection("Approvals");
    await userEvent.clear(
      screen.getByLabelText("Approval Threshold (net value)"),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: "Receipt" }));

    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(2));

    expect(puts[1]).toMatchObject({
      value_tracking_enabled: false,
      tax_handling: "NONE",
      default_tax_rate: null,
      default_currency: null,
      require_partner_tax_id: false,
      // Value tracking is off: the requirement went with it rather than
      // standing in the column where it could block a document nobody
      // can price.
      require_unit_price: false,
      confirm_shelf_by_scan: false,
      type_labels: null,
      approval_threshold: null,
      // The whole point of the round trip: an emptied list is an answer,
      // and `undefined` would have dropped the key and left the old one.
      approval_required_for_types: [],
    });
    expect(puts[1]["approval_required_for_types"]).toEqual([]);
  });

  it("saves the quarantine location it is given and clears it again", async () => {
    useCapturingProfile();
    serveLocations([{ id: "q1", name: "Quarantine shelf" }]);
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);

    await userEvent.click(
      screen.getByRole("combobox", { name: "Quarantine location" }),
    );
    // The location's name is also a row of the receiving choice on another
    // section, which is hidden; the pick is the visible one.
    await userEvent.click(
      (await screen.findAllByText("Quarantine shelf")).find(
        (row) => !row.closest("[hidden]"),
      )!,
    );
    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ quarantine_location_id: "q1" });

    await userEvent.click(
      screen.getByRole("combobox", { name: "Quarantine location" }),
    );
    await userEvent.click(await screen.findByText("No quarantine location"));
    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts[1]["quarantine_location_id"]).toBeNull();
  });

  it("the unit-price box cannot be ticked while value tracking is off", async () => {
    useCapturingProfile();
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);
    await openSection("Numbering and prices");

    const box = screen.getByRole("checkbox", { name: /require unit price/i });
    expect(box).toBeDisabled();

    await userEvent.click(
      screen.getByRole("checkbox", { name: /enable value tracking/i }),
    );
    expect(
      screen.getByRole("checkbox", { name: /require unit price/i }),
    ).not.toBeDisabled();
  });
});

describe("DocumentProfileSettingsPage — the picking order is chosen by name", () => {
  it("offers each registered strategy under its module's catalogue label", async () => {
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);
    await openSection("Work on the floor");

    const chooser = screen.getByRole("combobox", {
      name: "Picking order",
    }) as HTMLSelectElement;
    // The default's label is read from the owning module's catalogue under
    // the key the registry names it by; a module whose catalogue this
    // build does not carry falls back to the registered name.
    expect(
      within(chooser).getByRole("option", { name: "Location order" }),
    ).toBeInTheDocument();
    expect(
      within(chooser).getByRole("option", { name: "certified_first" }),
    ).toBeInTheDocument();
    // Nothing chosen shows the default walk.
    expect(chooser.value).toBe("location_sequence");
  });

  it("saves a module's strategy by name and the default as nothing chosen", async () => {
    const puts: Record<string, unknown>[] = [];
    server.use(
      http.put("*/warehouse/profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        puts.push(body);
        return HttpResponse.json({ ...profile, ...body });
      }),
    );
    renderPage();
    await screen.findByDisplayValue(profile.numbering_format);
    await openSection("Work on the floor");

    // The choice waits for the page's Save, like everything else on it.
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Picking order" }),
      "certified_first",
    );
    expect(puts).toHaveLength(0);
    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ pick_order_strategy: "certified_first" });

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Picking order" }),
      "location_sequence",
    );
    await userEvent.click(await saveButton());
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts[1]).toMatchObject({ pick_order_strategy: null });
  });
});

describe("DocumentProfileSettingsPage — a preset asks before it overwrites", () => {
  const applied: string[] = [];

  /**
   * The PL Magazyn row as the server stores it: seven labels, ``SCRAP``
   * among them. The undo has to put every one of them back.
   */
  const plProfile = {
    ...profile,
    name: "PL Magazyn",
    value_tracking_enabled: true,
    tax_handling: "PER_LINE_RATE",
    numbering_format: "{TYPE_LABEL}/{YEAR}/{MONTH}/{SEQ:04d}",
    number_padding: 4,
    type_labels: {
      IN: "PZ",
      OUT: "WZ",
      INT: "MM",
      INTERNAL_IN: "PW",
      INTERNAL_OUT: "RW",
      CORRECTION: "KOR",
      SCRAP: "ZL",
    },
    visible_line_fields: ["batch_number", "expiry_date"],
    print_template: "pl_pz",
  };

  /** The keys `_schemas_profile.py` accepts on the wire. */
  const writableTypeLabelKeys = [
    "IN",
    "OUT",
    "INT",
    "INTERNAL_IN",
    "INTERNAL_OUT",
    "CORRECTION",
    "ADJUSTMENT",
    "SCRAP",
  ];

  function useCapturingPreset() {
    applied.length = 0;
    server.use(
      http.get("*/warehouse/profile", () => HttpResponse.json(plProfile)),
      http.get("*/warehouse/profile/presets", () =>
        HttpResponse.json(["Simple", "UK Warehouse"]),
      ),
      http.post("*/warehouse/profile/apply-preset/:name", ({ params }) => {
        applied.push(String(params.name));
        return HttpResponse.json({ ...plProfile, name: String(params.name) });
      }),
      http.put("*/warehouse/profile", () => HttpResponse.json(plProfile)),
      http.get("*/warehouse/templates", () => HttpResponse.json([])),
      http.get("*/uoms", () => HttpResponse.json(onePage([]))),
    );
  }

  it("declining the question leaves the profile alone", async () => {
    useCapturingPreset();
    confirmMock.mockResolvedValueOnce(false);
    renderPage();
    await openSection("Ready-made setup");
    const select = await screen.findByRole("combobox", {
      name: "Apply Preset",
    });

    await userEvent.selectOptions(select, "UK Warehouse");

    await waitFor(() => expect(confirmMock).toHaveBeenCalled());
    // The question names the preset and says what the apply overwrites.
    const question = confirmMock.mock.calls[0][0] as { message: string };
    expect(question.message).toContain("UK Warehouse");
    expect(question.message).toMatch(/numbering/i);
    expect(question.message).toMatch(/tax ID/i);
    expect(question.message).toMatch(/unsaved/i);
    expect(applied).toHaveLength(0);
  });

  it("accepting writes the preset and offers the row as it stood", async () => {
    useCapturingPreset();
    const toastSuccess = vi
      .spyOn(toast, "success")
      .mockImplementation(() => "");
    confirmMock.mockResolvedValueOnce(true);
    renderPage();
    await openSection("Ready-made setup");
    const select = await screen.findByRole("combobox", {
      name: "Apply Preset",
    });

    await userEvent.selectOptions(select, "Simple");
    await waitFor(() => expect(applied).toEqual(["Simple"]));
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());

    const [, options] = toastSuccess.mock.calls[0] as unknown as [
      string,
      { action?: { label: string; onClick: () => void } } | undefined,
    ];
    expect(options?.action?.label).toBeTruthy();

    // The undo puts the profile back — the whole row, including the fields
    // this page holds no state for, which is why the draft cannot do it.
    // Its PUT answers the way the server does: a label the update schema
    // refuses is a 422, not a write. A snapshot forwarded verbatim would
    // fail here exactly as it did live — PL row, undo, 422, nothing
    // restored.
    const puts: Array<Record<string, unknown>> = [];
    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    server.use(
      http.put("*/warehouse/profile", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        puts.push(body);
        const labels = body.type_labels as Record<string, string> | null;
        const refused = labels
          ? Object.keys(labels).filter(
              (key) => !writableTypeLabelKeys.includes(key),
            )
          : [];
        if (refused.length > 0) {
          return HttpResponse.json(
            {
              detail: `type_labels keys must be IN, OUT, INT, INTERNAL_IN, INTERNAL_OUT, ADJUSTMENT, CORRECTION, or SCRAP; got ${refused[0]}`,
            },
            { status: 422 },
          );
        }
        return HttpResponse.json(plProfile);
      }),
    );
    options?.action?.onClick();
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({
      // The row is renamed by `apply_preset`, so the undo carries the name
      // as well — settings restored under the preset's name would leave the
      // selector naming a configuration the row no longer holds.
      name: plProfile.name,
      value_tracking_enabled: plProfile.value_tracking_enabled,
      numbering_format: plProfile.numbering_format,
      type_labels: {
        IN: "PZ",
        OUT: "WZ",
        INT: "MM",
        INTERNAL_IN: "PW",
        INTERNAL_OUT: "RW",
        CORRECTION: "KOR",
        SCRAP: "ZL",
      },
      print_template: "pl_pz",
      default_unit: "pcs",
    });
    expect(toastError).not.toHaveBeenCalled();
  });
});
