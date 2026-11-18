import { describe, expect, it } from "vitest";

import { DEMO_VIDEOS, embedUrl, publishedVideos } from "./demo-videos";

describe("demo videos", () => {
  it("lists only videos that have a YouTube id", () => {
    const list = publishedVideos([
      { id: "_pjZODEwXyk", title: "Product demo", minutes: 5, thumb: "/videos/a.jpg" },
      { id: "", title: "Not uploaded yet", minutes: 6, thumb: "/videos/b.jpg" },
      { id: "bad id!", title: "Malformed", minutes: 1, thumb: "/videos/c.jpg" },
    ]);
    expect(list.map((v) => v.title)).toEqual(["Product demo"]);
  });

  it("plays from YouTube's privacy-enhanced domain, without related videos from other channels", () => {
    const url = new URL(embedUrl("_pjZODEwXyk"));
    expect(url.origin).toBe("https://www.youtube-nocookie.com");
    expect(url.pathname).toBe("/embed/_pjZODEwXyk");
    expect(url.searchParams.get("autoplay")).toBe("1");
    expect(url.searchParams.get("rel")).toBe("0");
  });

  it("has the product demo published", () => {
    expect(publishedVideos(DEMO_VIDEOS)[0]?.id).toBe("_pjZODEwXyk");
  });
});
