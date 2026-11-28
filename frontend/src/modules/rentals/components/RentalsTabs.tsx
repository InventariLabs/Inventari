import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { ScrollRow } from "@/module-sdk";

const TABS = [
  { to: "/rentals", key: "tabs.today", end: true },
  { to: "/rentals/calendar", key: "tabs.calendar", end: false },
  { to: "/rentals/bookings", key: "tabs.bookings", end: false },
  { to: "/rentals/kits", key: "tabs.kits", end: false },
  { to: "/rentals/blocks", key: "tabs.blocks", end: false },
] as const;

/** The module's views as one tab row. */
export function RentalsTabs() {
  const { t } = useTranslation("rentals");
  return (
    <ScrollRow>
      <div
        role="tablist"
        aria-label={t("tabs.label")}
        className="flex gap-1 border-b border-zinc-200"
      >
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            role="tab"
            className={({ isActive }) =>
              `flex min-h-11 items-center px-3.5 py-2.5 text-sm ${
                isActive
                  ? "border-b-2 border-teal-700 font-semibold text-teal-700"
                  : "border-b-2 border-transparent text-zinc-500 hover:text-zinc-800"
              }`
            }
          >
            {t(tab.key)}
          </NavLink>
        ))}
      </div>
    </ScrollRow>
  );
}
