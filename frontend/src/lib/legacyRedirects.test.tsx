import { describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  createMemoryRouter,
  RouterProvider,
  Route,
  createRoutesFromElements,
  useLocation,
} from "react-router-dom";
import {
  LEGACY_REDIRECTS,
  LEGACY_SETTINGS_REDIRECTS,
  LegacyRedirectTo,
} from "./legacyRedirects";

function Where() {
  const { pathname, search, hash } = useLocation();
  return <p data-testid="where">{`${pathname}${search}${hash}`}</p>;
}

/** Mounts the table the way App does and reports where `start` ends up. */
function landing(start: string): string {
  const router = createMemoryRouter(
    createRoutesFromElements(
      <>
        {LEGACY_REDIRECTS.map((a) => (
          <Route
            key={a.from}
            path={a.from}
            element={<LegacyRedirectTo {...a} />}
          />
        ))}
        <Route path="settings">
          {LEGACY_SETTINGS_REDIRECTS.map((a) => (
            <Route
              key={a.from}
              path={a.from}
              element={<LegacyRedirectTo {...a} />}
            />
          ))}
        </Route>
        <Route path="*" element={<Where />} />
      </>,
    ),
    { initialEntries: [start] },
  );
  render(<RouterProvider router={router} />);
  const where = screen.getByTestId("where").textContent ?? "";
  cleanup();
  return where;
}

describe("legacy redirect table", () => {
  it.each([
    ["/webhooks", "/settings/webhooks"],
    ["/items/add", "/inventory/items/add"],
    ["/items/abc%20d", "/inventory/items/abc%20d"],
    ["/categories", "/inventory/categories"],
    ["/storages", "/inventory/locations"],
    ["/storages/42", "/inventory/locations/42"],
    ["/labels", "/inventory/labels"],
    ["/stats", "/inventory/stats"],
    ["/stats/inventory", "/inventory/stats"],
    ["/stats/analytics", "/inventory/stats/analytics"],
    ["/stock-takes", "/inventory/stock-takes"],
    ["/stock-takes/7/counting", "/inventory/stock-takes/7/counting"],
    ["/settings/workspace", "/settings/my-modules"],
    ["/settings/focus", "/settings/my-modules"],
    ["/settings/modules", "/apps"],
    ["/settings/developer", "/settings/ai"],
  ])("%s lands on %s", (from, to) => {
    expect(landing(from)).toBe(to);
  });

  it("keeps the query string and hash where the address is a filter", () => {
    expect(landing("/items?location_id=X#top")).toBe(
      "/inventory/items?location_id=X#top",
    );
    expect(landing("/scan?code=abc")).toBe("/inventory/scan?code=abc");
  });

  it("drops them where the address carries none", () => {
    expect(landing("/categories?x=1")).toBe("/inventory/categories");
  });

  it("opens the scanner with a printed label's code, slashes kept", () => {
    expect(landing("/s/IN/2026/0001")).toBe(
      `/inventory/scan?code=${encodeURIComponent("IN/2026/0001")}`,
    );
  });

  it("has one row per address", () => {
    const froms = [...LEGACY_REDIRECTS, ...LEGACY_SETTINGS_REDIRECTS].map(
      (r) => r.from,
    );
    expect(new Set(froms).size).toBe(froms.length);
  });
});
