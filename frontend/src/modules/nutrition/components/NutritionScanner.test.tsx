import { fireEvent, waitFor } from "@/test/utils";
import { render, screen } from "@/test/utils";
import { describe, it, expect, vi } from "vitest";
import {
  useAiConnections,
  useAiPurposes,
} from "@/modules/settings/hooks/useAiConnections";
import { toast } from "sonner";
import NutritionScanner from "./NutritionScanner";
import { visionApi } from "@/lib/api/vision";

// jsdom has no canvas, so the real compressor never settles.
vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
}));

vi.mock("@/lib/api/vision", () => ({
  visionApi: { extractNutrition: vi.fn() },
}));

vi.mock("@/modules/nutrition/hooks/useNutrition", () => ({
  useUpdateNutrition: () => ({ mutateAsync: vi.fn() }),
  useSaveNutritionToItem: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// The how-it-works sentence branches on the registry's verdict about the
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

/** An error shaped like the ones the API client produces for a 422 detail. */
function axiosError(detail: string): Error {
  return Object.assign(new Error("Request failed with status code 422"), {
    isAxiosError: true,
    response: { status: 422, data: { detail } },
  });
}

const upload = async (file: File) => {
  const { container } = render(
    <NutritionScanner
      itemId="item-1"
      templateId="tpl-1"
      onSuccess={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const input = container.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
};

describe("the how-it-works sentence promises only what is configured", () => {
  const renderScanner = () =>
    render(
      <NutritionScanner
        itemId="item-1"
        templateId="tpl-1"
        onSuccess={vi.fn()}
        onClose={vi.fn()}
      />,
    );

  it("promises the extraction when the registry vouches the purpose runs", () => {
    vi.mocked(useAiPurposes).mockReturnValue({
      data: [purpose("vision.extract", "conn-1", true)],
      isSuccess: true,
    } as never);
    renderScanner();

    expect(screen.getByText(/AI can extract/)).toBeInTheDocument();
    expect(
      screen.queryByText(/Without an AI connection nothing is extracted/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Set one up in Settings/),
    ).not.toBeInTheDocument();
  });

  it("says there is nothing to read with — and offers the way to fix it", () => {
    vi.mocked(useAiPurposes).mockReturnValue({
      data: [purpose("vision.extract", null, false)],
      isSuccess: true,
    } as never);
    renderScanner();

    expect(
      screen.getByText(/Without an AI connection nothing is extracted/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/AI can extract/)).not.toBeInTheDocument();
    // The same door the quick-add camera offers: the sentence names what
    // is missing, the link names where to fix it.
    expect(screen.getByText(/Set one up in Settings/)).toBeInTheDocument();
    // And the refusal is real for the control itself, not only its paint.
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    expect(input.disabled).toBe(true);
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
    renderScanner();

    expect(
      screen.getByText(/Without an AI connection nothing is extracted/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/AI can extract/)).not.toBeInTheDocument();
  });

  it("says neither sentence while the registry has not answered", () => {
    // A registry that failed to load stays out of the way (the recipe
    // import tab's rule): a promise would be a guess, a refusal a lie.
    vi.mocked(useAiPurposes).mockReturnValue({
      data: undefined,
      isSuccess: false,
    } as never);
    renderScanner();

    expect(screen.queryByText(/AI can extract/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Without an AI connection nothing is extracted/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Set one up in Settings/),
    ).not.toBeInTheDocument();
  });
});

describe("NutritionScanner failure reporting", () => {
  it("shows the backend message naming the connection and model", async () => {
    vi.mocked(visionApi.extractNutrition).mockRejectedValue(
      axiosError(
        'The AI could not read this nutrition table using connection "Label Reader" (model "gpt-4o-mini").',
      ),
    );

    await upload(new File(["x"], "table.jpg", { type: "image/jpeg" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("Label Reader"),
    );
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      expect.stringContaining("gpt-4o-mini"),
    );
  });

  it("falls back to the static wording when the error carries no message", async () => {
    vi.mocked(visionApi.extractNutrition).mockRejectedValue(
      new Error("network down"),
    );

    await upload(new File(["x"], "table.jpg", { type: "image/jpeg" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith(
      "Failed to read the table. Try taking a clearer photo.",
    );
  });
});
