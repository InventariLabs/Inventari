import React from "react";
import {
  Apple,
  Archive,
  Baby,
  Backpack,
  BarChart3,
  Beef,
  Beer,
  BookOpen,
  Box,
  Building,
  Building2,
  CakeSlice,
  Camera,
  Candy,
  Carrot,
  CheckCheck,
  ChefHat,
  Cherry,
  ClipboardCheck,
  Coffee,
  Cookie,
  CookingPot,
  CupSoda,
  Container,
  Cpu,
  Cross,
  Croissant,
  Dog,
  Drumstick,
  Egg,
  FileCheck,
  Fish,
  FlaskConical,
  GlassWater,
  Grape,
  Hammer,
  Home,
  IceCream,
  Key,
  Landmark,
  Laptop,
  Leaf,
  LeafyGreen,
  Lock,
  Milk,
  Monitor,
  MonitorSmartphone,
  Mouse,
  Package,
  Pill,
  Pizza,
  Printer,
  Refrigerator,
  Sandwich,
  Server,
  Settings,
  Shapes,
  Shell,
  ShoppingBag,
  ShoppingBasket,
  ShoppingCart,
  Smartphone,
  Snowflake,
  SoapDispenserDroplet,
  Soup,
  Stethoscope,
  Store,
  Thermometer,
  Truck,
  Utensils,
  Warehouse,
  Webhook,
  Wheat,
  Wifi,
  Wine,
  Wrench,
  Zap,
  Factory,
  Move,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const ICON_MAP: Record<string, LucideIcon> = {
  Apple,
  Archive,
  Baby,
  Backpack,
  BarChart3,
  Beef,
  Beer,
  BookOpen,
  Box,
  Building,
  Building2,
  CakeSlice,
  Camera,
  Candy,
  Carrot,
  CheckCheck,
  Cheese: Cookie,
  ChefHat,
  Cherry,
  ClipboardCheck,
  Coffee,
  Cookie,
  CookingPot,
  CupSoda,
  Container,
  Cpu,
  Cross,
  Croissant,
  Dog,
  Drumstick,
  Egg,
  FileCheck,
  Fish,
  FlaskConical,
  GlassWater,
  Grape,
  Hammer,
  Home,
  IceCream,
  Key,
  Landmark,
  Laptop,
  Leaf,
  LeafyGreen,
  Lock,
  Milk,
  Monitor,
  MonitorSmartphone,
  Mouse,
  Package,
  Pill,
  Pint: Beer,
  Pizza,
  Printer,
  Refrigerator,
  Sandwich,
  Server,
  Settings,
  Shapes,
  Shell,
  ShoppingBag,
  ShoppingBasket,
  ShoppingCart,
  Smartphone,
  Snowflake,
  SoapDispenserDroplet,
  Soup,
  Stethoscope,
  Store,
  Thermometer,
  Truck,
  Utensils,
  Warehouse,
  Webhook,
  Wheat,
  Wifi,
  Wine,
  Wrench,
  Zap,
  Factory,
  Move,
};

function normalizeIconName(name: string): string {
  return name
    .split(/[-_]/)
    .map(
      (segment) =>
        segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase(),
    )
    .join("");
}

function resolveIcon(name: string): LucideIcon {
  if (ICON_MAP[name]) return ICON_MAP[name];

  const pascal = normalizeIconName(name);
  if (ICON_MAP[pascal]) return ICON_MAP[pascal];

  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console -- dev diagnostics for missing icon
    console.warn(
      `[DynamicIcon] Icon "${name}" not found in ICON_MAP. Falling back to Package.`,
    );
  }

  return Package;
}

export const DynamicIcon: React.FC<{
  name: string;
  size?: number;
  className?: string;
  strokeWidth?: number;
}> = ({ name, ...props }) => {
  const IconComponent = resolveIcon(name);
  return <IconComponent {...props} />;
};
