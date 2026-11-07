import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PageSaveProvider, usePageSave, usePageSavePart } from "./usePageSave";

function Part({
  name,
  dirty,
  save,
}: {
  name: string;
  dirty: boolean;
  save: () => Promise<unknown>;
}) {
  usePageSavePart(name, dirty, save);
  return null;
}

function Probe({ onFailures }: { onFailures?: (failures: unknown[]) => void }) {
  const { dirty, saving, saveAll, failedKeys } = usePageSave();
  return (
    <>
      <span data-testid="failed">{[...failedKeys].join(",")}</span>
      <span data-testid="state">
        {dirty ? "dirty" : "clean"}
        {saving ? " saving" : ""}
      </span>
      <button
        type="button"
        onClick={() => void saveAll().then((f) => onFailures?.(f))}
      >
        save
      </button>
    </>
  );
}

describe("PageSaveProvider", () => {
  it("is dirty while any part is, and clean otherwise", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <PageSaveProvider>
        <Part name="a" dirty={false} save={save} />
        <Part name="b" dirty save={save} />
        <Probe />
      </PageSaveProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("dirty");

    rerender(
      <PageSaveProvider>
        <Part name="a" dirty={false} save={save} />
        <Part name="b" dirty={false} save={save} />
        <Probe />
      </PageSaveProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("clean");
  });

  it("saves only the dirty parts, in the order they registered", async () => {
    const order: string[] = [];
    const saver = (name: string) => async () => {
      order.push(name);
    };
    render(
      <PageSaveProvider>
        <Part name="first" dirty save={saver("first")} />
        <Part name="untouched" dirty={false} save={saver("untouched")} />
        <Part name="second" dirty save={saver("second")} />
        <Probe />
      </PageSaveProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(order).toEqual(["first", "second"]);
  });

  it("keeps saving after a part is refused and hands the refusal back", async () => {
    const refusal = new Error("refused");
    const later = vi.fn().mockResolvedValue(undefined);
    const onFailures = vi.fn();
    render(
      <PageSaveProvider>
        <Part name="bad" dirty save={() => Promise.reject(refusal)} />
        <Part name="good" dirty save={later} />
        <Probe onFailures={onFailures} />
      </PageSaveProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(later).toHaveBeenCalledOnce();
    expect(onFailures).toHaveBeenCalledWith([refusal]);
  });

  it("names the parts that were refused until their edit is taken back", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const bad = () => Promise.reject(new Error("refused"));
    const { rerender } = render(
      <PageSaveProvider>
        <Part name="bad" dirty save={bad} />
        <Part name="good" dirty save={save} />
        <Probe />
      </PageSaveProvider>,
    );
    expect(screen.getByTestId("failed")).toHaveTextContent("");

    await userEvent.click(screen.getByRole("button", { name: "save" }));
    expect(screen.getByTestId("failed")).toHaveTextContent(/^bad$/);

    rerender(
      <PageSaveProvider>
        <Part name="bad" dirty={false} save={bad} />
        <Part name="good" dirty save={save} />
        <Probe />
      </PageSaveProvider>,
    );
    expect(screen.getByTestId("failed")).toHaveTextContent("");
  });

  it("forgets a part that unmounts", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <PageSaveProvider>
        <Part name="a" dirty save={save} />
        <Probe />
      </PageSaveProvider>,
    );
    expect(screen.getByTestId("state")).toHaveTextContent("dirty");

    act(() => {
      rerender(
        <PageSaveProvider>
          <Probe />
        </PageSaveProvider>,
      );
    });
    expect(screen.getByTestId("state")).toHaveTextContent("clean");
  });

  it("calls the latest save of a part, not the one it registered with", async () => {
    const first = vi.fn().mockResolvedValue(undefined);
    const second = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(
      <PageSaveProvider>
        <Part name="a" dirty save={first} />
        <Probe />
      </PageSaveProvider>,
    );
    rerender(
      <PageSaveProvider>
        <Part name="a" dirty save={second} />
        <Probe />
      </PageSaveProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });
});

describe("usePageSavePart outside a provider", () => {
  it("does nothing and reports that there is no page Save", () => {
    let underPage: boolean | null = null;
    function Lone() {
      underPage = usePageSavePart("a", true, async () => {});
      return null;
    }
    render(<Lone />);
    expect(underPage).toBe(false);
  });
});
