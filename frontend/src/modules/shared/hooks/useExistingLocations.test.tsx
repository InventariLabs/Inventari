import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { useExistingLocations } from "./useExistingLocations";

const FLOOR = [
  { id: "home", name: "Home", parent_id: null },
  { id: "pantry", name: "Pantry", parent_id: "home" },
];

describe("useExistingLocations", () => {
  it("reads the top level and the level under the parent", async () => {
    serveLocations(FLOOR);
    const { result } = renderHook(() => useExistingLocations("home"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.rows.map((row) => row.name).sort()).toEqual([
        "Home",
        "Pantry",
      ]),
    );
    expect(result.current.topLevelTotal).toBe(1);
    expect(result.current.isError).toBe(false);
  });

  it("checks names against every place at the level, a module's own and archived ones included", async () => {
    // A location's name is unique among its siblings whoever owns them, so a
    // chip naming the equipment module's hidden "Server Room" is a name the
    // server refuses at the top level — and, as a first step with a place
    // inside it, hangs the new place in the module's room.
    serveLocations([
      ...FLOOR,
      {
        id: "server-room",
        name: "Server Room",
        parent_id: null,
        context_tag: "equipment",
      },
      {
        id: "old-workshop",
        name: "Workshop",
        parent_id: null,
        settings: { archived: true },
      },
      {
        id: "old-shelf",
        name: "Shelf",
        parent_id: "home",
        settings: { archived: true },
      },
    ]);
    const { result } = renderHook(() => useExistingLocations("home"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() =>
      expect(result.current.rows.map((row) => row.name).sort()).toEqual([
        "Home",
        "Pantry",
        "Server Room",
        "Shelf",
        "Workshop",
      ]),
    );
    // The count still answers for the list the wizard was opened from: the
    // one place at the top that list shows.
    expect(result.current.topLevelTotal).toBe(1);
  });

  it("is a failed read when the level under the parent failed, not a shorter list of names", async () => {
    serveLocations(FLOOR);
    server.use(
      http.get("/api/v1/locations", ({ request }) =>
        new URL(request.url).searchParams.has("parent_id")
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : undefined,
      ),
    );
    const { result } = renderHook(() => useExistingLocations("home"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
