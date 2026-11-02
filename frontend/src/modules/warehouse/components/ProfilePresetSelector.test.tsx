import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ProfilePresetSelector } from "./ProfilePresetSelector";

const PRESETS = [
  "Simple",
  "PL Magazyn",
  "UK Warehouse",
  "DE Lager",
  "Full Value",
];

function renderSelector(country: string | null) {
  server.use(
    http.get("*/api/v1/organizations/my", () =>
      HttpResponse.json({ id: "org-1", country }),
    ),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ProfilePresetSelector
        selectedPreset=""
        presets={PRESETS}
        isPending={false}
        onChange={() => {}}
        onApply={() => {}}
      />
    </QueryClientProvider>,
  );
}

function offered() {
  return screen
    .getAllByRole("option")
    .map((option) => (option as HTMLOptionElement).value)
    .filter(Boolean);
}

describe("ProfilePresetSelector — the organization's country", () => {
  it("offers the preset of the organization's country first, marked as the suggestion", async () => {
    renderSelector("DE");

    expect(
      await screen.findByRole("option", {
        name: /suggested for your country/i,
      }),
    ).toHaveValue("DE Lager");
    expect(offered()).toEqual([
      "DE Lager",
      "Simple",
      "PL Magazyn",
      "UK Warehouse",
      "Full Value",
    ]);
  });

  it("keeps the list as it is for a country with no preset", async () => {
    renderSelector("US");

    await screen.findAllByRole("option");
    expect(offered()).toEqual(PRESETS);
    expect(
      screen.queryByRole("option", { name: /suggested for your country/i }),
    ).toBeNull();
  });
});
