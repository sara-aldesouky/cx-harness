import { ThemeToggle } from "@/components/layout/theme-toggle";

export function TopNavigation() {
  return (
    <header className="bg-background/95 sticky top-0 z-20 flex h-16 items-center justify-between border-b px-4 backdrop-blur md:px-8">
      <div>
        <p className="text-sm font-medium md:hidden">CX Harness</p>
        <p className="text-muted-foreground hidden text-sm md:block">
          Customer experience model evaluation
        </p>
      </div>
      <ThemeToggle />
    </header>
  );
}
