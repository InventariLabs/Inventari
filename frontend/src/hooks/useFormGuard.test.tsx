import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useFormGuard } from "./useFormGuard";

function Form({ dirty }: { dirty: boolean }) {
  useFormGuard(dirty, "The product form");
  return null;
}

/** What the browser does when the page itself is about to go: a reload, a
 * phone's pull-to-refresh, a closed tab. */
function unload(): BeforeUnloadEvent {
  const event = new Event("beforeunload", {
    cancelable: true,
  }) as BeforeUnloadEvent;
  window.dispatchEvent(event);
  return event;
}

describe("useFormGuard — leaving the page itself", () => {
  it("asks before a reload while the form holds unsaved work", () => {
    render(<Form dirty />);
    expect(unload().defaultPrevented).toBe(true);
  });

  it("lets a reload through when the form is clean", () => {
    render(<Form dirty={false} />);
    expect(unload().defaultPrevented).toBe(false);
  });

  it("stops asking once the form is gone", () => {
    const { unmount } = render(<Form dirty />);
    unmount();
    expect(unload().defaultPrevented).toBe(false);
  });
});
