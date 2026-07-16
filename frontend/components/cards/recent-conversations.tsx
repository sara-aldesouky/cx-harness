import { MessageSquareText } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { ConversationSummary } from "@/types";

interface RecentConversationsProps {
  conversations: ConversationSummary[];
  customerNames: ReadonlyMap<string, string>;
}

const dateTimeFormatter = new Intl.DateTimeFormat("en", {
  dateStyle: "medium",
  timeStyle: "short",
});

export function RecentConversations({
  conversations,
  customerNames,
}: RecentConversationsProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <MessageSquareText
            className="text-muted-foreground size-4"
            aria-hidden="true"
          />
          <CardTitle>Recent conversations</CardTitle>
        </div>
        <CardDescription>Latest customer support activity</CardDescription>
      </CardHeader>
      <CardContent>
        {conversations.length === 0 ? (
          <EmptyState
            title="No conversations"
            description="Conversation activity will appear here."
          />
        ) : (
          <ul className="divide-y" aria-label="Recent conversations">
            {conversations.map((conversation) => (
              <li
                key={conversation.id}
                className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">
                      {customerNames.get(conversation.customer_id) ??
                        "Unknown customer"}
                    </p>
                    <p className="text-muted-foreground truncate text-xs">
                      {conversation.related_order_id
                        ? `Order ${conversation.related_order_id.slice(0, 8)}…`
                        : "No related order"}
                    </p>
                  </div>
                  <Badge variant="secondary">
                    {conversation.status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <div className="text-muted-foreground flex items-center justify-between text-xs">
                  <span className="capitalize">{conversation.channel}</span>
                  <time dateTime={conversation.updated_at}>
                    {dateTimeFormatter.format(
                      new Date(conversation.updated_at),
                    )}
                  </time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
