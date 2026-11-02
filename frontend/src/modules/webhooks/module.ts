import { lazy } from "react";
import { Webhook } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const WebhooksPage = lazy(() => import("./pages/WebhooksPage"));

moduleRegistry.register({
  name: "webhooks",
  // No launcher tile and no flat route: the screen lives in settings, which is
  // where the sidebar links and where the shell provides the page header this
  // page needs. `/webhooks` stays alive as a redirect in App.tsx.
  routes: [],
  settingsSections: [
    {
      title: "webhooks:navigation.webhooks",
      path: "webhooks",
      icon: Webhook,
      component: WebhooksPage,
    },
  ],
});
