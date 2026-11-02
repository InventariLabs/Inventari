import { lazy } from "react";
import { LayoutDashboard, Settings, CheckCheck } from "lucide-react";

import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";

import { ApprovalStatusSlot } from "./slots/ApprovalStatusSlot";
import { ApprovalRequestBadgeSlot } from "./slots/ApprovalRequestBadgeSlot";
import { ApprovalDecisionPanelSlot } from "./slots/ApprovalDecisionPanelSlot";
import { ApprovalParkedRequestsSlot } from "./slots/ApprovalParkedRequestsSlot";
import { DocumentApprovalSetupNoticeSlot } from "./slots/DocumentApprovalSetupNoticeSlot";
import { useApprovalActionItems } from "./hooks/useApprovalActionItems";

const ApprovalsDashboard = lazy(() => import("./pages/ApprovalsDashboard"));
const WorkflowSettingsPage = lazy(() => import("./pages/WorkflowSettingsPage"));
const ApprovalsModuleSettingsPage = lazy(
  () => import("./pages/ApprovalsModuleSettingsPage"),
);

moduleRegistry.register({
  name: "approvals",
  launcher: {
    displayName: "approvals:launcher.title",
    description: "approvals:launcher.description",
    icon: CheckCheck,
    category: "business",
    color: "bg-violet-500",
    order: 25,
  },
  // The self-approve hatch lives on the generic settings screen, and the
  // sidebar builds its entries from this list — without a declaration here,
  // the screen was reachable only by typing its address.
  settingsSections: [
    {
      title: "approvals:navigation.settings",
      path: "modules/approvals",
      icon: Settings,
      component: ApprovalsModuleSettingsPage,
    },
  ],
  moduleNav: {
    basePath: "/approvals",
    items: [
      {
        path: "/approvals",
        icon: LayoutDashboard,
        labelKey: "approvals:navigation.dashboard",
        order: 10,
      },
      {
        path: "/approvals/workflows",
        icon: Settings,
        labelKey: "approvals:navigation.workflows",
        order: 20,
      },
    ],
  },
  routes: [
    { path: "/approvals", component: ApprovalsDashboard },
    { path: "/approvals/workflows", component: WorkflowSettingsPage },
  ],
  slots: [
    {
      slot: "approval_status_badge",
      component: slotComponent(ApprovalStatusSlot),
      priority: 50,
    },
    {
      slot: "approval_request_badge",
      component: slotComponent(ApprovalRequestBadgeSlot),
      priority: 50,
    },
    {
      slot: "approval_decision_panel",
      component: slotComponent(ApprovalDecisionPanelSlot),
      priority: 50,
    },
    {
      slot: "approval_parked_requests",
      component: slotComponent(ApprovalParkedRequestsSlot),
      priority: 50,
    },
    {
      slot: "document_approval_setup_notice",
      component: slotComponent(DocumentApprovalSetupNoticeSlot),
      priority: 50,
    },
  ],
  useActionItems: useApprovalActionItems,
  // Permissions live in backend/app/modules/approvals/manifest.json — one
  // declaration point. They used to be repeated here, where nothing read them.
});
