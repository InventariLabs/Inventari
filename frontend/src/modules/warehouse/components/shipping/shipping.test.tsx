import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderWithProviders, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { PageSaveProvider, usePageSave } from "@/module-sdk";
import type { DocumentProfile } from "@/modules/warehouse/types";
import { formatDateTime } from "@/utils/formatters";
import { DocumentShipmentCard } from "./DocumentShipmentCard";
import { TrackingLinksSection } from "./TrackingLinksSection";
import { ShipmentFields } from "./ShipmentFields";
import { EMPTY_SHIPMENT } from "./shipmentDraft";

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["warehouse"],
    hiddenModules: [],
    focusModule: null,
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

// The camera is a live device; what the field does with a read is tested.
const cameraMock = vi.hoisted(() => ({
  onCodeScanned: (_code: string) => {},
  restartCamera: vi.fn(),
  setIsCameraActive: vi.fn(),
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (code: string) => void;
  }) => {
    cameraMock.onCodeScanned = onCodeScanned;
    return {
      scannerError: null,
      isCameraActive: true,
      setIsCameraActive: cameraMock.setIsCameraActive,
      restartCamera: cameraMock.restartCamera,
      toggleTorch: vi.fn(),
      isTorchOn: false,
    };
  },
}));

afterEach(() => {
  cameraMock.restartCamera.mockReset();
  cameraMock.setIsCameraActive.mockReset();
});

