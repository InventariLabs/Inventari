/**
 * The edge's 404 rules must spare every route and built file. These specs run
 * the gate over a scratch tree, so what is pinned is the sentence a red build
 * prints, and one reads the shipped config against the real route table.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { makeRepo, runGate } from "./gate-fixture.mjs";
import { blockedPaths, regexLocations } from "./check-edge-probes.mjs";
import { routePaths } from "./check-route-reachability.mjs";

const NGINX = `server {
    location ~ /\\.(?!well-known/) {
        return 404;
    }

    location ~* (?:\\.php|^/wp(?:-|/|$)|(?:\\.(?:bak|old|orig|save|swp)|~)$) {
        return 404;
    }

    location ~* \\.(js|css)$ {
        expires 1y;
    }
}
`;

const APP_TSX = `import { Route, Routes } from "react-router-dom";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Shell />}>
        <Route path="login" element={<Login />} />
      </Route>
    </Routes>
  );
}
`;

let repo;
afterEach(() => repo?.cleanup());

const run = (files) => {
  repo = makeRepo();
  repo.write({
    "frontend/nginx.conf": NGINX,
    "frontend/src/App.tsx": APP_TSX,
    "frontend/src/modules/.gitkeep": "",
    "frontend/dist/index.html": "<!doctype html>",
    "frontend/dist/assets/app.js": "export {};",
    ...files,
  });
  return runGate(repo, "check-edge-probes.mjs", {
    siblings: ["check-route-reachability.mjs", "source-text.mjs"],
  });
};

describe("check-edge-probes", () => {
  it("passes when the routes and the built files stay clear of the 404 rules", () => {
    const { status, stdout } = run({});

    expect(status).toBe(0);
    expect(stdout).toContain("2 404 rule(s)");
    expect(stdout).toContain("2 built file(s)");
  });

  it("fails when a route is covered by a 404 rule, and names the route", () => {
    const { status, stderr } = run({
      "frontend/src/App.tsx": APP_TSX.replace(
        '        <Route path="login" element={<Login />} />',
        '        <Route path="login" element={<Login />} />\n' +
          '        <Route path="wp-admin" element={<Admin />} />',
      ),
    });

    expect(status).toBe(1);
    expect(stderr).toContain("/wp-admin");
    expect(stderr).toContain("answered 404 by the edge");
  });

  it("fails when a built file is covered by a 404 rule, and names the file", () => {
    const { status, stderr } = run({
      "frontend/dist/backup/config.old": "keep me",
    });

    expect(status).toBe(1);
    expect(stderr).toContain("/backup/config.old");
  });

  it("leaves a path alone when an ordinary regex location answers it first", () => {
    const { status } = run({
      "frontend/nginx.conf": NGINX.replace(
        "    location ~* (?:",
        "    location ~* /wp-admin {\n" +
          "        expires 1y;\n" +
          "    }\n\n" +
          "    location ~* (?:",
      ),
      "frontend/src/App.tsx": APP_TSX.replace(
        '        <Route path="login" element={<Login />} />',
        '        <Route path="login" element={<Login />} />\n' +
          '        <Route path="wp-admin" element={<Admin />} />',
      ),
    });

    expect(status).toBe(0);
  });

  it("refuses a checkout with no 404 rule at all, rather than measure nothing", () => {
    const { status, stderr } = run({
      "frontend/nginx.conf":
        "server {\n    location / {\n        try_files $uri /index.html;\n    }\n}\n",
    });

    expect(status).toBe(1);
    expect(stderr).toContain("no regex location that answers 404");
  });

  it("refuses a checkout with no build, rather than measure nothing", () => {
    repo = makeRepo();
    repo.write({
      "frontend/nginx.conf": NGINX,
      "frontend/src/App.tsx": APP_TSX,
      "frontend/src/modules/.gitkeep": "",
    });
    const { status, stderr } = runGate(repo, "check-edge-probes.mjs", {
      siblings: ["check-route-reachability.mjs", "source-text.mjs"],
    });

    expect(status).toBe(1);
    expect(stderr).toContain("build first");
  });
});

describe("the shipped edge", () => {
  it("answers no route the application mounts with 404", () => {
    const nginx = readFileSync(
      resolve(import.meta.dirname, "../nginx.conf"),
      "utf8",
    );
    const routes = routePaths();

    // The route table is the one check-route-reachability reads; an empty or
    // shrunken list would make this test pass by measuring nothing.
    expect(routes.length).toBeGreaterThan(100);
    expect(blockedPaths(regexLocations(nginx), routes).blocked).toEqual([]);
  });
});
