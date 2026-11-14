"use strict";

const SVG_NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function svgEl(tag, attrs = {}, parent = null) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

/* ---------- Shared helpers ---------- */

const tooltip = $("tooltip");
function showTip(text, event) {
  tooltip.textContent = text;
  tooltip.hidden = false;
  const box = tooltip.getBoundingClientRect();
  const x = Math.min(event.clientX + 14, window.innerWidth - box.width - 8);
  const y = Math.min(event.clientY + 14, window.innerHeight - box.height - 8);
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
}
const hideTip = () => { tooltip.hidden = true; };

let toastTimer = null;
function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 7000);
}

async function post(path, body = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) toast(data.message || `Request failed (${response.status})`);
  return { ok: response.ok, data };
}

function hexToRgb(hex) {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function mix(a, b, t) {
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t)).join(",")})`;
}
const fmt = (v, digits = 2) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(digits));

function niceMax(v) {
  if (!(v > 0)) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * mag) return m * mag;
  return 10 * mag;
}

/* ---------- Line chart: one y axis, crosshair and tooltip ---------- */

class LineChart {
  constructor(host, { title, unit = "", series, yMin = 0, yMax = null, xLabel = "s", digits = 2 }) {
    this.unit = unit; this.series = series; this.yMin = yMin; this.yMax = yMax;
    this.xLabel = xLabel; this.digits = digits;
    this.w = 460; this.h = 170; this.m = { l: 44, r: 12, t: 8, b: 22 };
    this.points = []; this.markers = [];
    host.classList.add("chart");
    const head = document.createElement("div");
    head.className = "chart-head";
    const titleEl = document.createElement("span");
    titleEl.className = "chart-title"; titleEl.textContent = title;
    this.valueEl = document.createElement("span");
    this.valueEl.className = "chart-value";
    head.append(titleEl, this.valueEl);
    host.appendChild(head);
    if (series.length > 1) {
      const legend = document.createElement("div");
      legend.className = "chart-legend";
      for (const s of series) {
        const item = document.createElement("span");
        item.className = "legend-item";
        const swatch = document.createElement("span");
        swatch.className = "swatch"; swatch.style.background = `var(${s.color})`;
        item.append(swatch, document.createTextNode(s.label));
        legend.appendChild(item);
      }
      host.appendChild(legend);
    }
    this.svg = svgEl("svg", { viewBox: `0 0 ${this.w} ${this.h}`, role: "img", "aria-label": title }, host);
    this.layer = svgEl("g", {}, this.svg);
    this.hover = svgEl("g", {}, this.svg);
    this.svg.addEventListener("mousemove", (e) => this.onMove(e));
    this.svg.addEventListener("mouseleave", () => { this.hover.replaceChildren(); hideTip(); });
    this.dirty = true;
    this.render();
  }

  reset() { this.points = []; this.markers = []; this.valueEl.textContent = ""; this.dirty = true; this.render(); }
  push(x, values) { this.points.push({ x, values }); this.dirty = true; }
  mark(x, label) { this.markers.push({ x, label }); this.dirty = true; }

  scales() {
    const { l, r, t, b } = this.m;
    const xs = this.points.map((p) => p.x);
    const x0 = xs.length ? xs[0] : 0;
    const x1 = xs.length > 1 ? xs[xs.length - 1] : x0 + 1;
    const vals = this.points.flatMap((p) => p.values.filter((v) => v !== null && v !== undefined));
    const biggest = Math.max(...vals, 0), smallest = Math.min(...vals, 0);
    const high = this.yMax ?? (biggest > 0 || smallest === 0 ? niceMax(biggest) : 0);
    const low = this.yMin ?? (smallest < 0 ? -niceMax(-smallest) : 0);
    const sx = (v) => l + ((v - x0) / (x1 - x0 || 1)) * (this.w - l - r);
    const sy = (v) => this.h - b - ((v - low) / (high - low || 1)) * (this.h - t - b);
    return { sx, sy, x0, x1, low, high };
  }

  render() {
    if (!this.dirty) return;
    this.dirty = false;
    const { l, r, t, b } = this.m;
    this.layer.replaceChildren();
    const { sx, sy, x0, x1, low, high } = this.scales();
    for (let i = 0; i <= 3; i++) {
      const v = low + ((high - low) * i) / 3;
      const y = sy(v);
      svgEl("line", { x1: l, x2: this.w - r, y1: y, y2: y, class: i === 0 ? "axis" : "grid" }, this.layer);
      const label = svgEl("text", { x: l - 6, y: y + 4, "text-anchor": "end" }, this.layer);
      label.textContent = Math.abs(high - low) >= 10 ? v.toFixed(0) : v.toFixed(Math.abs(high - low) >= 2 ? 1 : 2);
    }
    if (!this.points.length) {
      const note = svgEl("text", { x: (l + this.w - r) / 2, y: (t + this.h - b) / 2, class: "empty" }, this.layer);
      note.textContent = "No data yet";
      return;
    }
    for (const x of x1 - x0 < 2 ? [x0, x1] : [x0, (x0 + x1) / 2, x1]) {
      const label = svgEl("text", { x: sx(x), y: this.h - 6, "text-anchor": x === x0 ? "start" : x === x1 ? "end" : "middle" }, this.layer);
      label.textContent = `${Math.round(x)}${this.xLabel === "s" ? " s" : ""}`;
    }
    for (const m of this.markers) {
      if (m.x >= x0 && m.x <= x1) svgEl("line", { x1: sx(m.x), x2: sx(m.x), y1: t, y2: this.h - b, class: "marker-line" }, this.layer);
    }
    this.series.forEach((s, i) => {
      const pts = this.points.filter((p) => p.values[i] !== null && p.values[i] !== undefined);
      if (s.dots) {
        for (const p of pts) svgEl("circle", { cx: sx(p.x), cy: sy(p.values[i]), r: 4, class: "dot", fill: `var(${s.color})` }, this.layer);
        return;
      }
      if (pts.length) {
        svgEl("polyline", {
          class: "series", stroke: `var(${s.color})`,
          points: pts.map((p) => `${sx(p.x).toFixed(1)},${sy(p.values[i]).toFixed(1)}`).join(" "),
        }, this.layer);
      }
    });
    const lastValues = this.points[this.points.length - 1].values;
    if (this.series.length === 1 && lastValues[0] !== null && lastValues[0] !== undefined) {
      this.valueEl.textContent = `${fmt(lastValues[0], this.digits)}${this.unit ? " " + this.unit : ""}`;
    }
  }

  onMove(event) {
    if (!this.points.length) return;
    const rect = this.svg.getBoundingClientRect();
    const px = ((event.clientX - rect.left) / rect.width) * this.w;
    const { sx, sy } = this.scales();
    let best = this.points[0];
    for (const p of this.points) if (Math.abs(sx(p.x) - px) < Math.abs(sx(best.x) - px)) best = p;
    this.hover.replaceChildren();
    svgEl("line", { x1: sx(best.x), x2: sx(best.x), y1: this.m.t, y2: this.h - this.m.b, class: "crosshair" }, this.hover);
    const lines = [`${this.xLabel === "s" ? "t = " + best.x.toFixed(1) + " s" : this.xLabel + " " + best.x}`];
    this.series.forEach((s, i) => {
      const v = best.values[i];
      if (v === null || v === undefined) return;
      svgEl("circle", { cx: sx(best.x), cy: sy(v), r: 4, class: "dot", fill: `var(${s.color})` }, this.hover);
      lines.push(`${s.label}: ${fmt(v, this.digits)}${this.unit ? " " + this.unit : ""}`);
    });
    const near = this.markers.filter((m) => Math.abs(m.x - best.x) < 0.11);
    for (const m of near) lines.push(`Event: ${m.label}`);
    showTip(lines.join("\n"), event);
  }
}

/* ---------- Network map ---------- */

class NetworkMap {
  constructor(host, config, onLink, onNode) {
    this.config = config; this.onLink = onLink; this.onNode = onNode;
    this.frame = null; this.route = []; this.spfRoute = [];
    this.svg = svgEl("svg", { viewBox: "0 0 860 600", role: "img", "aria-label": "10-node network topology" }, host);
    this.links = config.links.map((link) => this.buildLink(link));
    this.spfOverlay = svgEl("polyline", { class: "spf-overlay" }, this.svg);
    this.routeOverlay = svgEl("polyline", { class: "route-overlay" }, this.svg);
    this.nodes = config.nodes.map((node) => this.buildNode(node));
    this.lastTick = performance.now();
    requestAnimationFrame((t) => this.animate(t));
  }

  pos(id) { return this.config.nodes[id]; }

  buildLink(link) {
    const a = this.pos(link.u), b = this.pos(link.v);
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy);
    const nx = (-dy / len) * 3.6, ny = (dx / len) * 3.6;
    const width = link.mbps >= 20 ? 5.5 : 3.5;
    const group = svgEl("g", {}, this.svg);
    const dirs = [[a, b, 1], [b, a, -1]].map(([p, q, side]) => {
      const coords = { x1: p.x + nx * side, y1: p.y + ny * side, x2: q.x + nx * side, y2: q.y + ny * side };
      const line = svgEl("line", { ...coords, class: "link-line", "stroke-width": width }, group);
      const flow = svgEl("line", { ...coords, class: "link-flow" }, group);
      return { line, flow, offset: 0 };
    });
    const hit = svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "link-hit" }, group);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    // Placed off-center so that the failure mark at the midpoint never covers it.
    const lx = a.x + dx * 0.3, ly = a.y + dy * 0.3;
    const label = svgEl("text", { x: lx + (-dy / len) * 18, y: ly + (dx / len) * 18 + 4, class: "link-label" }, group);
    label.textContent = `${link.mbps} Mb`;
    const mark = svgEl("text", { x: mx, y: my, class: "fail-mark" }, group);
    mark.textContent = "✕"; mark.style.display = "none";
    hit.addEventListener("click", () => this.onLink(link));
    hit.addEventListener("mousemove", (e) => showTip(this.linkTip(link), e));
    hit.addEventListener("mouseleave", hideTip);
    return { link, group, dirs, mark };
  }

  buildNode(node) {
    const group = svgEl("g", { class: "node", transform: `translate(${node.x},${node.y})` }, this.svg);
    const R = 25, C = 2 * Math.PI * R;
    svgEl("circle", { r: R, class: "queue-track" }, group);
    const ring = svgEl("circle", {
      r: R, class: "queue-ring", "stroke-dasharray": `0 ${C}`, transform: "rotate(-90)",
    }, group);
    svgEl("circle", { r: 20, class: "body" }, group);
    const text = svgEl("text", {}, group);
    text.textContent = node.id;
    group.addEventListener("click", () => this.onNode(node));
    group.addEventListener("mousemove", (e) => showTip(this.nodeTip(node), e));
    group.addEventListener("mouseleave", hideTip);
    return { group, ring, circumference: C };
  }

  linkTip(link) {
    const lines = [`Link ${link.id}: ${link.u} ↔ ${link.v}`, `${link.mbps} Mbps, ${link.delay_ms} ms`];
    const f = this.frame;
    if (f) {
      if (!f.link_up[link.id]) lines.push("Status: ✕ failed");
      const i = 2 * link.id;
      lines.push(`${link.u}→${link.v}: ${(100 * f.util[i]).toFixed(0)}% busy, queue ${(100 * f.queue[i]).toFixed(0)}%, loss ${(100 * f.loss[i]).toFixed(1)}%`);
      lines.push(`${link.v}→${link.u}: ${(100 * f.util[i + 1]).toFixed(0)}% busy, queue ${(100 * f.queue[i + 1]).toFixed(0)}%, loss ${(100 * f.loss[i + 1]).toFixed(1)}%`);
    }
    lines.push(f && !f.link_up[link.id] ? "Click to restore" : "Click to fail");
    return lines.join("\n");
  }

  nodeTip(node) {
    const f = this.frame;
    const lines = [`Router ${node.id}`];
    if (f) {
      if (f.node_down[node.id]) lines.push("Status: ✕ failed");
      lines.push(`Fullest outgoing queue: ${(100 * this.nodeQueue(node.id)).toFixed(0)}%`);
    }
    lines.push(f && f.node_down[node.id] ? "Click to restore" : "Click to fail");
    return lines.join("\n");
  }

  nodeQueue(id) {
    let most = 0;
    for (const link of this.config.links) {
      if (link.u === id) most = Math.max(most, this.frame.queue[2 * link.id]);
      if (link.v === id) most = Math.max(most, this.frame.queue[2 * link.id + 1]);
    }
    return most;
  }

  setColors() {
    this.low = hexToRgb(css("--seq-low"));
    this.high = hexToRgb(css("--seq-high"));
  }

  update(frame) {
    this.frame = frame;
    if (!this.low) this.setColors();
    this.links.forEach(({ link, group, dirs, mark }) => {
      const failed = !frame.link_up[link.id];
      group.classList.toggle("link-failed", failed);
      mark.style.display = failed ? "" : "none";
      dirs.forEach((d, side) => {
        d.util = frame.util[2 * link.id + side];
        d.line.setAttribute("stroke", mix(this.low, this.high, Math.min(1, d.util)));
      });
    });
    this.nodes.forEach(({ group, ring, circumference }, id) => {
      group.classList.toggle("down", frame.node_down[id]);
      const filled = this.nodeQueue(id) * circumference;
      ring.setAttribute("stroke-dasharray", `${filled.toFixed(1)} ${circumference}`);
    });
  }

  clear() {
    this.frame = null;
    if (!this.low) this.setColors();
    this.links.forEach(({ group, dirs, mark }) => {
      group.classList.remove("link-failed");
      mark.style.display = "none";
      dirs.forEach((d) => { d.util = 0; d.line.setAttribute("stroke", mix(this.low, this.high, 0)); });
    });
    this.nodes.forEach(({ group, ring, circumference }) => {
      group.classList.remove("down");
      ring.setAttribute("stroke-dasharray", `0 ${circumference}`);
    });
  }

  setRoutes(active, spf) {
    const toPoints = (path) => path.map((id) => `${this.pos(id).x},${this.pos(id).y}`).join(" ");
    this.routeOverlay.setAttribute("points", toPoints(active));
    this.spfOverlay.setAttribute("points", toPoints(spf));
  }

  animate(now) {
    const dt = Math.min(now - this.lastTick, 100) / 1000;
    this.lastTick = now;
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      for (const { dirs } of this.links) {
        for (const d of dirs) {
          if (d.util > 0.005) {
            d.offset -= (15 + 90 * d.util) * dt;
            d.flow.setAttribute("stroke-dashoffset", d.offset.toFixed(1));
            d.flow.style.opacity = 1;
          } else {
            d.flow.style.opacity = 0;
          }
        }
      }
    }
    requestAnimationFrame((t) => this.animate(t));
  }
}

/* ---------- Grouped bars for the benchmark ---------- */

function barChart(host, { title, unit, summary, metric, scale = 1, digits = 2, better }) {
  host.replaceChildren();
  host.classList.add("chart");
  const head = document.createElement("div");
  head.className = "chart-head";
  const t = document.createElement("span");
  t.className = "chart-title"; t.textContent = title;
  const note = document.createElement("span");
  note.className = "chart-value"; note.textContent = better;
  head.append(t, note);
  host.appendChild(head);

  const scenarios = [...new Set(summary.map((r) => r.scenario))];
  const W = 520, H = 200, m = { l: 44, r: 8, t: 10, b: 24 };
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": title }, host);
  const tops = summary.map((r) => (r[metric] + r[`${metric}_std`]) * scale);
  const hi = niceMax(Math.max(...tops, 0));
  const sy = (v) => H - m.b - (v / hi) * (H - m.t - m.b);
  for (let i = 0; i <= 3; i++) {
    const v = (hi * i) / 3, y = sy(v);
    svgEl("line", { x1: m.l, x2: W - m.r, y1: y, y2: y, class: i === 0 ? "axis" : "grid" }, svg);
    const label = svgEl("text", { x: m.l - 6, y: y + 4, "text-anchor": "end" }, svg);
    label.textContent = hi >= 10 ? v.toFixed(0) : v.toFixed(1);
  }
  const band = (W - m.l - m.r) / scenarios.length;
  const barW = Math.min(36, band * 0.3);
  scenarios.forEach((scenario, i) => {
    const center = m.l + band * (i + 0.5);
    const label = svgEl("text", { x: center, y: H - 7, "text-anchor": "middle" }, svg);
    label.textContent = scenario.replace("_", " ");
    [["dijkstra", "--series-1", "Dijkstra"], ["dqn", "--series-2", "DQN"]].forEach(([policy, color, name], j) => {
      const row = summary.find((r) => r.scenario === scenario && r.policy === policy);
      if (!row) return;
      const value = row[metric] * scale, std = row[`${metric}_std`] * scale;
      const x = center + (j === 0 ? -barW - 1 : 1);
      const y = sy(value), base = sy(0), r = Math.min(4, Math.max(base - y, 0));
      svgEl("path", {
        class: "bar", fill: `var(${color})`,
        d: `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + barW - r}Q${x + barW},${y} ${x + barW},${y + r}V${base}Z`,
      }, svg);
      const cx = x + barW / 2;
      if (std > 0) svgEl("line", { x1: cx, x2: cx, y1: sy(value + std), y2: sy(Math.max(value - std, 0)), class: "whisker" }, svg);
      const hit = svgEl("rect", { x, y: m.t, width: barW, height: base - m.t, fill: "transparent" }, svg);
      hit.addEventListener("mousemove", (e) => showTip(`${scenario.replace("_", " ")} · ${name}\n${title}: ${fmt(value, digits)} ± ${fmt(std, digits)} ${unit}\n${row.runs} runs`, e));
      hit.addEventListener("mouseleave", hideTip);
    });
  });
}

function renderBenchmark(results) {
  const summary = results.summary || [];
  const note = $("bench-note");
  if (!summary.length) {
    note.textContent = "No results yet. Run a benchmark to fill this page.";
    note.className = "state-note";
    $("bench-legend").hidden = true; $("bench-table-card").hidden = true;
    $("bench-charts").replaceChildren();
    return;
  }
  note.textContent = results.backend === "ns3"
    ? "Results from ns-3."
    : "⚠ These results come from the surrogate model, an approximation. Use ns-3 results in your report.";
  note.className = results.backend === "ns3" ? "state-note" : "state-note warn";
  $("bench-legend").hidden = false;
  const charts = $("bench-charts");
  charts.replaceChildren();
  const specs = [
    { title: "Packet delivery ratio", unit: "%", metric: "pdr", scale: 100, better: "higher is better" },
    { title: "End-to-end latency", unit: "ms", metric: "latency_ms", better: "lower is better" },
    { title: "Throughput", unit: "Mbps", metric: "throughput_mbps", better: "higher is better" },
    { title: "Jitter", unit: "ms", metric: "jitter_ms", better: "lower is better" },
  ];
  for (const spec of specs) {
    const card = document.createElement("div");
    card.className = "card chart-card";
    const host = document.createElement("div");
    card.appendChild(host); charts.appendChild(card);
    barChart(host, { ...spec, summary });
  }
  const body = $("bench-body");
  body.replaceChildren();
  for (const r of summary) {
    const tr = document.createElement("tr");
    const cells = [
      r.scenario.replace("_", " "), r.policy === "dqn" ? "DQN" : "Dijkstra", r.runs,
      `${fmt(100 * r.pdr)} ± ${fmt(100 * r.pdr_std)}`,
      `${fmt(r.latency_ms)} ± ${fmt(r.latency_ms_std)}`,
      `${fmt(r.throughput_mbps)} ± ${fmt(r.throughput_mbps_std)}`,
      `${fmt(r.jitter_ms)} ± ${fmt(r.jitter_ms_std)}`,
      fmt(r.reward, 3),
    ];
    for (const c of cells) { const td = document.createElement("td"); td.textContent = c; tr.appendChild(td); }
    body.appendChild(tr);
  }
  $("bench-table-card").hidden = false;
}

/* ---------- Application ---------- */

const app = { config: null, map: null, charts: {}, trainCharts: {}, job: null, paused: false, lastFrame: null, backend: "surrogate" };

function fillSelect(select, options, value) {
  select.replaceChildren();
  for (const opt of options) {
    const el = document.createElement("option");
    el.value = opt.value; el.textContent = opt.label; el.disabled = !!opt.disabled;
    select.appendChild(el);
  }
  if (value !== undefined) select.value = value;
}

function setBadge(backend) {
  const badge = $("backend-badge");
  if (backend === "ns3") {
    badge.textContent = "Simulator: ns-3"; badge.className = "pill good";
  } else {
    badge.textContent = "⚠ Simulator: surrogate approximation"; badge.className = "pill warn";
  }
}

function setJob(job, state) {
  app.job = state === "running" ? job : null;
  const running = !!app.job;
  const pill = $("job-pill");
  const names = { run: "Live run", train: "Training", benchmark: "Benchmark" };
  pill.className = "pill" + (state === "running" ? " good" : state === "error" ? " bad" : "");
  pill.textContent = running ? `${names[job]} in progress` : state === "error" ? "✕ Error" : "Idle";

  $("run-start").disabled = running;
  $("train-start").disabled = running;
  $("bench-start").disabled = running;
  $("run-pause").disabled = job !== "run" || !running;
  $("run-stop").disabled = job !== "run" || !running;
  $("train-stop").disabled = job !== "train" || !running;
  $("bench-stop").disabled = job !== "benchmark" || !running;
  $("run-scale").disabled = job !== "run" || !running;
  if (!running) {
    app.paused = false;
    $("run-pause").textContent = "Pause";
  }
}

function logEvent(text) {
  const li = document.createElement("li");
  const time = document.createElement("time");
  time.textContent = app.lastFrame ? `${app.lastFrame.time_s.toFixed(1)} s` : "0.0 s";
  li.append(time, document.createTextNode(text));
  const log = $("event-log");
  log.prepend(li);
  while (log.children.length > 40) log.lastChild.remove();
}

function describeEvent(text) {
  const [action, target] = text.split(" ");
  const names = { link_down: `Link ${target} failed`, link_up: `Link ${target} restored`, node_down: `Router ${target} failed`, node_up: `Router ${target} restored`, scale: `Traffic set to ${Math.round(target * 100)}%` };
  return names[action] || text;
}

function updateRoutes() {
  const f = app.lastFrame;
  const src = Number($("route-src").value), dst = Number($("route-dst").value);
  $("fib-caption").textContent = `Next hop towards node ${dst}`;
  const walk = (fib) => {
    const path = [src], seen = new Set([src]);
    while (path[path.length - 1] !== dst) {
      const hop = fib[path[path.length - 1]][dst];
      if (hop < 0 || seen.has(hop)) return { path, reached: false };
      path.push(hop); seen.add(hop);
    }
    return { path, reached: true };
  };
  if (!f) {
    $("route-active").textContent = "Start a run to see routes";
    $("route-spf").textContent = "–";
    $("fib-body").replaceChildren();
    app.map.setRoutes([], []);
    return;
  }
  const active = walk(f.fib), spf = walk(f.spf);
  const describe = (r) => r.path.join(" → ") + (r.reached ? "" : " (✕ unreachable)");
  $("route-active").textContent = describe(active);
  $("route-spf").textContent = describe(spf);
  app.map.setRoutes(active.path, spf.path);
  const body = $("fib-body");
  body.replaceChildren();
  for (let n = 0; n < app.config.nodes.length; n++) {
    if (n === dst) continue;
    const tr = document.createElement("tr");
    const a = f.fib[n][dst], b = f.spf[n][dst];
    if (a !== b) tr.className = "differs";
    for (const c of [n, a < 0 ? "none" : a, b < 0 ? "none" : b]) {
      const td = document.createElement("td"); td.textContent = c; tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

function onFrame(f) {
  app.lastFrame = f;
  app.map.update(f);
  $("run-progress").firstElementChild.style.width = `${(100 * f.step) / f.episode_steps}%`;
  $("tile-pdr").textContent = `${fmt(100 * f.metrics.pdr)}%`;
  $("tile-latency").textContent = `${fmt(f.metrics.latency_ms)} ms`;
  $("tile-throughput").textContent = `${fmt(f.metrics.throughput_mbps)} Mbps`;
  $("tile-jitter").textContent = `${fmt(f.metrics.jitter_ms)} ms`;
  $("tile-reward").textContent = fmt(f.reward, 3);
  $("guard-loops").textContent = f.guard.loops_broken;
  $("guard-invalid").textContent = f.guard.invalid_hops;
  $("run-scale-value").textContent = `${Math.round(f.scale * 100)}%`;
  if (document.activeElement !== $("run-scale")) $("run-scale").value = f.scale;

  const note = $("run-state");
  if (f.cold_start && app.runPolicy === "dqn") {
    note.textContent = "⚠ Cold start: using Dijkstra until the agent takes over";
    note.className = "state-note warn";
  } else {
    note.textContent = `${f.time_s.toFixed(1)} s of ${(f.episode_steps * 0.1).toFixed(0)} s simulated`;
    note.className = "state-note";
  }

  const i = f.instant, c = app.charts;
  c.pdr.push(f.time_s, [i.pdr === null ? null : 100 * i.pdr]);
  c.latency.push(f.time_s, [i.latency_ms]);
  c.throughput.push(f.time_s, [i.throughput_mbps]);
  c.jitter.push(f.time_s, [i.jitter_ms]);
  for (const e of f.events) {
    const label = describeEvent(e);
    logEvent(label);
    for (const chart of Object.values(c)) chart.mark(f.time_s, label);
  }
  updateRoutes();
}

function resetLive() {
  app.lastFrame = null;
  for (const chart of Object.values(app.charts)) chart.reset();
  app.map.clear();
  $("event-log").replaceChildren();
  for (const id of ["tile-pdr", "tile-latency", "tile-throughput", "tile-jitter", "tile-reward"]) $(id).textContent = "–";
  $("guard-loops").textContent = "0"; $("guard-invalid").textContent = "0";
  $("run-progress").firstElementChild.style.width = "0";
  updateRoutes();
}

function connectStream() {
  const stream = new EventSource("/api/stream");
  const on = (name, fn) => stream.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  on("frame", onFrame);
  on("run_start", (d) => {
    app.runPolicy = d.policy;
    setBadge(d.backend);
  });
  on("job", (d) => {
    setJob(d.job, d.state);
    if (d.state === "error") { toast(d.error); }
    const target = { run: $("run-state"), train: $("train-state"), benchmark: $("bench-note") }[d.job];
    if (d.state === "error") { target.textContent = `✕ ${d.error}`; target.className = "state-note bad"; }
    else if (d.state === "finished" && d.job === "run") { target.textContent = "Run finished"; target.className = "state-note"; }
    else if (d.state === "stopped" && d.job !== "benchmark") { target.textContent = "Stopped"; target.className = "state-note"; }
  });
  on("train", (r) => {
    $("train-progress").firstElementChild.style.width = `${(100 * r.episode) / r.episodes}%`;
    const held = r.eval_reward !== undefined ? `, held-out reward ${fmt(r.eval_reward, 3)}` : "";
    $("train-state").textContent = `Episode ${r.episode} of ${r.episodes} (${r.scenario.replace("_", " ")}), exploration ${fmt(r.epsilon)}${held}`;
    $("train-state").className = "state-note";
    app.trainCharts.reward.push(r.episode, [r.reward, r.eval_reward ?? null]);
    app.trainCharts.pdr.push(r.episode, [100 * r.pdr]);
  });
  on("train_done", (d) => {
    if (d.best_eval_reward > -Infinity) {
      $("train-state").textContent = `Done. Best held-out reward ${fmt(d.best_eval_reward, 3)}; saved to checkpoints/dqn.pt`;
    }
    app.config.checkpoint = true;
  });
  on("benchmark_progress", (p) => {
    $("bench-progress").firstElementChild.style.width = `${(100 * p.done) / p.total}%`;
    $("bench-note").textContent = `Completed ${p.done} of ${p.total} runs`;
    $("bench-note").className = "state-note";
  });
  on("benchmark", renderBenchmark);
}

function backendOptions(config) {
  return Object.entries(config.backends).map(([name, info]) => ({
    value: name,
    label: name === "ns3" ? (info.ready ? "ns-3" : "ns-3 (not set up)") : "Surrogate",
    disabled: !info.ready,
  }));
}

async function init() {
  const config = await (await fetch("/api/config")).json();
  app.config = config;
  const backends = backendOptions(config);
  const preferred = config.backends.ns3.ready ? "ns3" : "surrogate";
  for (const id of ["run-backend", "train-backend", "bench-backend"]) fillSelect($(id), backends, preferred);
  if (!config.backends.ns3.ready) {
    for (const id of ["run-backend", "train-backend", "bench-backend"]) $(id).title = `ns-3: ${config.backends.ns3.reason}`;
  }
  setBadge(preferred);
  fillSelect($("run-scenario"), config.scenarios.map((s) => ({ value: s, label: s.replace("_", " ") })), "bursty");
  const nodeOptions = config.nodes.map((n) => ({ value: n.id, label: `Node ${n.id}` }));
  fillSelect($("route-src"), nodeOptions, 0);
  fillSelect($("route-dst"), nodeOptions, 9);
  if (!config.checkpoint) $("run-policy").value = "dijkstra";

  const onLink = (link) => {
    if (app.job !== "run") { toast("Start a run first, then click links to fail or restore them."); return; }
    const up = app.lastFrame ? !app.lastFrame.link_up[link.id] : false;
    post("/api/run/link", { link: link.id, up });
    logEvent(`${up ? "Restored" : "Failed"} link ${link.u}–${link.v} (manual)`);
    for (const chart of Object.values(app.charts)) chart.mark(app.lastFrame ? app.lastFrame.time_s : 0, `link ${link.u}–${link.v} ${up ? "restored" : "failed"}`);
  };
  const onNode = (node) => {
    if (app.job !== "run") { toast("Start a run first, then click routers to fail or restore them."); return; }
    const up = app.lastFrame ? app.lastFrame.node_down[node.id] : false;
    post("/api/run/node", { node: node.id, up });
    logEvent(`${up ? "Restored" : "Failed"} router ${node.id} (manual)`);
    for (const chart of Object.values(app.charts)) chart.mark(app.lastFrame ? app.lastFrame.time_s : 0, `router ${node.id} ${up ? "restored" : "failed"}`);
  };
  app.map = new NetworkMap($("map"), config, onLink, onNode);

  app.charts = {
    pdr: new LineChart($("chart-pdr"), { title: "Delivery per step", unit: "%", series: [{ label: "Delivery", color: "--series-1" }], yMax: 100, digits: 1 }),
    latency: new LineChart($("chart-latency"), { title: "Latency", unit: "ms", series: [{ label: "Latency", color: "--series-1" }], digits: 1 }),
    throughput: new LineChart($("chart-throughput"), { title: "Throughput", unit: "Mbps", series: [{ label: "Throughput", color: "--series-1" }], digits: 1 }),
    jitter: new LineChart($("chart-jitter"), { title: "Jitter", unit: "ms", series: [{ label: "Jitter", color: "--series-1" }], digits: 2 }),
  };
  app.trainCharts = {
    reward: new LineChart($("chart-train-reward"), { title: "Mean reward per episode", xLabel: "Episode", yMin: null, digits: 3,
      series: [{ label: "Training", color: "--series-1" }, { label: "Held-out", color: "--series-2", dots: true }] }),
    pdr: new LineChart($("chart-train-pdr"), { title: "Delivery during training", unit: "%", xLabel: "Episode", yMax: 100, digits: 1, series: [{ label: "Delivery", color: "--series-1" }] }),
  };
  resetLive();
  setInterval(() => {
    for (const chart of [...Object.values(app.charts), ...Object.values(app.trainCharts)]) chart.render();
  }, 200);

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    if (tab.dataset.view === "bench" && app.job !== "benchmark") loadBenchmark();
  }));

  $("route-src").addEventListener("change", updateRoutes);
  $("route-dst").addEventListener("change", updateRoutes);

  $("run-start").addEventListener("click", async () => {
    const options = {
      backend: $("run-backend").value, policy: $("run-policy").value,
      scenario: $("run-scenario").value, seed: Number($("run-seed").value),
    };
    await post("/api/run/speed", { steps_per_second: Number($("run-speed").value) });
    resetLive();
    await post("/api/run/start", options);
  });
  $("run-pause").addEventListener("click", async () => {
    app.paused = !app.paused;
    await post("/api/run/pause", { paused: app.paused });
    $("run-pause").textContent = app.paused ? "Resume" : "Pause";
  });
  $("run-speed").addEventListener("change", () => post("/api/run/speed", { steps_per_second: Number($("run-speed").value) }));
  for (const id of ["run-stop", "train-stop", "bench-stop"]) $(id).addEventListener("click", () => post("/api/stop"));
  $("run-scale").addEventListener("input", () => { $("run-scale-value").textContent = `${Math.round($("run-scale").value * 100)}%`; });
  $("run-scale").addEventListener("change", () => post("/api/run/scale", { scale: Number($("run-scale").value) }));

  $("train-start").addEventListener("click", async () => {
    for (const chart of Object.values(app.trainCharts)) chart.reset();
    $("train-progress").firstElementChild.style.width = "0";
    await post("/api/train/start", {
      backend: $("train-backend").value, episodes: Number($("train-episodes").value), seed: Number($("train-seed").value),
    });
  });
  $("bench-start").addEventListener("click", async () => {
    $("bench-progress").firstElementChild.style.width = "0";
    await post("/api/benchmark/start", { backend: $("bench-backend").value, seeds: Number($("bench-seeds").value) });
  });
  $("bench-backend").addEventListener("change", loadBenchmark);

  connectStream();
  setJob(config.status.job, config.status.job ? "running" : "idle");
  loadBenchmark();
}

async function loadBenchmark() {
  const backend = $("bench-backend").value;
  const results = await (await fetch(`/api/benchmark/latest?backend=${encodeURIComponent(backend)}`)).json();
  renderBenchmark(results);
}

init().catch((error) => toast(`Could not start the dashboard: ${error.message}`));
