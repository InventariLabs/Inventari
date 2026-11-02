import { describe, it, expect } from "vitest";

import { dropRequestOnlyDefaults } from "./openapi-request-defaults.mjs";

const ref = (name) => ({ $ref: `#/components/schemas/${name}` });
const json = (schema) => ({ content: { "application/json": { schema } } });

const document = () => ({
  paths: {
    "/things": {
      post: {
        requestBody: json(ref("ThingCreate")),
        responses: { 200: json(ref("Thing")) },
      },
    },
    "/echo": {
      post: {
        requestBody: json(ref("Shared")),
        responses: { 200: json(ref("Shared")) },
      },
    },
  },
  components: {
    schemas: {
      ThingCreate: {
        type: "object",
        properties: {
          name: { type: "string" },
          sort_order: { type: "integer", default: 0 },
          tags: { type: "array", items: ref("Tag") },
        },
      },
      Tag: { type: "object", properties: { color: { type: "string", default: "red" } } },
      Thing: { type: "object", properties: { sort_order: { type: "integer", default: 0 } } },
      Shared: { type: "object", properties: { flag: { type: "boolean", default: false } } },
    },
  },
});

describe("dropRequestOnlyDefaults", () => {
  it("drops the defaults of a schema only requests use, nested ones included", () => {
    const { schemas } = dropRequestOnlyDefaults(document()).components;
    expect(schemas.ThingCreate.properties.sort_order).toEqual({ type: "integer" });
    expect(schemas.Tag.properties.color).toEqual({ type: "string" });
  });

  it("keeps the defaults of a schema a response also returns", () => {
    const { schemas } = dropRequestOnlyDefaults(document()).components;
    expect(schemas.Thing.properties.sort_order.default).toBe(0);
    expect(schemas.Shared.properties.flag.default).toBe(false);
  });

  it("points the request side of a shared schema at a twin without defaults", () => {
    const doc = dropRequestOnlyDefaults(document());
    expect(doc.paths["/echo"].post.requestBody.content["application/json"].schema).toEqual(
      ref("SharedInput"),
    );
    expect(doc.paths["/echo"].post.responses[200].content["application/json"].schema).toEqual(
      ref("Shared"),
    );
    expect(doc.components.schemas.SharedInput.properties.flag).toEqual({ type: "boolean" });
  });

  it("makes a nested shared schema optional inside a request-only body", () => {
    const doc = document();
    doc.components.schemas.ThingCreate.properties.tags.items = ref("Shared");
    const { schemas } = dropRequestOnlyDefaults(doc).components;
    expect(schemas.ThingCreate.properties.tags.items).toEqual(ref("SharedInput"));
    expect(schemas.Shared.properties.flag.default).toBe(false);
  });

  it("leaves a shared schema with nothing to drop alone", () => {
    const doc = document();
    doc.components.schemas.Kind = { type: "string", enum: ["a", "b"] };
    doc.components.schemas.ThingCreate.properties.kind = ref("Kind");
    doc.components.schemas.Thing.properties.kind = ref("Kind");
    const { schemas } = dropRequestOnlyDefaults(doc).components;
    expect(schemas.ThingCreate.properties.kind).toEqual(ref("Kind"));
    expect(schemas.KindInput).toBeUndefined();
  });

  it("reads parameters as requests too", () => {
    const doc = document();
    doc.paths["/q"] = {
      get: {
        parameters: [{ name: "f", in: "query", schema: ref("Filter") }],
        responses: { 200: json({ type: "string" }) },
      },
    };
    doc.components.schemas.Filter = {
      type: "object",
      properties: { limit: { type: "integer", default: 50 } },
    };
    expect(dropRequestOnlyDefaults(doc).components.schemas.Filter.properties.limit).toEqual({
      type: "integer",
    });
  });
});
