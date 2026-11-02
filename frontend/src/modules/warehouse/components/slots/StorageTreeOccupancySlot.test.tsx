import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { act, render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { floor } from "@/test/factories/occupancy";
import StorageTreeOccupancySlot from "./StorageTreeOccupancySlot";

beforeEach(() => {
  signInWith(["warehouse:read"]);
  server.use(
    http.get("/api/v1/warehouse/putaway/occupancy", () =>
      HttpResponse.json(floor),
    ),
  );
});

afterEach(() => signOut());

describe("StorageTreeOccupancySlot", () => {
  it("draws the compact bar and number for a limited location", async () => {
    render(<StorageTreeOccupancySlot data={{ storageId: "Fridge A" }} />);

    expect(await screen.findByText("52%")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Fridge A" })).toBeInTheDocument();
  });

  it("shows a zone's average over its limited locations", async () => {
    render(<StorageTreeOccupancySlot data={{ storageId: "Cold" }} />);

    expect(await screen.findByText("83%")).toBeInTheDocument();
  });

  it("draws nothing for a location nobody limited", async () => {
    const { container } = render(
      <StorageTreeOccupancySlot data={{ storageId: "Rack 1" }} />,
    );

    // Let the read land (inside act, so its update is accounted for), then
    // check the slot stayed quiet.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(container).toBeEmptyDOMElement();
  });
});
