import { describe, expect, it, afterEach, vi } from "vitest";
import { act, cleanup } from "@testing-library/react";
import i18next from "i18next";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { AssignmentsTab } from "@/modules/equipment/components/AssetAssignmentsTab";
import { useAuthStore } from "@/store/authStore";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * The button that opens the return on the asset page is worded for the
 * viewer: the person holding the asset hands it back ("Zwróć"), a manager
 * accepts it ("Przyjmij"). The dialog it opens already spoke the holder's verb.
 */

const assignment = {
  id: "assignment-1",
  item_id: "item-1",
  item_name: "ThinkPad T14",
  assigned_to_name: "Kasia Lis",
  assigned_to_email: "kasia@firma.example",
  checked_out_at: "2026-09-01T09:00:00Z",
  expected_return_at: null,
  checked_in_at: null,
};

const item = {
  id: "item-1",
  name: "ThinkPad T14",
  metadata: { equipment: { equipment_status: "DEPLOYED" } },
} as unknown as Item;

const before = useAuthStore.getState().user;

afterEach(async () => {
  // Unmount first: the language and the viewer change under a mounted tab.
  cleanup();
  act(() => useAuthStore.setState({ user: before }));
  await i18next.changeLanguage("en");
});

async function openTab(viewerEmail: string) {
  await i18next.changeLanguage("pl");
  act(() =>
    useAuthStore.setState({
      user: { ...(before ?? {}), email: viewerEmail } as never,
    }),
  );
  server.use(
    http.get("/api/v1/equipment/assignments/item/item-1", () =>
      HttpResponse.json(onePage([assignment])),
    ),
    http.get("/api/v1/organizations/my", () =>
      HttpResponse.json({ timezone: "UTC" }),
    ),
  );
  render(
    <AssignmentsTab item={item} onCheckout={vi.fn()} onCheckin={vi.fn()} />,
  );
  await screen.findByText("Kasia Lis");
}

describe("AssignmentsTab — the return button speaks the viewer's verb", () => {
  it("reads 'Zwróć' for the holder, whatever the case of the address", async () => {
    await openTab("Kasia@Firma.example");
    expect(screen.getByRole("button", { name: "Zwróć" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Przyjmij" }),
    ).not.toBeInTheDocument();
  });

  it("reads 'Przyjmij' for someone else", async () => {
    await openTab("kierownik@firma.example");
    expect(
      screen.getByRole("button", { name: "Przyjmij" }),
    ).toBeInTheDocument();
  });
});
