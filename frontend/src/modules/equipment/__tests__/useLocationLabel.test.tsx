import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useLocationLabel } from "../hooks/useLocationLabel";

/**
 * The detail payload carries an id and no name, so this is the lookup a card
 * needs to say where a record is. It no longer translates anything: a seeded
 * location is written in the reader's language, so the stored name is the
 * answer on every surface — including the ones no React component renders.
 *
 * It names the places the screen holds, by id: a warehouse of two thousand
 * shelves is never downloaded to label one asset.
 */
describe("useLocationLabel", () => {
  it("answers with the stored name for a known id", async () => {
    serveLocations([
      { id: "loc-server-room", name: "Serwerownia" },
      { id: "loc-renamed", name: "Serwerownia B2" },
    ]);
    const { result } = renderHook(() => useLocationLabel(["loc-server-room"]), {
      wrapper: QueryWrapper,
    });
    await waitFor(() =>
      expect(result.current("loc-server-room", "ignored fallback")).toBe(
        "Serwerownia",
      ),
    );
  });

  it("falls back to the payload name for an unknown id, and to null", async () => {
    const requests = serveLocations([{ id: "loc-a", name: "Serwerownia" }]);
    const { result } = renderHook(() => useLocationLabel(["loc-gone"]), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(result.current("loc-gone", "Old Name")).toBe("Old Name");
    expect(result.current(null, null)).toBeNull();
  });

  it("asks for the places on screen and nothing else", async () => {
    const requests = serveLocations(
      Array.from({ length: 2000 }, (_, i) => ({
        id: `s${i}`,
        name: `Rack ${i}`,
      })),
    );
    const { result } = renderHook(() => useLocationLabel(["s1999", "s7"]), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current("s1999", null)).toBe("Rack 1999"),
    );
    expect(requests).toHaveLength(1);
    expect(requests[0].getAll("ids").sort()).toEqual(["s1999", "s7"]);
  });
});
