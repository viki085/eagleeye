import { Icon, type IconName } from "@/components/admin/icons";

const POINTS: { icon: IconName; title: string; text: string }[] = [
  { icon: "book", title: "Answers with sources", text: "Every answer cites the enterprise documents it came from." },
  { icon: "database", title: "Governed data access", text: "Read-only, permission-checked questions over company databases." },
  { icon: "usage", title: "Analysis on your files", text: "Charts and figures from your own spreadsheets, verified against results." },
];

/** Left half of the sign-in page (wide screens only): the product, not marketing. */
export function BrandPanel() {
  return (
    <aside
      className="relative hidden w-[46%] max-w-[640px] flex-col justify-between overflow-hidden bg-[#0d1117] px-12 py-12 text-white lg:flex"
      style={{
        backgroundImage:
          "radial-gradient(60rem 30rem at -10% -10%, rgba(42,120,214,0.35), transparent 60%)," +
          "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px)," +
          "linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
        backgroundSize: "auto, 40px 40px, 40px 40px",
      }}
    >
      <div className="flex items-center gap-2.5">
        <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-lg bg-[#2a78d6] text-base font-bold">E</span>
        <span className="text-lg font-semibold tracking-tight">EagleEye</span>
      </div>
      <div className="max-w-md">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8ab8f0]">Enterprise AI assistant</p>
        <h2 className="mt-3 text-[34px] font-semibold leading-[1.15] tracking-tight [text-wrap:balance]">
          Your company&apos;s knowledge, data and files, answered with evidence.
        </h2>
        <ul className="mt-10 flex flex-col gap-6">
          {POINTS.map((p) => (
            <li key={p.title} className="flex gap-4">
              <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.06] text-[#8ab8f0]">
                <Icon name={p.icon} className="h-4 w-4" />
              </span>
              <span>
                <span className="block text-sm font-semibold">{p.title}</span>
                <span className="text-sm text-white/60">{p.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-white/40">Access is managed by your administrator</p>
    </aside>
  );
}
