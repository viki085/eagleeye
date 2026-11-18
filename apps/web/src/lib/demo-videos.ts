/** The EagleEye videos shown on the demo sign-in page. A video appears once it has its YouTube
 * id; the thumbnails are served by this site, so nothing loads from YouTube until a visitor
 * presses play. */
export interface DemoVideo {
  id: string; // YouTube video id; empty until the video is published
  title: string;
  minutes: number;
  thumb: string;
}

export const DEMO_VIDEOS: DemoVideo[] = [
  { id: "_pjZODEwXyk", title: "Product demo", minutes: 5, thumb: "/videos/product-demo.jpg" },
  { id: "klPBlEWFGSM", title: "How it works, and how it scales", minutes: 6, thumb: "/videos/how-it-scales.jpg" },
];

const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

export function publishedVideos(videos: DemoVideo[]): DemoVideo[] {
  return videos.filter((v) => YOUTUBE_ID.test(v.id));
}

/** Privacy-enhanced embed (no YouTube cookies until playback); related videos from this
 * channel only. */
export function embedUrl(id: string): string {
  const url = new URL(`https://www.youtube-nocookie.com/embed/${id}`);
  url.searchParams.set("autoplay", "1");
  url.searchParams.set("rel", "0");
  url.searchParams.set("modestbranding", "1");
  return url.toString();
}
