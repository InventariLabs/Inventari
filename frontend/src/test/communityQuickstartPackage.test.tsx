import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18next from "i18next";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement, type ComponentType } from "react";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { typecheckScratch } from "./typecheckScratch";

/**
 * The frontend half of the community quickstart's Path B, as written.
 *
 * MODULE_QUICKSTART.md gives the package a list screen: types, a query hook
 * and a page, each in a block preceded by
 * `<!-- quickstart-package: <file> replace -->`. Path B once pointed at Path
 * A's steps instead, whose page calls an endpoint the generated package does
 * not have, and the pasted page ended in "An error occurred". The backend half
 * (the list endpoint) is tested by
 * backend/tests/integration/test_the_community_quickstarts_package_steps_work.py.
 *
 * Here the blocks are written to a scratch directory inside the frontend (a
 * file outside it cannot resolve `react` or `@/module-sdk`), type-checked with
 * the project's own compiler settings, and the page is rendered against an
 * empty list.
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "../..");
const REPO_ROOT =
  process.env.INVENTARI_REPO_ROOT ?? path.resolve(FRONTEND, "..");
const SCRATCH = path.join(FRONTEND, ".quickstart-package");

const BLOCK =
  /<!-- quickstart-package: (frontend\/\S+) (replace|merge) -->\s*```\w+\n([\s\S]*?)\n```/g;

function documentedFiles(): Map<string, string> {
  const document = fs.readFileSync(
    path.join(REPO_ROOT, "MODULE_QUICKSTART.md"),
    "utf8",
  );
  return new Map(
    [...document.matchAll(BLOCK)].map((m) => [
      m[1].slice("frontend/".length),
      m[3],
    ]),
  );
}

const files = documentedFiles();
const SOURCES = [
  "types/index.ts",
  "hooks/useRecords.ts",
  "pages/IndexPage.tsx",
];

beforeAll(() => {
  fs.rmSync(SCRATCH, { recursive: true, force: true });
  for (const name of SOURCES) {
    const target = path.join(SCRATCH, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, `${files.get(name)}\n`);
  }
});

afterAll(() => {
  fs.rmSync(SCRATCH, { recursive: true, force: true });
});

describe("community quickstart, Path B: the screen", () => {
  it("documents every file of the screen", () => {
    expect([...files.keys()]).toEqual(
      expect.arrayContaining([...SOURCES, "i18n/en.json"]),
    );
  });

  it("type-checks as written", () => {
    expect(typecheckScratch(FRONTEND, SCRATCH, SOURCES)).toEqual([]);
  }, 120_000);

  it("draws a title and says so when the list is empty", async () => {
    vi.doMock("@/lib/api/client", async (importOriginal) => {
      const original =
        await importOriginal<typeof import("@/lib/api/client")>();
      return {
        ...original,
        api: {
          ...original.api,
          get: vi.fn().mockResolvedValue({
            data: { items: [], total: 0, has_more: false },
          }),
        },
      };
    });
    const page = (await import(
      /* @vite-ignore */ path.join(SCRATCH, "pages/IndexPage.tsx")
    )) as { default: ComponentType };
    const catalog = {
      title: "Warranty Tracker",
      description: "Warranty Tracker module.",
      ...(JSON.parse(files.get("i18n/en.json")!) as Record<string, string>),
    };
    i18next.addResourceBundle("en", "warranty_tracker", catalog, true, true);

    const setHeader = vi.fn();
    render(
      createElement(
        PageHeaderContext.Provider,
        { value: { data: {}, setHeader } },
        createElement(
          QueryClientProvider,
          {
            client: new QueryClient({
              defaultOptions: { queries: { retry: false } },
            }),
          },
          createElement(page.default),
        ),
      ),
    );

    expect(await screen.findByText("Nothing here yet.")).toBeInTheDocument();
    expect(screen.queryByText(/error occurred/i)).not.toBeInTheDocument();
    expect(setHeader).toHaveBeenCalledWith(
      expect.objectContaining({ title: "Warranty Tracker" }),
    );
  });
});
