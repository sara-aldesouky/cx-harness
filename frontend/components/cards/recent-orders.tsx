import { ShoppingBag } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { OrderSummary } from "@/types";

interface RecentOrdersProps {
  orders: OrderSummary[];
  customerNames: ReadonlyMap<string, string>;
}

const currencyFormatter = new Intl.NumberFormat("en", {
  style: "currency",
  currency: "EGP",
});

export function RecentOrders({ orders, customerNames }: RecentOrdersProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ShoppingBag
            className="text-muted-foreground size-4"
            aria-hidden="true"
          />
          <CardTitle>Recent orders</CardTitle>
        </div>
        <CardDescription>Latest commerce activity</CardDescription>
      </CardHeader>
      <CardContent>
        {orders.length === 0 ? (
          <EmptyState
            title="No orders"
            description="Recent orders will appear here."
          />
        ) : (
          <ul className="divide-y" aria-label="Recent orders">
            {orders.map((order) => (
              <li
                key={order.id}
                className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {order.order_number}
                  </p>
                  <p className="text-muted-foreground truncate text-xs">
                    {customerNames.get(order.customer_id) ?? "Unknown customer"}{" "}
                    · {currencyFormatter.format(Number(order.total_amount))}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge variant="secondary">{order.status}</Badge>
                  <span className="text-muted-foreground text-xs">
                    {order.payment_status.replaceAll("_", " ")}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
