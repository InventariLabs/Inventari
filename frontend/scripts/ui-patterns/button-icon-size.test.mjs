import { describe, expect, it } from "vitest";
import buttonIconSize from "./button-icon-size.mjs";

const files = (text) => [{ path: "Fixture.tsx", text }];
const run = (text) => buttonIconSize.run(files(text)).findings;

describe("button-icon-size", () => {
  it("reports 18 and 20 on a standard button, either side of the label", () => {
    expect(
      run(`<Button leftIcon={<Plus size={18} />}>Add</Button>
      <Button rightIcon={<ChevronRight size={20} />}>Next</Button>`),
    ).toEqual(["Fixture.tsx:1", "Fixture.tsx:2"]);
  });

  it("reads a size that follows a className expression on the icon", () => {
    expect(
      run(`<Button leftIcon={<Plus className={cn("a", b)} size={18} />}>Add</Button>`),
    ).toEqual(["Fixture.tsx:1"]);
  });

  it("allows 16 everywhere, 14 on a small button and 20 on a large one", () => {
    expect(
      run(`<Button leftIcon={<Plus size={16} />}>Add</Button>
      <Button size="sm" leftIcon={<Plus size={14} />}>Add</Button>
      <Button size="contentSm" leftIcon={<Plus size={14} />}>Add</Button>
      <Button size="lg" leftIcon={<Plus size={20} />}>Add</Button>`),
    ).toEqual([]);
  });

  it("reports the sizes a small or large button does not allow", () => {
    expect(
      run(`<Button size="sm" leftIcon={<Plus size={15} />}>Add</Button>
      <Button size="sm" leftIcon={<Plus size={12} />}>Add</Button>
      <Button size="lg" leftIcon={<Plus size={24} />}>Add</Button>
      <Button leftIcon={<Plus size={14} />}>Add</Button>`),
    ).toEqual(["Fixture.tsx:1", "Fixture.tsx:2", "Fixture.tsx:3", "Fixture.tsx:4"]);
  });

  it("skips a runtime size, an icon-only size and an icon without a number", () => {
    expect(
      run(`<Button size={compact ? "sm" : "default"} leftIcon={<Plus size={18} />}>A</Button>
      <Button size="icon" leftIcon={<Plus size={18} />} aria-label="x" />
      <Button leftIcon={<Plus className="h-4 w-4" />}>A</Button>
      <Button leftIcon={<Plus size={iconSize} />}>A</Button>`),
    ).toEqual([]);
  });

  it("does not read a comment as the mistake", () => {
    expect(
      run(`// <Button leftIcon={<Plus size={18} />}>Add</Button>
      <Button leftIcon={<Plus size={16} />}>Add</Button>`),
    ).toEqual([]);
  });
});
