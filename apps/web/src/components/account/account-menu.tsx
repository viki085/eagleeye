"use client";

import { useClerk, useOrganization, useUser } from "@clerk/nextjs";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { useApi } from "@/hooks/use-api";
import type { UsageSummary } from "@/lib/api";
import { initialsOf, menuPosition, nextIndex, type MenuPlacement, type MenuPosition } from "@/lib/account-menu";

interface AccountMenuProps {
  /** "below": opens under the avatar (headers). "right": opens beside it (collapsed rail). */
  placement?: MenuPlacement;
  role?: "admin" | "member";
  /** Shared demo account: no account settings (the password is shared), "Demo" badge. */
  isDemo?: boolean;
}

const MENU_WIDTH = 288;
const ITEM =
  "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-neutral-700 outline-none transition hover:bg-[#9E8253]/[0.09] focus-visible:bg-[#9E8253]/[0.12] focus-visible:ring-2 focus-visible:ring-[#9E8253]/40 dark:text-neutral-200 dark:hover:bg-[#C5A368]/[0.08] dark:focus-visible:bg-[#C5A368]/[0.12]";

function Avatar({ size, image, initials }: { size: number; image: string | null; initials: string }) {
  const style = { width: size, height: size };
  if (image) {
    // Clerk-hosted avatar: a plain <img> avoids configuring remote image domains
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={image} alt="" style={style} className="rounded-full object-cover" />;
  }
  return (
    <span style={style} className="grid place-items-center rounded-full bg-[#1C1B18] text-[11px] font-semibold tracking-wide text-[#C5A368]">
      {initials}
    </span>
  );
}

function MenuIcon({ path }: { path: ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden className="shrink-0 text-[#9E8253] dark:text-[#C5A368]">
      {path}
    </svg>
  );
}

function UsageRow({ usage }: { usage: UsageSummary | null }) {
  if (!usage || usage.limit_usd === null) return null; // demo visitors: no money figures
  const share = usage.limit_usd > 0 ? Math.min(1, usage.cost_usd / usage.limit_usd) : 0;
  return (
    <div className="px-3 py-2.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-medium text-neutral-600 dark:text-neutral-300">Usage</span>
        <span className="tabular-nums text-neutral-500">
          ${usage.cost_usd.toFixed(2)} of ${usage.limit_usd.toFixed(2)}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/[0.08]"
        role="meter" aria-label="Usage against your limit" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}>
        <div className="h-full rounded-full bg-[#9E8253]" style={{ width: `${Math.max(share * 100, 2)}%` }} />
      </div>
      <p className="mt-1 text-[11px] text-neutral-500">{usage.runs.toLocaleString()} answers so far</p>
    </div>
  );
}

