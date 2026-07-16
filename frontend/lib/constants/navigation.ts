import {
  Boxes,
  Gauge,
  MessagesSquare,
  Package,
  PackageOpen,
  Play,
  Settings,
  Sparkles,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export interface NavigationItem {
  label: string;
  href: string;
  icon: LucideIcon;
  disabled?: boolean;
}

export const navigationItems: NavigationItem[] = [
  { label: "Overview", href: "/", icon: Gauge },
  { label: "Customers", href: "/customers", icon: Users },
  { label: "Orders", href: "/orders", icon: Package },
  {
    label: "Order Items",
    href: "/order-items",
    icon: PackageOpen,
  },
  {
    label: "Conversations",
    href: "/conversations",
    icon: MessagesSquare,
    disabled: true,
  },
  { label: "Messages", href: "/messages", icon: Sparkles, disabled: true },
  { label: "Model Runs", href: "/model-runs", icon: Play, disabled: true },
  { label: "Tool Calls", href: "/tool-calls", icon: Wrench, disabled: true },
  { label: "Evaluations", href: "/evaluations", icon: Boxes, disabled: true },
  { label: "Settings", href: "/settings", icon: Settings, disabled: true },
];
