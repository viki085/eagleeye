"use client";

import { useState } from "react";

import { FIELD, Modal, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/admin/modal";
import type { ApiClient, ProvisionedUser, UserRole } from "@/lib/api";
import { defaultUsername } from "@/lib/csv-users";

export const ROLE_INFO: Record<UserRole, { label: string; help: string }> = {
  member: { label: "Member", help: "Asks questions over documents, data and files they can access." },
  knowledge_admin: { label: "Knowledge admin", help: "Member, plus manages enterprise documents." },
  data_admin: { label: "Data admin", help: "Member, plus manages data-source settings." },
  admin: { label: "Administrator", help: "Full access, including this console and user management." },
};

const EMPTY = { email: "", username: "", first_name: "", last_name: "", role: "member" as UserRole };

export function AddUserDialog({ api, open, onClose, onAdded }: {
  api: ApiClient;
  open: boolean;
  onClose: () => void;
  onAdded: (user: ProvisionedUser) => void;
}) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function close(): void {
    setForm(EMPTY);
    setError(null);
    onClose();
  }

  async function submit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const user = await api.addUser({
        ...form,
        email: form.email.trim(),
        username: form.username.trim().toLowerCase() || undefined,
      });
      onAdded(user);
      close();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not add this user.");
    } finally {
      setBusy(false);
    }
  }

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) =>
    setForm((prev) => ({ ...prev, [key]: e.target.value }));

  return (
    <Modal
      open={open}
      busy={busy}
      onClose={close}
      title="Add user"
      subtitle="They sign in with their username or email (a one-time code is emailed), or with Google."
    >
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="flex flex-col gap-1 text-xs font-medium">
          Work email
          <input type="email" required autoFocus autoComplete="off" value={form.email} onChange={set("email")}
            placeholder="name@yourcompany.com" className={FIELD} maxLength={254} />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium">
          Username <span className="font-normal text-neutral-500">(optional)</span>
          <input
            value={form.username}
            onChange={set("username")}
            autoComplete="off"
            spellCheck={false}
            placeholder={defaultUsername(form.email) || "jane_doe"}
            pattern="[A-Za-z0-9_\-]{4,64}"
            title="4-64 letters, digits, _ or -"
            className={`${FIELD} font-mono`}
            maxLength={64}
          />
          <span className="font-normal text-neutral-500">
            {form.username.trim()
              ? "Used to sign in instead of the email."
              : `Leave blank to use ${defaultUsername(form.email) ? `"${defaultUsername(form.email)}"` : "a name based on the email"}.`}
          </span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium">
            First name
            <input value={form.first_name} onChange={set("first_name")} className={FIELD} maxLength={100} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium">
            Last name
            <input value={form.last_name} onChange={set("last_name")} className={FIELD} maxLength={100} />
          </label>
        </div>
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 text-xs font-medium">Role</legend>
          {(Object.keys(ROLE_INFO) as UserRole[]).map((role) => (
            <label
              key={role}
              className={`flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 text-xs ${
                form.role === role
                  ? "border-[#2a78d6] bg-[#2a78d6]/[0.06]"
                  : "border-black/10 hover:bg-black/[0.02] dark:border-white/10 dark:hover:bg-white/[0.03]"
              }`}
            >
              <input type="radio" name="role" value={role} checked={form.role === role} onChange={set("role")} className="mt-0.5" />
              <span>
                <span className="block font-semibold">{ROLE_INFO[role].label}</span>
                <span className="text-neutral-500">{ROLE_INFO[role].help}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {error && <p role="alert" className="text-xs text-red-600 dark:text-red-400">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={close} disabled={busy} className={SECONDARY_BUTTON}>Cancel</button>
          <button type="submit" disabled={busy || !form.email.trim()} className={PRIMARY_BUTTON}>
            {busy ? "Adding…" : "Add user"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
