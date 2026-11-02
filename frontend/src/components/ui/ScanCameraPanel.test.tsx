import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";

const base = {
  open: true,
  scannerError: null,
  isCameraActive: true,
  isTorchOn: false,
  onRetry: vi.fn(),
  onToggleTorch: vi.fn(),
  onClose: vi.fn(),
};

/** Where the panel's slot sits in the viewport, as the page scrolls. */
function placeSlotAt(slot: HTMLElement, top: number) {
  slot.getBoundingClientRect = () =>
    ({ top, left: 12, width: 366, height: 300 }) as DOMRect;
  act(() => {
    window.dispatchEvent(new Event("scroll"));
  });
}

describe("ScanCameraPanel", () => {
  beforeEach(() => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
  });
  afterEach(() => vi.restoreAllMocks());

  it("keeps the refusal text clear of the close button on both sides", () => {
    render(<ScanCameraPanel {...base} scannerError="Allow the camera" />);
    const text = screen.getByText("Allow the camera");
    // The button is 2rem wide, 0.5rem from the edge: 3rem of padding on
    // each side keeps centred text out from under it.
    expect(text.parentElement).toHaveClass("px-12");
  });

  it("puts the torch on the video's own box, narrow like the video, not on the wide panel", () => {
    render(<ScanCameraPanel {...base} />);
    const videoBox = document.getElementById("qr-reader")!.parentElement!;
    expect(videoBox).toHaveClass("relative", "mx-auto", "max-w-sm");
    // The only button besides "close" is the torch.
    expect(within(videoBox).getAllByRole("button")).toHaveLength(1);
  });

  it("stays in the flow until the page scrolls it up to the app bar", () => {
    const { container } = render(<ScanCameraPanel {...base} pinned />);
    const slot = container.firstElementChild as HTMLElement;
    const box = slot.firstElementChild as HTMLElement;

    placeSlotAt(slot, 300);
    expect(box).not.toHaveClass("fixed");

    placeSlotAt(slot, 20);
    expect(box).toHaveClass("fixed", "top-16");
    expect(box.style.left).toBe("12px");
    expect(box.style.width).toBe("366px");

    placeSlotAt(slot, 300);
    expect(box).not.toHaveClass("fixed");
  });

  it("never pins on a wide screen", () => {
    window.matchMedia = vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    const { container } = render(<ScanCameraPanel {...base} pinned />);
    const slot = container.firstElementChild as HTMLElement;
    placeSlotAt(slot, 20);
    expect(slot.firstElementChild).not.toHaveClass("fixed");
  });

  it("does not pin unless asked", () => {
    const { container } = render(<ScanCameraPanel {...base} />);
    expect(container.firstElementChild).not.toHaveClass("fixed");
  });

  it("holds the box's height in the page flow while it is pinned, so the page below does not jump", () => {
    let resized: () => void = () => {};
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized = callback;
        }
        observe() {}
        disconnect() {}
      },
    );
    const { container } = render(<ScanCameraPanel {...base} pinned />);
    const slot = container.firstElementChild as HTMLElement;
    const box = slot.firstElementChild as HTMLElement;
    Object.defineProperty(box, "offsetHeight", {
      configurable: true,
      value: 280,
    });
    act(() => resized());

    placeSlotAt(slot, 20);

    expect(slot.style.minHeight).toBe("280px");
    vi.unstubAllGlobals();
  });
});
