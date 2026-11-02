import { describe, it, expect, vi } from "vitest";
import { Package } from "lucide-react";

import type { FrontendModule } from "./moduleInterfaces";
import { shellRoutes } from "./shellRoutes";
import { moduleRegistry } from "./registry";

const Screen = () => null;

const host: FrontendModule = {
  name: "host",
  moduleNav: {
    basePath: "/host",
    items: [{ path: "/host/places", icon: Package, labelKey: "x" }],
  },
  routes: [{ path: "/host", component: Screen, index: true }],
} as FrontendModule;

const guest: FrontendModule = {
  name: "guest",
  routes: [
    { path: "/host/places", component: Screen, shell: "host" },
    { path: "/guest", component: Screen },
  ],
} as FrontendModule;

describe("shellRoutes", () => {
  it("mounts a route naming another module's shell among that shell's routes", () => {
    const { shellModules, flatRoutes } = shellRoutes([host, guest]);

    expect(shellModules).toHaveLength(1);
    expect(shellModules[0].routes.map((r) => r.path)).toEqual([
      "/host",
      "/host/places",
    ]);
    expect(flatRoutes.map((r) => r.path)).toEqual(["/guest"]);
  });

  it("mounts the hosted route nowhere while its host is off", () => {
    const { shellModules, flatRoutes } = shellRoutes([guest]);

    expect(shellModules).toEqual([]);
    expect(flatRoutes.map((r) => r.path)).toEqual(["/guest"]);
  });
});

describe("warnOrphanedNav", () => {
  it("counts a route another module hosts in the shell, whichever registered first", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    moduleRegistry.register({ ...host, name: "shell-host-a" });
    moduleRegistry.register({
      ...guest,
      name: "shell-guest-a",
      routes: [
        { path: "/host/places", component: Screen, shell: "shell-host-a" },
      ],
    });
    moduleRegistry.warnOrphanedNav(["shell-host-a", "shell-guest-a"]);
    expect(warn).not.toHaveBeenCalled();

    moduleRegistry.register({ ...host, name: "shell-host-b" });
    moduleRegistry.warnOrphanedNav(["shell-host-b"]);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining('"shell-host-b" has moduleNav items'),
    );
    warn.mockRestore();
  });
});
