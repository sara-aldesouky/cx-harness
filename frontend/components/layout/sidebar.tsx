import Link from "next/link";
import { Activity } from "lucide-react";

import { navigationItems } from "@/lib/constants/navigation";
import { cn } from "@/lib/utils";

export function Sidebar() {
  return (
    <aside className="bg-sidebar fixed inset-y-0 left-0 hidden w-64 border-r md:flex md:flex-col">
      <div className="flex h-16 items-center gap-3 border-b px-6">
        <div className="bg-sidebar-primary text-sidebar-primary-foreground flex size-9 items-center justify-center rounded-lg">
          <Activity className="size-5" aria-hidden="true" />
        </div>
        <div>
          <p className="font-semibold">CX Harness</p>
          <p className="text-muted-foreground text-xs">Model evaluation</p>
        </div>
      </div>
      <nav className="flex-1 space-y-1 p-3" aria-label="Primary navigation">
        {navigationItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.label}
              href={item.href}
              aria-disabled={item.disabled}
              tabIndex={item.disabled ? -1 : undefined}
              className={cn(
                "text-sidebar-foreground flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                item.disabled
                  ? "pointer-events-none opacity-50"
                  : "bg-sidebar-accent text-sidebar-accent-foreground font-medium",
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
