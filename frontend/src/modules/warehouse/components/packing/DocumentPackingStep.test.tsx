import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, waitFor, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { scanWithHardwareScanner as scan } from "@/test/scanner";
import { documentLine, warehouseDocument } from "@/test/factories/documents";
import {
  packingApi,
  type PackageOut,
  type PackingView,
} from "@/modules/warehouse/api/packing";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { signInWith, signOut } from "@/test/auth";
import * as scanSessionHooks from "@/modules/warehouse/hooks/useDocumentScanSession";
import { DocumentPackingStep } from "./DocumentPackingStep";
import { onePage } from "@/test/mocks/page";

const downloadBlob = vi.hoisted(() => vi.fn());
vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob,
}));

const location = vi.hoisted(() => ({ hash: "" }));
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useLocation: () => ({ ...location, pathname: "/warehouse/documents/doc-1" }),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentScanSession", () => ({
  useDocumentScanSession: vi.fn(),
}));

const BASE = "/api/v1/warehouse/documents/doc-1";

/** A picked dispatch: 4 of 4 bolts and 2 of 3 nuts came off the shelf. */
function pickedDispatch(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    type: "OUT",
    number: "OUT/2026/0042",
    status: "CONFIRMED",
    lines: [
      documentLine({
        id: "bolts",
        name: "Bolt M8",
        quantity: "4",
        done_quantity: "4",
      }),
      documentLine({
        id: "nuts",
        name: "Nut M8",
        quantity: "3",
        done_quantity: "2",
        line_number: 2,
      }),
    ],
    ...overrides,
  });
}

/**
 * The packing door as a tiny in-memory server: the same rules the backend
 * keeps (a package holds what was picked and is not packed elsewhere), so a
 * test reads what the screen shows after each write rather than a canned
 * answer.
 */
function packingServer() {
  const picked: Record<string, number> = { bolts: 4, nuts: 2 };
  const names: Record<string, string> = { bolts: "Bolt M8", nuts: "Nut M8" };
  let packages: PackageOut[] = [];
  const requests: string[] = [];

  const packed = (lineId: string) =>
    packages
      .flatMap((p) => p.lines)
      .filter((ln) => ln.document_line_id === lineId)
      .reduce((sum, ln) => sum + Number(ln.quantity), 0);

  const view = (): PackingView => ({
    editable: true,
    packages: packages.map((p, i) => ({
      ...p,
      number: i + 1,
      code: `OUT/2026/0042-P${i + 1}`,
    })),
    lines: Object.keys(picked).map((id, i) => ({
      document_line_id: id,
      line_number: i + 1,
      product_name: names[id],
      uom_symbol: "pcs",
      picked_quantity: String(picked[id]),
      packed_quantity: String(packed(id)),
      remaining_quantity: String(picked[id] - packed(id)),
    })),
  });

  const open = (lines: [string, number][] = []) => {
    packages = [
      ...packages,
      {
        id: `pkg-${packages.length + 1}`,
        number: packages.length + 1,
        code: "",
        weight_kg: null,
        created_at: "2026-10-17T10:00:00Z",
        lines: lines.map(([id, qty]) => ({
          document_line_id: id,
          line_number: 1,
          product_name: names[id],
          uom_symbol: "pcs",
          quantity: String(qty),
        })),
      },
    ];
  };

  const setLine = (packageId: string, lineId: string, quantity: number) => {
    packages = packages.map((p) =>
      p.id !== packageId
        ? p
        : {
            ...p,
            lines: [
              ...p.lines.filter((ln) => ln.document_line_id !== lineId),
              ...(quantity > 0
                ? [
                    {
                      document_line_id: lineId,
                      line_number: 1,
                      product_name: names[lineId],
                      uom_symbol: "pcs",
                      quantity: String(quantity),
                    },
                  ]
                : []),
            ],
          },
    );
  };

  server.use(
    http.get(`${BASE}/packages`, () => HttpResponse.json(view())),
    http.post(`${BASE}/packages`, () => {
      requests.push("create");
      open();
      return HttpResponse.json(view(), { status: 201 });
    }),
    http.post(`${BASE}/packages/pack-all`, () => {
      requests.push("pack-all");
      open(
        Object.keys(picked)
          .map((id): [string, number] => [id, picked[id] - packed(id)])
          .filter(([, qty]) => qty > 0),
      );
      return HttpResponse.json(view(), { status: 201 });
    }),
    http.put(
      `${BASE}/packages/:pkg/lines/:line`,
      async ({ params, request }) => {
        const { quantity } = (await request.json()) as { quantity: string };
        requests.push(`put ${params.pkg} ${params.line} ${quantity}`);
        setLine(String(params.pkg), String(params.line), Number(quantity));
        return HttpResponse.json(view());
      },
    ),
    http.post(`${BASE}/packages/:pkg/scan`, async ({ params, request }) => {
      const { code } = (await request.json()) as { code: string };
      requests.push(`scan ${params.pkg} ${code}`);
      if (code !== "5901234123457") {
        return HttpResponse.json(
          { detail: { message: `No product carries the code ${code}.` } },
          { status: 400 },
        );
      }
      const held = Number(
        packages
          .find((p) => p.id === params.pkg)
          ?.lines.find((ln) => ln.document_line_id === "nuts")?.quantity ?? 0,
      );
      setLine(String(params.pkg), "nuts", held + 1);
      return HttpResponse.json(view());
    }),
    http.patch(`${BASE}/packages/:pkg`, async ({ params, request }) => {
      const { weight_kg } = (await request.json()) as { weight_kg: string };
      requests.push(`weigh ${params.pkg} ${weight_kg}`);
      packages = packages.map((p) =>
        p.id === params.pkg ? { ...p, weight_kg } : p,
      );
      return HttpResponse.json(view());
    }),
    http.delete(`${BASE}/packages/:pkg`, ({ params }) => {
      requests.push(`delete ${params.pkg}`);
      packages = packages.filter((p) => p.id !== params.pkg);
      return HttpResponse.json(view());
    }),
    http.get(`${BASE}/packages/:pkg/packing-slip`, () =>
      HttpResponse.arrayBuffer(new ArrayBuffer(4), {
        headers: { "Content-Type": "application/pdf" },
      }),
    ),
    http.get(`${BASE}/packages/:pkg/label`, () =>
      HttpResponse.arrayBuffer(new ArrayBuffer(4), {
        headers: { "Content-Type": "image/png" },
      }),
    ),
  );
  return { requests };
}

