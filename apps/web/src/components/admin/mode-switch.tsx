"use client";

import Link from "next/link";

/** Admin-only "Chat | Admin console" switch at the top of the left panel. */
export function ModeSwitch({ active }: { active: "chat" | "admin" }) {
  const item = (mode: "chat" | "admin", href: string, label: string) => (
    <Link
      href={href}
      aria-current={active === mode ? "page" : undefined}
      className={`rounded-md px-2 py-1 text-center ${
        active === mode
          ? "bg-neutral-200 font-medium dark:bg-neutral-800"
          : "text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
      }`}
    >
      {label}
    </Link>
  );
  return (
    <nav
      aria-label="Switch between chat and admin console"
      className="mx-3 mb-2 grid grid-cols-2 rounded-lg border border-neutral-300 p-0.5 text-xs dark:border-neutral-700"
    >
      {item("chat", "/", "Chat")}
      {item("admin", "/admin", "Admin console")}
    </nav>
  );
}
