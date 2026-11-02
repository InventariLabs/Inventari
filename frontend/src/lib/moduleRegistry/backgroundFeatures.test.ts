import { describe, expect, it } from "vitest";
import { RegistryQueries } from "./registryQueries";
import type { FrontendModule } from "./moduleInterfaces";

const Panel = () => null;
const declaration = {
  provider: "inventory",
  feature: "stock",
  labelKey: "recipes:background.pantry",
};
const modules = new Map<string, FrontendModule>([
  [
    "inventory",
    { name: "inventory", routes: [], backgroundFeatures: { stock: Panel } },
  ],
  [
    "consumer",
    {
      name: "consumer",
      routes: [],
      standalone: {
        coreSections: {
          labels: "renounce",
          scan: "renounce",
          stats: "renounce",
          stock_takes: "renounce",
          archive: "renounce",
        },
        backgroundFeatures: [declaration],
      },
    },
  ],
  ["plain", { name: "plain", routes: [] }],
]);
const queries = new RegistryQueries(modules, new Map(), new Map());

describe("background features", () => {
  it("resolves only declared features whose provider is enabled", () => {
    expect(queries.getBackgroundFeatures("consumer", ["inventory"])).toEqual([
      { ...declaration, component: Panel },
    ]);
    expect(queries.getBackgroundFeatures("consumer", [])).toEqual([]);
  });
  it("gives a module with no declaration no background features", () => {
    expect(queries.getBackgroundFeatures("plain", ["inventory"])).toEqual([]);
  });
});
