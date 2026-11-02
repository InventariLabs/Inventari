#!/usr/bin/env node
// Make a server default read as "optional" in the generated request types.
//
// FastAPI writes `default: x` on a field the caller may leave out, and
// openapi-typescript (defaultNonNullable, its default) reads a default as
// "always present" — right for a response, wrong for a request body, where it
// made every caller spell out `sort_order`, `is_default`, `scope_type`… (the
// `WithServerDefaults` helper in types/request.ts worked around it per call
// site). A schema reachable only from request bodies and parameters is never
// read back from the server, so its defaults are dropped before generating:
// the field stays in the schema as not required, which is what the API
// accepts. A schema a response also returns keeps its defaults and gets a
// twin, `<Name>Input`, without them; the request side points at the twin, so a
// nested shared schema (a workflow's stages, say) is optional on the way in
// and complete on the way out. A response value is still assignable to the
// twin, so no consumer of a response type changes.
//
// Filter: reads an OpenAPI document on stdin, writes the adjusted one.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function reachable(schemas, roots) {
  const seen = new Set();
  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (node && typeof node === "object") {
      for (const [key, value] of Object.entries(node)) {
        if (key === "$ref" && typeof value === "string") {
          const name = value.split("/").pop();
          if (!seen.has(name)) {
            seen.add(name);
            walk(schemas[name]);
          }
        } else {
          walk(value);
        }
      }
    }
  };
  walk(roots);
  return seen;
}

export function dropRequestOnlyDefaults(document) {
  const schemas = document.components?.schemas ?? {};
  const requests = [];
  const responses = [];
  for (const item of Object.values(document.paths ?? {})) {
    for (const operation of Object.values(item)) {
      if (operation.requestBody) requests.push(operation.requestBody);
      if (operation.parameters) requests.push(operation.parameters);
      if (operation.responses) responses.push(operation.responses);
    }
  }
  const inResponse = reachable(schemas, responses);
  const resolved = new Map();

  // The name a request-side reference should point at, preparing the schema
  // (or its twin) behind it on first use.
  const requestName = (name) => {
    if (resolved.has(name)) return resolved.get(name);
    let target = name;
    // A schema with no default and no reference (an enum) has nothing to drop.
    const text = JSON.stringify(schemas[name]);
    if (inResponse.has(name) && (text.includes('"default"') || text.includes('"$ref"'))) {
      target = `${name}Input`;
      if (target in schemas) throw new Error(`${target} already exists in the schema`);
      schemas[target] = structuredClone(schemas[name]);
    }
    resolved.set(name, target);
    for (const property of Object.values(schemas[target]?.properties ?? {})) {
      delete property.default;
    }
    repoint(schemas[target]);
    return target;
  };
  const repoint = (node) => {
    if (Array.isArray(node)) {
      node.forEach(repoint);
    } else if (node && typeof node === "object") {
      for (const [key, value] of Object.entries(node)) {
        if (key === "$ref" && typeof value === "string") {
          node[key] = `#/components/schemas/${requestName(value.split("/").pop())}`;
        } else {
          repoint(value);
        }
      }
    }
  };
  repoint(requests);
  return document;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const document = JSON.parse(readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify(dropRequestOnlyDefaults(document)));
}
