// Small chart helpers for the analytics page: plain SVG and HTML, no library.

const SVG = "http://www.w3.org/2000/svg";
const tooltip = document.getElementById("an-tooltip");

export function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function svg(tag, attributes = {}) {
  const element = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

export const formatNumber = (value) => Number(value ?? 0).toLocaleString();
export const formatPercent = (value) => (value == null ? "–" : `${Math.round(value * 100)}%`);

function niceMax(value) {
  if (value <= 4) return 4;
  const step = 10 ** Math.floor(Math.log10(value));
  for (const factor of [1, 2, 2.5, 5, 10]) if (factor * step >= value) return factor * step;
  return value;
}

// Tooltip: rows of [color or null, label, value].
export function showTooltip(event, title, rows) {
  tooltip.replaceChildren(el("div", "an-tooltip-title", title));
  for (const [color, label, value] of rows) {
    const row = el("div", "an-tooltip-row");
    const key = el("span", "an-key");
    if (color) {
      const swatch = el("span", "an-swatch");
      swatch.style.background = color;
      key.append(swatch);
    }
    key.append(label);
    row.append(key, el("strong", "", value));
    tooltip.append(row);
  }
  tooltip.hidden = false;
  moveTooltip(event);
}

export function moveTooltip(event) {
  const gap = 14;
  const { innerWidth } = window;
  const width = tooltip.offsetWidth;
  const left = event.clientX + gap + width > innerWidth ? event.clientX - gap - width : event.clientX + gap;
  tooltip.style.left = `${Math.max(8, left)}px`;
  tooltip.style.top = `${event.clientY + gap}px`;
}

export function hideTooltip() {
  tooltip.hidden = true;
}

export function legend(series) {
  const box = el("div", "an-legend");
  for (const { label, color } of series) {
    const item = el("span", "an-key");
    const swatch = el("span", "an-swatch");
    swatch.style.background = color;
    item.append(swatch, label);
    box.append(item);
  }
  return box;
}

// A collapsed table under each chart, so the numbers can be read without colors.
export function dataTable(headers, rows) {
  const details = el("details", "an-table-toggle");
  details.append(el("summary", "", "Table"));
  const table = el("table", "an-table");
  const head = el("tr");
  for (const header of headers) head.append(el("th", "", header));
  table.append(el("thead")).append(head);
  const body = el("tbody");
  for (const row of rows) {
    const line = el("tr");
    for (const cell of row) line.append(el("td", "", String(cell)));
    body.append(line);
  }
  table.append(body);
  details.append(table);
  return details;
}

export function emptyState(text) {
  return el("p", "an-empty", text);
}

function yAxis(root, plot, max, format) {
  for (const fraction of [0, 0.5, 1]) {
    const y = plot.top + plot.height - fraction * plot.height;
    root.append(svg("line", { x1: plot.left, x2: plot.left + plot.width, y1: y, y2: y, class: fraction ? "an-grid-line" : "an-axis-line" }));
    const label = svg("text", { x: plot.left - 6, y: y + 3.5, class: "an-axis-text", "text-anchor": "end" });
    label.textContent = format(max * fraction);
    root.append(label);
  }
}

// Stacked columns, one per item. series: [{key, label, color}]; items: [{label, short, ...values}].
export function stackedColumns(container, items, series, { height = 190, format = formatNumber } = {}) {
  const width = Math.max(container.clientWidth, 280);
  const plot = { left: 34, top: 10, width: width - 42, height: height - 34 };
  const max = niceMax(Math.max(...items.map((item) => series.reduce((sum, s) => sum + item[s.key], 0)), 0));
  const root = svg("svg", { width, height, role: "img", "aria-label": container.getAttribute("aria-label") ?? "" });
  yAxis(root, plot, max, (value) => format(Math.round(value)));

  const band = plot.width / items.length;
  const barWidth = Math.max(2, Math.min(18, band * 0.68));
  const labelEvery = Math.ceil(items.length / Math.max(2, Math.floor(plot.width / 70)));
  items.forEach((item, index) => {
    const x = plot.left + index * band + (band - barWidth) / 2;
    let base = plot.top + plot.height;
    const parts = series.filter((s) => item[s.key] > 0);
    parts.forEach((s, partIndex) => {
      const full = (item[s.key] / max) * plot.height;
      const isTop = partIndex === parts.length - 1;
      const gap = isTop ? 0 : Math.min(2, full / 2);
      const segmentHeight = Math.max(1, full - gap);
      const y = base - full + gap;
      const radius = isTop ? Math.min(4, barWidth / 2, segmentHeight) : 0;
      const path = `M${x},${base} V${y + radius} Q${x},${y} ${x + radius},${y} H${x + barWidth - radius} Q${x + barWidth},${y} ${x + barWidth},${y + radius} V${base} Z`;
      root.append(svg("path", { d: path, fill: s.color }));
      base -= full;
    });
    if (index % labelEvery === 0 || index === items.length - 1) {
      const label = svg("text", { x: x + barWidth / 2, y: height - 8, class: "an-axis-text", "text-anchor": "middle" });
      label.textContent = item.short;
      root.append(label);
    }
    const hit = svg("rect", { x: plot.left + index * band, y: plot.top, width: band, height: plot.height, fill: "transparent" });
    hit.addEventListener("mouseenter", (event) => {
      showTooltip(event, item.label, series.map((s) => [s.color, s.label, format(item[s.key])]));
    });
    hit.addEventListener("mousemove", moveTooltip);
    hit.addEventListener("mouseleave", hideTooltip);
    root.append(hit);
  });
  container.replaceChildren(root);
}

// Lines over a shared x axis on a 0–1 scale. series: [{key, label, color}]; points: [{x, label, ...values}].
export function lines(container, points, series, { height = 200, marker = null, xFormat = String } = {}) {
  const width = Math.max(container.clientWidth, 280);
  const plot = { left: 40, top: 12, width: width - 54, height: height - 38 };
  const xs = points.map((point) => point.x);
  const minX = Math.min(...xs);
  const spanX = Math.max(...xs) - minX || 1;
  const xAt = (value) => plot.left + ((value - minX) / spanX) * plot.width;
  const yAt = (value) => plot.top + plot.height - value * plot.height;
  const root = svg("svg", { width, height, role: "img", "aria-label": container.getAttribute("aria-label") ?? "" });
  yAxis(root, plot, 1, formatPercent);

  for (const [index, point] of points.entries()) {
    if (index !== 0 && index !== points.length - 1 && index % Math.ceil(points.length / 5) !== 0) continue;
    const label = svg("text", { x: xAt(point.x), y: height - 10, class: "an-axis-text", "text-anchor": "middle" });
    label.textContent = xFormat(point.x);
    root.append(label);
  }

  if (marker !== null) {
    root.append(svg("line", { x1: xAt(marker.x), x2: xAt(marker.x), y1: plot.top, y2: plot.top + plot.height, class: "an-marker-line" }));
    const label = svg("text", { x: xAt(marker.x) + 5, y: plot.top + 10, class: "an-axis-text" });
    label.textContent = marker.label;
    root.append(label);
  }

  for (const s of series) {
    const drawn = points.filter((point) => point[s.key] != null);
    if (!drawn.length) continue;
    const d = drawn.map((point, index) => `${index ? "L" : "M"}${xAt(point.x)},${yAt(point[s.key])}`).join(" ");
    root.append(svg("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  }

  const crosshair = svg("line", { y1: plot.top, y2: plot.top + plot.height, class: "an-crosshair", visibility: "hidden" });
  root.append(crosshair);
  const dots = series.map((s) => {
    const dot = svg("circle", { r: 4.5, fill: s.color, class: "an-dot", visibility: "hidden" });
    root.append(dot);
    return dot;
  });

  const hit = svg("rect", { x: plot.left - 8, y: plot.top, width: plot.width + 16, height: plot.height, fill: "transparent" });
  hit.addEventListener("mousemove", (event) => {
    const box = root.getBoundingClientRect();
    const mouseX = event.clientX - box.left;
    const point = points.reduce((best, p) => (Math.abs(xAt(p.x) - mouseX) < Math.abs(xAt(best.x) - mouseX) ? p : best));
    crosshair.setAttribute("x1", xAt(point.x));
    crosshair.setAttribute("x2", xAt(point.x));
    crosshair.setAttribute("visibility", "visible");
    series.forEach((s, index) => {
      const visible = point[s.key] != null;
      dots[index].setAttribute("visibility", visible ? "visible" : "hidden");
      if (visible) {
        dots[index].setAttribute("cx", xAt(point.x));
        dots[index].setAttribute("cy", yAt(point[s.key]));
      }
    });
    showTooltip(event, point.label, series.map((s) => [s.color, s.label, formatPercent(point[s.key])]));
  });
  hit.addEventListener("mouseleave", () => {
    crosshair.setAttribute("visibility", "hidden");
    dots.forEach((dot) => dot.setAttribute("visibility", "hidden"));
    hideTooltip();
  });
  root.append(hit);
  container.replaceChildren(root);
}

// Horizontal bars, one row per item, stacked when there's more than one series.
export function barRows(items, series, { label = (item) => item.label, format = formatNumber } = {}) {
  const max = Math.max(...items.map((item) => series.reduce((sum, s) => sum + item[s.key], 0)), 1);
  const list = el("div", "an-bars");
  for (const item of items) {
    const total = series.reduce((sum, s) => sum + item[s.key], 0);
    const row = el("div", "an-bar-row");
    const name = el("span", "an-bar-label", label(item));
    name.title = label(item);
    const track = el("div", "an-bar-track");
    for (const s of series) {
      if (!item[s.key]) continue;
      const segment = el("span", "an-bar-segment");
      segment.style.width = `${(item[s.key] / max) * 100}%`;
      segment.style.background = s.color;
      track.append(segment);
    }
    track.addEventListener("mouseenter", (event) => {
      const rows = series.map((s) => [series.length > 1 ? s.color : null, s.label, format(item[s.key])]);
      showTooltip(event, label(item), rows);
    });
    track.addEventListener("mousemove", moveTooltip);
    track.addEventListener("mouseleave", hideTooltip);
    row.append(name, track, el("span", "an-bar-value", format(total)));
    list.append(row);
  }
  return list;
}

export function stat(label, value, note) {
  const box = el("div", "an-stat");
  box.append(el("span", "an-stat-label", label), el("span", "an-stat-value", value));
  if (note) box.append(el("span", "an-stat-note", note));
  return box;
}
