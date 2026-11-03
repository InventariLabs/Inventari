import { useEffect } from "react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { rememberLastUsedLocations } from "@/modules/warehouse/lib/lastUsedLocations";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import * as modulesCtx from "@/contexts/ModulesContext";
import * as mediaQuery from "@/hooks/useMediaQuery";
import * as documentHooks from "@/modules/warehouse/hooks/useDocuments";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { ReadableError } from "@/lib/errors";
import IssueGoodsPage from "./IssueGoodsPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/hooks/useMediaQuery", () => ({ useMediaQuery: vi.fn() }));
vi.mock("@/hooks/useCanWrite", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCanWrite")>()),
  useCanWrite: () => true,
}));
vi.mock("@/hooks/useDocumentCurrency", () => ({
  useDocumentCurrency: () => "USD",
}));
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: () => ({
    isCameraActive: false,
    scannerError: null,
    isTorchOn: false,
    toggleTorch: vi.fn(),
    restartCamera: vi.fn(),
  }),
}));

const storagesTree = vi.hoisted(() => ({
  showModuleData: false,
  calls: [] as URLSearchParams[],
}));

vi.mock("@/modules/settings/hooks/useOrganization", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/settings/hooks/useOrganization")
  >()),
  useShowModuleData: () => storagesTree.showModuleData,
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: false, tax_handling: "NONE" },
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentPartnerOptions", () => ({
  useDocumentPartnerOptions: () => ({
    partnerTypes: ["CUSTOMER", "BOTH"],
    selectedPartnerOffered: true,
    fieldProps: {
      partners: [{ id: "c1", name: "Acme Bistro" }],
      onPartnerSearch: vi.fn(),
      partnersLoading: false,
      partnersError: null,
      retryPartners: vi.fn(),
    },
  }),
}));

const rice = {
  item_id: "rec-1",
  product_template_id: "pt-rice",
  name: "Jasmine Rice",
  available_quantity: "12",
  location_name: "Shelf A",
  uom_id: null,
  uom_symbol: "pcs",
  is_stub: false,
};

vi.mock("@/modules/warehouse/hooks/useProductSearch", () => ({
  useProductSearch: () => ({
    results: [rice],
    elsewhere: [],
    isLoading: false,
    error: null,
    search: vi.fn(),
    selectResult: vi.fn(),
    clearSearch: vi.fn(),
    query: "",
    setQuery: vi.fn(),
  }),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  usePostNewDocument: vi.fn(),
  useUndoDocument: () => ({ mutate: vi.fn(), isPending: false }),
}));

// A native <select> stands in for the searchable picker.
vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    options,
    value,
    onChange,
    label,
    error,
    id,
  }: {
    options: { id: string; name: string }[];
    value: string;
    onChange: (v: string) => void;
    label?: string;
    error?: string;
    id?: string;
  }) => (
    <div>
      <select
        id={id}
        aria-label={label}
        aria-invalid={error ? true : undefined}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.name}
          </option>
        ))}
      </select>
      {error && <p role="alert">{error}</p>}
    </div>
  ),
}));

const postMutate = vi.fn();

function renderPage() {
  const header = { data: { title: "", actions: null }, setHeader: vi.fn() };
  return render(
    <PageHeaderContext.Provider value={header}>
      <IssueGoodsPage />
    </PageHeaderContext.Provider>,
  );
}

/** What the one-step post was sent. */
function posted() {
  expect(postMutate).toHaveBeenCalledOnce();
  return postMutate.mock.calls[0][0].data;
}

