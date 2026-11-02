import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NutritionLabelScan } from "./NutritionLabelScan";
import { visionApi } from "@/lib/api/vision";

const toasts = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: toasts }));

vi.mock("@/lib/api/vision", () => ({
  visionApi: { extractNutrition: vi.fn() },
}));

// The compression is a browser canvas job with nothing to say about this.
vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
}));

const t = (key: string, options?: Record<string, unknown>) =>
  options?.count !== undefined ? `${key}:${String(options.count)}` : key;

const photo = () => new File(["label"], "label.jpg", { type: "image/jpeg" });

const onRead = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

const open = () => render(<NutritionLabelScan onRead={onRead} t={t} />);

describe("NutritionLabelScan", () => {
  it("hands the values to the form instead of saving them", async () => {
    // These numbers go on to count the calories in every recipe using the
    // ingredient, so the photograph fills the draft and stops there.
    vi.mocked(visionApi.extractNutrition).mockResolvedValue({
      energy_kcal: 884,
      fat: 100,
      saturated_fat: 14,
      salt: 0,
    });
    const user = userEvent.setup();
    const { container } = open();

    await user.upload(
      container.querySelector("input[type=file]") as HTMLInputElement,
      photo(),
    );

    await waitFor(() =>
      expect(onRead).toHaveBeenCalledWith({
        calories_kcal: 884,
        fat_g: 100,
        salt_g: 0,
      }),
    );
    // `saturated_fat` has no column in this table and is dropped rather than
    // guessed into one.
    expect(onRead.mock.calls[0][0]).not.toHaveProperty("saturated_fat");
  });

  it("leaves out what the label did not carry", async () => {
    vi.mocked(visionApi.extractNutrition).mockResolvedValue({
      energy_kcal: 40,
      proteins: null,
      fat: undefined,
    });
    const user = userEvent.setup();
    const { container } = open();

    await user.upload(
      container.querySelector("input[type=file]") as HTMLInputElement,
      photo(),
    );

    // A field left out keeps whatever the person typed; a field sent as null
    // would erase it.
    await waitFor(() =>
      expect(onRead).toHaveBeenCalledWith({ calories_kcal: 40 }),
    );
  });

  it("says so when the photo held no table, and changes nothing", async () => {
    vi.mocked(visionApi.extractNutrition).mockResolvedValue({});
    const user = userEvent.setup();
    const { container } = open();

    await user.upload(
      container.querySelector("input[type=file]") as HTMLInputElement,
      photo(),
    );

    await waitFor(() =>
      expect(toasts.warning).toHaveBeenCalledWith(
        "recipes:ingredient_defaults.scan_nothing_read",
      ),
    );
    expect(onRead).not.toHaveBeenCalled();
  });

  it("reports a failed reading rather than an empty form", async () => {
    vi.mocked(visionApi.extractNutrition).mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    const { container } = open();

    await user.upload(
      container.querySelector("input[type=file]") as HTMLInputElement,
      photo(),
    );

    await waitFor(() => expect(toasts.error).toHaveBeenCalled());
    expect(onRead).not.toHaveBeenCalled();
  });

  it("opens the camera rather than the gallery on a phone", () => {
    // The label being read is on a package in the reader's hand.
    const { container } = open();

    expect(container.querySelector("input[type=file]")).toHaveAttribute(
      "capture",
      "environment",
    );
  });
});
