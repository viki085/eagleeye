import React from "react";
import { AbsoluteFill, OffthreadVideo, staticFile } from "remotion";
import { DATA, GREEN, MONO } from "./data";

const W = 1920;
const H = 1080;

/** One window: a recorded session with a thin hacker-style title bar. */
const Window: React.FC<{ src: string; startFrom: number; x: number; y: number; w: number; h: number; label?: string; fps: number }> = ({ src, startFrom, x, y, w, h, label, fps }) => (
  <div style={{ position: "absolute", left: x, top: y, width: w, height: h, border: `1px solid ${GREEN}66`, boxShadow: `0 0 18px ${GREEN}22`, overflow: "hidden", background: "#000" }}>
    {label && h > 160 && (
      <div style={{ position: "absolute", zIndex: 2, left: 0, top: 0, right: 0, height: 26, background: "rgba(0,12,4,0.85)", color: GREEN, fontFamily: MONO, fontSize: 15, lineHeight: "26px", paddingLeft: 10 }}>{label}</div>
    )}
    <OffthreadVideo src={staticFile(src)} startFrom={Math.round(startFrom * fps)} muted style={{ width: "100%", height: "100%", objectFit: "cover" }} />
  </div>
);

function grid(n: number, inset: number) {
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const w = (W - inset * 2) / cols;
  const h = w * (9 / 16);
  const top = (H - h * rows) / 2;
  return Array.from({ length: n }, (_, i) => ({ x: inset + (i % cols) * w, y: top + Math.floor(i / cols) * h, w, h }));
}

/**
 * The doubling wall. 1-4 windows use the 4K recordings, 8 use 960-pixel proxies, 16 is the
 * pre-built 4x4 mosaic, 64 and 256 tile that mosaic 2x2 / 4x4 (time-shifted so tiles differ).
 * Each new stage zooms out from the previous one.
 */
export const Wall: React.FC<{ n: number; sinceStage: number; fps: number }> = ({ n, sinceStage, fps }) => {
  const zoom = 1 + Math.max(0, 1 - sinceStage / 0.45) * (n > 1 ? 0.9 : 0.15);
  let tiles: React.ReactNode[] = [];
  if (n <= 8) {
    const g = grid(n, n === 1 ? 140 : 40);
    tiles = g.map((b, i) => {
      const clip = DATA.walls[i % DATA.walls.length];
      const src = n <= 4 ? `load/${clip.name}.mp4` : `load/${clip.name}-960.mp4`;
      return <Window key={i} src={src} startFrom={Math.max(0, clip.ready - 1)} fps={fps} label={`user ${i + 1} · ${clip.kind}`} {...b} />;
    });
  } else {
    const per = n === 16 ? 1 : n === 64 ? 2 : 4;
    const w = W / per;
    const h = H / per;
    tiles = Array.from({ length: per * per }, (_, i) => (
      <Window key={i} src="load/mosaic.mp4" startFrom={(i * 5.3) % (DATA.mosaicSeconds - 8)} fps={fps} x={(i % per) * w} y={Math.floor(i / per) * h} w={w} h={h} />
    ));
  }
  return (
    <AbsoluteFill style={{ background: "#020403", transform: `scale(${zoom})`, transformOrigin: "50% 50%" }}>
      {tiles}
    </AbsoluteFill>
  );
};