async function pickRice(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("combobox", { name: /Item/ }), "rice");
  await user.click(await screen.findByRole("option", { name: /Jasmine Rice/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  storagesTree.calls = serveLocations([
    { id: "wh", name: "Main Warehouse" },
    { id: "shelf-a", name: "Shelf A", parent_id: "wh" },
  ]);
  vi.mocked(mediaQuery.useMediaQuery).mockReturnValue(false);
  vi.spyOn(modulesCtx, "useModules").mockReturnValue({
    enabledModules: ["warehouse", "partners"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
    focusModule: null,
    hiddenModules: [],
  } as unknown as ReturnType<typeof modulesCtx.useModules>);
  vi.mocked(documentHooks.usePostNewDocument).mockReturnValue({
    mutate: postMutate,
    isPending: false,
  } as unknown as ReturnType<typeof documentHooks.usePostNewDocument>);
});

describe("IssueGoodsPage", () => {
  it("issues to a customer as a delivery from the only warehouse, in one post", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onSuccess({
        id: "doc-1",
        number: "OUT/2026/001",
        type: "OUT",
        status: "COMPLETED",
        lines: [],
      }),
    );
    renderPage();

    expect(screen.getByText("The office gets: Delivery")).toBeInTheDocument();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);
    const quantity = screen.getByRole("spinbutton", { name: /Quantity/ });
    await user.clear(quantity);
    await user.type(quantity, "3");
    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );

    expect(posted()).toMatchObject({
      type: "OUT",
      partner_id: "c1",
      source_location_id: "wh",
      lines: [{ item_id: "rec-1", expected_quantity: 3 }],
    });
    expect(
      await screen.findByRole("heading", { name: "Issued 1 line" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "OUT/2026/001" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Undo issue" })).toBeVisible();
  });

  it("keeps the shelf it last issued from when the check that it is still on offer failed", async () => {
    const user = userEvent.setup();
    window.localStorage.clear();
    rememberLastUsedLocations("OUT", "shelf-a", "");
    // Only the question "is this place still offered" fails; the places
    // themselves are named as before.
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const asked = new URL(request.url).searchParams;
        return asked.has("ids") && !asked.has("usage")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined;
      }),
    );
    postMutate.mockImplementation((_payload, options) =>
      options.onSuccess({
        id: "doc-1",
        number: "OUT/2026/001",
        type: "OUT",
        status: "COMPLETED",
        lines: [],
      }),
    );
    renderPage();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);
    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );

    // A check that could not be made is not an answer that the place is gone:
    // the shelf stays the source, and the server has the last word.
    expect(posted()).toMatchObject({ source_location_id: "shelf-a" });
  });

  it("writes off damaged goods as a scrap that names neither a customer nor a source", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);
    await user.click(screen.getByRole("radio", { name: /Damaged or expired/ }));

    expect(screen.getByText("The office gets: Scrap")).toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Customer" }),
    ).not.toBeInTheDocument();
    // The line entered before the purpose changed is still there.
    await user.selectOptions(
      screen.getByTestId("scrap-reason-code"),
      "EXPIRED",
    );
    await user.click(screen.getByRole("button", { name: "Write off" }));

    const payload = posted();
    expect(payload).toMatchObject({
      type: "SCRAP",
      reason_code: "EXPIRED",
      lines: [{ item_id: "rec-1" }],
    });
    expect(payload.partner_id).toBeUndefined();
    expect(payload.source_location_id).toBeUndefined();
  });

  it("asks why before it writes goods off", async () => {
    const user = userEvent.setup();
    renderPage();

    await pickRice(user);
    await user.click(screen.getByRole("radio", { name: /Damaged or expired/ }));
    await user.click(screen.getByRole("button", { name: "Write off" }));

    expect(postMutate).not.toHaveBeenCalled();
    expect(screen.getByText("Pick a reason")).toBeInTheDocument();
  });

  it("issues for production or own use as an internal issue, with no customer asked", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /For production or own use/ }),
    );
    expect(
      screen.queryByRole("combobox", { name: "Customer" }),
    ).not.toBeInTheDocument();
    await pickRice(user);
    await user.click(screen.getByRole("button", { name: "Issue for use" }));

    const payload = posted();
    expect(payload).toMatchObject({
      type: "INTERNAL_OUT",
      source_location_id: "wh",
    });
    expect(payload.partner_id).toBeUndefined();
  });

  it("offers no place another module claims, whatever the general lists mix", async () => {
    // The organization lets its general lists show module data; an issue
    // still takes goods only from places that may hold stock.
    storagesTree.showModuleData = true;
    renderPage();
    await waitFor(() => expect(storagesTree.calls.length).toBeGreaterThan(0));
    for (const asked of storagesTree.calls) {
      expect(asked.get("exclude_module_contexts")).toBe("true");
    }
    storagesTree.showModuleData = false;
  });

  it("never reads the whole tree or the whole list of locations", async () => {
    storagesTree.calls = serveLocations([
      { id: "wh", name: "Main Warehouse" },
      ...Array.from({ length: 300 }, (_, i) => ({
        id: `shelf-${i}`,
        name: `Shelf ${i}`,
        parent_id: "wh",
      })),
    ]);
    renderPage();

    await waitFor(() => expect(storagesTree.calls.length).toBeGreaterThan(1));
    for (const request of storagesTree.calls) {
      // A list request is a page of at most thirty; a tree request is one
      // level: the top, for the default source.
      if (request.has("depth")) expect(request.get("depth")).toBe("1");
      else expect(Number(request.get("limit"))).toBeLessThanOrEqual(30);
    }
  });

  it("says why nothing was posted when no goods are on the list", async () => {
    const user = userEvent.setup();
    // Two warehouses and none remembered: no source is picked for the reader.
    storagesTree.calls = serveLocations([
      { id: "wh", name: "Main Warehouse" },
      { id: "cold", name: "Cold Store" },
    ]);
    renderPage();

    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );

    expect(
      screen
        .getAllByRole("alert")
        .some((alert) => alert.textContent === "No lines added yet"),
    ).toBe(true);
    expect(postMutate).not.toHaveBeenCalled();
    // The field is the customer's, and the footer counts lines, the word
    // the posted answer uses for the same count.
    expect(screen.getByText("Choose the customer.")).toBeInTheDocument();
    expect(
      screen.queryByText("Partner is required for this document type"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Choose the location the goods come from."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("From location is required for this document type"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("0 lines")).toBeInTheDocument();
  });

  it("drops the empty-list message from the footer once a line exists", async () => {
    const user = userEvent.setup();
    storagesTree.calls = serveLocations([
      { id: "wh", name: "Main Warehouse" },
      { id: "cold", name: "Cold Store" },
    ]);
    renderPage();

    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );
    expect(screen.getByText("No lines added yet")).toBeInTheDocument();

    await pickRice(user);

    expect(screen.queryByText("No lines added yet")).not.toBeInTheDocument();
  });

  it("keeps the server's refusal beside the button", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onError({
        isAxiosError: true,
        response: {
          status: 422,
          data: { detail: { message: "Only 2 left on the shelf" } },
        },
      }),
    );
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /For production or own use/ }),
    );
    await pickRice(user);
    await user.click(screen.getByRole("button", { name: "Issue for use" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only 2 left on the shelf",
    );
  });

  it("retries a failed press under the same key, and a changed list under a new one", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onError(new Error("Network Error")),
    );
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /For production or own use/ }),
    );
    await pickRice(user);
    await user.click(screen.getByRole("button", { name: "Issue for use" }));
    await user.click(screen.getByRole("button", { name: "Issue for use" }));

    expect(postMutate).toHaveBeenCalledTimes(2);
    const [first, retry] = postMutate.mock.calls.map(([vars]) => vars.key);
    expect(first).toBeTruthy();
    expect(retry).toBe(first);

    const quantity = screen.getByRole("spinbutton", { name: /Quantity/ });
    await user.clear(quantity);
    await user.type(quantity, "2");
    await user.click(screen.getByRole("button", { name: "Issue for use" }));

    expect(postMutate.mock.calls[2][0].key).not.toBe(first);
  });

  it("on a phone takes the goods one by one, counted with big buttons", async () => {
    const user = userEvent.setup();
    vi.mocked(mediaQuery.useMediaQuery).mockReturnValue(true);
    renderPage();

    await user.click(
      screen.getByRole("radio", { name: /For production or own use/ }),
    );
    await user.type(
      screen.getByRole("textbox", { name: /Scan or type a name/ }),
      "rice",
    );
    await user.click(
      screen.getByRole("button", { name: /Jasmine Rice.*In Shelf A: 12 pcs/ }),
    );
    const card = screen.getByRole("region", { name: "Jasmine Rice" });
    expect(within(card).getByText("In Shelf A: 12 pcs.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Increase" }));
    await user.click(within(card).getByRole("button", { name: "Increase" }));
    await user.click(within(card).getByRole("button", { name: "Add" }));

    expect(screen.getByText("1 product on the list")).toBeInTheDocument();
    expect(screen.getByText("Quantity: 3")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Issue for use" }));

    expect(posted()).toMatchObject({
      type: "INTERNAL_OUT",
      lines: [{ item_id: "rec-1", expected_quantity: 3 }],
    });
  });
});

