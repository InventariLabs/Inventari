import { describe, expect, it } from "vitest";

import {
  closeOnRefusalIn,
  isScanned,
} from "./check-dialog-close-on-refusal.mjs";

/**
 * The gate flags a dialog that closes before the server accepted the change.
 * Both directions are pinned: the shapes that must fire, and the twins that
 * are right and must stay green.
 */

const rel = "modules/things/components/ThingDialog.tsx";

const dialog = (body) => `function ThingDialog() {
  const [open, setOpen] = useState("");
  return (
    <ConfirmDialog open onConfirm={${body}}>
      <Input value={open} />
    </ConfirmDialog>
  );
}`;

describe("check-dialog-close-on-refusal", () => {
  it("fires on a close before the mutation", () => {
    const source = dialog(`() => {
      setOpen(false);
      save.mutate(values);
    }`);
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { handler: "<arrow>", reason: "closes before the request" },
    ]);
  });

  it("fires on a close right after an un-awaited mutation", () => {
    const source = dialog(`() => {
      save.mutate(values);
      setOpen(false);
    }`);
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { reason: "closes right after an un-awaited request" },
    ]);
  });

  it("fires on a close in onSettled", () => {
    const source = dialog(`() => {
      save.mutate(values, { onSettled: () => setOpen(false) });
    }`);
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { reason: "closes in a refusal path" },
    ]);
  });

  it("fires on a close in finally", () => {
    const source = dialog(`async () => {
      try {
        await save.mutateAsync(values);
      } finally {
        setOpen(false);
      }
    }`);
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { reason: "closes in finally" },
    ]);
  });

  it("fires on a close in catch", () => {
    const source = dialog(`async () => {
      try {
        await save.mutateAsync(values);
      } catch {
        setOpen(false);
      }
    }`);
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { reason: "closes in catch" },
    ]);
  });

  it("leaves a close after an awaited mutation", () => {
    const source = dialog(`async () => {
      await save.mutateAsync(values);
      setOpen(false);
    }`);
    expect(closeOnRefusalIn(rel, source)).toEqual([]);
  });

  it("leaves a close in onSuccess", () => {
    const source = dialog(`() => {
      save.mutate(values, { onSuccess: () => setOpen(false) });
    }`);
    expect(closeOnRefusalIn(rel, source)).toEqual([]);
  });

  it("leaves a close in a named onSuccess callback", () => {
    const source = `function ThingDialog() {
      const [open, setOpen] = useState("");
      return (
        <ConfirmDialog
          open
          onConfirm={() => save.mutate(values, { onSuccess: done })}
        >
          <Input value={open} />
        </ConfirmDialog>
      );
      function done() {
        setOpen(false);
      }
    }`;
    expect(closeOnRefusalIn(rel, source)).toEqual([]);
  });

  it("reads a handler through the local function it hands the work to", () => {
    // The production run's Cancel: the arrow closes the dialog and calls the
    // page's own handler, which is where the request is sent.
    const source = `function RunPage() {
      const [asking, setAsking] = useState("");
      function handleCancel() {
        cancel.mutate({ id });
      }
      return (
        <ConfirmDialog
          open
          onConfirm={() => {
            setAsking(false);
            handleCancel();
          }}
        >
          <Input value={asking} />
        </ConfirmDialog>
      );
    }`;
    expect(closeOnRefusalIn(rel, source)).toMatchObject([
      { reason: "closes right after an un-awaited request" },
    ]);
  });

  it("ignores a close with nothing typed and no confirm hand-off", () => {
    const source = `function ItemSheet({ onAddOne }) {
      return (
        <Sheet open onClose={() => undefined}>
          <Button
            onClick={() => {
              onClose();
              onAddOne(item.id);
            }}
          >
            Add one
          </Button>
        </Sheet>
      );
    }`;
    expect(closeOnRefusalIn(rel, source)).toEqual([]);
  });

  it("ignores a file that draws no dialog", () => {
    const source = `function Toolbar() {
      const [q, setQ] = useState("");
      return <Input value={q} onChange={(e) => setQ(e.target.value)} />;
    }`;
    expect(closeOnRefusalIn(rel, source)).toEqual([]);
  });

  it("scans product sources but not tests", () => {
    expect(isScanned("modules/things/components/Dialog.tsx")).toBe(true);
    expect(isScanned("modules/things/components/Dialog.test.tsx")).toBe(false);
  });
});
