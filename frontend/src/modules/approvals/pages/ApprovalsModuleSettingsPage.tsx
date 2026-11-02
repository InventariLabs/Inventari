import ModuleSettingsPage from "@/modules/settings/pages/ModuleSettingsPage";

/**
 * Approvals settings, reachable from the settings sidebar.
 *
 * The generic schema screen served this module only at
 * `/settings/modules/approvals`, an address nothing in the app linked to — the
 * sidebar builds its entries from `settingsSections`, which this module
 * never declared (the same gap recipes once had, closed by moving its
 * settings into the module).
 */
export default function ApprovalsModuleSettingsPage() {
  {
    return <ModuleSettingsPage moduleName="approvals" />;
  }
}
