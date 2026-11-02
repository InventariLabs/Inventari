import { describe, expect, it } from "vitest";
import { diffBaseline, unhandledIn } from "./check-mutate-async-handled.mjs";

const sites = (text, rel = "modules/things/ThingPage.tsx") =>
  unhandledIn(rel, text).map((f) => f.site);

describe("check-mutate-async-handled — what nothing catches", () => {
  it("flags an awaited mutateAsync in a click handler", () => {
    expect(
      sites(`
        function ThingPage() {
          const save = async () => { await m.mutateAsync(1); toast.success("x"); };
          return <Button onClick={save} />;
        }`),
    ).toEqual(["save :: m.mutateAsync"]);
  });

  it("flags an inline arrow handed to a prop that does not catch", () => {
    expect(sites(`<Button onClick={() => m.mutateAsync(1)} />`)).toHaveLength(
      1,
    );
  });

  it("flags a try with a finally and no catch", () => {
    expect(
      sites(
        `const go = async () => { try { await m.mutateAsync(1); } finally { done(); } };`,
      ),
    ).toHaveLength(1);
  });

  it("flags a destructured mutateAsync used bare", () => {
    expect(
      sites(`
        function useThing() {
          const { mutateAsync: save } = useSaveThing();
          return () => save(1);
        }`),
    ).toEqual([expect.stringMatching(/:: save$/)]);
  });

  it("flags a handler a hook returns to another file", () => {
    expect(
      sites(`
        export function useThingActions() {
          const archive = async () => { await m.mutateAsync(1); };
          return { archive };
        }`),
    ).toHaveLength(1);
  });

  it("does not follow an awaited result as if it were the promise", () => {
    expect(
      sites(`
        const go = async () => {
          const saved = await m.mutateAsync(1);
          try { use(saved); } catch (e) { toast.error(e); }
        };
        go();`),
    ).toHaveLength(1);
  });

  it.each([
    [
      "a try around a call nobody awaits",
      `const go = () => { try { m.mutateAsync(1); } catch (e) { toast.error(e); } };`,
    ],
    [
      "a try around a promise returned unawaited",
      `function P() {
         const go = async () => { try { return m.mutateAsync(1); } catch (e) { say(e); } };
         return <Button onClick={go} />;
       }`,
    ],
    [
      "a catching prop handed a callback that drops the promise",
      `<ConfirmDialog onConfirm={() => { m.mutateAsync(1); }} />`,
    ],
    [
      "a named callback that drops the promise",
      `function P() {
         const retire = () => { m.mutateAsync(1); };
         return <ConfirmDialog onConfirm={retire} />;
       }`,
    ],
    ["a voided call", `const go = () => { void m.mutateAsync(1); };`],
    [
      "a .catch with no handler",
      `async function save() { await m.mutateAsync(1).catch(); }`,
    ],
    ["a .catch with an empty handler", `m.mutateAsync(1).catch(() => {});`],
    [
      "a .then whose rejection arm is undefined",
      `m.mutateAsync(1).then(done, undefined);`,
    ],
    [
      "a .then whose rejection arm is empty",
      `m.mutateAsync(1).then(done, () => {});`,
    ],
    [
      "an empty catch block",
      `const go = async () => { try { await m.mutateAsync(1); } catch { /* ignored */ } };`,
    ],
  ])("flags %s", (_name, text) => {
    expect(sites(text)).toHaveLength(1);
  });
});

describe("check-mutate-async-handled — what reaches a handler", () => {
  it.each([
    [
      "a try with a catch",
      `const go = async () => { try { await m.mutateAsync(1); } catch (e) { toast.error(e); } };`,
    ],
    ["a .catch on the call", `m.mutateAsync(1).then(done).catch(report);`],
    ["a two-armed .then", `m.mutateAsync(1).then(done, report);`],
    [
      "a handler-less .catch that hands the rejection on to a catch",
      `const go = async () => {
         try { await m.mutateAsync(1).catch(); } catch (e) { say(e); }
       };`,
    ],
    [
      "runWithToast",
      `void runWithToast(() => m.mutateAsync(1), { errorFallback: "x" });`,
    ],
    [
      "a ConfirmDialog's onConfirm, through a named handler",
      `function P() {
         const retire = async () => { await m.mutateAsync(1); };
         return <ConfirmDialog onConfirm={retire} />;
       }`,
    ],
    [
      "showConfirm's onConfirm",
      `showConfirm({ onConfirm: async () => { await m.mutateAsync(1); } });`,
    ],
    [
      "the page's Save",
      `usePageSavePart("x", dirty, async () => { await m.mutateAsync(1); });`,
    ],
    [
      "a handler called inside a try",
      `function P() {
         const inner = async () => { await m.mutateAsync(1); };
         const outer = async () => { try { await inner(); } catch (e) { say(e); } };
         return <Button onClick={outer} />;
       }`,
    ],
    [
      "Promise.all over a map inside a try",
      `const go = async () => {
         try { await Promise.all(ids.map((id) => m.mutateAsync(id))); }
         catch (e) { say(e); }
       };`,
    ],
    [
      "a promise kept in a variable and caught there",
      `const p = m.mutateAsync(1); p.then(done, report);`,
    ],
    [
      "a queue that catches what it chains",
      `const write = async () => { await m.mutateAsync(1); };
       queue.current = queue.current.then(write).catch(report);`,
    ],
    [
      "a wrapper named mutateAsync, whose callers are sites of their own",
      `const actions = { mutateAsync: async (v) => { await m.mutateAsync(v); } };`,
    ],
    [
      "an approvals slot's onApprove",
      `<TypedSlot name="approval_status_badge" data={{ onApprove: async () => { await m.mutateAsync(1); } }} />`,
    ],
  ])("passes %s", (_name, text) => {
    expect(sites(text)).toEqual([]);
  });

  it("does not take a slot it has not read as a catcher", () => {
    expect(
      sites(
        `<TypedSlot name="document_detail_line_extra" data={{ onApprove: async () => { await m.mutateAsync(1); } }} />`,
      ),
    ).toHaveLength(1);
  });
});

describe("check-mutate-async-handled — baseline", () => {
  it("fails only on a site above its baseline count", () => {
    const findings = [
      { file: "a.tsx", site: "save :: m.mutateAsync" },
      { file: "a.tsx", site: "save :: m.mutateAsync" },
    ];
    expect(
      diffBaseline(findings, { "a.tsx :: save :: m.mutateAsync": 2 }).added,
    ).toEqual([]);
    expect(
      diffBaseline(findings, { "a.tsx :: save :: m.mutateAsync": 1 }).added,
    ).toHaveLength(1);
  });
});
