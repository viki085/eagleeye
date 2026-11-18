"use client";

import { useEffect, useRef, useState } from "react";

import { DEMO_VIDEOS, type DemoVideo, embedUrl, publishedVideos } from "@/lib/demo-videos";

const FOCUS =
  "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#9E8253]/30";

/** "Watch first": the EagleEye videos as cards under the demo sign-in; a card opens the video in
 * an overlay player (YouTube, privacy-enhanced, loaded only on click). */
export function DemoVideos() {
  const videos = publishedVideos(DEMO_VIDEOS);
  const [playing, setPlaying] = useState<DemoVideo | null>(null);
  if (videos.length === 0) return null;
  return (
    <section aria-labelledby="demo-videos" className="mt-8">
      <h2 id="demo-videos" className="text-center text-xs font-semibold uppercase tracking-[0.14em] text-[#7d6540] dark:text-[#C5A368]">
        Watch first
      </h2>
      <div className={`mt-3 grid gap-3 ${videos.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
        {videos.map((v) => (
          <button
            key={v.id}
            type="button"
            onClick={() => setPlaying(v)}
            aria-label={`Play video: ${v.title}, ${v.minutes} minutes`}
            className={`group overflow-hidden rounded-xl border border-[rgba(197,163,104,0.3)] bg-white text-left shadow-sm transition hover:border-[rgba(197,163,104,0.6)] dark:bg-[#141517] ${FOCUS}`}
          >
            <span className="relative block aspect-video">
              {/* eslint-disable-next-line @next/next/no-img-element -- small static thumbnails */}
              <img src={v.thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
              <span aria-hidden className="absolute inset-0 grid place-items-center bg-black/10 transition group-hover:bg-black/25">
                <span className="grid h-11 w-11 place-items-center rounded-full bg-black/70 text-white shadow-lg">
                  <svg viewBox="0 0 24 24" className="ml-0.5 h-5 w-5" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                </span>
              </span>
            </span>
            <span className="flex items-baseline justify-between gap-2 px-3 py-2">
              <span className="truncate text-xs font-medium text-neutral-800 dark:text-neutral-100">{v.title}</span>
              <span className="shrink-0 text-[11px] text-neutral-500">{v.minutes} min</span>
            </span>
          </button>
        ))}
      </div>
      {playing && <Player video={playing} onClose={() => setPlaying(null)} />}
    </section>
  );
}

function Player({ video, onClose }: { video: DemoVideo; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={video.title}
      onClick={onClose}
      className="fixed inset-0 z-50 grid place-items-center bg-black/80 p-4"
    >
      <div className="w-full max-w-5xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between text-sm text-white">
          <span className="font-medium">{video.title}</span>
          <button ref={close} type="button" onClick={onClose} aria-label="Close video" className={`rounded-lg px-2 py-1 text-lg leading-none hover:bg-white/10 ${FOCUS}`}>
            ✕
          </button>
        </div>
        <div className="aspect-video overflow-hidden rounded-xl bg-black shadow-2xl">
          <iframe
            src={embedUrl(video.id)}
            title={video.title}
            allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
            className="h-full w-full"
          />
        </div>
      </div>
    </div>
  );
}