/** EagleEye's account menu (replaces Clerk's default UserButton popover). */
export function AccountMenu({ placement = "below", role, isDemo = false }: AccountMenuProps) {
  const { user, isLoaded } = useUser();
  const { organization } = useOrganization();
  const clerk = useClerk();
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<MenuPosition | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);

  useLayoutEffect(() => {
    if (!open || !trigger.current) return;
    const place = () => {
      const r = trigger.current!.getBoundingClientRect();
      setPos(menuPosition(r, placement, MENU_WIDTH, window.innerWidth, window.innerHeight));
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [open, placement]);

  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    let cancelled = false;
    api.getUsage().then((u) => !cancelled && setUsage(u)).catch(() => !cancelled && setUsage(null));
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !trigger.current?.contains(t)) close(false);
    };
    // Escape closes the menu wherever focus is (e.g. still in the message box)
    const onEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(panel.current?.contains(document.activeElement) ?? false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEscape);
    return () => {
      cancelled = true;
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open, api, close]);

  if (!isLoaded || !user) return <span className="h-8 w-8 rounded-full bg-black/[0.06] dark:bg-white/[0.08]" aria-hidden />;

  const name = user.fullName || user.username || "Your account";
  const email = user.primaryEmailAddress?.emailAddress ?? (user.username ? `@${user.username}` : "");
  const initials = initialsOf(user.fullName, user.username, email);
  const image = user.hasImage ? user.imageUrl : null;

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = Array.from(panel.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
    const current = items.indexOf(document.activeElement as HTMLElement);
    const keys: Record<string, "next" | "prev" | "first" | "last"> = {
      ArrowDown: "next", ArrowUp: "prev", Home: "first", End: "last",
    };
    if (e.key === "Escape") return close(true);
    if (e.key === "Tab") return close(false);
    if (keys[e.key]) {
      e.preventDefault();
      items[nextIndex(current, items.length, keys[e.key])]?.focus();
    }
  };

  return (
    <>
      <button
        ref={trigger}
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Account menu for ${name}`}
        className={`rounded-full outline-none ring-offset-2 ring-offset-neutral-50 transition hover:ring-2 hover:ring-[#C5A368]/50 focus-visible:ring-2 focus-visible:ring-[#9E8253] dark:ring-offset-neutral-900 ${open ? "ring-2 ring-[#9E8253]" : ""}`}
      >
        <Avatar size={28} image={image} initials={initials} />
      </button>
      {open && pos && (
        <div
          ref={panel}
          id={menuId}
          role="menu"
          aria-label="Account"
          onKeyDown={onKeyDown}
          style={{ ...pos, width: MENU_WIDTH }}
          className="fixed z-50 overflow-hidden rounded-xl border border-[rgba(197,163,104,0.35)] bg-white shadow-[0_16px_48px_rgba(0,0,0,0.14)] dark:border-[rgba(197,163,104,0.25)] dark:bg-[#141517] dark:shadow-[0_16px_48px_rgba(0,0,0,0.55)]"
        >
          <div className="flex items-center gap-3 border-b border-black/[0.06] px-4 py-3.5 dark:border-white/[0.07]">
            <span className="rounded-full ring-2 ring-[#C5A368]/40">
              <Avatar size={40} image={image} initials={initials} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-neutral-900 dark:text-neutral-50">{name}</p>
              {email && <p className="truncate text-xs text-neutral-500">{email}</p>}
              <div className="mt-1 flex items-center gap-1.5">
                {role && (
                  <span className="rounded-full border border-[rgba(197,163,104,0.45)] bg-[#9E8253]/[0.08] px-2 py-px text-[10px] font-semibold uppercase tracking-[0.08em] text-[#7d6540] dark:text-[#C5A368]">
                    {isDemo ? "Demo" : role === "admin" ? "Admin" : "Member"}
                  </span>
                )}
                {organization && <span className="truncate text-[11px] text-neutral-500">{organization.name}</span>}
              </div>
            </div>
          </div>
          {!isDemo && (
            <div className="border-b border-black/[0.06] dark:border-white/[0.07]">
              <UsageRow usage={usage} />
            </div>
          )}
          <div className="flex flex-col gap-0.5 p-1.5">
            {!isDemo && (
              <button type="button" role="menuitem" className={ITEM}
                onClick={() => { close(false); clerk.openUserProfile(); }}>
                <MenuIcon path={<><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>} />
                Manage account
              </button>
            )}
            <button type="button" role="menuitem" className={ITEM}
              onClick={() => {
                close(false);
                // tell the server first so the admin console shows this person offline at once
                void api.noteSignOut().finally(() => clerk.signOut({ redirectUrl: isDemo ? "/demo" : "/sign-in" }));
              }}>
              <MenuIcon path={<><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3" /><path d="M10 17l-5-5 5-5" /><path d="M5 12h11" /></>} />
              Sign out
            </button>
          </div>
          <p className="border-t border-black/[0.06] px-4 py-2.5 text-[11px] text-neutral-500 dark:border-white/[0.07]">
            {isDemo ? "Shared demo account, reset every day." : "Access is managed by your organisation."}
          </p>
        </div>
      )}
    </>
  );
}
