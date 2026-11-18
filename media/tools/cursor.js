// Visible cursor for screen recordings. Playwright moves an invisible mouse, so this draws an
// arrow that follows it, a ripple on every click, and (optionally) a spotlight around a region.
// Injected with page.addInitScript({ path: "media/tools/cursor.js" }) before navigation.
(() => {
  if (window.__eeCursor) return;
  window.__eeCursor = true;

  const install = () => {
    const style = document.createElement("style");
    style.textContent = `
      #ee-cursor { position: fixed; left: 0; top: 0; width: 18px; height: 18px; z-index: 2147483647;
        pointer-events: none; transform: translate(-2px, -1px);
        filter: drop-shadow(0 2px 3px rgba(0,0,0,0.45)); }
      .ee-ripple { position: fixed; z-index: 2147483646; pointer-events: none; width: 14px; height: 14px;
        margin: -7px 0 0 -7px; border-radius: 9999px; border: 2px solid rgba(42,120,214,0.9);
        animation: ee-ripple 520ms ease-out forwards; }
      @keyframes ee-ripple { from { transform: scale(0.6); opacity: 1; } to { transform: scale(3.4); opacity: 0; } }
      #ee-spotlight { position: fixed; z-index: 2147483645; pointer-events: none; border-radius: 12px;
        box-shadow: 0 0 0 9999px rgba(0,0,0,0.45); transition: all 400ms ease; opacity: 0; }
    `;
    document.documentElement.appendChild(style);

    const cursor = document.createElement("div");
    cursor.id = "ee-cursor";
    cursor.innerHTML =
      '<svg viewBox="0 0 24 24" width="18" height="18"><path d="M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.7 L11.5 14 L18 14 Z" fill="white" stroke="black" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(cursor);

    const spotlight = document.createElement("div");
    spotlight.id = "ee-spotlight";
    document.documentElement.appendChild(spotlight);

    const saved = sessionStorage.getItem("ee-cursor-pos");
    if (saved) cursor.style.transform = saved;

    window.addEventListener("mousemove", (e) => {
      const t = `translate(${e.clientX - 2}px, ${e.clientY - 1}px)`;
      cursor.style.transform = t;
      try { sessionStorage.setItem("ee-cursor-pos", t); } catch {}
    }, true);
    window.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "ee-ripple";
      r.style.left = `${e.clientX}px`;
      r.style.top = `${e.clientY}px`;
      document.documentElement.appendChild(r);
      setTimeout(() => r.remove(), 600);
    }, true);

    // window.__eeSpotlight(rect | null): darken everything outside rect ({x, y, width, height})
    window.__eeSpotlight = (rect, pad = 10) => {
      if (!rect) { spotlight.style.opacity = "0"; return; }
      Object.assign(spotlight.style, {
        left: `${rect.x - pad}px`, top: `${rect.y - pad}px`,
        width: `${rect.width + pad * 2}px`, height: `${rect.height + pad * 2}px`, opacity: "1",
      });
    };
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
})();
