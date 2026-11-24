import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { act, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import {
  HomeShelvesAfterPosting,
  ReceiptHomeShelves,
} from "./ReceiptHomeShelves";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

beforeEach(() => {
  withModules("warehouse");
  signInWith(["warehouse:read"]);
});

afterEach(() => {
  signOut();
});

const offer = {
  kind: "set",
  product_template_id: "p-1",
  product_name: "Flour",
  location_id: "l-1",
  location_name: "Cold Room",
  reason: null,
};

function serveOffers(rows: unknown[]) {
  let asked = 0;
  server.use(
    http.get("/api/v1/warehouse/documents/doc-1/home-shelf-offers", () => {
      asked += 1;
      return HttpResponse.json(onePage(rows));
    }),
  );
  return () => asked;
}

describe("ReceiptHomeShelves", () => {
  it("asks when the posted receipt offers a shelf", async () => {
    serveOffers([offer]);
    render(<ReceiptHomeShelves documentId="doc-1" />);

    expect(
      await screen.findByText(/Flour has no home location yet/),
    ).toBeInTheDocument();
  });

  it("stays out of the way when the receipt asks nothing", async () => {
    const asked = serveOffers([]);
    render(<ReceiptHomeShelves documentId="doc-1" />);

    await waitFor(() => expect(asked()).toBe(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("HomeShelvesAfterPosting", () => {
  it("asks when the page watches the receipt turn completed", async () => {
    serveOffers([offer]);
    const { rerender } = render(
      <HomeShelvesAfterPosting documentId="doc-1" status="CONFIRMED" />,
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    rerender(<HomeShelvesAfterPosting documentId="doc-1" status="COMPLETED" />);

    expect(
      await screen.findByText(/Flour has no home location yet/),
    ).toBeInTheDocument();
  });

  it("does not ask about a receipt that was completed before the page opened", async () => {
    const asked = serveOffers([offer]);
    render(<HomeShelvesAfterPosting documentId="doc-1" status="COMPLETED" />);

    await act(() => new Promise((resolve) => setTimeout(resolve, 100)));
    expect(asked()).toBe(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
