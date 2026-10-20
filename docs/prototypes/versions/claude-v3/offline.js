// Serve the page's API calls from window.FIXTURES so the snapshot opens
// from disk with no server. The 60' check is put together from the recorded
// part for each call's decision state. Anything not recorded fails visibly.
(() => {
  const reply = (body, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  window.fetch = async (url, opts = {}) => {
    const path = String(url).replace(/^\.?\//, "");
    // A test can set OFFLINE_DELAY_MS to hold a reply and probe stale results.
    await new Promise((r) => setTimeout(r, window.OFFLINE_DELAY_MS ?? 150));
    if (path === "api/check") {
      const b = JSON.parse(opts.body || "{}"), rec = window.FIXTURES["check:" + b.focus];
      if (!rec) return reply({ detail: "not in this offline snapshot: check " + b.focus }, 404);
      const out = JSON.parse(JSON.stringify(rec.common));
      Object.assign(out, { checks: [], verdicts: [], choices: {}, decisions: {} });
      for (const f of ["press", "threat", "scoreline"]) {
        const d = (b.decisions || {})[f] || {};
        const key = `${d.option || "-"}:${d.status || "open"}:${d.implemented ? 1 : 0}`;
        const part = rec.per[f][key];
        if (!part) return reply({ detail: "not in this offline snapshot: " + f + " " + key }, 404);
        out.checks.push(part.check); out.verdicts.push(part.verdict);
        out.choices[f] = part.choice; out.decisions[f] = part.decision;
      }
      return reply(out);
    }
    if (path in window.FIXTURES) return reply(window.FIXTURES[path]);
    return reply({ detail: "not in this offline snapshot: " + path }, 404);
  };
})();
