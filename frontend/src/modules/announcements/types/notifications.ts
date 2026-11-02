import type { components } from "@/types/api-generated";
// Notification / announcement types.

export type Announcement = components["schemas"]["AnnouncementDTO"];

export interface UserNotification {
  id: string;
  title: string;
  content: string;
  type: string;
  is_read: boolean;
  link?: string;
  created_at: string;
}
