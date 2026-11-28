import { useMutation } from "@tanstack/react-query";

import { useModuleQuery } from "@/module-sdk";
import { useAppMutation } from "@/module-sdk";
import type { QueryClient } from "@tanstack/react-query";

import {
  rentalsApi,
  type BookingCheckRequest,
  type BookingListParams,
  type BufferRuleIn,
  type KitCreate,
  type PickupRequest,
} from "../api/rentals";
import { queryKeys } from "../queryKeys";

const MODULE = "rentals";

function invalidateRentals(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: queryKeys.rentals.all });
}

export function useToday() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.today(),
    queryFn: rentalsApi.today,
  });
}

export function useCalendar(
  startsAt: string,
  endsAt: string,
  model?: string,
  category?: string,
  enabled = true,
) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.calendar(startsAt, endsAt, model, category),
    queryFn: () =>
      rentalsApi.calendar({
        starts_at: startsAt,
        ends_at: endsAt,
        model,
        category_id: category,
      }),
    extraEnabled: enabled,
  });
}

export function useBookings(params: BookingListParams) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.bookings(params as Record<string, unknown>),
    queryFn: () => rentalsApi.bookings(params),
  });
}

export function useKits() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.kits(),
    queryFn: rentalsApi.kits,
  });
}

export function useKit(id: string | undefined) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.kit(id ?? ""),
    queryFn: () => rentalsApi.kit(id as string),
    extraEnabled: Boolean(id),
  });
}

export function useCreateKit() {
  return useAppMutation(rentalsApi.createKit, invalidateRentals);
}

export function useUpdateKit() {
  return useAppMutation(
    ({ id, data }: { id: string; data: KitCreate }) =>
      rentalsApi.updateKit(id, data),
    invalidateRentals,
  );
}

export function useDeleteKit() {
  return useAppMutation(
    (id: string) => rentalsApi.deleteKit(id),
    invalidateRentals,
  );
}

export function useBooking(id: string | undefined) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.booking(id ?? ""),
    queryFn: () => rentalsApi.booking(id as string),
    extraEnabled: Boolean(id),
  });
}

export function useBlocks(params: Record<string, unknown>) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.blocks(params),
    queryFn: () => rentalsApi.blocks(params),
  });
}

export function useBufferRules() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.bufferRules(),
    queryFn: rentalsApi.bufferRules,
  });
}

export function useModels() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.models(),
    queryFn: rentalsApi.models,
  });
}

export function useRentalAssets(search: string, category?: string) {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.assets(search, category),
    queryFn: () =>
      rentalsApi.assets({ search: search || undefined, category_id: category }),
  });
}

export function useRentalCategories() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.categories(),
    queryFn: rentalsApi.categories,
  });
}

export function usePartners() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.partners(),
    queryFn: rentalsApi.partners,
  });
}

export function useMembers() {
  return useModuleQuery(MODULE, {
    queryKey: queryKeys.rentals.members(),
    queryFn: rentalsApi.members,
  });
}

/** The sheet's live check: a read, quiet on failure, refetched as the form changes. */
export function useBookingCheck() {
  return useMutation({
    mutationFn: (data: BookingCheckRequest) => rentalsApi.check(data),
  });
}

export function useCreateBooking() {
  return useAppMutation(rentalsApi.createBooking, invalidateRentals);
}

export function usePickupBooking() {
  return useAppMutation(
    ({ id, data }: { id: string; data: PickupRequest }) =>
      rentalsApi.pickup(id, data),
    invalidateRentals,
  );
}

export function useDeleteBlock() {
  return useAppMutation(
    (id: string) => rentalsApi.deleteBlock(id),
    invalidateRentals,
  );
}

export function useSetBufferRule() {
  return useAppMutation(
    (data: BufferRuleIn) => rentalsApi.setBufferRule(data),
    invalidateRentals,
  );
}

export function useDeleteBufferRule() {
  return useAppMutation(
    (id: string) => rentalsApi.deleteBufferRule(id),
    invalidateRentals,
  );
}
