import React from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { QueryWrapper } from "@/test/queryWrapper";
import { withModules } from "@/test/moduleList";
import { ModulesProvider } from "@/contexts/ModulesContext";

import { useEquipmentStatusBadge } from "./useEquipmentStatusBadge";

function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryWrapper>
      <ModulesProvider>{children}</ModulesProvider>
    </QueryWrapper>
  );
}

beforeEach(() => {
  withModules("equipment");
});

/**
 * The launcher tile counts the warranty alerts of the overview it opens.
 * The failures caught: the tile asking its own window instead of reading the
 * overview's, counting something other than the alerts, or showing a zero
 * badge instead of none.
 */
describe("useEquipmentStatusBadge", () => {
  it("leaves the horizon to the module's settings, as the overview does", async () => {
    let days: string | null = "not asked";
    server.use(
      http.get("/api/v1/equipment/warranty-alerts", ({ request }) => {
        days = new URL(request.url).searchParams.get("days");
        return HttpResponse.json(onePage([{ id: "a" }, { id: "b" }]));
      }),
    );
    const { result } = renderHook(() => useEquipmentStatusBadge(), {
      wrapper,
    });

    await waitFor(() =>
      expect(result.current).toEqual({
        count: 2,
        labelKey: "equipment:statusBadge.warrantyAlerts",
      }),
    );
    expect(days).toBeNull();
  });

  it("shows no badge while nothing is running out", async () => {
    let asked = false;
    server.use(
      http.get("/api/v1/equipment/warranty-alerts", () => {
        asked = true;
        return HttpResponse.json(onePage([]));
      }),
    );
    const { result } = renderHook(() => useEquipmentStatusBadge(), {
      wrapper,
    });

    await waitFor(() => expect(asked).toBe(true));
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current).toBeNull();
  });
});
