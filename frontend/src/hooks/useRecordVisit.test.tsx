import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderHook } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { getRecentItems, RECENT_ITEMS_SCOPE } from "@/lib/recentItems";
import { signInWith, signOut } from "@/test/auth";
import { useRecordVisit, type VisitedRecord } from "./useRecordVisit";

const recent = () => getRecentItems("current-user", RECENT_ITEMS_SCOPE);

function at(path: string) {
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  );
}

const RICE = { id: "item-1", name: "Arborio rice" };

describe("useRecordVisit", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => signOut());

  it("puts the record a page shows at the top of the person's list", () => {
    signInWith([]);
    renderHook(
      () => useRecordVisit("recipes", { id: "recipe-1", name: "Risotto" }),
      { wrapper: at("/recipes/recipe-1") },
    );
    renderHook(() => useRecordVisit("inventory", RICE), {
      wrapper: at("/inventory/items/item-1"),
    });

    expect(recent().map((item) => item.title)).toEqual([
      "Arborio rice",
      "Risotto",
    ]);
    expect(recent()[0]).toMatchObject({
      id: "item-1",
      title: "Arborio rice",
      module: "inventory",
      path: "/inventory/items/item-1",
    });
  });

  it("records nothing before the record has loaded", () => {
    signInWith([]);
    renderHook(() => useRecordVisit("inventory", undefined), {
      wrapper: at("/inventory/items/item-1"),
    });
    expect(recent()).toEqual([]);
  });

  it("keeps one entry per record, under the name it has now", () => {
    signInWith([]);
    const { rerender } = renderHook(
      ({ record }: { record: VisitedRecord }) =>
        useRecordVisit("inventory", record),
      {
        initialProps: { record: RICE },
        wrapper: at("/inventory/items/item-1"),
      },
    );
    rerender({ record: { ...RICE, name: "Carnaroli rice" } });

    expect(recent().map((item) => item.title)).toEqual(["Carnaroli rice"]);
  });

  it("records nothing for nobody signed in", () => {
    renderHook(() => useRecordVisit("inventory", RICE), {
      wrapper: at("/inventory/items/item-1"),
    });
    expect(localStorage.length).toBe(0);
  });
});
