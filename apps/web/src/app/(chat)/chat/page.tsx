import { NewChatPageClient } from "./new-chat-page-client";

type ChatPageSearchParams = Promise<{
  intent?: string | string[];
}>;

function readIntent(value: string | string[] | undefined) {
  return typeof value === "string" ? value : undefined;
}

export default async function NewChatPage({
  searchParams,
}: {
  searchParams: ChatPageSearchParams;
}) {
  const resolvedSearchParams = await searchParams;

  return (
    <NewChatPageClient initialIntent={readIntent(resolvedSearchParams.intent)} />
  );
}
