import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { ModelSelectCard } from "./ModelSelectCard";

function renderCard() {
  return render(
    <MemoryRouter>
      <ModelSelectCard models={[]} selectedModelId="" onSelect={vi.fn()} />
    </MemoryRouter>,
  );
}

describe("ModelSelectCard", () => {
  it("keeps the create link out of the heading's accessible name", () => {
    // The link used to live inside the heading's node, so the heading's
    // accessible name glued into "Select model (optional)Create model" —
    // one name for a heading and an action that are two things.
    renderCard();

    expect(
      screen.getByRole("heading", { name: "Select model (optional)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /create model/i }),
    ).toBeInTheDocument();
  });
});
