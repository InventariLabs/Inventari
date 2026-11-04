import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import {
  render as rtlRender,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { server } from "@/test/mocks/server";
import type { WorkItem } from "@/modules/warehouse/types";
import { PutawaySheet } from "./PutawaySheet";

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));

vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => true,
}));

// The camera is a live device; the card is what these tests read.
const cameraMock = vi.hoisted(() => ({
  onCodeScanned: (_code: string) => {},
  scannerError: null as string | null,
  restartCamera: vi.fn(),
  setIsCameraActive: vi.fn(),
  toggleTorch: vi.fn(),
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
      scannerError: cameraMock.scannerError,
      isCameraActive: true,
      isCameraRunning: true,
      setIsCameraActive: cameraMock.setIsCameraActive,
      restartCamera: cameraMock.restartCamera,
      startCamera: vi.fn(),
      resumeCamera: vi.fn(),
      pauseCamera: vi.fn(),
      toggleTorch: cameraMock.toggleTorch,
      isTorchOn: false,
    };
  },
}));

const TREE_PATH = "/api/v1/locations/tree";
const POST_PATH = "/api/v1/warehouse/work-items/putaway/:lineId";
const SCAN_PATH = "/api/v1/labels/scan/:code";

function shelfTree() {
  return [
    {
      id: "wh-1",
      name: "Main Warehouse",
      parent_id: null,
      short_code: null,
      items_count: 0,
      children: [
        {
          id: "shelf-a",
          name: "Shelf A - Top",
          parent_id: "wh-1",
          short_code: "A-01-01",
          items_count: 0,
          children: [],
        },
        {
          id: "shelf-b",
          name: "Shelf B",
          parent_id: "wh-1",
          short_code: "A-02-01",
          items_count: 0,
          children: [],
        },
      ],
    },
  ];
}

function task(overrides: Partial<WorkItem> = {}): WorkItem {
  return {
    key: "putaway:line-1",
    kind: "putaway",
    state: "todo",
    source_kind: "putaway",
    source_id: "line-1",
    overdue: false,
    next_action: "put_away",
    subject: "Jasmine Rice",
    count: "40",
    unit: "kg",
    number: "PZ/1",
    shelf_scan_required: false,
    ...overrides,
  };
}

function render(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>{children}</BrowserRouter>
      </QueryClientProvider>
    ),
  });
}

function scannedShelf(id: string, code: string, name: string) {
  return {
    status: "storage_context",
    label_code: code,
    action: "set_storage_context",
    location: { id, name, icon: "shelf", type_code: "SHELF" },
  };
}

beforeEach(() => {
  cameraMock.scannerError = null;
  server.use(http.get(TREE_PATH, () => HttpResponse.json(shelfTree())));
});

