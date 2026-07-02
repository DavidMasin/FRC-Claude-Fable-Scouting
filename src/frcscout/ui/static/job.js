/* live job page: poll the job API, stream events into the feed, redirect on
   completion */
(function () {
  const feed = document.getElementById("feed");
  const status = document.getElementById("job-status");
  let offset = 0;
  let first = true;

  function fmt(ev) {
    const t = ev.match_t != null ? ev.match_t : ev.t;
    const who = ev.team != null ? "team " + ev.team : (ev.alliance || "—");
    const flags = ev.flags && ev.flags.length ? " · " + ev.flags.join(", ") : "";
    return `<div><span class="t">[${Number(t).toFixed(1)}s]</span> ` +
      `${ev.type} · ${who} · ×${ev.count} · conf ${ev.conf}${flags}</div>`;
  }

  async function poll() {
    let res;
    try {
      res = await fetch(`/api/jobs/${window.JOB_ID}?since=${offset}`);
    } catch (e) { return setTimeout(poll, 2000); }
    if (!res.ok) return setTimeout(poll, 2000);
    const job = await res.json();

    if (job.events.length) {
      if (first) { feed.innerHTML = ""; first = false; }
      for (const ev of job.events) feed.insertAdjacentHTML("beforeend", fmt(ev));
      offset += job.events.length;
      feed.scrollTop = feed.scrollHeight;
    }
    status.textContent =
      `${job.status} · ${job.n_events} events · ${job.elapsed_s}s elapsed` +
      (job.n_frames ? ` · ${job.n_frames} frames (${job.n_unstable} suspended)` : "");

    if (job.status === "done" && job.match_url) {
      document.getElementById("spin").remove();
      status.innerHTML += ` — <a href="${job.match_url}">view match report →</a>`;
      window.location = job.match_url;
      return;
    }
    if (job.status === "error") {
      document.getElementById("spin").remove();
      document.getElementById("job-error").innerHTML =
        `<div class="warnbox">${job.error}</div>`;
      return;
    }
    setTimeout(poll, 1000);
  }
  poll();
})();