function renderStep(
  document: WarehouseDocument = pickedDispatch(),
  props: Partial<{
    canWrite: boolean;
    onComplete: (shipment?: ShipmentCreate) => void;
  }> = {},
) {
  signInWith(
    props.canWrite === false
      ? ["warehouse:read"]
      : ["warehouse:read", "warehouse:write"],
  );
  return renderWithProviders(
    <DocumentPackingStep
      document={document}
      onComplete={props.onComplete ?? vi.fn()}
      isCompletePending={false}
    />,
  );
}

const packages = () => screen.queryAllByTestId("package-card");

describe("DocumentPackingStep", () => {
  afterEach(() => {
    signOut();
    location.hash = "";
  });

  beforeEach(() => {
    downloadBlob.mockClear();
    vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
      data: null,
      isPending: false,
    } as unknown as ReturnType<typeof scanSessionHooks.useDocumentScanSession>);
  });

  describe("is offered only between picking and completion", () => {
    it.each([
      [
        "a dispatch nothing was picked of",
        { lines: [documentLine({ done_quantity: "0" })] },
      ],
      ["a completed dispatch", { status: "COMPLETED" }],
      ["a receipt", { type: "IN" }],
      ["a transfer", { type: "INT" }],
    ] as const)("not on %s", (_, overrides) => {
      packingServer();
      renderStep(pickedDispatch(overrides as Partial<WarehouseDocument>));
      expect(screen.queryByText("Packing")).not.toBeInTheDocument();
    });

    it("not while a picking session is still open over it", () => {
      packingServer();
      const getPacking = vi.spyOn(packingApi, "get");
      vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
        data: { kind: "picking", id: "s1", status: "active" },
        isPending: false,
      } as unknown as ReturnType<
        typeof scanSessionHooks.useDocumentScanSession
      >);
      renderStep();
      expect(screen.queryByText("Packing")).not.toBeInTheDocument();
      // Not the absence of a query still in flight: the packing view is
      // never asked for, so the open session, not a loading state, keeps
      // the step away.
      expect(getPacking).not.toHaveBeenCalled();
      getPacking.mockRestore();
    });

    it("once the picking session over it has finished", async () => {
      packingServer();
      vi.mocked(scanSessionHooks.useDocumentScanSession).mockReturnValue({
        data: { kind: "picking", id: "s1", status: "finished" },
        isPending: false,
      } as unknown as ReturnType<
        typeof scanSessionHooks.useDocumentScanSession
      >);
      renderStep();
      expect(await screen.findByText("Packing")).toBeInTheDocument();
    });

    it("on a picked dispatch, with what is left to pack", async () => {
      packingServer();
      renderStep();
      expect(await screen.findByText("Packing")).toBeInTheDocument();
      const toPack = screen.getByRole("region", { name: "To pack" });
      expect(within(toPack).getByText("Bolt M8")).toBeInTheDocument();
      expect(within(toPack).getByText("4 pcs. left")).toBeInTheDocument();
      expect(within(toPack).getByText("2 pcs. left")).toBeInTheDocument();
      // Opened from the page itself, the step stays where it is.
      expect(HTMLElement.prototype.scrollIntoView).not.toHaveBeenCalled();
    });
  });

  it("scrolls into view when the picking summary sent the reader to pack", async () => {
    packingServer();
    const scrolled = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
    location.hash = "#pack";

    renderStep();

    await screen.findByText("Packing");
    await waitFor(() => expect(scrolled).toHaveBeenCalledOnce());
  });

  it("packs everything into one package with one tap, then prints its slip and label", async () => {
    const user = userEvent.setup();
    const { requests } = packingServer();
    renderStep();

    await user.click(
      await screen.findByRole("button", { name: "Everything in one package" }),
    );

    expect(await screen.findByText("OUT/2026/0042-P1")).toBeInTheDocument();
    expect(requests).toEqual(["pack-all"]);
    expect(
      screen.getByText("Everything picked is packed."),
    ).toBeInTheDocument();
    // Nothing left to scan in, so no package is "being filled".
    expect(screen.queryByText("Filling")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /in one package/ }),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Packing slip" }));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        expect.any(Blob),
        "packing_slip_OUT-2026-0042-P1.pdf",
      ),
    );
    await user.click(screen.getByRole("button", { name: "Label" }));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        expect.any(Blob),
        "package_label_OUT-2026-0042-P1.png",
      ),
    );
  });

  it("sends a package's label to the printer, keeping the download", async () => {
    const user = userEvent.setup();
    packingServer();
    const queued: unknown[] = [];
    server.use(
      http.get("/api/v1/modules/my", () =>
        HttpResponse.json(["core", "items", "warehouse", "printing"]),
      ),
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([
            {
              id: "agent-1",
              name: "Packing bench",
              printer_type: "zebra",
              last_seen_at: "2026-10-24T10:00:00Z",
              online: true,
            },
          ]),
        ),
      ),
      http.post(
        `${BASE}/packages/:pkg/label/print`,
        async ({ params, request }) => {
          queued.push({ pkg: params.pkg, body: await request.json() });
          return HttpResponse.json({ job_id: "job-1" }, { status: 201 });
        },
      ),
    );
    renderStep();

    await user.click(
      await screen.findByRole("button", { name: "Everything in one package" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Send to printer" }),
    );

    await waitFor(() =>
      expect(queued).toEqual([
        {
          pkg: "pkg-1",
          body: expect.objectContaining({ agent_id: "agent-1" }),
        },
      ]),
    );
    expect(screen.getByRole("button", { name: "Label" })).toBeInTheDocument();
  });

  it("fills a package by tapping a line and saying how much goes in", async () => {
    const user = userEvent.setup();
    const { requests } = packingServer();
    renderStep();

    await user.click(await screen.findByRole("button", { name: /Bolt M8/ }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).getByText("Into a new package")).toBeInTheDocument();
    const quantity = within(sheet).getByLabelText("Quantity");
    expect(quantity).toHaveValue(4);
    await user.clear(quantity);
    await user.type(quantity, "3");
    await user.click(within(sheet).getByRole("button", { name: "Pack" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(requests).toEqual(["create", "put pkg-1 bolts 3"]);
    const [box] = packages();
    expect(within(box).getByText("3 pcs.")).toBeInTheDocument();
    expect(screen.getByText("1 pcs. left")).toBeInTheDocument();
  });

  it("refuses to tap more into a package than is left to pack", async () => {
    const user = userEvent.setup();
    const { requests } = packingServer();
    renderStep();

    await user.click(await screen.findByRole("button", { name: /Nut M8/ }));
    const sheet = await screen.findByRole("dialog");
    const quantity = within(sheet).getByLabelText("Quantity");
    await user.clear(quantity);
    await user.type(quantity, "3");
    await user.click(within(sheet).getByRole("button", { name: "Pack" }));

    expect(
      within(sheet).getByText("Only 2 pcs. is left to pack"),
    ).toBeInTheDocument();
    expect(requests).toEqual([]);
  });

  it("fills a package by scan, opening one when there is none yet", async () => {
    const { requests } = packingServer();
    renderStep();
    await screen.findByText("Packing");

    scan("5901234123457");
    await waitFor(() => expect(packages()).toHaveLength(1));
    // The same code again within 300 ms is the scanner's double read; the
    // packer's second unit comes later than that.
    const now = Date.now();
    const clock = vi.spyOn(Date, "now").mockReturnValue(now + 1000);
    scan("5901234123457");
    clock.mockRestore();

    await waitFor(() =>
      expect(requests).toEqual([
        "create",
        "scan pkg-1 5901234123457",
        "scan pkg-1 5901234123457",
      ]),
    );
    expect(
      await within(packages()[0]).findByText("2 pcs."),
    ).toBeInTheDocument();
  });

  it("scans into the package chosen to fill", async () => {
    const user = userEvent.setup();
    const { requests } = packingServer();
    renderStep();

    await user.click(
      await screen.findByRole("button", { name: "Add package" }),
    );
    await screen.findByText("OUT/2026/0042-P1");
    await user.click(screen.getByRole("button", { name: "Add package" }));
    await screen.findByText("OUT/2026/0042-P2");
    // The newest is filled until another one is chosen.
    expect(within(packages()[1]).getByText("Filling")).toBeInTheDocument();
    await user.click(
      within(packages()[0]).getByRole("button", { name: "Fill this one" }),
    );

    scan("5901234123457");

    await waitFor(() =>
      expect(requests.at(-1)).toBe("scan pkg-1 5901234123457"),
    );
  });

  it("takes a line out of a package, weighs a package and removes one", async () => {
    const user = userEvent.setup();
    const { requests } = packingServer();
    renderStep();

    await user.click(
      await screen.findByRole("button", { name: "Everything in one package" }),
    );
    await screen.findByText("OUT/2026/0042-P1");

    await user.click(
      screen.getByRole("button", {
        name: "Take Nut M8 out of OUT/2026/0042-P1",
      }),
    );
    expect(await screen.findByText("2 pcs. left")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Weight"), "1.25");
    await user.tab();
    await waitFor(() => expect(requests).toContain("weigh pkg-1 1.25"));

    await user.click(screen.getByRole("button", { name: "Remove package" }));
    await waitFor(() => expect(packages()).toHaveLength(0));
    expect(requests).toEqual([
      "pack-all",
      "put pkg-1 nuts 0",
      "weigh pkg-1 1.25",
      "delete pkg-1",
    ]);
  });

  it("completes the dispatch from the step", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    packingServer();
    renderStep(pickedDispatch(), { onComplete });

    await user.click(
      await screen.findByRole("button", { name: "Complete dispatch" }),
    );

    expect(onComplete).toHaveBeenCalledOnce();
    // Both shipping fields empty: the completion carries what it always did.
    expect(onComplete).toHaveBeenCalledWith(undefined);
  });

  it("completes the dispatch with the carrier and tracking number typed", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    packingServer();
    server.use(
      http.get("/api/v1/warehouse/shipments/carriers", () =>
        HttpResponse.json({ carriers: ["InPost", "DHL"] }),
      ),
    );
    renderStep(pickedDispatch(), { onComplete });

    const carrier = await screen.findByLabelText("Carrier");
    // The organization's carriers are offered as the field is typed.
    await waitFor(() => {
      const list = document.getElementById(carrier.getAttribute("list") ?? "");
      expect(
        [...(list?.querySelectorAll("option") ?? [])].map((o) => o.value),
      ).toEqual(["InPost", "DHL"]);
    });
    await user.type(carrier, " InPost ");
    await user.type(screen.getByLabelText("Tracking number"), "6200 1234");
    await user.click(screen.getByRole("button", { name: "Complete dispatch" }));

    expect(onComplete).toHaveBeenCalledWith({
      carrier: "InPost",
      tracking_number: "6200 1234",
    });
  });

  it("asks for the carrier of a tracking number typed alone", async () => {
    const user = userEvent.setup();
    const onComplete = vi.fn();
    packingServer();
    renderStep(pickedDispatch(), { onComplete });

    await user.type(await screen.findByLabelText("Tracking number"), "X1");
    await user.click(screen.getByRole("button", { name: "Complete dispatch" }));

    expect(
      await screen.findByText(
        "Name the carrier this tracking number belongs to.",
      ),
    ).toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("shows a reader who may not write the packages, and no action", async () => {
    const user = userEvent.setup();
    packingServer();
    const { unmount } = renderStep();
    await user.click(
      await screen.findByRole("button", { name: "Everything in one package" }),
    );
    await screen.findByText("OUT/2026/0042-P1");
    unmount();

    renderStep(pickedDispatch(), { canWrite: false });

    expect(await screen.findByText("OUT/2026/0042-P1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Packing slip" }),
    ).toBeInTheDocument();
    for (const name of [
      "Add package",
      "Remove package",
      "Complete dispatch",
      /Take Bolt M8/,
    ]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });
});
