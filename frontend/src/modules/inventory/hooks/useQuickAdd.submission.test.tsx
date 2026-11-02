import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { visionApi } from "@/lib/api/vision";
import { onePage } from "@/test/mocks/page";
import type { VisionExtractResult } from "@/types";
import { useQuickAdd } from "./useQuickAdd";

vi.mock("sonner", () => {
  const toastFn = Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  });
  return { toast: toastFn };
});

vi.mock("@/lib/imageUtils", () => ({
  compressImage: (file: File) => Promise.resolve(file),
  prepareImageUpload: (file: File) => Promise.resolve(file),
}));

vi.mock("@/lib/api/vision", () => ({
  visionApi: { extract: vi.fn(), extractNutrition: vi.fn() },
}));

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>{children}</ModulesProvider>
    </QueryClientProvider>
  );
};

const pantry = { id: "cat-pantry", name: "Pantry", sort_order: 1 };
const tools = {
  id: "cat-tools",
  name: "Tools",
  sort_order: 2,
  context_tag: "workshop",
};

function serveCategories() {
  server.use(
    http.get("*/api/v1/categories", () =>
      HttpResponse.json(onePage([pantry, tools])),
    ),
  );
}

function fillIn(result: { current: ReturnType<typeof useQuickAdd> }) {
  act(() => {
    result.current.setFormData((prev) => ({
      ...prev,
      name: "Jam",
      quantity: "1",
      location_id: "1",
    }));
  });
}

/**
 * What happens around the create call: a file field's upload is written back
 * into the record's metadata (or reported when it fails), a refused create
 * says so instead of closing the form, a label's purpose preselects its
 * category, and a photographed category is matched to the picker's own
 * entry. Each failure here is a save that looks complete and is not.
 */
describe("useQuickAdd — around the save", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serveCategories();
  });

  it("uploads a file field as an attachment and writes its address into the metadata", async () => {
    let update: { metadata?: Record<string, unknown> } | undefined;
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json(
          { id: "new-item", name: "Jam", quantity: 1, metadata: { a: 1 } },
          { status: 201 },
        ),
      ),
      http.post("/api/v1/items/new-item/attachments", () =>
        HttpResponse.json({ id: "att-1", file_path: "manuals/jam.pdf" }),
      ),
      http.put("/api/v1/items/new-item", async ({ request }) => {
        update = (await request.json()) as typeof update;
        return HttpResponse.json({ id: "new-item" });
      }),
    );
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useQuickAdd({ onSuccess }), {
      wrapper: createWrapper(),
    });

    act(() =>
      result.current.handleFileSelect(
        "manual",
        new File(["pdf"], "jam.pdf", { type: "application/pdf" }),
      ),
    );
    fillIn(result);
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(update?.metadata).toEqual({
      a: 1,
      manual: "/uploads/manuals/jam.pdf",
    });
    expect(toast.success).toHaveBeenCalledWith("Product added!");
  });

  it("reports a failed attachment upload and still finishes the save", async () => {
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json(
          { id: "new-item", name: "Jam", quantity: 1, metadata: null },
          { status: 201 },
        ),
      ),
      http.post("/api/v1/items/new-item/attachments", () =>
        HttpResponse.json({ detail: "Disk full" }, { status: 400 }),
      ),
    );
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useQuickAdd({ onSuccess }), {
      wrapper: createWrapper(),
    });

    act(() =>
      result.current.handleFileSelect("manual", new File(["x"], "a.pdf")),
    );
    fillIn(result);
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("keeps the form open with a message when the create is refused", async () => {
    server.use(
      http.post("/api/v1/items", () =>
        HttpResponse.json({ detail: "Name taken" }, { status: 409 }),
      ),
    );
    const onSuccess = vi.fn();
    const { result } = renderHook(() => useQuickAdd({ onSuccess }), {
      wrapper: createWrapper(),
    });

    fillIn(result);
    await act(async () => {
      await result.current.submit();
    });

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0]?.[1]).toEqual({
      duration: 5000,
    });
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("preselects the category a label's purpose names", async () => {
    const { result } = renderHook(
      () => useQuickAdd({ onSuccess: vi.fn(), contextTag: "workshop" }),
      { wrapper: createWrapper() },
    );

    await waitFor(() =>
      expect(result.current.formData.category_id).toBe("cat-tools"),
    );
  });

  it("matches a photographed category to the picker's entry, and only suggests one it cannot find", async () => {
    vi.mocked(visionApi.extract).mockResolvedValueOnce({
      name: "Jam",
      category: "pantry",
    } as unknown as VisionExtractResult);
    const { result } = renderHook(() => useQuickAdd({ onSuccess: vi.fn() }), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.categories?.length).toBe(2));

    await act(async () => {
      await result.current.handleVisionAI([new File(["x"], "a.jpg")]);
    });
    expect(result.current.formData.category_id).toBe("cat-pantry");
    expect(toast).not.toHaveBeenCalled();

    vi.mocked(visionApi.extract).mockResolvedValueOnce({
      name: "Jam",
      category: "Spreads",
    } as unknown as VisionExtractResult);
    await act(async () => {
      await result.current.handleVisionAI([new File(["x"], "a.jpg")]);
    });
    expect(toast).toHaveBeenCalledWith(
      'AI suggests: "Spreads"',
      expect.any(Object),
    );
  });
});
