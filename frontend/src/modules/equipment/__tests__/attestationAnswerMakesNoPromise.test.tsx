/**
 * After answering, the public attestation page says the answer is recorded and
 * that the reader may close the tab. It promises nothing it cannot keep: a
 * browser refuses `window.close()` for a tab the script did not open, and an
 * e-mail link is exactly that tab.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { StatusDisplay } from "@/modules/equipment/components/attestation/StatusDisplay";

describe("an answered attestation link makes no promise it cannot keep", () => {
  it.each(["CONFIRMED", "DISPUTED"])(
    "%s: no countdown, no Close button, one sentence that the tab may be closed",
    (status) => {
      vi.useFakeTimers();
      const close = vi.spyOn(window, "close").mockImplementation(() => {});

      render(<StatusDisplay status={status} />);
      vi.advanceTimersByTime(10_000);

      expect(screen.queryByRole("button")).not.toBeInTheDocument();
      expect(
        screen.queryByText(/close automatically/i),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText(/saved, and you can close this tab now/i),
      ).toBeInTheDocument();
      expect(close).not.toHaveBeenCalled();

      close.mockRestore();
      vi.useRealTimers();
    },
  );
});

describe("StatusDisplay — a report beside confirmations", () => {
  it("says what was confirmed, not only that an issue was reported", () => {
    render(<StatusDisplay status="DISPUTED" confirmedCount={2} />);
    expect(screen.getByText(/confirmation of 2 other assets/)).toBeVisible();
  });

  it("keeps the plain sentence when nothing else was confirmed", () => {
    render(<StatusDisplay status="DISPUTED" />);
    expect(screen.queryByText(/confirmation of/)).not.toBeInTheDocument();
  });
});