describe("PutawaySheet", () => {
  it("asks for the shelf label before it posts, when the profile asks", async () => {
    const posts: { lineId: string; body: unknown }[] = [];
    server.use(
      http.post(POST_PATH, async ({ params, request }) => {
        posts.push({
          lineId: params.lineId as string,
          body: await request.json(),
        });
        return HttpResponse.json(
          { id: "move-1", number: "MM/2026/006", status: "COMPLETED" },
          { status: 201 },
        );
      }),
      http.get(SCAN_PATH, () =>
        HttpResponse.json(scannedShelf("shelf-a", "A-01-01", "Shelf A - Top")),
      ),
    );
    const onClose = vi.fn();
    const rice = task({
      place: "Shelf A - Top",
      place_id: "shelf-a",
      place_code: "A-01-01",
      place_source: "rule",
      shelf_scan_required: true,
    });

    render(<PutawaySheet item={rice} queue={[rice]} onClose={onClose} />);

    const dialog = screen.getByRole("dialog", { name: "Put away" });
    expect(within(dialog).getByText("A-01-01")).toBeInTheDocument();
    expect(within(dialog).getByText("Shelf A - Top")).toBeInTheDocument();
    expect(
      within(dialog).getByText("A put-away rule sends it here"),
    ).toBeInTheDocument();
    // The card says the label is still owed, and the one button that posts
    // the carry waits for it.
    expect(
      within(dialog).getByText("Scan the location to confirm"),
    ).toBeInTheDocument();
    const putAway = within(dialog).getByRole("button", { name: "Put away" });
    expect(putAway).toBeDisabled();

    await userEvent.type(
      within(dialog).getByPlaceholderText("Scan the location label"),
      "A-01-01{Enter}",
    );

    expect(
      await within(dialog).findByText("Location confirmed"),
    ).toBeInTheDocument();
    expect(putAway).toBeEnabled();
    await userEvent.click(putAway);

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      lineId: "line-1",
      body: { location_id: "shelf-a", scanned_code: "A-01-01" },
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("carries the shelf the previous task just filled to the next step", async () => {
    server.use(
      http.post(POST_PATH, () =>
        HttpResponse.json(
          { id: "move-1", number: "MM/2026/006", status: "COMPLETED" },
          { status: 201 },
        ),
      ),
    );
    const rice = task({
      place: "Shelf A - Top",
      place_id: "shelf-a",
      place_code: "A-01-01",
      place_source: "rule",
    });
    const beans = task({
      key: "putaway:line-2",
      source_id: "line-2",
      subject: "Black Beans",
      count: "12",
      unit: "pcs",
      number: "PZ/1",
      place: null,
      place_id: null,
      place_code: null,
      place_source: null,
    });
    const onClose = vi.fn();
    const { rerender } = render(
      <PutawaySheet item={rice} queue={[rice, beans]} onClose={onClose} />,
    );

    const dialog = screen.getByRole("dialog", { name: "Put away" });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Put away" }),
    );

    // The list now reports the beans with the shelf the carry just filled.
    const offered = {
      ...beans,
      place: "Shelf A - Top",
      place_id: "shelf-a",
      place_code: "A-01-01",
      place_source: "zone" as const,
    };
    rerender(<PutawaySheet item={rice} queue={[offered]} onClose={onClose} />);

    expect(
      await within(dialog).findByText("Put away 2 of 2"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("A-01-01")).toBeInTheDocument();
    expect(
      within(dialog).getByText("The location of the last move here"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Put away" }),
    ).toBeEnabled();
  });

  it("ends the walk when the tasks still queued were done elsewhere", async () => {
    server.use(
      http.post(POST_PATH, () =>
        HttpResponse.json(
          { id: "move-1", number: "MM/2026/007", status: "COMPLETED" },
          { status: 201 },
        ),
      ),
    );
    const rice = task({
      place: "Shelf A - Top",
      place_id: "shelf-a",
      place_code: "A-01-01",
      place_source: "rule",
    });
    const beans = task({
      key: "putaway:line-2",
      source_id: "line-2",
      subject: "Black Beans",
    });
    const onClose = vi.fn();
    const { rerender } = render(
      <PutawaySheet item={rice} queue={[rice, beans]} onClose={onClose} />,
    );

    const dialog = screen.getByRole("dialog", { name: "Put away" });
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Put away" }),
    );
    await within(dialog).findByText("Put away 2 of 2");
    expect(onClose).not.toHaveBeenCalled();

    // Someone else put the beans away meanwhile: the list has nothing left,
    // and the rice just posted must not come back as a step to post again.
    rerender(<PutawaySheet item={rice} queue={[]} onClose={onClose} />);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  describe("the home location it learns", () => {
    const HOME_PATH = "/api/v1/warehouse/putaway/home-shelf";
    const SILENCE_PATH =
      "/api/v1/warehouse/putaway/home-shelf/silenced/:productId";

    const offer = (overrides: Record<string, unknown> = {}) => ({
      kind: "change",
      reason: null,
      product_template_id: "tpl-rice",
      product_name: "Jasmine Rice",
      location_id: "shelf-b",
      location_name: "Shelf B",
      ...overrides,
    });

    function postReturns(homeShelf: unknown) {
      server.use(
        http.post(POST_PATH, () =>
          HttpResponse.json(
            {
              id: "move-1",
              number: "MM/2026/008",
              status: "COMPLETED",
              home_shelf: homeShelf,
            },
            { status: 201 },
          ),
        ),
      );
    }

    const rice = () =>
      task({
        place: "Shelf A - Top",
        place_id: "shelf-a",
        place_code: "A-01-01",
        place_source: "rule",
      });

    it("asks whether the location is the product's home, and yes writes it", async () => {
      postReturns(offer());
      const homes: unknown[] = [];
      server.use(
        http.put(HOME_PATH, async ({ request }) => {
          homes.push(await request.json());
          return HttpResponse.json({
            rule_id: "rule-1",
            product_template_id: "tpl-rice",
            location_id: "shelf-b",
          });
        }),
      );
      const onClose = vi.fn();
      const item = rice();
      render(<PutawaySheet item={item} queue={[item]} onClose={onClose} />);

      await userEvent.click(screen.getByRole("button", { name: "Put away" }));

      const ask = await screen.findByRole("dialog", { name: "Home location" });
      expect(
        within(ask).getByText(
          "Jasmine Rice usually goes elsewhere. Make Shelf B its home location from now on?",
        ),
      ).toBeInTheDocument();
      // The question holds the walk: nothing closes until it is answered.
      expect(onClose).not.toHaveBeenCalled();

      await userEvent.click(
        within(ask).getByRole("button", { name: "Yes, make it the home" }),
      );

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(homes).toEqual([
        { product_template_id: "tpl-rice", location_id: "shelf-b" },
      ]);
    });

    it("keeps the question while the carry just posted leaves the list", async () => {
      postReturns(offer({ kind: "set" }));
      const onClose = vi.fn();
      const item = rice();
      const { rerender } = render(
        <PutawaySheet item={item} queue={[item]} onClose={onClose} />,
      );

      await userEvent.click(screen.getByRole("button", { name: "Put away" }));
      await screen.findByRole("dialog", { name: "Home location" });
      // The list refetches and no task is left.
      rerender(<PutawaySheet item={item} queue={[]} onClose={onClose} />);

      expect(
        screen.getByRole("dialog", { name: "Home location" }),
      ).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("remembers 'do not ask again' for the product, and no writes nothing", async () => {
      postReturns(offer());
      const silenced: string[] = [];
      let homeWrites = 0;
      server.use(
        http.put(SILENCE_PATH, ({ params }) => {
          silenced.push(params.productId as string);
          return new HttpResponse(null, { status: 204 });
        }),
        http.put(HOME_PATH, () => {
          homeWrites += 1;
          return HttpResponse.json({});
        }),
      );
      const onClose = vi.fn();
      const item = rice();
      render(<PutawaySheet item={item} queue={[item]} onClose={onClose} />);
      await userEvent.click(screen.getByRole("button", { name: "Put away" }));
      const ask = await screen.findByRole("dialog", { name: "Home location" });

      await userEvent.click(
        within(ask).getByRole("button", {
          name: "Don't ask about Jasmine Rice again",
        }),
      );

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(silenced).toEqual(["tpl-rice"]);
      expect(homeWrites).toBe(0);
    });

    it("says why a location that cannot be a home is not offered", async () => {
      postReturns(
        offer({ kind: "refused", reason: "quarantine", location_name: "Hold" }),
      );
      const onClose = vi.fn();
      const item = rice();
      render(<PutawaySheet item={item} queue={[item]} onClose={onClose} />);
      await userEvent.click(screen.getByRole("button", { name: "Put away" }));

      const ask = await screen.findByRole("dialog", { name: "Home location" });
      expect(
        within(ask).getByText(
          "Hold is for goods set aside, so it cannot be the home location of Jasmine Rice.",
        ),
      ).toBeInTheDocument();
      expect(
        within(ask).queryByRole("button", { name: "Yes, make it the home" }),
      ).toBeNull();

      await userEvent.click(within(ask).getByText("Close"));
      await waitFor(() => expect(onClose).toHaveBeenCalled());
    });

    it("asks nothing when the put-away has no offer", async () => {
      postReturns(null);
      const onClose = vi.fn();
      const item = rice();
      render(<PutawaySheet item={item} queue={[item]} onClose={onClose} />);

      await userEvent.click(screen.getByRole("button", { name: "Put away" }));

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(
        screen.queryByRole("dialog", { name: "Home location" }),
      ).toBeNull();
    });
  });
});
