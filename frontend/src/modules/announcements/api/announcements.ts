import { api, getEveryPage, type Page } from "@/lib/api/client";
import type {
  Announcement,
  UserNotification,
} from "@/modules/announcements/types/notifications";

export const announcementsApi = {
  getActive: async (): Promise<Announcement[]> => {
    return getEveryPage<Announcement>("/announcements/active");
  },

  getAll: async (): Promise<Announcement[]> => {
    return getEveryPage<Announcement>("/announcements");
  },

  create: async (data: {
    title: string;
    content: string;
    type?: string;
    active_until?: string;
  }): Promise<Announcement> => {
    const response = await api.post("/announcements", data);
    return response.data;
  },

  delete: async (id: string): Promise<void> => {
    await api.delete(`/announcements/${id}`);
  },
};

export const notificationsApi = {
  getAll: async (unreadOnly = false): Promise<UserNotification[]> => {
    // The newest page only: the bell shows the latest, not the whole history.
    const response = await api.get<Page<UserNotification>>("/notifications", {
      params: { unread_only: unreadOnly },
    });
    return response.data.items;
  },

  markRead: async (id: string): Promise<Record<string, unknown>> => {
    const response = await api.patch(`/notifications/${id}`, { is_read: true });
    return response.data;
  },

  markAllRead: async (): Promise<Record<string, unknown>> => {
    const response = await api.post("/notifications/read-all");
    return response.data;
  },

  delete: async (id: string): Promise<Record<string, unknown>> => {
    const response = await api.delete(`/notifications/${id}`);
    return response.data;
  },
};
