"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MessageBubbleProps {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
}

export function MessageBubble({ role, text, streaming = false }: MessageBubbleProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-blue-600 px-4 py-2 text-sm text-white">
          {text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex">
      <div className="prose prose-sm prose-neutral max-w-[85%] dark:prose-invert [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-neutral-100 [&_pre]:p-3 dark:[&_pre]:bg-neutral-900">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        {streaming && <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-neutral-400" />}
      </div>
    </div>
  );
}
