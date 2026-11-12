import type { ChatMessage, Citation } from "@/lib/api";

export interface UiMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  citations: readonly Citation[];
}

export function toUiMessage(m: ChatMessage): UiMessage {
  const parts = m.parts.parts;
  return {
    key: m.id,
    role: m.role,
    text: parts
      .filter((p) => p.type === "text")
      .map((p) => p.text ?? "")
      .join(""),
    citations: parts.filter((p) => p.type === "citations").flatMap((p) => p.items ?? []),
  };
}

export function isCitation(value: unknown): value is Citation {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.n === "number" &&
    typeof v.document_id === "string" &&
    typeof v.chunk_id === "string" &&
    typeof v.title === "string"
  );
}
