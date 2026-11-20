import { describe, expect, it } from "vitest";

import {
  loadingWithoutFailureIn,
  pagedEmptyIn,
  unguardedClaimsIn,
  unreadErrorsIn,
} from "./check-query-error-read.mjs";

/**
 * The gate flags a defaulted query result whose error the same destructuring
 * never takes. These cases pin both directions: the shapes that must fire,
 * and the ones that must not, so every finding is a real gap.
 */

const rel = "modules/things/pages/ThingsPage.tsx";

describe("check-query-error-read", () => {
  it("fires on a data default with no error read", () => {
    expect(
      unreadErrorsIn(rel, "const { data: things = [] } = useThings();"),
    ).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("fires on a default applied at the use", () => {
    const source = [
      "const { data: page } = useThings();",
      "const total = page?.total ?? 0;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("fires on a whole-query variable read through .data", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([{ file: rel, line: 1 }]);
  });

  it("does not fire when the destructuring takes isError or error", () => {
    const source = [
      "const { data: a = [], isError } = useThings();",
      "const { data: b = [], error: loadError } = useOthers();",
      "if (isError || loadError) return null;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("fires when isError is taken but never read", () => {
    const source = [
      "const { data = [], isError } = useThings();",
      "const n = data.length;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toHaveLength(1);
  });

  it("does not fire without an empty default", () => {
    expect(unreadErrorsIn(rel, "const { data } = useThings();")).toEqual([]);
  });

  it("does not fire when the whole-query variable reads isError", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
      "if (q.isError) return null;",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("ignores a destructuring that is not a hook call", () => {
    expect(unreadErrorsIn(rel, "const { data = [] } = props;")).toEqual([]);
  });

  it("does not take another component's read for this query's", () => {
    const source = [
      "function Good() {",
      "  const { data = [], isError } = useThings();",
      "  if (isError) return null;",
      "  return data.length;",
      "}",
      "function Bad() {",
      "  const { data = [], isError } = useThings();",
      '  return { title: "isError", count: data.length };',
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([
      { line: 7, site: expect.stringContaining("Bad ::") },
    ]);
  });

  it("does not take another query's isError, or template text, for a read", () => {
    const other = [
      "function C() {",
      "  const { data = [], isError } = useA();",
      "  const other = useB();",
      "  if (other.isError) return null;",
      "  return data.length;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, other)).toHaveLength(1);
    const template = [
      "function C() {",
      "  const { data = [], isError } = useA();",
      "  const label = `isError`;",
      "  return data.length;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, template)).toHaveLength(1);
    const hole = template.replace("`isError`", "`${isError}`");
    expect(unreadErrorsIn(rel, hole)).toHaveLength(0);
  });

  it("fires on an inline query read that binds no error at all", () => {
    expect(
      unreadErrorsIn(rel, "const scopes = useThings().data?.scopes ?? [];"),
    ).toMatchObject([{ line: 1, site: "<module> :: useThings().data" }]);
    expect(
      unreadErrorsIn(
        rel,
        "const has = (useThings({ a: f(1) }).data ?? []).length;",
      ),
    ).toHaveLength(1);
    expect(unreadErrorsIn(rel, "const n = useThings().data?.total;")).toEqual(
      [],
    );
  });

  it("does not let a plain destructuring hide a read of the error", () => {
    const source = [
      "function C(props) {",
      "  const { data = [], isError } = useA();",
      "  const { id } = props;",
      '  const label = isError ? "failed" : id;',
      "  const { data: other } = useB();",
      "  return data.length + label + other;",
      "}",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toEqual([]);
  });

  it("does not take another declaration's fallback for this query's", () => {
    const source = [
      "function Good() { const { data } = useA(); return data?.name; }",
      "function Bad() { const { data } = useB(); return data ?? []; }",
    ].join("\n");
    expect(unreadErrorsIn(rel, source)).toMatchObject([
      { line: 2, site: "Bad :: useB data" },
    ]);
  });

  it("finds the end of an inline call past a parenthesis in a quoted argument", () => {
    for (const arg of ['")"', '"("', "')'", "`)`"]) {
      expect(
        unreadErrorsIn(rel, `const a = useThings(${arg}).data ?? [];`),
      ).toHaveLength(1);
    }
    expect(
      unreadErrorsIn(rel, 'const a = useThings(f(")")).data ?? [];'),
    ).toHaveLength(1);
  });

  it("does not read a mention of an inline query in a literal as code", () => {
    const mentions = [
      'const text = "useThings().data ?? []";',
      "const text = 'useThings().data ?? []';",
      "const text = `useThings().data ?? []`;",
      'const text = `say "${name}": useThings().data ?? []`;',
    ];
    for (const source of mentions) {
      expect(unreadErrorsIn(rel, source)).toEqual([]);
    }
  });

  it("still sees an inline query inside a template expression", () => {
    expect(
      unreadErrorsIn(
        rel,
        "const text = `n: ${(useThings().data ?? []).length}`;",
      ),
    ).toHaveLength(1);
    expect(
      unreadErrorsIn(rel, "const text = `a ${`b ${useThings().data ?? []}`}`;"),
    ).toHaveLength(1);
  });

  it("does not let a quote in JSX text, a regex or a comment hide a later read", () => {
    const read =
      "export function Z() { const b = useThings().data ?? []; return b; }";
    const before = [
      "export function Y() { return <p>Don't worry</p>; }",
      'export const csv = /[",\n]/;',
      "// it's a comment\nconst a = `${`x`}`; /* don't */",
      "const msg = `${a ? `it's` : 'b'}`; // don't",
    ];
    for (const lead of before) {
      expect(unreadErrorsIn("x.tsx", `${lead}\n${read}`)).toHaveLength(1);
    }
  });

  it("sees an inline read through a comment in the chain", () => {
    const shapes = [
      "useThings() /* why */ .data ?? []",
      "useThings() // why\n  .data ?? []",
      "useThings().data /* why */ ?? []",
      "useThings().data ?? /* none */ []",
    ];
    for (const read of shapes) {
      expect(
        unreadErrorsIn(rel, `export function Z() { const b = ${read}; }`),
      ).toHaveLength(1);
    }
  });
});

describe("unguardedClaimsIn", () => {
  it("fires on a has-rows claim built from a defaulted query", () => {
    const source = [
      "const listQuery = useItems(params);",
      "const items = listQuery.data?.items ?? [];",
      "const total = countOf(items);",
      "return <Header hasRows={total > 0} />;",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toMatchObject([
      { file: rel, line: 4 },
    ]);
  });

  it("leaves the claim once the expression reads the outcome", () => {
    const source = [
      "const listQuery = useItems(params);",
      "const total = listQuery.data?.total ?? 0;",
      "return <Header hasRows={!listQuery.isLoading && total > 0} />;",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("leaves a count that no empty state or disabled action decides", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
      "return <p>{rows.length} records</p>;",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("fires on a count inside an empty-state branch", () => {
    const source = [
      "const q = useThings();",
      "const rows = q.data ?? [];",
      "return rows.length === 0 ? <EmptyState title={t('none')} /> : <Table rows={rows} />;",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toHaveLength(1);
  });

  it("does not make a local array query data because a hook sits beside it", () => {
    const source = [
      "function Form() {",
      "  const [names] = useState<string[]>([]);",
      "  const { mutate } = useCreateNames();",
      "  const { data: options = [] } = useNameOptions();",
      "  return <Button disabled={names.length === 0}>Save</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("does not take a non-query hook's result for query data", () => {
    const source = [
      "function Table({ count }) {",
      "  const virtualizer = useWindowVirtualizer({ count });",
      "  const virtualRows = virtualizer.getVirtualItems();",
      "  return <Button disabled={virtualRows.length === 0}>Go</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("leaves a claim under an early return on the error or the load", () => {
    const source = [
      "function List() {",
      "  const { data: things = [], isError, isLoading } = useThings();",
      "  if (isError) return <QueryFailure />;",
      "  if (isLoading) return <Spinner />;",
      "  return <Button disabled={things.length === 0}>Save</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("leaves a claim under a conditional return on the error or the load", () => {
    const source = [
      "function List() {",
      "  const { data: things = [], isError, isLoading } = useThings();",
      "  return isError ? <QueryFailure /> : isLoading ? <Spinner /> : <Button disabled={things.length === 0}>Save</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("leaves a claim in the alternate branch of a conditional on the flag", () => {
    const source = [
      "function List() {",
      "  const { data: things = [], isError } = useThings();",
      "  return (",
      "    <div>",
      "      {isError ? <QueryFailure /> : <Button disabled={things.length === 0}>Save</Button>}",
      "    </div>",
      "  );",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("leaves a claim whose expression names the outcome under another name", () => {
    const source = [
      "function List() {",
      "  const { data: locations = [], isLoading: locationsLoading } = useThings();",
      "  return <Select disabled={locationsLoading || locations.length === 0} />;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("does not make a hook whose record carries a status a query", () => {
    const source = [
      "function Card({ stored }) {",
      "  const doc = useLineNames(stored) ?? stored;",
      "  const preview = doc.lines.slice(0, 3);",
      "  return <Button status={doc.status} disabled={preview.length === 0}>Go</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("does not read a mutation result's property as the query's", () => {
    const source = [
      "function List() {",
      "  const { data: runs = [], isLoading } = useRuns();",
      "  const plan = usePlan();",
      "  return (",
      "    <Button",
      '      onClick={() => plan.mutate(1, { onSuccess: (result) => toast.success(t("planned", { count: result.runs.length })) })}',
      "      disabled={isLoading || runs.length === 0}",
      "    >",
      "      Go",
      "    </Button>",
      "  );",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toEqual([]);
  });

  it("fires on a claim beside an error drawn as a sibling", () => {
    const source = [
      "function List() {",
      "  const { data: rows = [], isError } = useThings();",
      "  const total = rows.length;",
      "  return (",
      "    <div>",
      "      {isError ? <QueryFailure /> : null}",
      "      <ListHeader hasRows={total > 0} />",
      "    </div>",
      "  );",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toMatchObject([
      { site: "List :: total>0" },
    ]);
  });

  it("fires on an empty state beside the error and a mutation's progress", () => {
    const source = [
      "function List() {",
      "  const { data: rows = [], isError } = useThings();",
      "  const save = useSave();",
      "  return (",
      "    <div>",
      '      <Button>{save.isPending ? "Saving" : "Save"}</Button>',
      "      {isError && <p>An error occurred</p>}",
      '      {rows.length === 0 && <EmptyState title="No things yet" />}',
      "    </div>",
      "  );",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toMatchObject([
      { site: "List :: rows.length" },
    ]);
  });

  it("does not accept a guard inside a handler or an effect", () => {
    const source = [
      "function List() {",
      "  const { data: rows = [], isError, isFetching } = useThings();",
      "  const total = rows.length;",
      "  const save = useSave();",
      "  const onSave = () => { if (save.isPending) return; doSave(); };",
      "  useEffect(() => { if (isFetching) return; doThing(); }, []);",
      "  return (",
      "    <div>",
      "      {isError && <QueryFailure />}",
      "      <ListHeader hasRows={total > 0} />",
      "    </div>",
      "  );",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toMatchObject([
      { site: "List :: total>0" },
    ]);
  });

  it("does not accept a guard that returns on the answer", () => {
    const source = [
      "function List() {",
      "  const { data: things = [], isLoading } = useThings();",
      "  if (!isLoading) return <ListBody rows={things} />;",
      "  return <Button disabled={things.length === 0}>Save</Button>;",
      "}",
    ].join("\n");
    expect(unguardedClaimsIn(rel, source)).toMatchObject([
      { site: "List :: things.length" },
    ]);
  });
});

describe("loadingWithoutFailureIn", () => {
  const leaf = (body) =>
    [
      "interface ThingListProps {",
      "  suggestions: Thing[];",
      "  isLoading: boolean;",
      "}",
      `export function ThingList({ suggestions, isLoading }: ThingListProps) {`,
      "  if (isLoading) return <Spinner />;",
      body,
      "}",
    ].join("\n");

  it("fires on a list component that models loading and not failure", () => {
    expect(
      loadingWithoutFailureIn(
        "modules/things/components/ThingList.tsx",
        leaf("  if (suggestions.length === 0) return <EmptyState />;"),
      ),
    ).toMatchObject([{ site: expect.stringContaining("no failure prop") }]);
  });

  it("leaves the component once it takes the failure", () => {
    const source = leaf(
      "  if (suggestions.length === 0) return <EmptyState />;",
    )
      .replace(
        "  isLoading: boolean;",
        "  isLoading: boolean;\n  isError: boolean;",
      )
      .replace(
        "{ suggestions, isLoading }",
        "{ suggestions, isLoading, isError }",
      );
    expect(
      loadingWithoutFailureIn(
        "modules/things/components/ThingList.tsx",
        source,
      ),
    ).toEqual([]);
  });
});

describe("pagedEmptyIn", () => {
  const page = (guard) =>
    [
      "const { data: pages, isLoading } = useLocationPages();",
      "const locations = pages?.pages.flatMap((page) => page.items) ?? [];",
      `return isLoading ? <Spinner /> : locations.length === 0 ? <EmptyState /> : <List />;`,
      guard,
    ].join("\n");

  it("fires on an empty state over a paged list guarded by isLoading alone", () => {
    expect(
      pagedEmptyIn("modules/things/pages/ThingsPage.tsx", page("")),
    ).toMatchObject([{ site: expect.stringContaining("isPlaceholderData") }]);
  });

  it("leaves the page once it reads the placeholder flag", () => {
    expect(
      pagedEmptyIn(
        "modules/things/pages/ThingsPage.tsx",
        page("const { isPlaceholderData } = useLocationPages();"),
      ),
    ).toEqual([]);
  });

  it("fires on an ordinary query that keeps the previous data", () => {
    const source = [
      "const { data: locations = [], isLoading } = useLocations({ placeholderData: keepPreviousData });",
      "return isLoading ? <Spinner /> : locations.length === 0 ? <EmptyState /> : <List />;",
    ].join("\n");
    expect(
      pagedEmptyIn("modules/things/pages/ThingsPage.tsx", source),
    ).toMatchObject([{ site: expect.stringContaining("isPlaceholderData") }]);
  });

  it("leaves a list that does not keep the previous data", () => {
    const source = [
      "const { data: locations = [], isLoading } = useLocations();",
      "return isLoading ? <Spinner /> : locations.length === 0 ? <EmptyState /> : <List />;",
    ].join("\n");
    expect(pagedEmptyIn("modules/things/pages/ThingsPage.tsx", source)).toEqual(
      [],
    );
  });
});
