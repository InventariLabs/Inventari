import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { useLocationPicker } from "./useLocationPicker";

const shelf = {
  id: "loc-1",
  name: "Shelf A",
  full_path: "Pantry › Shelf A",
};

describe("useLocationPicker", () => {
  it("offers the places the server lists, with the way to each as its caption", async () => {
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json({ items: [shelf], total: 1 }),
      ),
    );

    const { result } = renderHook(() => useLocationPicker({}), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.options).toHaveLength(1));
    expect(result.current.options[0]).toMatchObject({
      id: "loc-1",
      name: "Shelf A",
      path: "Pantry",
    });
    expect(result.current.error).toBeNull();
    expect(result.current.total).toBe(1);
  });

  it("reports a failed read, then lists the places once the reader retries", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({ items: [shelf], total: 1 });
      }),
    );
    const { result } = renderHook(() => useLocationPicker({}), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.options).toEqual([]);

    act(() => result.current.retry());

    await waitFor(() => expect(result.current.options).toHaveLength(1));
    expect(result.current.error).toBeNull();
  });

  it("asks the server for what was typed instead of filtering a loaded page", async () => {
    const asked: Array<string | null> = [];
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("q"));
        return HttpResponse.json({ items: [shelf], total: 1 });
      }),
    );
    const { result } = renderHook(() => useLocationPicker({}), {
      wrapper: QueryWrapper,
    });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.setSearch("shelf"));
    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(asked).toContain("shelf"));
  });
});
