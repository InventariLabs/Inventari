import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { withLanguage } from "@/test/mocks/i18n";
import { CategoryAvatar, FALLBACK_COLORS } from "./CategoryAvatar";

const baseCategory = {
  name: "Fresh Eggs",
  code: null,
  emoji: null,
  color: null,
  contextTag: null,
};

describe("CategoryAvatar - cascade resolution", () => {
  it("renders emoji from keyword guess (Eggs -> egg)", () => {
    render(<CategoryAvatar category={baseCategory} />);
    // The image alt is the emoji
    const img = screen.getByAltText("🥚");
    expect(img).toBeInTheDocument();
  });

  it("honors user-set emoji (layer 1 beats layer 2)", () => {
    render(
      <CategoryAvatar
        category={{ ...baseCategory, name: "Fresh Eggs", emoji: "🐔" }}
      />,
    );
    expect(screen.getByText("🐔")).toBeInTheDocument();
  });

  it("uses vertical default emoji when keyword match fails (equipment context)", () => {
    render(
      <CategoryAvatar
        category={{
          ...baseCategory,
          name: "Xylophone",
          contextTag: "equipment",
        }}
      />,
    );
    expect(screen.getByAltText("💻")).toBeInTheDocument();
  });

  it("falls back to package emoji for completely empty category", () => {
    render(
      <CategoryAvatar
        category={{ name: "", code: null, emoji: null, color: null }}
      />,
    );
    expect(screen.getByAltText("📦")).toBeInTheDocument();
  });
});

describe("CategoryAvatar - color resolution", () => {
  it("honors user-set color (palette key)", () => {
    const { container } = render(
      <CategoryAvatar
        category={{ ...baseCategory, name: "Eggs", color: "indigo" }}
      />,
    );
    expect(container.querySelector(".bg-indigo-100")).toBeInTheDocument();
  });

  it("ignores invalid color and falls back to hash", () => {
    const { container } = render(
      <CategoryAvatar
        category={{ ...baseCategory, name: "Eggs", color: "not-a-color" }}
      />,
    );
    // Hash produces one of the FALLBACK_COLORS classes
    const has = FALLBACK_COLORS.some((c) =>
      container.querySelector(`.bg-${c}-100`),
    );
    expect(has).toBe(true);
  });

  it("hashes the name even for a category the food seed grouped by type", () => {
    const { container } = render(
      <CategoryAvatar category={{ ...baseCategory, name: "X" }} />,
    );
    const has = FALLBACK_COLORS.some((c) =>
      container.querySelector(`.bg-${c}-100`),
    );
    expect(has).toBe(true);
  });

  it("hashes the name to pick a fallback color when no override", () => {
    const { container } = render(<CategoryAvatar category={baseCategory} />);
    const has = FALLBACK_COLORS.some((c) =>
      container.querySelector(`.bg-${c}-100`),
    );
    expect(has).toBe(true);
  });
});

describe("CategoryAvatar - component shape", () => {
  it("renders with size=sm (24 px)", () => {
    const { container } = render(
      <CategoryAvatar category={baseCategory} size="sm" />,
    );
    const box = container.querySelector(
      '[data-testid="category-avatar"] > div',
    );
    expect(box).toHaveStyle({ width: "24px", height: "24px" });
  });

  it("renders with size=md (32 px)", () => {
    const { container } = render(
      <CategoryAvatar category={baseCategory} size="md" />,
    );
    const box = container.querySelector(
      '[data-testid="category-avatar"] > div',
    );
    expect(box).toHaveStyle({ width: "32px", height: "32px" });
  });

  it("renders with size=lg (48 px)", () => {
    const { container } = render(
      <CategoryAvatar category={baseCategory} size="lg" />,
    );
    const box = container.querySelector(
      '[data-testid="category-avatar"] > div',
    );
    expect(box).toHaveStyle({ width: "48px", height: "48px" });
  });

  it("defaults to circle shape", () => {
    const { container } = render(<CategoryAvatar category={baseCategory} />);
    const box = container.querySelector(
      '[data-testid="category-avatar"] > div',
    );
    expect(box).toHaveClass("rounded-full");
  });

  it("accepts square shape", () => {
    const { container } = render(
      <CategoryAvatar category={baseCategory} shape="square" />,
    );
    const box = container.querySelector(
      '[data-testid="category-avatar"] > div',
    );
    expect(box).toHaveClass("rounded-xl");
  });

  it("shows name when showName=true", () => {
    render(<CategoryAvatar category={baseCategory} showName />);
    expect(screen.getByText("Fresh Eggs")).toBeInTheDocument();
  });

  it("hides name by default", () => {
    render(<CategoryAvatar category={baseCategory} />);
    expect(screen.queryByText("Fresh Eggs")).not.toBeInTheDocument();
  });

  it("applies className to wrapper", () => {
    const { container } = render(
      <CategoryAvatar category={baseCategory} className="extra-class" />,
    );
    expect(
      container.querySelector('[data-testid="category-avatar"]'),
    ).toHaveClass("extra-class");
  });
});

describe("CategoryAvatar - name", () => {
  // Keep the tooltip and optional caption localized even though the visual
  // avatar itself is decorative.
  it("names a seeded category in the reader's language", async () => {
    const deli = { ...baseCategory, name: "Deli", code: "deli" };

    const { unmount } = render(<CategoryAvatar category={deli} showName />);
    expect(screen.getByText("Cold cuts")).toBeInTheDocument();
    expect(screen.getByTitle("Cold cuts")).toBeInTheDocument();
    unmount();

    await withLanguage("pl", () => {
      render(<CategoryAvatar category={deli} showName />);
      expect(screen.getByText("Wędliny")).toBeInTheDocument();
      expect(screen.getByTitle("Wędliny")).toBeInTheDocument();
    });
  });
});

describe("CategoryAvatar - decorative identity", () => {
  it.each([false, true])(
    "announces the category once with showName=%s",
    (showName) => {
      render(
        <button>
          <CategoryAvatar
            category={{ name: "Laptop", emoji: "💻" }}
            showName={showName}
          />
          {!showName && <span>Laptop</span>}
        </button>,
      );
      expect(screen.getByRole("button")).toHaveAccessibleName("Laptop");
      expect(screen.queryByRole("img")).not.toBeInTheDocument();
    },
  );

  it("keeps a failed emoji image decorative while retaining the caption", () => {
    render(
      <button>
        <CategoryAvatar category={{ name: "Laptop", emoji: "💻" }} showName />
      </button>,
    );
    fireEvent.error(screen.getByAltText("💻"));
    expect(screen.getByRole("button")).toHaveAccessibleName("Laptop");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
