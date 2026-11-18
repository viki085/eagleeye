import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import * as si from "simple-icons";

const GOLD = "#C5A368";
const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
const GROUP_GAP_S = 0.8; // each group appears this long after the previous one; nothing fades out

type Tool = { name: string; icon?: keyof typeof si; letters?: string; note?: string };

const GROUPS: { title: string; tools: Tool[] }[] = [
  {
    title: "Frontend",
    tools: [
      { name: "Next.js", icon: "siNextdotjs" },
      { name: "React", icon: "siReact" },
      { name: "TypeScript", icon: "siTypescript" },
      { name: "Tailwind CSS", icon: "siTailwindcss" },
      { name: "ECharts", icon: "siApacheecharts" },
      { name: "Clerk", icon: "siClerk", note: "sign-in" },
    ],
  },
  {
    title: "Backend and AI",
    tools: [
      { name: "Python", icon: "siPython" },
      { name: "FastAPI", icon: "siFastapi" },
      { name: "Celery", icon: "siCelery" },
      { name: "OpenAI", icon: "siOpenai" },
      { name: "Docling", letters: "Dl", note: "document parsing" },
    ],
  },
  {
    title: "Data",
    tools: [
      { name: "PostgreSQL", icon: "siPostgresql" },
      { name: "Supabase", icon: "siSupabase" },
      { name: "Qdrant", letters: "Qd", note: "vector search" },
      { name: "Redis", icon: "siRedis" },
      { name: "DuckDB", icon: "siDuckdb" },
      { name: "pandas", icon: "siPandas" },
    ],
  },
  {
    title: "Cloud and delivery",
    tools: [
      { name: "AWS", icon: "siAmazonwebservices" },
      { name: "EC2", icon: "siAmazonec2" },
      { name: "Lambda", icon: "siAwslambda" },
      { name: "S3", icon: "siAmazons3" },
      { name: "CloudFront", letters: "CF" },
      { name: "CloudWatch", icon: "siAmazoncloudwatch" },
      { name: "Terraform", icon: "siTerraform" },
      { name: "Docker", icon: "siDocker" },
      { name: "Vercel", icon: "siVercel" },
      { name: "GitHub Actions", icon: "siGithubactions" },
    ],
  },
];

/** Brand colour, or white when the brand colour is too dark to see on the dark card. */
function visible(hex: string): string {
  const n = parseInt(hex, 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 70 ? "#f2f2f2" : `#${hex}`;
}

const Tile: React.FC<{ tool: Tool }> = ({ tool }) => {
  const icon = tool.icon ? (si[tool.icon] as { path: string; hex: string } | undefined) : undefined;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 128 }}>
      <div style={{ width: 76, height: 76, borderRadius: 18, background: "#17171a", border: "1px solid #2a2a2e", display: "flex", alignItems: "center", justifyContent: "center" }}>
        {icon ? (
          <svg viewBox="0 0 24 24" width={40} height={40}>
            <path d={icon.path} fill={visible(icon.hex)} />
          </svg>
        ) : (
          <span style={{ color: GOLD, fontSize: 26, fontWeight: 700, fontFamily: FONT }}>{tool.letters}</span>
        )}
      </div>
      <div style={{ marginTop: 10, color: "#e9e9e9", fontSize: 19, fontWeight: 600, textAlign: "center" }}>{tool.name}</div>
      {tool.note && <div style={{ color: "#8d8d92", fontSize: 14, textAlign: "center" }}>{tool.note}</div>}
    </div>
  );
};

export const BuiltWith: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const appear = (i: number) => {
    const start = (0.4 + i * GROUP_GAP_S) * fps;
    return interpolate(frame, [start, start + 0.45 * fps], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  };
  const footer = appear(GROUPS.length);
  return (
    <AbsoluteFill style={{ background: "radial-gradient(ellipse at 50% 30%, #17150f 0%, #0a0a0a 70%)", fontFamily: FONT, padding: "56px 90px", alignItems: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <Img src={staticFile("brand/eagleeye-icon.png")} style={{ width: 54, height: 54, borderRadius: 12 }} />
        <div style={{ color: "#f4f1ea", fontSize: 44, fontWeight: 700 }}>Built with</div>
      </div>
      <div style={{ marginTop: 34, display: "flex", flexDirection: "column", gap: 26, width: "100%" }}>
        {GROUPS.map((g, i) => {
          const a = appear(i);
          return (
            <div key={g.title} style={{ opacity: a, transform: `translateY(${(1 - a) * 18}px)`, display: "flex", alignItems: "center", gap: 28 }}>
              <div style={{ width: 230, color: GOLD, fontSize: 20, fontWeight: 700, letterSpacing: 2, textTransform: "uppercase", textAlign: "right" }}>{g.title}</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {g.tools.map((t) => (
                  <Tile key={t.name} tool={t} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: "auto", textAlign: "center", opacity: footer }}>
        <div style={{ color: "#f4f1ea", fontSize: 34, fontWeight: 600, letterSpacing: 0.5 }}>eagleeye-z85t.vercel.app</div>
        <div style={{ marginTop: 10, color: "#a9a9ad", fontSize: 22 }}>
          Designed and built by <span style={{ color: "#f4f1ea", fontWeight: 600 }}>Vikram Karthikeyan</span> · viki.kma085@gmail.com
        </div>
        <div style={{ marginTop: 14, color: "#5d5d62", fontSize: 13 }}>Product names and logos are trademarks of their respective owners. Icons: Simple Icons (CC0).</div>
      </div>
    </AbsoluteFill>
  );
};
