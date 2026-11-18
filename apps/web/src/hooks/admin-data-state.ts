export type Loadable<T> =
  | { kind: "loading" }
  | { kind: "ok"; data: T; at: Date }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

/** While a report reloads: numbers already on screen stay until the new ones arrive (Live
 * mode refreshes every few seconds, and a busy system can take longer than that to answer);
 * a first load, or one after an error, shows the loading state. */
export function stateWhileReloading<T>(prev: Loadable<T>): Loadable<T> {
  return prev.kind === "ok" ? prev : { kind: "loading" };
}
