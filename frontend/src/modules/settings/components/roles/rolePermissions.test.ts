import { describe, expect, it } from "vitest";
import type {
  PermissionCatalog,
  PermissionDefinition,
  Role,
} from "@/modules/settings/hooks/useRoles";
import {
  groupState,
  invisiblePermissions,
  matchPermissions,
  permissionGroups,
  summarizeRole,
} from "./rolePermissions";

const perm = (key: string): PermissionDefinition => ({
  key,
  label_key: `permissions:${key}`,
  description_key: null,
  default_roles: [],
});

const CATALOG: PermissionCatalog = {
  system: [perm("items:read"), perm("items:write")],
  modules: [
    { module: "warehouse", permissions: [perm("warehouse:read")] },
    { module: "vision", permissions: [] },
  ],
};

const role = (permissions: string[]): Role => ({
  id: "r1",
  organization_id: "org-1",
  name: "Warehouse",
  permissions,
  is_system: false,
  created_at: null,
  member_count: 0,
});

describe("permissionGroups", () => {
  it("puts the system group first and one group per module", () => {
    expect(permissionGroups(CATALOG).map((g) => g.id)).toEqual([
      "system",
      "warehouse",
    ]);
  });

  it("drops a module that declares no permission", () => {
    // An empty accordion promises content that is not behind it.
    expect(permissionGroups(CATALOG).some((g) => g.id === "vision")).toBe(
      false,
    );
  });

  it("survives a catalog that has not loaded", () => {
    expect(permissionGroups(undefined)).toEqual([]);
  });
});

describe("groupState", () => {
  const [system] = permissionGroups(CATALOG);

  it("reports none, some and all", () => {
    expect(groupState(system, new Set())).toBe("none");
    expect(groupState(system, new Set(["items:read"]))).toBe("some");
    expect(groupState(system, new Set(["items:read", "items:write"]))).toBe(
      "all",
    );
  });
});

describe("summarizeRole", () => {
  const groups = permissionGroups(CATALOG);

  it("names the areas the role touches, in catalog order", () => {
    expect(
      summarizeRole(role(["warehouse:read", "items:read"]), groups),
    ).toEqual({ count: 2, areas: ["system", "warehouse"] });
  });

  it("counts every permission, including ones no group offers", () => {
    expect(summarizeRole(role(["items:read", "gone:key"]), groups).count).toBe(
      2,
    );
  });

  it("names nothing for a role that grants nothing", () => {
    expect(summarizeRole(role([]), groups).areas).toEqual([]);
  });
});

describe("invisiblePermissions", () => {
  const groups = permissionGroups(CATALOG);

  it("finds keys no group offers", () => {
    // A module was switched off. The editor has no checkbox for its keys, so
    // it must carry them: rebuilding the set from the visible boxes alone
    // would revoke access nobody touched.
    expect(
      invisiblePermissions(new Set(["items:read", "maker:write"]), groups),
    ).toEqual(["maker:write"]);
  });

  it("finds none when every key has a home", () => {
    expect(invisiblePermissions(new Set(["items:read"]), groups)).toEqual([]);
  });
});

describe("matchPermissions", () => {
  const permissions = [perm("items:read"), perm("warehouse:write")];
  const labelOf = (p: PermissionDefinition) =>
    p.key === "items:read" ? "View products" : "Manage documents";

  it("matches the label a reader sees", () => {
    expect(matchPermissions(permissions, "produc", labelOf)).toEqual([
      permissions[0],
    ]);
  });

  it("matches the raw key, for whoever thinks in keys", () => {
    expect(matchPermissions(permissions, "warehouse:", labelOf)).toEqual([
      permissions[1],
    ]);
  });

  it("returns everything for an empty or blank term", () => {
    expect(matchPermissions(permissions, "   ", labelOf)).toHaveLength(2);
  });
});
