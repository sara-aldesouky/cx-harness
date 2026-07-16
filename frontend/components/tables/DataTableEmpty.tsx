import { SearchX } from "lucide-react";

export function DataTableEmpty({
  colSpan,
  message = "No records found.",
}: {
  colSpan: number;
  message?: string;
}) {
  return (
    <tbody>
      <tr>
        <td colSpan={colSpan} className="h-56 text-center">
          <div className="text-muted-foreground flex flex-col items-center justify-center gap-3">
            <SearchX className="size-8" aria-hidden="true" />
            <p className="text-sm">{message}</p>
          </div>
        </td>
      </tr>
    </tbody>
  );
}
