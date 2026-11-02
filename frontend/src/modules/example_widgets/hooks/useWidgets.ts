import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/module-sdk";
import type {
  Widget,
  WidgetCreateInput,
  WidgetPage,
  WidgetUpdate,
} from "./types";

const QUERY_KEY = ["example-widgets"];

export function useWidgets() {
  return useQuery<WidgetPage>({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const response = await api.get<WidgetPage>("/example-widgets");
      return response.data;
    },
  });
}

export function useCreateWidget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: WidgetCreateInput) => {
      const response = await api.post<Widget>("/example-widgets", data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useUpdateWidget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, data }: { id: string; data: WidgetUpdate }) => {
      const response = await api.patch<Widget>(`/example-widgets/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useDeleteWidget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/example-widgets/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
