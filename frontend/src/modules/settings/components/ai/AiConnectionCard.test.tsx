import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";

import { AiConnectionCard } from "@/modules/settings/components/ai/AiConnectionCard";
import { renderWithProviders } from "@/test/utils";
import type { AiConnection } from "@/types/ai";

const connection = (over: Partial<AiConnection> = {}): AiConnection => ({
  id: "c1",
  name: "Label reader",
  provider: "openrouter",
  api_key: "**********",
  api_base_url: "",
  model_name: "deepseek-v4-flash",
  temperature: null,
  max_tokens: null,
  top_p: null,
  capabilities: ["vision"],
  capability_checks: {},
  created_at: "",
  updated_at: "",
  ...over,
});

const render = (over: Partial<AiConnection> = {}) =>
  renderWithProviders(
    <AiConnectionCard
      connection={connection(over)}
      isBoundHere={false}
      onEdit={vi.fn()}
      onDelete={vi.fn()}
    />,
  );

/**
 * A capability is a claim until the model is asked to make good on it.
 *
 * The card drew it as a fact, and the claim usually came from the form
 * guessing off the provider's name: a connection to a text-only model through
 * an OpenAI-compatible endpoint wore a VISION badge that nothing could take
 * off — and stayed on the list of things to read photographs with.
 */
describe("AiConnectionCard — declared, confirmed, failed", () => {
  it("says a capability is unverified when nobody has tested it", () => {
    render();
    expect(screen.getByText(/Declared, not yet checked/i)).toBeInTheDocument();
  });

  it("marks a capability the connection test confirmed", () => {
    render({ capability_checks: { vision: { ok: true } } });
    expect(
      screen.getByText(/Confirmed by the connection test/i),
    ).toBeInTheDocument();
  });

  it("does not leave a failed test invisible", () => {
    render({ capability_checks: { vision: { ok: false } } });
    expect(screen.getByText(/failed this test/i)).toBeInTheDocument();
    expect(
      screen.getByText(/not offered for purposes that need it/i),
    ).toBeInTheDocument();
  });
});
