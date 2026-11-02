import { beforeEach, describe, expect, it } from "vitest";
import {
  readLastUsedLocations,
  rememberLastUsedLocations,
} from "./lastUsedLocations";

describe("lastUsedLocations", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns an empty map when nothing was stored", () => {
    expect(readLastUsedLocations()).toEqual({});
  });

  it("round-trips source and target per document type", () => {
    rememberLastUsedLocations("IN", "", "loc-target");
    rememberLastUsedLocations("OUT", "loc-source", "");

    const map = readLastUsedLocations();
    expect(map.IN).toEqual({ target: "loc-target" });
    expect(map.OUT).toEqual({ source: "loc-source" });
  });

  it("overwrites the entry for the same document type", () => {
    rememberLastUsedLocations("IN", "", "loc-a");
    rememberLastUsedLocations("IN", "", "loc-b");
    expect(readLastUsedLocations().IN).toEqual({ target: "loc-b" });
  });

  it("does not store anything when both locations are empty", () => {
    rememberLastUsedLocations("INT", "", "");
    expect(readLastUsedLocations()).toEqual({});
  });

  it("returns an empty map for corrupted storage", () => {
    localStorage.setItem("warehouse:lastUsedLocations", "{not json");
    expect(readLastUsedLocations()).toEqual({});
  });
});