describe("fields another module adds to the issue screen", () => {
  const beforeSubmit = vi.fn();

  function CarrierPanel({
    data,
  }: {
    data: SlotDataMap["document_form_extra"];
  }) {
    return (
      <>
        <p>
          Carrier panel: {data.action} {data.documentType}, {data.lines.length}{" "}
          lines
        </p>
        <button
          type="button"
          onClick={() => data.setMetaData("slot_probe", { carrier: "DHL" })}
        >
          Carrier DHL
        </button>
      </>
    );
  }

  function GradeField({
    data,
  }: {
    data: SlotDataMap["document_line_form_extra"];
  }) {
    const { registerBeforeSubmit, line } = data;
    useEffect(
      () => registerBeforeSubmit(() => beforeSubmit(line.name)),
      [registerBeforeSubmit, line.name],
    );
    return (
      <>
        <p>Grade of {line.name}</p>
        <button
          type="button"
          onClick={() => data.setMetaData("slot_probe", { grade: "A" })}
        >
          Grade {line.name} A
        </button>
        {line.metaData.slot_probe && <p>{line.name} graded</p>}
      </>
    );
  }

  beforeEach(() => {
    beforeSubmit.mockReset();
    moduleRegistry.register({
      name: "slot-probe",
      routes: [],
      slots: [
        {
          slot: "document_form_extra",
          component: slotComponent(CarrierPanel),
        },
        {
          slot: "document_line_form_extra",
          component: slotComponent(GradeField),
        },
      ],
    });
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["warehouse", "partners", "slot-probe"],
      isModuleEnabled: () => true,
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    } as unknown as ReturnType<typeof modulesCtx.useModules>);
  });

  it("shows the panel, follows the purpose, and puts a field under every line", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(
      screen.getByText("Carrier panel: issue OUT, 0 lines"),
    ).toBeInTheDocument();

    await pickRice(user);
    expect(screen.getByText("Grade of Jasmine Rice")).toBeInTheDocument();
    expect(
      screen.getByText("Carrier panel: issue OUT, 1 lines"),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /Damaged or expired/ }));
    expect(
      screen.getByText("Carrier panel: issue SCRAP, 1 lines"),
    ).toBeInTheDocument();
  });

  it("sends what the module put on the document and on the line", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);

    await user.click(
      screen.getByRole("button", { name: "Grade Jasmine Rice A" }),
    );
    await user.click(screen.getByRole("button", { name: "Carrier DHL" }));
    expect(screen.getByText("Jasmine Rice graded")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );

    expect(posted()).toMatchObject({
      meta_data: { slot_probe: { carrier: "DHL" } },
      lines: [{ meta_data: { slot_probe: { grade: "A" } } }],
    });
  });

  it("shows the line field in the phone's list as well", async () => {
    vi.mocked(mediaQuery.useMediaQuery).mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();
    await user.type(
      screen.getByRole("textbox", { name: /Scan or type a name/ }),
      "rice",
    );
    await user.click(
      screen.getByRole("button", { name: /Jasmine Rice.*In Shelf A: 12 pcs/ }),
    );
    await user.click(
      within(screen.getByRole("region", { name: "Jasmine Rice" })).getByRole(
        "button",
        { name: "Add" },
      ),
    );

    expect(
      await screen.findByText("Grade of Jasmine Rice"),
    ).toBeInTheDocument();
  });

  it("lets the module save before the press is sent, and stops it when the module refuses", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onSuccess({
        id: "doc-1",
        number: "OUT/2026/001",
        type: "OUT",
        status: "COMPLETED",
        lines: [],
      }),
    );
    renderPage();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);

    beforeSubmit.mockRejectedValueOnce(
      new ReadableError("Grade the rice first"),
    );
    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );
    expect(await screen.findByText("Grade the rice first")).toBeInTheDocument();
    expect(postMutate).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Issue to the customer" }),
    );
    await screen.findByRole("heading", { name: "Issued 1 line" });
    expect(beforeSubmit).toHaveBeenCalledTimes(2);
    expect(beforeSubmit.mock.invocationCallOrder[1]).toBeLessThan(
      postMutate.mock.invocationCallOrder[0],
    );
  });

  it("takes one press at a time while a module is still saving its fields", async () => {
    const user = userEvent.setup();
    postMutate.mockImplementation((_payload, options) =>
      options.onSuccess({
        id: "doc-1",
        number: "OUT/2026/001",
        type: "OUT",
        status: "COMPLETED",
        lines: [],
      }),
    );
    renderPage();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Customer" }),
      "c1",
    );
    await pickRice(user);

    let finishSaving: () => void = () => {};
    beforeSubmit.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finishSaving = resolve;
      }),
    );
    const issue = screen.getByRole("button", { name: "Issue to the customer" });
    await user.click(issue);

    // The press is still waiting for the module: a second one, or a changed
    // list, must not start a second document.
    expect(issue).toBeDisabled();
    await user.click(issue);
    expect(beforeSubmit).toHaveBeenCalledTimes(1);

    finishSaving();
    await screen.findByRole("heading", { name: "Issued 1 line" });
    expect(postMutate).toHaveBeenCalledTimes(1);
  });
});
