import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  readJson,
  readSessionJson,
  writeJson,
  writeSessionJson,
} from "../localStorage";

describe("the session pair", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });

  it("round-trips a value within the tab's session", () => {
    writeSessionJson("probe:key", "loc-1");
    expect(readSessionJson("probe:key", "fallback")).toBe("loc-1");
  });

  it("answers the fallback for a missing key", () => {
    expect(readSessionJson("probe:missing", "fallback")).toBe("fallback");
  });

  it("answers the fallback for a corrupted value instead of throwing", () => {
    sessionStorage.setItem("probe:key", "{not json");
    expect(readSessionJson("probe:key", "fallback")).toBe("fallback");
  });

  it("keeps session and local stores apart under one key", () => {
    writeSessionJson("probe:key", "session-value");
    writeJson("probe:key", "local-value");
    expect(readSessionJson("probe:key", "")).toBe("session-value");
    expect(readJson("probe:key", "")).toBe("local-value");
  });

  it("survives a storage that refuses writes", () => {
    const spy = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("quota");
      });
    expect(() => writeSessionJson("probe:key", "loc-1")).not.toThrow();
    expect(readSessionJson("probe:key", "fallback")).toBe("fallback");
    spy.mockRestore();
  });
});
