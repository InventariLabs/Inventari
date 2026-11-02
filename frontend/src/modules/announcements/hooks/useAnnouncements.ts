import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { announcementsApi } from "@/modules/announcements/api/announcements";
import type { Announcement } from "@/modules/announcements/types/notifications";

export function useAdminAnnouncements() {
  return useQuery<Announcement[]>({
    queryKey: queryKeys.admin.announcements,
    queryFn: () => announcementsApi.getAll(),
  });
}

export function useActiveAnnouncements() {
  return useQuery<Announcement[]>({
    queryKey: queryKeys.announcements.active,
    queryFn: () => announcementsApi.getActive(),
  });
}
