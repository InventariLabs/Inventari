import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderWithProviders, screen } from "@/test/utils";
import {
  useAiConnections,
  useAiPurposes,
} from "@/modules/settings/hooks/useAiConnections";
import { VisionTab } from "./VisionTab";

// The camera sentence branches on the registry's verdict about the
// image-reading purpose; the default stand-in is an organization whose
// registry answered and named the purpose unbound. The predicate itself
// stays real — only the registry answer is a stand-in.
vi.mock("@/modules/settings/hooks/useAiConnections", async (importOriginal) => {
  const actual =
    await importOriginal<
      typeof import("@/modules/settings/hooks/useAiConnections")
    >();
  return {
    ...actual,
    useAiConnections: vi.fn(() => ({ data: [], isSuccess: true })),
    useAiPurposes: vi.fn(() => ({ data: [], isSuccess: true })),
  };
});

/** A purpose row shaped like the registry serves it: the raw choice and
 * the verdict, in their separate fields. */
const purpose = (key: string, bound: string | null, usable: boolean) =>
  ({ key, bound_connection_id: bound, usable }) as never;

const renderTab = () =>
  renderWithProviders(
    <VisionTab
      onAnalyze={vi.fn()}
      onEnterManually={vi.fn()}
      isAnalyzing={false}
    />,
  );

describe("the camera sentence promises only what the registry vouched for", () => {
  beforeEach(() => {
    vi.mocked(useAiConnections).mockReturnValue({
      data: [],
      isSuccess: true,
    } as never);
    vi.mocked(useAiPurposes).mockReturnValue({
      data: [],
      isSuccess: true,
    } as never);
  });

  it("promises the fill-in when the registry vouches the purpose runs", () => {
    vi.mocked(useAiPurposes).mockReturnValue({
      data: [purpose("vision.extract", "conn-1", true)],
      isSuccess: true,
    } as never);
    renderTab();

    expect(
      screen.getByText(/AI can fill in the name, brand and expiry date/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No AI connection is configured yet/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /take product photo/i }),
    ).toBeEnabled();
  });

  it("refuses, and stops the invitation into the refusal, when nothing is chosen", () => {
    renderTab();

    expect(
      screen.getByText(/No AI connection is configured yet/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/AI can fill in the name, brand and expiry date/),
    ).not.toBeInTheDocument();
    // The sentence explains why; the button does not lead into the 503.
    expect(
      screen.getByRole("button", { name: /take product photo/i }),
    ).toBeDisabled();
    expect(screen.getByText(/Set one up in Settings/)).toBeInTheDocument();
  });

  it("does not promise on a bound connection the verdict refuses", () => {
    // The measured 503 state, as the registry now reports it: the org
    // chose a text-only connection for vision.extract — the choice stays
    // readable in bound_connection_id — while `usable` carries the
    // refusal. A text binding elsewhere does not change that.
    vi.mocked(useAiConnections).mockReturnValue({
      data: [{ id: "conn-1" } as never],
      isSuccess: true,
    } as never);
    vi.mocked(useAiPurposes).mockReturnValue({
      data: [
        purpose("vision.extract", "conn-1", false),
        purpose("recipes.text_parse", "conn-1", true),
      ],
      isSuccess: true,
    } as never);
    renderTab();

    expect(
      screen.getByText(/No AI connection is configured yet/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/AI can fill in the name, brand and expiry date/),
    ).not.toBeInTheDocument();
  });

  it("says neither sentence while the registry has not answered", () => {
    // A registry that failed to load stays out of the way (the recipe
    // import tab's rule): a promise would be a guess, a refusal a lie.
    vi.mocked(useAiPurposes).mockReturnValue({
      data: undefined,
      isSuccess: false,
    } as never);
    renderTab();

    expect(
      screen.queryByText(/AI can fill in the name, brand and expiry date/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/No AI connection is configured yet/),
    ).not.toBeInTheDocument();
    // And the camera stays alone with its question — the backend may work.
    expect(
      screen.getByRole("button", { name: /take product photo/i }),
    ).toBeEnabled();
  });
});
