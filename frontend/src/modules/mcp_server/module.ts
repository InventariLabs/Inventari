import { lazy } from "react";
import { Server } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

const IndexPage = lazy(() => import("./pages/IndexPage"));

moduleRegistry.register({
  name: "mcp_server",
  routes: [
    {
      path: "/mcp-server",
      component: IndexPage,
    },
  ],
  // The launcher lists only modules that declare a tile: without it the module
  // is switched on and then reachable only by its address.
  launcher: {
    displayName: "mcp_server:navigation.title",
    description: "mcp_server:description",
    icon: Server,
    category: "business",
  },
  moduleNav: {
    basePath: "/mcp-server",
    items: [
      {
        // Absolute: the shell links a nav item exactly as written.
        path: "/mcp-server",
        icon: Server,
        labelKey: "mcp_server:navigation.title",
      },
    ],
  },
});
