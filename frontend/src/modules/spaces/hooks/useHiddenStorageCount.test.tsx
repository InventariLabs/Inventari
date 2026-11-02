import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useHiddenStorageCount } from "./useHiddenStorageCount";

const FLOOR = [
  { id: "a", name: "Kitchen" },
  { id: "b", name: "Garage" },
  { id: "c", name: "Server room", context_tag: "equipment" },
  ...Array.from({ length: 300 }, (_, i) => ({
    id: `rack-${i}`,
    name: `Rack ${i}`,
    context_tag: "equipment",
  })),
];

describe("useHiddenStorageCount", () => {
  it("counts what the policy keeps off the list from two totals, without reading the list", async () => {
    const requests = serveLocations(FLOOR);
    const { result } = renderHook(
      () => useHiddenStorageCount(true, false, false),
      {
        wrapper: QueryWrapper,
      },
    );

    await waitFor(() => expect(result.current).toBe(301));
    // Two one-row pages: the totals are the answer, the rows are not read.
    expect(requests).toHaveLength(2);
    expect(requests.every((r) => r.get("limit") === "1")).toBe(true);
    expect(requests.every((r) => r.get("counts") === "false")).toBe(true);
  });

  it("asks nothing when the organization shows module data, or while the reader filters", () => {
    const requests = serveLocations(FLOOR);
    renderHook(() => useHiddenStorageCount(false, false, false), {
      wrapper: QueryWrapper,
    });
    renderHook(() => useHiddenStorageCount(true, false, true), {
      wrapper: QueryWrapper,
    });

    expect(requests).toHaveLength(0);
  });
});

/**
 * Quiet on failure, so this is a behaviour document rather than teeth: a
 * failed probe leaves no list, which answers the same as no read at all —
 * the test passes either way. What it pins is the silence: the counter
 * claims no number it does not have, and the list beside it carries the
 * failure on its own.
 */
describe("useHiddenStorageCount — the probe failed", () => {
  it("reports nothing hidden instead of a count it does not have", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(
      () => useHiddenStorageCount(true, false, false),
      { wrapper: QueryWrapper },
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(result.current).toBe(0);
  });
});
