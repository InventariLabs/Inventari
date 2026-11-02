import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { toast } from "sonner";
import { render, screen } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import AppToaster from "./AppToaster";

/**
 * The notification surface is configuration, and configuration nobody tests
 * is configuration that quietly stops existing: dropping `closeButton`, or
 * the `installToastDefaults()` call in the entry point, used to break nothing
 * at all. These are the two halves — what the surface renders, and that the
 * entry point still builds it.
 */

async function raiseWarning(message: string) {
  await act(async () => {
    toast.warning(message);
  });
}

describe("AppToaster — the notification surface", () => {
  it("names the close button in the interface language, not the library's English", async () => {
    await withLanguage("pl", async () => {
      render(<AppToaster />);
      await raiseWarning("Nazwa jest wymagana");

      const close = await screen.findByRole("button", {
        name: "Zamknij powiadomienie",
      });
      expect(close).toBeInTheDocument();
      expect(close).toHaveAttribute("data-close-button");

      // Sonner's own default, which a Polish screen reader used to read out.
      expect(
        screen.queryByRole("button", { name: "Close toast" }),
      ).not.toBeInTheDocument();
    });
  });

  it("names the notification region in the interface language too", async () => {
    await withLanguage("pl", async () => {
      render(<AppToaster />);

      expect(
        screen.getByRole("region", { name: /Powiadomienia/ }),
      ).toBeInTheDocument();
    });
  });
});

const MAIN_SOURCE = readFileSync(join(__dirname, "..", "main.tsx"), "utf8");

describe("the entry point keeps building the notification surface", () => {
  it("renders the surface through AppToaster", () => {
    expect(MAIN_SOURCE).toMatch(/<AppToaster\s*\/>/);
  });

  it("installs the reading-time rule that gives long messages their time", () => {
    expect(MAIN_SOURCE).toMatch(/^installToastDefaults\(\);$/m);
  });

  it("keeps a second, hand-configured Toaster out of the entry point", () => {
    expect(MAIN_SOURCE).not.toContain("<Toaster");
  });
});

const INDEX_CSS = readFileSync(join(__dirname, "..", "index.css"), "utf8");

describe("the toast close button is a target a thumb can land on", () => {
  it("is a 44px box, not the 20px sonner ships", () => {
    // The reachable area used to be a transparent pseudo-element: a thumb
    // could reach 44px while the element itself still measured 20x20 to
    // anything that asked it — which is how a layout measurement reported
    // the close button at 20x20 with that fix already on screen. The
    // box is 44 now, and the painted circle stays 20 inside it.
    const rule = INDEX_CSS.slice(INDEX_CSS.indexOf("[data-sonner-toaster]"));
    expect(rule).toContain("[data-close-button][data-close-button]");
    expect(rule).toMatch(/width:\s*44px/);
    expect(rule).toMatch(/height:\s*44px/);
  });
});
