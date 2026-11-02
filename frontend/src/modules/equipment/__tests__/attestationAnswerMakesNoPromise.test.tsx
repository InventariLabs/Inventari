/**
 * After answering, the public attestation page used to count down "This tab
 * will close automatically in 5s" and offer "Close now" — both calling
 * `window.close()`, which a browser refuses for a tab the script did not
 * open. An e-mail link is exactly that tab, so the countdown stopped at 0s
 * and the button did nothing. The page now says the answer is recorded and
 * that the reader may close the tab, and promises nothing it cannot keep.
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
