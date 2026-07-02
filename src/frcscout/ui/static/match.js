/* match dashboard: robot cards + two SVG charts + event table.
   Marks follow the dataviz specs: thin bars with 4px rounding on the value
   end only, 2px surface gaps, >=8px hover-able dots with a 2px surface ring,
   recessive hairline grid, text in ink tokens (never series color). */
(function () {
  const css = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const SVG = "http://www.w3.org/2000/svg";
  const el = (tag, attrs) => {
    const node = document.createElementNS(SVG, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  };
  const tooltip = document.getElementById("tooltip");
  function showTip(html, evt) {
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const pad = 14;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    const r = tooltip.getBoundingClientRect();
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    tooltip.style.left = x + "px";
    tooltip.style.top = y + "px";
  }
  const hideTip = () => { tooltip.hidden = true; };

  const allianceColor = (a) =>
    a === "red" ? css("--red-alliance") : css("--blue-alliance");

  // ---- robot cards ----------------------------------------------------------
  function renderCards(record) {
    const root = document.getElementById("robot-cards");
    const robots = [...record.robots].sort((a, b) =>
      a.alliance === b.alliance ? a.station - b.station
                                : (a.alliance === "red" ? -1 : 1));
    for (const r of robots) {
      const climb = r.endgame.climb
        ? r.endgame.climb.replace("_", " ")
        : (r.endgame.attempted ? "attempt" : "no climb");
      const conf = Math.round(r.assignment_confidence * 100);
      const flags = r.flags.map((f) =>
        `<span class="flag ${f.includes("mismatch") ? "warn" : ""}">${f}</span>`).join("");
      const card = document.createElement("div");
      card.className = `card robot-card ${r.alliance}`;
      card.innerHTML = `
        <div class="robot-head">
          <span class="team">${r.team}</span>
          <span class="meta">${r.alliance} · station ${r.station}</span>
        </div>
        <div class="stats">
          <div class="stat"><div class="v">${r.auto.fuel_scored}</div><div class="l">auto fuel</div></div>
          <div class="stat"><div class="v">${r.teleop.fuel_scored}</div><div class="l">teleop fuel</div></div>
          <div class="stat"><div class="v">${r.teleop.cycles.length}</div><div class="l">cycles</div></div>
          <div class="stat"><div class="v">${climb}</div><div class="l">endgame</div></div>
          <div class="stat"><div class="v">${r.defense_played_s.toFixed(0)}s</div><div class="l">defense</div></div>
          <div class="stat"><div class="v">${r.teleop.avg_cycle_s ?? "–"}</div><div class="l">avg cycle s</div></div>
        </div>
        <div class="meter">
          <div class="l"><span>identity confidence</span><span>${conf}%</span></div>
          <div class="bar"><div class="fill" style="width:${conf}%"></div></div>
        </div>
        ${flags ? `<div class="flags">${flags}</div>` : ""}`;
      root.appendChild(card);
    }
  }

  // ---- fuel bar chart (horizontal, one bar per robot) --------------------------
  function renderFuel(record) {
    const robots = [...record.robots].sort((a, b) =>
      a.alliance === b.alliance ? a.station - b.station
                                : (a.alliance === "red" ? -1 : 1));
    const W = 960, rowH = 30, padL = 76, padR = 56, padT = 8;
    const H = padT + robots.length * rowH + 24;
    const maxFuel = Math.max(1, ...robots.map(
      (r) => r.auto.fuel_scored + r.teleop.fuel_scored));
    const x = (v) => padL + (v / maxFuel) * (W - padL - padR);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
                            "aria-label": "Fuel scored per robot" });

    for (const gv of [0, Math.ceil(maxFuel / 2), maxFuel]) {  // hairline grid
      svg.append(el("line", { x1: x(gv), x2: x(gv), y1: padT, y2: H - 22,
                              stroke: css("--grid"), "stroke-width": 1 }));
      const t = el("text", { x: x(gv), y: H - 8, "text-anchor": "middle",
                             fill: css("--text-muted"), "font-size": 11 });
      t.textContent = gv;
      svg.append(t);
    }
    svg.append(el("line", { x1: padL, x2: padL, y1: padT, y2: H - 22,
                            stroke: css("--baseline"), "stroke-width": 1 }));

    robots.forEach((r, i) => {
      const total = r.auto.fuel_scored + r.teleop.fuel_scored;
      const y = padT + i * rowH + 5;
      const barH = rowH - 12;
      const label = el("text", { x: padL - 10, y: y + barH / 2 + 4,
                                 "text-anchor": "end", fill: css("--text-primary"),
                                 "font-size": 13, "font-weight": 600 });
      label.textContent = r.team;
      svg.append(label);
      const sw = el("rect", { x: padL - 68, y: y + barH / 2 - 4, width: 8,
                              height: 8, rx: 2, fill: allianceColor(r.alliance) });
      svg.append(sw);
      const w = Math.max(total > 0 ? 4 : 0, x(total) - padL);
      const bar = el("rect", { x: padL + 1, y, width: w, height: barH,
                               rx: 4, fill: allianceColor(r.alliance) });
      if (w > 8)  // square the baseline end: rounded corners at the value end only
        svg.append(el("rect", { x: padL + 1, y, width: 5, height: barH,
                                fill: allianceColor(r.alliance) }));
      const val = el("text", { x: padL + w + 8, y: y + barH / 2 + 4,
                               fill: css("--text-secondary"), "font-size": 12 });
      val.textContent = total;
      const hit = el("rect", { x: padL, y: y - 3, width: W - padL - padR,
                               height: barH + 6, fill: "transparent" });
      hit.addEventListener("mousemove", (evt) => showTip(
        `<div class="t">${r.team} · ${r.alliance}</div>` +
        `<div class="m">${r.auto.fuel_scored} auto + ${r.teleop.fuel_scored} teleop` +
        ` = ${total} fuel</div>`, evt));
      hit.addEventListener("mouseleave", hideTip);
      svg.append(bar, val, hit);
    });
    document.getElementById("fuel-chart").appendChild(svg);
  }

  // ---- event timeline (dot strip per robot) --------------------------------------
  function renderTimeline(record, timing) {
    const autoS = timing.auto_s ?? 20, teleopS = timing.teleop_s ?? 140;
    const endgameS = timing.endgame_s ?? 30;
    const totalS = autoS + teleopS;
    const robots = [...record.robots].sort((a, b) =>
      a.alliance === b.alliance ? a.station - b.station
                                : (a.alliance === "red" ? -1 : 1));
    const rowOf = {};
    robots.forEach((r, i) => (rowOf[r.team] = i));
    const W = 960, rowH = 26, padL = 76, padR = 16, padT = 20;
    const H = padT + robots.length * rowH + 30;
    const x = (t) => padL + (Math.min(t, totalS) / totalS) * (W - padL - padR);
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
                            "aria-label": "Event timeline" });

    const phases = [["auto", 0], ["teleop", autoS], ["endgame", totalS - endgameS]];
    for (const [name, t0] of phases) {
      svg.append(el("line", { x1: x(t0), x2: x(t0), y1: padT - 4, y2: H - 26,
                              stroke: css("--grid"), "stroke-width": 1 }));
      const t = el("text", { x: x(t0) + 4, y: padT - 8,
                             fill: css("--text-muted"), "font-size": 11 });
      t.textContent = name;
      svg.append(t);
    }
    for (let tick = 0; tick <= totalS; tick += 30) {
      const t = el("text", { x: x(tick), y: H - 10, "text-anchor": "middle",
                             fill: css("--text-muted"), "font-size": 10.5 });
      t.textContent = tick + "s";
      svg.append(t);
    }
    robots.forEach((r, i) => {
      const y = padT + i * rowH + rowH / 2;
      svg.append(el("line", { x1: padL, x2: W - padR, y1: y, y2: y,
                              stroke: css("--grid"), "stroke-width": 1 }));
      const label = el("text", { x: padL - 10, y: y + 4, "text-anchor": "end",
                                 fill: css("--text-primary"), "font-size": 12.5,
                                 "font-weight": 600 });
      label.textContent = r.team;
      svg.append(label);
    });

    const events = record.robots.flatMap((r) =>
      r.events.map((e) => ({ ...e, team: r.team, alliance: r.alliance })));
    for (const ev of events) {
      if (ev.match_t == null || rowOf[ev.team] == null) continue;
      const y = padT + rowOf[ev.team] * rowH + rowH / 2;
      const dot = el("circle", {
        cx: x(ev.match_t), cy: y, r: 5,
        fill: allianceColor(ev.alliance),
        stroke: css("--surface-1"), "stroke-width": 2,  // surface ring for overlaps
        opacity: ev.conf >= 0.6 ? 1 : 0.55,
      });
      const hit = el("circle", { cx: x(ev.match_t), cy: y, r: 11,
                                 fill: "transparent" });
      const flags = ev.flags && ev.flags.length
        ? `<div class="m">${ev.flags.join(", ")}</div>` : "";
      hit.addEventListener("mousemove", (evt) => showTip(
        `<div class="t">${ev.type} · team ${ev.team}</div>` +
        `<div class="m">t=${ev.match_t}s · ×${ev.count} · conf ${ev.conf}` +
        ` · ${ev.source}</div>${flags}`, evt));
      hit.addEventListener("mouseleave", hideTip);
      svg.append(dot, hit);
    }
    document.getElementById("timeline-chart").appendChild(svg);
  }

  // ---- events table (the accessible view of the same data) -------------------------
  function renderTable(record) {
    const tbody = document.querySelector("#events-table tbody");
    const rows = record.robots
      .flatMap((r) => r.events.map((e) => ({ ...e, team: r.team })))
      .concat(record.unattributed_events)
      .sort((a, b) => a.t - b.t);
    for (const e of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML =
        `<td>${e.match_t ?? "–"}</td><td>${e.type}</td>` +
        `<td>${e.team ?? "–"}</td><td>${e.alliance ?? "–"}</td>` +
        `<td>${e.count}</td><td>${e.points ?? "–"}</td><td>${e.conf}</td>` +
        `<td>${e.source}</td><td>${(e.flags || []).join(", ")}</td>`;
      tbody.appendChild(tr);
    }
  }

  Promise.all([
    fetch(`/api/matches/${window.MATCH_KEY}`).then((r) => r.json()),
    fetch("/api/rubric").then((r) => r.json()),
  ]).then(([record, timing]) => {
    renderCards(record);
    renderFuel(record);
    renderTimeline(record, timing);
    renderTable(record);
  });
})();
