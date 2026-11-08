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
 * entry point still builds it. (That the entry point installs the reading-time
 * rule is `main.test.tsx`: it runs the entry point rather than reading it.)
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

// The entry point mounts `Root`, and `Root` draws the providers and the trees.
const ENTRY_SOURCE = readFileSync(join(__dirname, "..", "main.tsx"), "utf8");
const ROOT_SOURCE = readFileSync(join(__dirname, "..", "Root.tsx"), "utf8");

describe("the entry point keeps building the notification surface", () => {
  it("renders the surface through AppToaster", () => {
    expect(ROOT_SOURCE).toMatch(/<AppToaster\s*\/>/);
  });

  it("keeps a second, hand-configured Toaster out of the entry point", () => {
    expect(ENTRY_SOURCE + ROOT_SOURCE).not.toContain("<Toaster");
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
    //
    // This reads the stylesheet because jsdom computes no layout: a
    // measurement in it would be 0x0 with the rule or without. The match is
    // the rule's own block, so a `width: 44px` anywhere else in the file
    // cannot stand in for it.
    // Comments are removed first: a commented-out rule would still match.
    const css = INDEX_CSS.replace(/\/\*[\s\S]*?\*\//g, "");
    const block = css.match(
      /\[data-close-button\]\[data-close-button\]\s*\{([^}]*)\}/,
    );
    expect(block, "the close-button rule in index.css").not.toBeNull();
    expect(block![1]).toMatch(/width:\s*44px/);
    expect(block![1]).toMatch(/height:\s*44px/);
  });
});
