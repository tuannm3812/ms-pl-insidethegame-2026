// Serve the page's API calls from window.FIXTURES so the snapshot opens
// from disk with no server. Anything not recorded fails visibly.
(() => {
  const reply = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  window.fetch = async (url, opts = {}) => {
    const path = String(url).replace(/^\.?\//, "");
    // A test can set OFFLINE_DELAY_MS to hold a reply and probe stale results.
    await new Promise((r) => setTimeout(r, window.OFFLINE_DELAY_MS ?? 150));
    if (path === "api/check") {
      const b = JSON.parse(opts.body || "{}"), c = b.choices || {};
      const key = `api/check:${b.focus}:${["press", "threat", "scoreline"].map((f) => c[f] || "a").join("")}`;
      if (key in window.FIXTURES) return reply(window.FIXTURES[key]);
    } else if (path in window.FIXTURES) {
      return reply(window.FIXTURES[path]);
    }
    return reply({ detail: "not in this offline snapshot: " + path }, 404);
  };
})();
