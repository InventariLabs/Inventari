import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import { useScanStore } from "@/store/scanStore";
import { DemoSandboxNotice } from "./DemoSandboxNotice";

describe("DemoSandboxNotice", () => {
  const assign = vi.fn();
  const realLocation = window.location;

  /** A viewport: `phone` matches the strip's phone query, nothing else. */
  const setViewport = (phone: boolean) => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: phone && query === "(max-width: 639px)",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  };

  beforeEach(() => {
    setViewport(false);
    assign.mockReset();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...realLocation, assign },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: realLocation,
    });
  });

  const renderOn = (isDemo: boolean, demoInboxUrl: string | null = null) => {
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({
          is_initialized: true,
          is_demo: isDemo,
          demo_inbox_url: demoInboxUrl,
        }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const rendered = render(
      <QueryClientProvider client={queryClient}>
        <DemoSandboxNotice />
      </QueryClientProvider>,
    );
    return { ...rendered, queryClient };
  };

  it("says nothing outside a demo", async () => {
    const { container, queryClient } = renderOn(false);
    // An absence means something only once the status has answered.
    await waitFor(() =>
      expect(
        queryClient.getQueryState(queryKeys.admin.initStatus)?.status,
      ).toBe("success"),
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("tells the visitor what to keep out of the demo and when it ends", async () => {
    renderOn(true);

    // Both halves of the deal sit in the same line: the schedule the copy
    // lives on, and the plain instruction to keep real data out.
    expect(await screen.findByText(/wiped every night/i)).toBeInTheDocument();
    expect(screen.getByText(/no real data/i)).toBeInTheDocument();
  });

  it("says where the mail it sends lands and links to that inbox", async () => {
    renderOn(true, "https://demo.test/mailpit/");

    // A visitor who invites a colleague by their real address is owed the
    // sentence where they read "sent", not only on the sign-in screen.
    expect(
      await screen.findByText(/public inbox anyone can read/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the inbox" }),
    ).toHaveAttribute("href", "https://demo.test/mailpit/");
  });

  describe("on a phone", () => {
    beforeEach(() => setViewport(true));

    it("says it in one short sentence and keeps the inbox link in one piece", async () => {
      renderOn(true, "https://demo.test/mailpit/");

      // The long sentence and the mail sentence are the desktop's: together
      // they took three lines above every screen of an 844px phone.
      expect(
        await screen.findByText("Demo, wiped nightly. No real data."),
      ).toBeInTheDocument();
      expect(screen.queryByText(/wiped every night/i)).not.toBeInTheDocument();
      expect(
        screen.queryByText(/public inbox anyone can read/i),
      ).not.toBeInTheDocument();

      // Both actions stay one press away, and the link cannot break over two
      // lines.
      const inbox = screen.getByRole("link", { name: "Public inbox" });
      expect(inbox).toHaveAttribute("href", "https://demo.test/mailpit/");
      expect(inbox.className).toContain("whitespace-nowrap");
      expect(
        screen.getByRole("button", { name: "Start over" }),
      ).toBeInTheDocument();
    });
  });

  it("claims nothing about an inbox it has no address for", async () => {
    const { queryClient } = renderOn(true);
    await waitFor(() =>
      expect(
        queryClient.getQueryState(queryKeys.admin.initStatus)?.status,
      ).toBe("success"),
    );

    expect(screen.queryByText(/public inbox/i)).not.toBeInTheDocument();
  });

  it("opens the label sheet a visitor prints and scans, in one step", async () => {
    // The strip is above the welcome and above the warehouse alike, so the
    // sheet never needs a screen of its own to be reached from — one press
    // here, in focus mode included, and it is open.
    server.use(
      http.get(
        "/api/v1/printing/demo-label-sheet",
        () =>
          new HttpResponse(new Uint8Array([0x89, 0x50]), {
            headers: { "Content-Type": "image/png" },
          }),
      ),
    );
    window.URL.createObjectURL = vi.fn(() => "blob:sheet");
    renderOn(true);

    fireEvent.click(await screen.findByRole("button", { name: "Label sheet" }));

    expect(
      await screen.findByRole("dialog", { name: "Print the demo's labels" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByAltText(
        "Preview of the demo's label sheet: location and product labels",
      ),
    ).toHaveAttribute("src", "blob:sheet");
  });

  it("closes the label sheet and leaves the visitor on the strip", async () => {
    server.use(
      http.get(
        "/api/v1/printing/demo-label-sheet",
        () =>
          new HttpResponse(new Uint8Array([0x89, 0x50]), {
            headers: { "Content-Type": "image/png" },
          }),
      ),
    );
    window.URL.createObjectURL = vi.fn(() => "blob:sheet");
    renderOn(true);
    fireEvent.click(await screen.findByRole("button", { name: "Label sheet" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Print the demo's labels",
    });

    fireEvent.click(
      within(dialog).getAllByRole("button", { name: /close/i })[0],
    );

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Label sheet" })).toBeEnabled();
  });

  it("starts over on a new organization after asking, with a full load", async () => {
    let asked: unknown = null;
    server.use(
      http.post("/api/v1/demo/sandbox", async ({ request }) => {
        asked = await request.json();
        return HttpResponse.json({
          access_token: "t",
          token_type: "bearer",
        });
      }),
    );
    renderOn(true);

    fireEvent.click(await screen.findByRole("button", { name: "Start over" }));
    // The confirmation is its own dialog with its own "Start over".
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      Array.from(dialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Start over",
      )!,
    );

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/launcher"));
    expect(asked).toEqual({ fresh: true, preferred_language: "en" });
  });

  it("takes the previous organization's remembered scan location with it", async () => {
    // The scanner remembers where the last scan went so a batch day does
    // not ask again — but that shelf belongs to the organization that had
    // it. Starting over is a full load, so no logout runs on the way to
    // the fresh copy: without this the new organization opens showing the
    // old one's storage.
    useScanStore.getState().setStorageContext({
      id: "loc-1",
      name: "Walk-in Cooler",
      icon: "Snowflake",
    });
    useScanStore.getState().setLastUsed("loc-1", "cat-1");
    server.use(
      http.post("/api/v1/demo/sandbox", () =>
        HttpResponse.json({ access_token: "t", token_type: "bearer" }),
      ),
    );
    renderOn(true);

    fireEvent.click(await screen.findByRole("button", { name: "Start over" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      Array.from(dialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Start over",
      )!,
    );

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/launcher"));
    const scan = useScanStore.getState();
    expect(scan.storageContext).toBeNull();
    expect(scan.lastStorageId).toBeNull();
    expect(scan.lastCategoryId).toBeNull();
  });

  it("keeps the visitor where they are and says why when no copy is left", async () => {
    // The visitor stays in the organization they are in, so what the
    // scanner remembers of it stays too — only a new identity takes it.
    useScanStore.getState().setStorageContext({
      id: "loc-1",
      name: "Walk-in Cooler",
      icon: "Snowflake",
    });
    server.use(
      http.post("/api/v1/demo/sandbox", () =>
        HttpResponse.json(
          { detail: { code: "DEMO_SANDBOX_CAP_REACHED", message: "x" } },
          { status: 429 },
        ),
      ),
    );
    renderOn(true);

    fireEvent.click(await screen.findByRole("button", { name: "Start over" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(
      Array.from(dialog.querySelectorAll("button")).find(
        (button) => button.textContent === "Start over",
      )!,
    );

    expect(
      await screen.findByText(/handed out all its copies for today/),
    ).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    expect(useScanStore.getState().storageContext).not.toBeNull();
  });
});
