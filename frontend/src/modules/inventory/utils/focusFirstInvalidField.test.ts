import { afterEach, describe, expect, it } from "vitest";
import { focusFirstInvalidField } from "./focusFirstInvalidField";

const mount = (html: string) => {
  document.body.innerHTML = html;
};

afterEach(() => {
  document.body.innerHTML = "";
});

describe("focusFirstInvalidField", () => {
  it("focuses the first invalid field in reading order", () => {
    mount(`
      <div data-field-key="name"><input id="name" /></div>
      <div data-field-key="size"><select id="size"></select></div>
      <div data-field-key="finish"><input id="finish" /></div>`);

    expect(focusFirstInvalidField(["finish", "size"])).toBe(true);

    expect(document.activeElement?.id).toBe("size");
  });

  it("scrolls the field into view", () => {
    mount(`<div data-field-key="size"><select id="size"></select></div>`);
    let scrolled = false;
    document.getElementById("size")!.scrollIntoView = () => {
      scrolled = true;
    };

    focusFirstInvalidField(["size"]);

    expect(scrolled).toBe(true);
  });

  it("does nothing when no invalid field is on the page", () => {
    mount(`<div data-field-key="name"><input id="name" /></div>`);

    expect(focusFirstInvalidField(["other"])).toBe(false);
    expect(document.activeElement).toBe(document.body);
  });
});
