import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { HomeShelvesSheet } from "./HomeShelvesSheet";
import type { HomeShelfOffer } from "@/modules/warehouse/api/putaway";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const offer = (over: Partial<HomeShelfOffer>): HomeShelfOffer =>
  ({
    kind: "set",
    product_template_id: "p-1",
    product_name: "Flour",
    location_id: "l-1",
    location_name: "Cold Room",
    reason: null,
    ...over,
  }) as HomeShelfOffer;

const flour = offer({});
const rice = offer({
  product_template_id: "p-2",
  product_name: "Rice",
  location_id: "l-2",
  location_name: "Dry Store",
  kind: "change",
});

describe("HomeShelvesSheet", () => {
  it("asks about every product of a receipt in one sheet", () => {
    render(<HomeShelvesSheet offers={[flour, rice]} onDone={vi.fn()} />);

    expect(
      screen.getByText(/Flour has no home location yet.*Cold Room/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Rice usually goes elsewhere.*Dry Store/),
    ).toBeInTheDocument();
  });

  it("makes the answered product's shelf its home and keeps asking about the rest", async () => {
    let written: unknown;
    server.use(
      http.put("/api/v1/warehouse/putaway/home-shelf", async ({ request }) => {
        written = await request.json();
        return HttpResponse.json({});
      }),
    );
    const onDone = vi.fn();
    render(<HomeShelvesSheet offers={[flour, rice]} onDone={onDone} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Yes, make it the home: Flour" }),
    );

    await waitFor(() =>
      expect(screen.queryByText(/Flour has no home/)).not.toBeInTheDocument(),
    );
    expect(written).toEqual({
      product_template_id: "p-1",
      location_id: "l-1",
    });
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("Cold Room is now the home of Flour"),
    );
    expect(screen.getByText(/Rice usually goes elsewhere/)).toBeInTheDocument();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("closes itself when the last question is answered", async () => {
    const onDone = vi.fn();
    render(<HomeShelvesSheet offers={[flour]} onDone={onDone} />);

    await userEvent.click(screen.getByRole("button", { name: "No: Flour" }));

    expect(onDone).toHaveBeenCalled();
  });

  it("says why a shelf cannot be a home, without asking", () => {
    render(
      <HomeShelvesSheet
        offers={[offer({ kind: "refused", reason: "quarantine" })]}
        onDone={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Cold Room is for goods set aside",
    );
    expect(screen.queryByRole("button", { name: /Yes/ })).toBeNull();
  });
});
