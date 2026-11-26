import { describe, it, expect } from "vitest";
import type { CategoryDTO } from "@/types";
import { grocyCategoryMatches } from "./grocyCategoryMatches";

const POLISH: Record<string, string> = { "categories:codes.dairy": "Nabiał" };
const t = (key: string, opts?: Record<string, unknown>) =>
  POLISH[key] ?? String(opts?.defaultValue ?? key);

const dairy = { id: "c-dairy", name: "Dairy", code: "dairy" } as CategoryDTO;
const own = { id: "c-own", name: "Przetwory", code: null } as CategoryDTO;

describe("grocyCategoryMatches", () => {
  it("matches a group by the name the screen shows, not the stored one", () => {
    expect(
      grocyCategoryMatches(["Nabiał", " przetwory ", "Sery"], [dairy, own], t),
    ).toEqual({ Nabiał: "c-dairy", " przetwory ": "c-own" });
  });

  it("matches nothing while the categories have not arrived", () => {
    expect(grocyCategoryMatches(["Nabiał"], undefined, t)).toEqual({});
  });
});
