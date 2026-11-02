import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FluentEmoji } from "./FluentEmoji";

describe("FluentEmoji", () => {
  it("renders <img> for emoji present in the manifest", () => {
    // 🥚 is in the manifest (downloaded by sync-fluent-emoji.mjs)
    render(<FluentEmoji emoji="🥚" />);
    const img = screen.getByRole("img", { name: "🥚" });
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src");
    // src should point to the public emoji asset
    expect(img.getAttribute("src")).toMatch(/^\/emoji\//);
  });

  it("falls back to native <span> when emoji is not in manifest", () => {
    // A user-picked emoji that is unlikely to be in our curated subset
    render(<FluentEmoji emoji="🦄" />);
    const span = screen.getByRole("img", { name: "🦄" });
    expect(span.tagName).toBe("SPAN");
  });

  it("falls back to native <span> when <img> onError fires", () => {
    render(<FluentEmoji emoji="🥚" />);
    const img = screen.getByRole("img", { name: "🥚" }) as HTMLImageElement;
    // Simulate the browser firing onError
    fireEvent.error(img);
    // After the error, the same role/name should now be a SPAN
    const span = screen.getByRole("img", { name: "🥚" });
    expect(span.tagName).toBe("SPAN");
    expect(span.textContent).toBe("🥚");
  });

  it("respects size prop (px)", () => {
    render(<FluentEmoji emoji="🥚" size={40} />);
    const img = screen.getByRole("img", { name: "🥚" });
    expect(img).toHaveAttribute("width", "40");
    expect(img).toHaveAttribute("height", "40");
  });

  it("respects custom alt text", () => {
    render(<FluentEmoji emoji="🥚" alt="Eggs category" />);
    expect(
      screen.getByRole("img", { name: "Eggs category" }),
    ).toBeInTheDocument();
  });

  it("uses lazy loading + async decoding", () => {
    render(<FluentEmoji emoji="🥚" />);
    const img = screen.getByRole("img", { name: "🥚" });
    expect(img).toHaveAttribute("loading", "lazy");
    expect(img).toHaveAttribute("decoding", "async");
  });
});
