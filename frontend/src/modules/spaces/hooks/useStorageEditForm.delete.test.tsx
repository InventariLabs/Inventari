import React from "react";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useStorageEditForm } from "./useStorageEditForm";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation, StorageLocationSummary } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const confirmMock = vi.hoisted(() => vi.fn().mockResolvedValue(false));

vi.mock("@/hooks/useConfirm", () => ({
  useConfirm: () => ({ confirm: confirmMock, confirmDialogProps: {} }),
}));

const storage = {
  id: "s1",
  user_id: "u1",
  location_type_id: null,
  parent_id: null,
  name: "Cold Storage",
  description: null,
  location_details: null,
  settings: null,
  created_at: "2026-01-01T00:00:00Z",
  context_schema: [],
  behavior_mode: "STOCK",
  field_definitions: [],
  context_tag: null,
} as unknown as StorageLocation;

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider
    client={
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
    }
  >
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

const renderForm = (rows: StorageLocationSummary[]) =>
  renderHook(
    () =>
      useStorageEditForm(
        true,
        storage,
        rows.find((row) => row.id === storage.id),
        vi.fn(),
        vi.fn(),
      ),
    { wrapper },
  );

const askedMessage = () => {
  expect(confirmMock).toHaveBeenCalled();
  const options = confirmMock.mock.calls[0][0] as { message: string };
  return options.message;
};

/**
 * Deleting a location that parents a subtree is a tree rebuild: the children
 * move up a level and every record standing inside them changes its place.
 * The spaces sheet used to ask about it as if only the location itself were
 * at stake, while the equipment screen — over the same core rows — named
 * both numbers. One operation, one sentence: the consequences now come from
 * the shared `locations:edit.…` keys on both screens.
 */
describe("the delete question names what the tree loses", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names the child locations and the records standing below them", async () => {
    const { result } = renderForm([
      makeStorageSummary({
        id: "s1",
        name: "Cold Storage",
        direct_children_count: 2,
        // The two counts differ exactly when the reader cannot see every
        // descendant: a module claimed it, or it is archived. The dialog
        // must read the full-tree total — the fold over the visible rows
        // would undersell the consequence.
        subtree_items_count: 1,
        total_subtree_items_count: 4,
      }),
    ]);

    await act(async () => {
      await result.current.handleDelete();
    });

    const message = askedMessage();
    expect(message).toContain("Cold Storage");
    expect(message).toContain("2 child locations move up a level");
    expect(message).toContain("4 records move up a level");
    expect(message).not.toContain("1 record");
  });

  it("says how many of what moves this list does not show", async () => {
    // An archived child and the records of another module's places are
    // lifted with the rest, so they stay in the numbers; the reader is told
    // they are not among the rows on screen rather than left to find a
    // child or a record the list never showed.
    const { result } = renderForm([
      makeStorageSummary({
        id: "s1",
        name: "Cold Storage",
        direct_children_count: 2,
        listed_children_count: 1,
        subtree_items_count: 1,
        total_subtree_items_count: 4,
      }),
    ]);

    await act(async () => {
      await result.current.handleDelete();
    });

    const message = askedMessage();
    expect(message).toContain(
      "2 child locations move up a level. 1 of them is not shown on this list.",
    );
    expect(message).toContain(
      "4 records move up a level. 3 of them are not shown on this list.",
    );
  });

  it("adds nothing when the list shows everything that moves", async () => {
    const { result } = renderForm([
      makeStorageSummary({
        id: "s1",
        name: "Cold Storage",
        direct_children_count: 2,
        listed_children_count: 2,
        subtree_items_count: 4,
        total_subtree_items_count: 4,
      }),
    ]);

    await act(async () => {
      await result.current.handleDelete();
    });

    expect(askedMessage()).not.toContain("not shown");
  });

  it("keeps the singular form for the one child, for the one record", async () => {
    const { result } = renderForm([
      makeStorageSummary({
        id: "s1",
        name: "Cold Storage",
        direct_children_count: 1,
        subtree_items_count: 7,
        total_subtree_items_count: 1,
      }),
    ]);

    await act(async () => {
      await result.current.handleDelete();
    });

    const message = askedMessage();
    expect(message).toContain("1 child location moves up a level");
    expect(message).toContain("1 record moves up a level");
    expect(message).not.toContain("7 records");
  });

  it("says nothing about a tree with nothing under it", async () => {
    const { result } = renderForm([
      makeStorageSummary({ id: "s1", name: "Cold Storage" }),
    ]);

    await act(async () => {
      await result.current.handleDelete();
    });

    const message = askedMessage();
    expect(message).not.toContain("up a level");
  });

  it("invents no number when the caller handed over no row for it", async () => {
    // `?? 0` bridges a missing row by omitting the sentence; a number the
    // server never counted would be worse than either silence or a refusal.
    const { result } = renderForm([]);

    await act(async () => {
      await result.current.handleDelete();
    });

    const message = askedMessage();
    expect(message).not.toContain("child location");
    expect(message).not.toContain("change their place");
  });
});
