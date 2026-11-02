import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { useSavedTileOrder, useTileOrder } from "./useTileOrder";

const KEY = "launcher_tile_order:default:current-user:business";

describe("useTileOrder", () => {
  beforeEach(() => {
    localStorage.clear();
    signInWith([]);
  });

  afterEach(() => signOut());

  it("moves a tile to its new place and remembers the arrangement", () => {
    const { result } = renderHook(() =>
      useTileOrder(["stock", "recipes", "labels"], "business"),
    );
    expect(result.current.order).toEqual(["stock", "recipes", "labels"]);

    act(() => result.current.reorder(0, 2));

    expect(result.current.order).toEqual(["recipes", "labels", "stock"]);
    expect(JSON.parse(localStorage.getItem(KEY) ?? "null")).toEqual([
      "recipes",
      "labels",
      "stock",
    ]);
  });

  it("starts from the arrangement saved on an earlier visit, and appends a new module", () => {
    const first = renderHook(() =>
      useTileOrder(["stock", "recipes", "labels"], "business"),
    );
    act(() => first.result.current.reorder(2, 0));
    first.unmount();

    const { result } = renderHook(() =>
      useTileOrder(["stock", "recipes", "labels", "stats"], "business"),
    );

    expect(result.current.order).toEqual([
      "labels",
      "stock",
      "recipes",
      "stats",
    ]);
  });

  it("keeps each section's arrangement apart from the others", () => {
    const { result } = renderHook(() =>
      useTileOrder(["stock", "recipes"], "business"),
    );
    act(() => result.current.reorder(0, 1));

    const other = renderHook(() =>
      useTileOrder(["stock", "recipes"], "analytics"),
    );

    expect(other.result.current.order).toEqual(["stock", "recipes"]);
  });
});

describe("useSavedTileOrder", () => {
  beforeEach(() => {
    localStorage.clear();
    signInWith([]);
  });

  afterEach(() => signOut());

  it("shows the grid the arrangement the desktop sections saved, without writing one", () => {
    localStorage.setItem(KEY, JSON.stringify(["recipes", "stock"]));
    const { result } = renderHook(() => useSavedTileOrder());

    expect(result.current(["stock", "recipes"], "business")).toEqual([
      "recipes",
      "stock",
    ]);
    expect(result.current(["stock", "recipes"], "analytics")).toEqual([
      "stock",
      "recipes",
    ]);
  });

  it("ignores a saved value that is not a list of names", () => {
    localStorage.setItem(KEY, JSON.stringify({ recipes: 1 }));
    const { result } = renderHook(() => useSavedTileOrder());

    expect(result.current(["stock", "recipes"], "business")).toEqual([
      "stock",
      "recipes",
    ]);
  });
});
