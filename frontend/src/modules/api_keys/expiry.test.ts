import { describe, expect, it } from "vitest";
import { isKeyExpired, liveKeysFirst } from "./expiry";
import type { ApiKey } from "./types";

const NOON = Date.parse("2026-08-26T12:00:00Z");

const key = (id: string, expiresAt: string | null): ApiKey => ({
  id,
  name: id,
  key_prefix: "inv_live_abcd",
  is_active: true,
  last_used_at: null,
  expires_at: expiresAt,
  created_at: "2026-08-01T10:00:00Z",
  created_by_email: null,
  permissions: [],
  scopes: [],
});

describe("isKeyExpired", () => {
  it("follows the instant the server refuses on, not the day", () => {
    // The server rejects at `now > expires_at`. A day-granularity check —
    // which is what the shared helper does, correctly, for food — would call
    // a key that lapsed this morning live until tomorrow.
    expect(isKeyExpired("2026-08-26T09:00:00Z", NOON)).toBe(true);
    expect(isKeyExpired("2026-08-26T15:00:00Z", NOON)).toBe(false);
  });

  it("treats the exact expiry instant as still valid, as the server does", () => {
    expect(isKeyExpired("2026-08-26T12:00:00Z", NOON)).toBe(false);
  });

  it("does not call a key without an expiry date expired", () => {
    expect(isKeyExpired(null, NOON)).toBe(false);
  });
});

describe("liveKeysFirst", () => {
  it("moves the lapsed keys to the end and keeps each group's order", () => {
    const ordered = liveKeysFirst(
      [
        key("dead-a", "2026-01-01T00:00:00Z"),
        key("live-a", null),
        key("dead-b", "2026-02-01T00:00:00Z"),
        key("live-b", "2099-01-01T00:00:00Z"),
      ],
      NOON,
    );

    expect(ordered.map((k) => k.id)).toEqual([
      "live-a",
      "live-b",
      "dead-a",
      "dead-b",
    ]);
  });
});
