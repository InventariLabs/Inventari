import { render, screen, waitFor } from "@/test/utils";
import { describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { serveLocations } from "@/test/serveLocations";
import { isInsidePath, LocationTargetPicker } from "./LocationTargetPicker";

describe("isInsidePath", () => {
  it("takes a place and everything below it, and nothing that only starts alike", () => {
    expect(isInsidePath("A › B", "A › B")).toBe(true);
    expect(isInsidePath("A › B › C", "A › B")).toBe(true);
    expect(isInsidePath("A › Bravo", "A › B")).toBe(false);
    expect(isInsidePath("A", "A › B")).toBe(false);
    expect(isInsidePath(null, "A")).toBe(false);
  });
});

const FLOOR = [
  { id: "home", name: "Home", parent_id: null },
  { id: "me", name: "Pantry", parent_id: "home" },
  { id: "drawer", name: "Drawer", parent_id: "me" },
  { id: "garage", name: "Garage", parent_id: "home" },
  { id: "attic", name: "Attic", parent_id: null },
];

function renderPicker(
  props: Partial<React.ComponentProps<typeof LocationTargetPicker>> = {},
) {
  return render(
    <LocationTargetPicker
      label="Lies in"
      value=""
      onChange={() => undefined}
      excludeSubtreeOf={["me"]}
      {...props}
    />,
  );
}

describe("LocationTargetPicker", () => {
  it("leaves out the excluded place and what stands inside it", async () => {
    serveLocations(FLOOR);
    renderPicker();
    await userEvent.click(screen.getByLabelText("Lies in"));

    expect(
      await screen.findByRole("button", { name: /Garage/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pantry/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Drawer/ })).toBeNull();
  });

  it("names the place already chosen even when the lists keep it off", async () => {
    // A module-owned parent: the scoped page does not hold it, the record does.
    serveLocations([
      ...FLOOR,
      {
        id: "rack",
        name: "Server rack",
        parent_id: null,
        context_tag: "equipment",
      },
    ]);
    renderPicker({ value: "rack", scope: { purpose: "stock" } });

    await waitFor(() =>
      expect(screen.getByLabelText("Lies in")).toHaveTextContent("Server rack"),
    );
  });

  it("says the search failed, with a retry, instead of offering nothing", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "down" }, { status: 500 }),
      ),
    );
    renderPicker();
    await userEvent.click(screen.getByLabelText("Lies in"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred",
    );
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("No results found")).toBeNull();
  });

  it("lists the places again once 'Try again' is pressed and the search works", async () => {
    serveLocations(FLOOR);
    let failing = true;
    server.use(
      http.get("/api/v1/locations", () =>
        failing
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );
    renderPicker();
    await userEvent.click(screen.getByLabelText("Lies in"));
    const retry = await screen.findByRole("button", { name: "Try again" });

    failing = false;
    await userEvent.click(retry);

    expect(
      await screen.findByRole("button", { name: /Garage/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
