import { describe, expect, it } from "vitest";
import { settingsRoutePermission } from "./settingsAccess";

describe("settingsRoutePermission", () => {
  it("lets every member reach the general section", () => {
    expect(settingsRoutePermission("/settings")).toBeNull();
    expect(settingsRoutePermission("/settings/")).toBeNull();
  });

  it("lets every member read the licence and the source link", () => {
    // AGPL-3.0 §13 offers the source to every user, not to administrators.
    expect(settingsRoutePermission("/settings/about")).toBeNull();
  });

  it("lets every member manage their own profile", () => {
    expect(settingsRoutePermission("/settings/profile")).toBeNull();
  });

  it.each([
    "/settings/my-modules",
    "/settings/modules",
    "/settings/email",
    "/settings/audit-log",
    // Module-contributed sections land here too.
    "/settings/webhooks",
  ])("keeps %s for administrators", (path) => {
    expect(settingsRoutePermission(path)).toBe("admin:access");
  });

  it("opens the AI connections with the key their writes ask for", () => {
    // The API refuses those writes without `org:settings:write` and lets a
    // custom role holding it make them; the screen asked for `admin:access`
    // instead, so the grant could only be used through the API.
    expect(settingsRoutePermission("/settings/ai")).toBe("org:settings:write");
  });

  it("opens the role catalogue with the key its whole API asks for", () => {
    expect(settingsRoutePermission("/settings/roles")).toBe(
      "system:config:write",
    );
  });

  it("opens a module's section with the key the module names", () => {
    const sections = [
      { path: "api-keys", permission: "org:settings:write" },
      { path: "modules/approvals" },
    ];

    expect(settingsRoutePermission("/settings/api-keys", sections)).toBe(
      "org:settings:write",
    );
    // A section that names no key stays with the default, and a two-segment
    // section path does not lend its answer to the parent route it sits in.
    expect(
      settingsRoutePermission("/settings/modules/approvals", sections),
    ).toBe("admin:access");
    expect(
      settingsRoutePermission("/settings/modules/equipment", sections),
    ).toBe("admin:access");
  });

  it("makes a child route inherit its parent's answer", () => {
    // `/settings/modules/:name` had no guard of its own and walked past the
    // one its parent never had either.
    expect(settingsRoutePermission("/settings/modules/equipment")).toBe(
      "admin:access",
    );
    expect(settingsRoutePermission("/settings/ai/anything")).toBe(
      "org:settings:write",
    );
  });

  it("protects a settings screen nobody has classified yet", () => {
    expect(settingsRoutePermission("/settings/something-new")).toBe(
      "admin:access",
    );
  });
});
