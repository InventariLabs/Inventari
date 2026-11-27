import { lazy } from "react";
import { CalendarClock } from "lucide-react";
import { moduleRegistry } from "@/module-sdk";

const TodayPage = lazy(() => import("./pages/TodayPage"));
const CalendarPage = lazy(() => import("./pages/CalendarPage"));
const BookingsPage = lazy(() => import("./pages/BookingsPage"));
const NewBookingPage = lazy(() => import("./pages/NewBookingPage"));
const BookingDetailPage = lazy(() => import("./pages/BookingDetailPage"));
const PickupPage = lazy(() => import("./pages/PickupPage"));
const BlocksPage = lazy(() => import("./pages/BlocksPage"));
const GuidePage = lazy(() => import("./pages/GuidePage"));

moduleRegistry.register({
  name: "rentals",
  launcher: {
    displayName: "rentals:navigation.title",
    description: "rentals:description",
    icon: CalendarClock,
    category: "business",
    order: 30,
  },
  moduleNav: {
    basePath: "/rentals",
    items: [
      {
        path: "/rentals",
        icon: CalendarClock,
        labelKey: "rentals:navigation.title",
        titleKey: "rentals:title",
        order: 10,
        mobileBar: true,
      },
    ],
  },
  routes: [
    { path: "/rentals", component: TodayPage },
    { path: "/rentals/calendar", component: CalendarPage },
    { path: "/rentals/bookings", component: BookingsPage },
    { path: "/rentals/bookings/new", component: NewBookingPage },
    { path: "/rentals/bookings/:id", component: BookingDetailPage },
    { path: "/rentals/bookings/:id/pickup", component: PickupPage },
    { path: "/rentals/blocks", component: BlocksPage },
    { path: "/rentals/guide", component: GuidePage },
  ],
});
