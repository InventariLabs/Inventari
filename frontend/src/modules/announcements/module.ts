import { Megaphone } from "lucide-react";
import AnnouncementBanner from "./components/AnnouncementBanner";
import { moduleRegistry } from "@/lib/moduleRegistry";

moduleRegistry.register({
  name: "announcements",
  launcher: {
    displayName: "",
    icon: Megaphone,
    hidden: true,
  },
  routes: [],
  slots: [
    {
      slot: "global_notifications",
      component: AnnouncementBanner,
      priority: 1, // High priority to show at the top
    },
  ],
});
