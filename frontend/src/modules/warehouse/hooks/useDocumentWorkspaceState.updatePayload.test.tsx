import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";

import { useDocumentWorkspaceState } from "./useDocumentWorkspaceState";
import type { WarehouseDocument } from "../types";

/**
 * The update payload spells "clear" as null, not as a key left out.
 *
 * The form turns an emptied input into an empty string, and the payload
 * builder used to turn that into `undefined` — JSON drops the key, the
 * server reads an absent key as "leave it alone", and the save answered
 * "updated" over a note that never changed (backend AGENTS.md §2b).
 * Both halves are pinned: emptied means null, still-held means itself.
 */
const draft = (patch: Partial<WarehouseDocument>): WarehouseDocument =>
  ({
    id: "doc-1",
    type: "IN",
    status: "DRAFT",
    partner_id: "partner-1",
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: "2026-04-01",
    notes: "kept unless emptied",
    external_reference: "REF-1",
    lines: [],
    ...patch,
  }) as unknown as WarehouseDocument;

const render = (document: WarehouseDocument) =>
  renderHook(() => useDocumentWorkspaceState({ initialType: "IN", document }));

describe("useDocumentWorkspaceState — the update payload", () => {
  it("sends a cleared field as null, not as a key that is missing", () => {
    const { result } = render(draft({}));

    act(() => {
      result.current.setNotes("");
      result.current.setPartnerId("");
      result.current.setScheduledDate("");
      result.current.setExternalReference("");
    });

    const payload = result.current.toUpdatePayload();

    expect(payload.notes).toBeNull();
    expect(payload.partner_id).toBeNull();
    expect(payload.scheduled_date).toBeNull();
    expect(payload.external_reference).toBeNull();
    // and the key is really there — `undefined` would vanish on the wire
    expect(Object.keys(payload)).toEqual(
      expect.arrayContaining([
        "notes",
        "partner_id",
        "scheduled_date",
        "external_reference",
      ]),
    );
  });

  it("keeps the values the user did not touch", () => {
    const { result } = render(draft({}));

    act(() => {
      result.current.setNotes("a new note");
    });

    const payload = result.current.toUpdatePayload();

    expect(payload.notes).toBe("a new note");
    expect(payload.partner_id).toBe("partner-1");
    expect(payload.target_location_id).toBe("loc-1");
    expect(payload.scheduled_date).toBe("2026-04-01");
  });
});
