/**
 * The manifest shorthand used to slip past the drift gate: a permission
 * written as `"stats:export"` carries no `label_key` field, so the extractor
 * that looks for `*_key` values never saw it. The screen then rendered the raw
 * key and nothing reported the missing translation.
 */
import { describe, expect, it } from "vitest";

import { shorthandPermissionKeys } from "./manifest-permission-keys.mjs";

describe("shorthandPermissionKeys", () => {
  it("expands a bare string the way the backend does", () => {
    expect(shorthandPermissionKeys(["stats:export"], "stats")).toEqual([
      "stats:permissions.export",
    ]);
  });

  it("joins a multi-segment action with an underscore", () => {
    expect(
      shorthandPermissionKeys(["nutrition:scan:barcode"], "nutrition"),
    ).toEqual(["nutrition:permissions.scan_barcode"]);
  });

  it("ignores a full object — its label_key is collected already", () => {
    expect(
      shorthandPermissionKeys(
        [{ key: "stats:read", label_key: "stats:permissions.read" }],
        "stats",
      ),
    ).toEqual([]);
  });

  it("ignores a core key a module merely depends on", () => {
    // recipes names items:read to say what it reads; the backend keeps that
    // out of the module's catalog section, so no module translation is owed.
    expect(shorthandPermissionKeys(["items:read"], "recipes")).toEqual([]);
  });
});
