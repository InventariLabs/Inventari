import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import LabelScanPage from "./LabelScanPage";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import { signInWith } from "@/test/auth";
import { http, HttpResponse } from "msw";

let queryClient: QueryClient;

/** Where the page sent the reader, written out so a test can read it. */
function Arrived({ name }: { name: string }) {
  const location = useLocation();
  return (
    <p>
      {name}: {location.pathname}
      {location.search}
    </p>
  );
}

const renderPage = (initialEntries: string[] = ["/labels/scan/STM-0001"]) =>
  render(
    <MemoryRouter
      initialEntries={initialEntries}
      initialIndex={initialEntries.length - 1}
    >
      <Routes>
        <Route path="/" element={<p>Home</p>} />
        <Route path="/labels" element={<p>Label pool</p>} />
        <Route
          path="/inventory/scan"
          element={<Arrived name="scan screen" />}
        />
        <Route
          path="/inventory/labels"
          element={<Arrived name="pool screen" />}
        />
        <Route
          path="/labels/scan/:code"
          element={
            <QueryClientProvider client={queryClient}>
              <LabelScanPage />
            </QueryClientProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );

describe("LabelScanPage", () => {
  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  it("says the code is unknown when the server says so", async () => {
    server.use(
      http.get(
        "/api/v1/labels/scan/STM-0001",
        () => new HttpResponse(null, { status: 404 }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/no label matches this code/i),
    ).toBeInTheDocument();
  });

  it("does not offer a new label when the lookup failed", async () => {
    // This screen is the only entry a printed QR code has. "Create a new label"
    // after a 500 puts a second sticker on a thing that already carries one.
    server.use(
      http.get(
        "/api/v1/labels/scan/STM-0001",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderPage();

    expect(await screen.findByText("An error occurred")).toBeInTheDocument();
    expect(
      screen.queryByText(/no label matches this code/i),
    ).not.toBeInTheDocument();
    // And still a way out of the dead end.
    expect(screen.getByRole("button", { name: /back/i })).toBeInTheDocument();
  });

  it("asks the reader to wait when the lookups come faster than the API takes them", async () => {
    // A burst of scans past the per-minute allowance is not a failure the
    // retry button can fix right now: the page says to wait, as the scanner does.
    server.use(
      http.get("/api/v1/labels/scan/STM-0001", () =>
        HttpResponse.json(
          { detail: "Too many requests. Try again later." },
          { status: 429 },
        ),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(
        "Too many scans in a minute. Wait a moment, then scan again.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("An error occurred")).not.toBeInTheDocument();
  });

  it("goes home from a label opened by its QR code, where there is no back", async () => {
    // A phone's camera opens the printed address in a fresh tab: the scan
    // screen is the first entry of its history, and popping it did nothing —
    // the only button on the dead end did not move.
    server.use(
      http.get(
        "/api/v1/labels/scan/STM-0001",
        () => new HttpResponse(null, { status: 404 }),
      ),
    );
    renderPage();

    await userEvent.click(await screen.findByRole("button", { name: /back/i }));

    expect(await screen.findByText("Home")).toBeInTheDocument();
  });

  it("still goes back to where the reader came from inside the app", async () => {
    server.use(
      http.get(
        "/api/v1/labels/scan/STM-0001",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderPage(["/labels", "/labels/scan/STM-0001"]);

    await userEvent.click(await screen.findByRole("button", { name: /back/i }));

    expect(await screen.findByText("Label pool")).toBeInTheDocument();
  });

  it("writes the server's line in the reader's language", async () => {
    // The line under the status arrives as a catalogue key: the server had
    // no way to know which language the person holding the phone reads, and
    // it answered in English under a status that was already Polish.
    server.use(
      http.get("/api/v1/labels/scan/STM-0001", () =>
        HttpResponse.json({
          status: "unassigned",
          label_code: "STM-0001",
          message_key: "scan:result.foundInHistory",
          message_params: { product: "Gouda" },
          action: "show_quick_add",
        }),
      ),
    );

    await withLanguage("pl", async () => {
      renderPage();
      expect(
        await screen.findByText("Znaleziono w historii: Gouda"),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Found in history/)).not.toBeInTheDocument();
    });
  });
});

describe("LabelScanPage — a read-only account", () => {
  const serveFreeLabel = () =>
    server.use(
      http.get("/api/v1/labels/scan/STM-0001", () =>
        HttpResponse.json({
          status: "unassigned",
          label_code: "STM-0001",
          action: "show_quick_add",
        }),
      ),
    );

  it("is not offered the assignment, and is told why", async () => {
    // The button led to the scan screen, which refuses before the form opens
    // — so the reader was offered a door that says "you can view this, not
    // change it" one screen later.
    signInWith(["items:read"]);
    serveFreeLabel();
    renderPage();

    expect(await screen.findByText("STM-0001")).toBeInTheDocument();
    expect(screen.queryByTestId("label-assign-btn")).not.toBeInTheDocument();
    expect(
      screen.getByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
  });

  it("still offers it to an account that may create products", async () => {
    signInWith(["items:read", "items:write"]);
    serveFreeLabel();
    renderPage();

    expect(await screen.findByTestId("label-assign-btn")).toBeInTheDocument();
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });
});

describe("LabelScanPage — where its buttons lead", () => {
  const serveLabel = (status: "unassigned" | "assigned") =>
    server.use(
      http.get("/api/v1/labels/scan/STM-0001", () =>
        HttpResponse.json(
          status === "unassigned"
            ? {
                status: "unassigned",
                label_code: "STM-0001",
                action: "show_quick_add",
              }
            : {
                status: "assigned",
                label_code: "STM-0001",
                action: "show_quick_actions",
                item: { id: "i1", name: "Gouda" },
              },
        ),
      ),
    );

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    signInWith(["items:read", "items:write"]);
  });

  it("takes a free label to the scan screen with its code, to be assigned", async () => {
    serveLabel("unassigned");
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Assign label" }),
    );

    expect(
      await screen.findByText("scan screen: /inventory/scan?code=STM-0001"),
    ).toBeInTheDocument();
  });

  it("takes a label that is already in use to the same screen, to act on its product", async () => {
    serveLabel("assigned");
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "Open scan actions" }),
    );

    expect(
      await screen.findByText("scan screen: /inventory/scan?code=STM-0001"),
    ).toBeInTheDocument();
  });

  it("leads to the label pool from its secondary button", async () => {
    serveLabel("unassigned");
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: "View label pool" }),
    );

    expect(
      await screen.findByText("pool screen: /inventory/labels"),
    ).toBeInTheDocument();
  });
});
