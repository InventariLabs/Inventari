import { describe, expect, it } from "vitest";
import failureAsEmpty from "./failure-as-empty.mjs";

const file = (text) => [
  { path: "modules/things/components/ThingsList.tsx", text },
];

describe("failure-as-empty", () => {
  it("reports a defaulted array with an empty state and no look at the error", () => {
    const { findings } = failureAsEmpty.run(
      file(`const { data: things = [], isLoading } = useThings();
      return things.length === 0 ? <EmptyState /> : <List />;`),
    );

    expect(findings).toEqual(["modules/things/components/ThingsList.tsx"]);
  });

  it("leaves a file that reads isError", () => {
    const { findings } = failureAsEmpty.run(
      file(`const { data: things = [], isError, error, refetch } = useThings();
      if (isError) return <QueryFailure error={error} onRetry={refetch} />;
      return things.length === 0 ? <EmptyState /> : <List />;`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a picker, where the default array renders an empty dropdown", () => {
    // Nothing false is said over an empty list of options, so the rule must
    // not claim it — this is most of the 50-odd files it considers.
    const { findings } = failureAsEmpty.run(
      file(`const { data: uoms = [] } = useFlatUoms();
      return <Select options={uoms.map((u) => ({ id: u.id }))} />;`),
    );

    expect(findings).toEqual([]);
  });

  it("does not confuse local state with the query it defaulted", () => {
    // `lines` is the component's own state; `uoms` is the read. An empty
    // state over the first says nothing about the second.
    const { findings } = failureAsEmpty.run(
      file(`const { data: uoms = [] } = useFlatUoms();
      const [lines, setLines] = useState([]);
      return lines.length === 0 ? <EmptyState /> : <Rows />;`),
    );

    expect(findings).toEqual([]);
  });

  it("claims an empty state over an array the component builds from the read", () => {
    // `events` is not the defaulted array, but it is made of it: the loops
    // feed it from the reads, and the empty state still speaks about a
    // request that never arrived.
    const { findings } = failureAsEmpty.run(
      file(`const { data: assignments = [], isLoading } = useAssignments();
      const { data: logs = [], isLoading: loadingLogs } = useLogs();
      const events: Event[] = [];
      for (const a of assignments) events.push({ id: a.id });
      for (const l of logs) events.push({ id: l.id });
      return events.length === 0 ? <EmptyState /> : <Timeline />;`),
    );

    expect(findings).toEqual(["modules/things/components/ThingsList.tsx"]);
  });

  it("leaves a built array the defaulted read never fed", () => {
    // The rows come from props; the read is unpacked and never touched, so
    // its default fed nothing and the empty state is honest about what it
    // counts.
    const { findings } = failureAsEmpty.run(
      file(`const { data: things = [] } = useThings();
      const rows: Row[] = [];
      props.items.forEach((item) => rows.push(item));
      return rows.length === 0 ? <EmptyState /> : <Rows />;`),
    );

    expect(findings).toEqual([]);
  });

  it("leaves a built array whose length answers a question, not an empty state", () => {
    // `stack.length === 0` is a tag-balance check inside a helper — a
    // boolean the code computes, not a claim rendered over an unread list.
    const { findings } = failureAsEmpty.run(
      file(`const { data: things = [] } = useThings();
      function balanced(html: string) {
        const stack: string[] = [];
        for (const tag of html.matchAll(/</g)) stack.push(tag);
        return stack.length === 0;
      }
      return <Editor things={things} balanced={balanced} />;`),
    );

    expect(findings).toEqual([]);
  });

  it("claims the bare `data = []` spelling too", () => {
    const { findings } = failureAsEmpty.run(
      file(`const { data = [] } = useThings();
      return data.length === 0 ? <EmptyState /> : <List />;`),
    );

    expect(findings).toEqual(["modules/things/components/ThingsList.tsx"]);
  });

  it("considers every file with the shape, not only the ones it claims", () => {
    // The regex is /g/, and a `test` that leaves `lastIndex` behind would let
    // every second file through the candidate filter unseen.
    const { considered } = failureAsEmpty.run([
      { path: "a/One.tsx", text: "const { data: a = [] } = useA();" },
      { path: "a/Two.tsx", text: "const { data: b = [] } = useB();" },
      { path: "a/Three.tsx", text: "const { data: c = [] } = useC();" },
      { path: "a/Four.tsx", text: "const { data: d = [] } = useD();" },
    ]);

    expect(considered).toBe(4);
  });

  it("looks only at .tsx files that are not specs", () => {
    const { considered } = failureAsEmpty.run([
      { path: "hooks/useThings.ts", text: "const { data = [] } = q();" },
      { path: "a/One.test.tsx", text: "const { data = [] } = q();" },
    ]);

    expect(considered).toBe(0);
  });
});
