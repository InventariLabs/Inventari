import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import { JournalCard, type JournalEntry } from "@/components/ui/JournalCard";

const entries: JournalEntry[] = [
  {
    id: "1",
    tone: "info",
    text: (
      <>
        Moved <strong>Flour 1 kg</strong> → Fridge
      </>
    ),
    timeLabel: "09:12",
    dateTime: "2026-09-22T09:12:00Z",
    href: "/inventory/moves/1",
  },
  {
    id: "2",
    tone: "success",
    text: (
      <>
        +8 pcs <strong>Orange juice</strong>
      </>
    ),
    timeLabel: "21.09.2026",
  },
];

function renderCard(props: Partial<Parameters<typeof JournalCard>[0]> = {}) {
  return render(
    <MemoryRouter>
      <JournalCard
        title="Recent moves"
        entries={entries}
        linkLabel="Journal"
        linkHref="/inventory/moves"
        empty={{
          text: "No moves yet.",
          linkLabel: "Go to stock",
          linkHref: "/inventory/stock",
        }}
        {...props}
      />
    </MemoryRouter>,
  );
}

describe("JournalCard", () => {
  it("renders a titled card with a link to the full journal", () => {
    renderCard();
    expect(
      screen.getByRole("heading", { name: "Recent moves" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Journal" })).toHaveAttribute(
      "href",
      "/inventory/moves",
    );
  });

  it("renders the rows in the order given, each with its time", () => {
    renderCard();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Moved Flour 1 kg → Fridge");
    expect(within(rows[0]).getByText("09:12").tagName).toBe("TIME");
    expect(within(rows[0]).getByText("09:12")).toHaveAttribute(
      "datetime",
      "2026-09-22T09:12:00Z",
    );
    expect(rows[1]).toHaveTextContent("21.09.2026");
  });

  it("makes a row with a destination a link, and one without plain text", () => {
    renderCard();
    const rows = screen.getAllByRole("listitem");
    expect(within(rows[0]).getByRole("link")).toHaveAttribute(
      "href",
      "/inventory/moves/1",
    );
    expect(within(rows[1]).queryByRole("link")).toBeNull();
  });

  it("points an empty journal at where things happen", () => {
    renderCard({ entries: [] });
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText("No moves yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to stock" })).toHaveAttribute(
      "href",
      "/inventory/stock",
    );
  });

  it("does not call a journal empty before it has arrived", () => {
    renderCard({ entries: [], loading: true });
    expect(screen.queryByText("No moves yet.")).toBeNull();
    expect(screen.getByRole("list")).toHaveAttribute("aria-busy", "true");
  });
});