describe("ShipmentFields", () => {
  it("reads the tracking number off the parcel label with the camera", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <ShipmentFields
        value={{ carrier: "InPost", trackingNumber: "" }}
        onChange={onChange}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Scan tracking number" }),
    );
    expect(cameraMock.restartCamera).toHaveBeenCalledOnce();

    act(() => cameraMock.onCodeScanned(" 620012345678901234567 "));

    expect(onChange).toHaveBeenCalledWith({
      carrier: "InPost",
      trackingNumber: "620012345678901234567",
    });
    // One parcel, one number: the camera is put away after the read.
    expect(cameraMock.setIsCameraActive).toHaveBeenCalledWith(false);
    expect(
      screen.getByRole("button", { name: "Scan tracking number" }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("keeps the tracking number typed by hand", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <ShipmentFields value={EMPTY_SHIPMENT} onChange={onChange} />,
    );

    await user.type(screen.getByLabelText("Tracking number"), "7");

    expect(onChange).toHaveBeenLastCalledWith({
      carrier: "",
      trackingNumber: "7",
    });
  });

  it("says the carriers could not be loaded and stays free text", async () => {
    server.use(
      http.get("/api/v1/warehouse/shipments/carriers", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    renderWithProviders(
      <ShipmentFields value={EMPTY_SHIPMENT} onChange={() => {}} />,
    );

    expect(
      await screen.findByText(
        "Your carriers could not be loaded — type the name.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Carrier")).toBeEnabled();
  });
});

describe("DocumentShipmentCard", () => {
  it("shows nothing for a document that never shipped", () => {
    const { container } = renderWithProviders(
      <DocumentShipmentCard shipment={null} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names the carrier, links the number and says how many, when and who", () => {
    renderWithProviders(
      <DocumentShipmentCard
        shipment={{
          carrier: "InPost",
          tracking_number: "6200 1234",
          tracking_url:
            "https://inpost.pl/sledzenie-przesylek?number=6200%201234",
          shipped_at: "2026-10-17T12:00:00Z",
          shipped_by: "user-1",
          shipped_by_name: "Ada Admin",
          notes: "Courier at gate 2",
          package_count: 2,
        }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Shipment" }),
    ).toBeInTheDocument();
    expect(screen.getByText("InPost")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Track parcel 6200 1234/ }),
    ).toHaveAttribute(
      "href",
      "https://inpost.pl/sledzenie-przesylek?number=6200%201234",
    );
    expect(screen.getByText("2")).toBeInTheDocument();
    // The time as the rest of the document page prints it.
    expect(
      screen.getByText(formatDateTime("2026-10-17T12:00:00Z")),
    ).toBeInTheDocument();
    expect(screen.getByText("Ada Admin")).toBeInTheDocument();
    expect(screen.getByText("Courier at gate 2")).toBeInTheDocument();
  });

  it("shows a number no template links as plain text", () => {
    renderWithProviders(
      <DocumentShipmentCard
        shipment={{
          carrier: "Own van",
          tracking_number: "VAN-7",
          tracking_url: null,
          shipped_at: "2026-10-17T12:00:00Z",
          package_count: 0,
        }}
      />,
    );

    expect(screen.getByText("VAN-7")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("lets a long number and carrier break inside their column", () => {
    renderWithProviders(
      <DocumentShipmentCard
        shipment={{
          carrier: "Poczta Polska Pocztex Kurier 48",
          tracking_number: "6200123456789012345678",
          tracking_url: "https://inpost.pl/sledzenie-przesylek?number=6200",
          shipped_at: "2026-10-17T12:00:00Z",
          package_count: 1,
        }}
      />,
    );

    // jsdom lays nothing out; the phone measurement is the browser's. What
    // this pins is that both values may wrap and their column may shrink.
    for (const value of [
      screen.getByText("Poczta Polska Pocztex Kurier 48"),
      screen.getByRole("link", { name: /Track parcel/ }),
    ]) {
      const cell = value.closest("dd");
      expect(cell).toHaveClass("[overflow-wrap:anywhere]");
      expect(cell?.parentElement).toHaveClass("min-w-0");
    }
    expect(screen.getByRole("link", { name: /Track parcel/ })).not.toHaveClass(
      "inline-flex",
    );
  });
});

function profileWith(templates: Record<string, string> | null) {
  return {
    id: "profile-1",
    name: "Default",
    tracking_url_templates: templates,
  } as unknown as DocumentProfile;
}

/** The page's one Save, reduced to a button: the section only registers its edit. */
function SaveHarness() {
  const { dirty, saveAll } = usePageSave();
  return (
    <button type="button" disabled={!dirty} onClick={() => void saveAll()}>
      page save
    </button>
  );
}

const renderSection = () =>
  renderWithProviders(
    <PageSaveProvider>
      <TrackingLinksSection />
      <SaveHarness />
    </PageSaveProvider>,
  );

describe("TrackingLinksSection", () => {
  afterEach(() => signOut());

  it("saves the organization's links and nothing else of the profile", async () => {
    signInWith(["warehouse:read", "warehouse:manage"]);
    const user = userEvent.setup();
    const sent: unknown[] = [];
    server.use(
      http.get("/api/v1/warehouse/profile", () =>
        HttpResponse.json(
          profileWith({ Raben: "https://raben.example/t/{tracking_number}" }),
        ),
      ),
      http.put("/api/v1/warehouse/profile", async ({ request }) => {
        const body = (await request.json()) as {
          tracking_url_templates: Record<string, string>;
        };
        sent.push(body);
        return HttpResponse.json(profileWith(body.tracking_url_templates));
      }),
    );
    renderSection();

    expect(await screen.findByDisplayValue("Raben")).toBeInTheDocument();
    // The hint shows the literal the reader types into a link.
    expect(
      screen.getByText(/with \{tracking_number\} where the number goes/),
    ).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "page save" });
    // Nothing edited, nothing to save.
    expect(save).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Add a carrier" }));
    const carriers = screen.getAllByLabelText("Carrier");
    const links = screen.getAllByLabelText("Tracking link");
    await user.type(carriers[1], "Geis");
    await user.type(links[1], "https://geis.example/?n={{tracking_number}");
    await user.click(save);

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual({
      tracking_url_templates: {
        Raben: "https://raben.example/t/{tracking_number}",
        Geis: "https://geis.example/?n={tracking_number}",
      },
    });
    // The answer is what the list now holds: nothing left to save.
    await waitFor(() => expect(save).toBeDisabled());
  });

  it("clears a removed link by saving the list without it", async () => {
    signInWith(["warehouse:read", "warehouse:manage"]);
    const user = userEvent.setup();
    const sent: unknown[] = [];
    server.use(
      http.get("/api/v1/warehouse/profile", () =>
        HttpResponse.json(
          profileWith({ Raben: "https://raben.example/{tracking_number}" }),
        ),
      ),
      http.put("/api/v1/warehouse/profile", async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json(profileWith({}));
      }),
    );
    renderSection();

    await user.click(
      await screen.findByRole("button", { name: "Remove the link for Raben" }),
    );
    await user.click(screen.getByRole("button", { name: "page save" }));

    await waitFor(() => expect(sent).toEqual([{ tracking_url_templates: {} }]));
    expect(
      await screen.findByText("No links of your own yet."),
    ).toBeInTheDocument();
  });

  it("lets a reader without the manage right read the links, not change them", async () => {
    signInWith(["warehouse:read"]);
    server.use(
      http.get("/api/v1/warehouse/profile", () =>
        HttpResponse.json(
          profileWith({ Raben: "https://raben.example/{tracking_number}" }),
        ),
      ),
    );
    renderSection();

    expect(await screen.findByDisplayValue("Raben")).toBeDisabled();
    expect(screen.getByRole("button", { name: "page save" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Add a carrier" }),
    ).not.toBeInTheDocument();
  });
});
