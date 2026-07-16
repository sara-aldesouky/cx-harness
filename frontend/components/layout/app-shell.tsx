import { Sidebar } from "@/components/layout/sidebar";
import { TopNavigation } from "@/components/layout/top-navigation";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-muted/30 min-h-screen">
      <Sidebar />
      <div className="md:pl-64">
        <TopNavigation />
        <main>{children}</main>
      </div>
    </div>
  );
}
