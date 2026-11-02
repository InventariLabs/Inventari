import { describe, expect, it } from "vitest";
import writeActionUngated from "./write-action-ungated.mjs";

const page = (text, path = "modules/things/pages/ThingsPage.tsx") => ({
  path,
  text,
});

const WRITES = `const remove = useDeleteThing();
  remove.mutate(thing.id);`;

describe("write-action-ungated", () => {
  it("reports a page that mutates and names no permission", () => {
    const { findings } = writeActionUngated.run([page(WRITES)]);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("leaves a page that asks through its module's own hook", () => {
    // approvals spells the question `useCanConfigureWorkflows()`, because the
    // key it guards is `approvals:configure` rather than a `:write`.
    const { findings } = writeActionUngated.run([
      page(`const canConfigure = useCanConfigureWorkflows();\n  ${WRITES}`),
    ]);

    expect(findings).toEqual([]);
  });

  it("leaves a page handed the answer as a prop", () => {
    const { findings } = writeActionUngated.run([
      page(`export function Page({ canWrite }) {\n  ${WRITES}\n}`),
    ]);

    expect(findings).toEqual([]);
  });

  it("leaves a page mounted in the public tree, where there is no account", () => {
    const files = [
      page(WRITES, "modules/equipment/pages/AttestationPublicPage.tsx"),
      {
        path: "PublicApp.tsx",
        text: `const AttestationPublicPage = lazy(
          () => import("@/modules/equipment/pages/AttestationPublicPage"),
        );`,
      },
    ];

    const { considered, findings } = writeActionUngated.run(files);

    expect(findings).toEqual([]);
    // Not merely unreported — never a candidate, so the class it belongs to
    // is not counted against the drain either.
    expect(considered).toBe(0);
  });

  it("still reports the other pages when the public tree is present", () => {
    const files = [
      page(WRITES),
      { path: "PublicApp.tsx", text: `import("@/modules/other/pages/Bare");` },
    ];

    const { findings } = writeActionUngated.run(files);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("follows a write the page makes through its module's hook", () => {
    const files = [
      page(`import { useQuickAdd } from "@/modules/things/hooks/useQuickAdd";
        const { submit } = useQuickAdd({});`),
      {
        path: "modules/things/hooks/useQuickAdd.ts",
        text: `import { useAppMutation } from "@/lib/api/mutationFactory";
          export function useQuickAdd(opts) {
            const save = useAppMutation(createThing);
            return { submit: () => save.mutateAsync(opts) };
          }`,
      },
    ];

    const { considered, findings } = writeActionUngated.run(files);

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("does not call a page a writer for merely listing through a read hook", () => {
    // Reads and writes live side by side in one hooks file; taking the file
    // whole would make every list page that reads it a writer.
    const files = [
      page(`import { useThings } from "@/modules/things/hooks/useThings";
        const { data } = useThings();`),
      {
        path: "modules/things/hooks/useThings.ts",
        text: `export function useThings() {
            return useQuery(thingsQuery);
          }

          export function useCreateThing() {
            return useAppMutation(createThing);
          }`,
      },
    ];

    const { considered, findings } = writeActionUngated.run(files);

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });

  it("ignores a mutation that only appears in a comment", () => {
    const { findings } = writeActionUngated.run([
      page(`// the old version called remove.mutate(thing.id) here`),
    ]);

    expect(findings).toEqual([]);
  });

  it("reports a page whose imported component mutates and asks nothing", () => {
    const files = [
      page(`import { ThingEditor } from "@/modules/things/components/ThingEditor";
        return <ThingEditor thing={thing} />;`),
      {
        path: "modules/things/components/ThingEditor.tsx",
        text: `export function ThingEditor({ thing }) {
          const save = useSaveThing();
          return <button onClick={() => save.mutate(thing)}>Save</button>;
        }`,
      },
    ];

    const { considered, findings } = writeActionUngated.run(files);

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("sees through a component that opens the mutating modal", () => {
    // The product-card shape: the page calls no mutation — it renders a component
    // that opens a modal, and the modal writes.
    const files = [
      page(`import { ThingPanel } from "@/modules/things/components/ThingPanel";
        return <ThingPanel item={item} />;`),
      {
        path: "modules/things/components/ThingPanel.tsx",
        text: `import { ThingModal } from "@/modules/things/components/ThingModal";
          export function ThingPanel({ item }) {
            return item.open ? <ThingModal item={item} /> : null;
          }`,
      },
      {
        path: "modules/things/components/ThingModal.tsx",
        text: `export function ThingModal({ item }) {
          const save = useSaveThing();
          return <button onClick={() => save.mutate(item)}>Save</button>;
        }`,
      },
    ];

    const { findings } = writeActionUngated.run(files);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("leaves a page whose component asks for itself", () => {
    const files = [
      page(`import { ThingEditor } from "@/modules/things/components/ThingEditor";
        return <ThingEditor thing={thing} />;`),
      {
        path: "modules/things/components/ThingEditor.tsx",
        text: `import { useCanWrite } from "@/hooks/useCanWrite";
          export function ThingEditor({ thing }) {
            const canWrite = useCanWrite("things");
            const save = useSaveThing();
            return canWrite ? (
              <button onClick={() => save.mutate(thing)}>Save</button>
            ) : null;
          }`,
      },
    ];

    const { findings } = writeActionUngated.run(files);

    expect(findings).toEqual([]);
  });

  it("reports a page that opens a floor flow through its fragment", () => {
    // The To do screen's shape: the only write is the hash the detail page
    // turns into a picking or receiving sheet, and the first request there
    // is a POST.
    const { findings } = writeActionUngated.run([
      page(`const navigate = useNavigate();
        navigate(\`/warehouse\${doc.id}#pick\`);`),
    ]);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("reads a fragment built from a template, as the To do screen builds it", () => {
    const { findings } = writeActionUngated.run([
      page(`function target(doc) {
          return \`/warehouse\${doc.id}#\${doc.type === "IN" ? "receive" : "pick"}\`;
        }
        const navigate = useNavigate();
        navigate(target(doc));`),
    ]);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("leaves a fragment navigation gated by the write hook", () => {
    const { findings } = writeActionUngated.run([
      page(`const canWrite = useCanWrite("warehouse");
        const navigate = useNavigate();
        canWrite && navigate(\`/warehouse\${doc.id}#pick\`);`),
    ]);

    expect(findings).toEqual([]);
  });

  it("does not accept a read-only notice as the gate for a fragment navigation", () => {
    // The notice says the screen is read-only while the control it explains
    // is still offered — the defect that made this shape worth reading.
    const { findings } = writeActionUngated.run([
      page(`<ReadOnlyNotice module="warehouse" />
        <Button onClick={() => navigate(\`/warehouse\${doc.id}#pick\`)}>
          Pick
        </Button>`),
    ]);

    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("does not accept a read-only notice as the gate in a child that opens a fragment", () => {
    // The same shape one hop down: the page renders a component whose
    // control navigates to the fragment, and the notice beside it is a caption.
    const { considered, findings } = writeActionUngated.run([
      page(`import { PickButton } from "@/modules/things/components/PickButton";
        export default function ThingsPage() { return <PickButton doc={doc} />; }`),
      {
        path: "modules/things/components/PickButton.tsx",
        text: `export function PickButton({ doc }) {
          return (
            <>
              <ReadOnlyNotice module="warehouse" />
              <Button onClick={() => navigate(\`/warehouse\${doc.id}#pick\`)}>
                Pick
              </Button>
            </>
          );
        }`,
      },
    ]);

    expect(considered).toBe(1);
    expect(findings).toEqual(["modules/things/pages/ThingsPage.tsx"]);
  });

  it("leaves a child that opens a fragment behind the write hook", () => {
    const { findings } = writeActionUngated.run([
      page(`import { PickButton } from "@/modules/things/components/PickButton";
        export default function ThingsPage() { return <PickButton doc={doc} />; }`),
      {
        path: "modules/things/components/PickButton.tsx",
        text: `export function PickButton({ doc }) {
          const canWrite = useCanWrite("warehouse");
          return canWrite ? (
            <Button onClick={() => navigate(\`/warehouse\${doc.id}#pick\`)}>
              Pick
            </Button>
          ) : null;
        }`,
      },
    ]);

    expect(findings).toEqual([]);
  });

  it("does not call an anchor to a settings section a write", () => {
    const { considered, findings } = writeActionUngated.run([
      page(`<Button onClick={() => navigate("/settings#module-data")}>Open</Button>`),
    ]);

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });

  it("ignores an imported writer that never becomes a tag", () => {
    const files = [
      page(
        `import { createThing } from "@/modules/things/components/createThing";`,
      ),
      {
        path: "modules/things/components/createThing.tsx",
        text: `export function createThing(api) { return api.mutate({}); }`,
      },
    ];

    const { considered, findings } = writeActionUngated.run(files);

    expect(considered).toBe(0);
    expect(findings).toEqual([]);
  });
});
