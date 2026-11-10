import { requestJson } from "../shared/httpClient.js";
import {
  barRows,
  dataTable,
  el,
  emptyState,
  formatNumber,
  formatPercent,
  legend,
  lines,
  stackedColumns,
  stat,
} from "./charts.js";

const RANGE_KEY = "analyticsDays";
const DEFAULT_DAYS = 30;
const METHODS = [
  { key: "words", label: "Words" },
  { key: "meaning", label: "Meaning" },
  { key: "hybrid", label: "Hybrid" },
];
const QUESTION_TYPES = {
  same_meaning: "Same meaning, other words",
  exact: "Exact names and numbers",
  dates: "Within dates",
  actions: "Past actions",
  answerable: "All with an answer",
};
const OUTCOMES = [
  { key: "done", label: "Done" },
  { key: "changed", label: "Changed" },
  { key: "denied", label: "Denied" },
  { key: "failed", label: "Failed" },
];
const CALL_LABELS = {
  booked: "Booked",
  calling: "In progress",
  needs_review: "Needs review",
  not_booked: "Not booked",
  failed: "Failed",
  unknown: "Unknown",
};
const VERDICT_LABELS = {
  task: "New task",
  same_task: "Same task again",
  completion: "Task finished",
  neither: "Nothing to do",
  discarded: "Skipped",
};

const status = document.getElementById("an-status");
const rangeButtons = [...document.querySelectorAll(".an-range button")];
const byId = (id) => document.getElementById(id);

let latest = null;

// Categorical slots, read from CSS so light and dark each use their own steps.
function color(slot) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--an-series-${slot}`).trim();
}

function readDays() {
  try {
    const saved = Number(localStorage.getItem(RANGE_KEY));
    return [7, 30, 90, 365].includes(saved) ? saved : DEFAULT_DAYS;
  } catch {
    return DEFAULT_DAYS;
  }
}

function saveDays(days) {
  try {
    localStorage.setItem(RANGE_KEY, String(days));
  } catch {
    // Remembering the range is only a convenience.
  }
}

function fill(id, ...children) {
  byId(id).replaceChildren(...children);
}

function unavailable(id, text = "Not available yet.") {
  fill(id, emptyState(text));
}

function formatDuration(seconds) {
  if (seconds == null) return "–";
  if (seconds < 90) return `${seconds}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function renderKpis(data) {
  const overview = data.overview;
  const tasks = data.tasks;
  const range = data.days === 365 ? "past year" : `last ${data.days} days`;
  const tiles = overview
    ? [
        stat("Questions asked", formatNumber(overview.asked), range),
        stat("Replies", formatNumber(overview.answered), range),
        stat("Chats used", formatNumber(overview.chats), `${formatNumber(overview.allChats)} in total`),
        stat("Tool actions", formatNumber(overview.actions), range),
      ]
    : [stat("Chats", "–", "The database isn't connected")];
  if (tasks) tiles.push(stat("Open To Do", formatNumber(tasks.open), `${formatNumber(tasks.completed)} finished`));
  fill("an-kpis", ...tiles);
}

function renderDaily(data) {
  if (!data.daily) return unavailable("an-daily");
  const series = [
    { key: "web", label: "Web", color: color(1) },
    { key: "telegram", label: "Telegram", color: color(2) },
  ];
  const items = data.daily.map((day) => {
    const date = new Date(`${day.day}T00:00:00`);
    return {
      ...day,
      label: date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }),
      short: date.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    };
  });
  const box = byId("an-daily");
  const chart = el("div", "an-plot");
  chart.setAttribute("aria-label", "Questions asked per day, web and Telegram");
  box.replaceChildren(legend(series), chart, dataTable(["Day", "Web", "Telegram"], items.map((i) => [i.day, i.web, i.telegram])));
  if (items.every((item) => item.web + item.telegram === 0)) {
    chart.replaceChildren(emptyState("No questions in this range."));
    return;
  }
  stackedColumns(chart, items, series);
}

function renderModels(data) {
  if (!data.models) return unavailable("an-models");
  if (!data.models.length) return unavailable("an-models", "No replies in this range.");
  const series = [{ key: "replies", label: "Replies", color: color(1) }];
  fill(
    "an-models",
    barRows(data.models, series, { label: (item) => item.model }),
    dataTable(["Model", "Replies"], data.models.map((m) => [m.model, m.replies])),
  );
}

function renderTools(data) {
  if (!data.tools) return unavailable("an-tools");
  const { tools, totals } = data.tools;
  if (!tools.length) return unavailable("an-tools", "No tools used in this range.");
  const series = OUTCOMES.map((outcome, index) => ({ ...outcome, color: color(index + 1) }));
  const done = totals.done + totals.changed;
  const asked = totals.done + totals.changed + totals.denied;
  const summary = el("p", "an-note", asked ? `${formatPercent(done / asked)} of actions that needed a decision went ahead.` : "");
  fill(
    "an-tools",
    legend(series),
    barRows(tools, series, { label: (item) => item.tool }),
    summary,
    dataTable(["Tool", ...OUTCOMES.map((o) => o.label), "Total"], tools.map((t) => [t.tool, ...OUTCOMES.map((o) => t[o.key]), t.total])),
  );
}

function renderTasks(data) {
  const tasks = data.tasks;
  if (!tasks) return unavailable("an-tasks");
  const stats = el("div", "an-stats");
  stats.append(
    stat("Found", formatNumber(tasks.found)),
    stat("Finished", formatNumber(tasks.completed), `${formatNumber(tasks.closedByEmail)} confirmed by email`),
    stat("Open now", formatNumber(tasks.open)),
  );
  const checked = tasks.emailsChecked.map((v) => ({ ...v, label: VERDICT_LABELS[v.verdict] ?? v.verdict }));
  const total = checked.reduce((sum, v) => sum + v.emails, 0);
  const parts = [stats, el("h4", "an-subtitle", `Emails checked: ${formatNumber(total)}`)];
  if (total) parts.push(barRows(checked, [{ key: "emails", label: "Emails", color: color(1) }]));
  parts.push(dataTable(["Email verdict", "Emails"], checked.map((v) => [v.label, v.emails])));
  fill("an-tasks", ...parts);
}

function renderCalls(data) {
  if (!data.calls) return unavailable("an-calls");
  const calls = data.calls.map((c) => ({ ...c, label: CALL_LABELS[c.status] ?? c.status }));
  const total = calls.reduce((sum, c) => sum + c.calls, 0);
  if (!total) return unavailable("an-calls", "No calls in this range.");
  const booked = calls.find((c) => c.status === "booked")?.calls ?? 0;
  const stats = el("div", "an-stats");
  stats.append(stat("Calls", formatNumber(total)), stat("Booked", formatPercent(booked / total)));
  fill(
    "an-calls",
    stats,
    barRows(calls, [{ key: "calls", label: "Calls", color: color(1) }]),
    dataTable(["Result", "Calls"], calls.map((c) => [c.label, c.calls])),
  );
}

function renderAlarms(data) {
  const alarms = data.alarms;
  if (!alarms) return unavailable("an-alarms", "Alarms appear here once their migration has run.");
  const stats = el("div", "an-stats");
  stats.append(
    stat("Active now", formatNumber(alarms.active)),
    stat("Raised", formatNumber(alarms.raised)),
    stat("Median time to fix", formatDuration(alarms.medianFixSeconds)),
  );
  const parts = [stats];
  if (alarms.byName.length) {
    parts.push(el("h4", "an-subtitle", "Most frequent"));
    parts.push(barRows(alarms.byName, [{ key: "raised", label: "Raised", color: color(1) }], { label: (item) => item.name }));
  }
  fill("an-alarms", ...parts);
}

function meter(label, done, total) {
  const box = el("div", "an-meter");
  const share = total ? done / total : 0;
  const head = el("div", "an-meter-head");
  head.append(el("span", "", label), el("strong", "", `${formatNumber(done)} of ${formatNumber(total)} · ${formatPercent(total ? share : null)}`));
  box.append(head);
  const track = el("div", "an-bar-track");
  const segment = el("span", "an-bar-segment");
  segment.style.width = `${share * 100}%`;
  segment.style.background = color(1);
  track.append(segment);
  box.append(track);
  return box;
}

function renderCoverage(data) {
  const coverage = data.searchCoverage;
  if (!coverage) {
    return unavailable("an-coverage", "Meaning search isn't set up yet: pgvector needs installing. Word search works meanwhile.");
  }
  fill(
    "an-coverage",
    meter("Messages", coverage.messagesEmbedded, coverage.messages),
    meter("Tool actions", coverage.actionsEmbedded, coverage.actions),
    el("p", "an-note", `Model: ${coverage.model}. New messages are added about once a minute.`),
  );
}

function scoreCell(row) {
  const cell = el("td", "an-score");
  if (!row) {
    cell.textContent = "–";
    return cell;
  }
  const value = row.recall_at_5 ?? row.empty_rate;
  const bar = el("span", "an-score-bar");
  bar.style.width = `${(value ?? 0) * 100}%`;
  const text = el("span", "an-score-text", formatPercent(value));
  if (row.mrr != null) text.title = `MRR ${row.mrr.toFixed(2)}`;
  cell.append(bar, text);
  return cell;
}

function renderScores(evaluation) {
  const run = evaluation.latest;
  const table = el("table", "an-table an-scorecard");
  const head = el("tr");
  head.append(el("th", "", "Question type"));
  for (const method of METHODS) head.append(el("th", "", method.label));
  table.append(el("thead")).append(head);
  const body = el("tbody");
  for (const [type, name] of Object.entries(QUESTION_TYPES)) {
    const row = el("tr", type === "answerable" ? "an-total-row" : "");
    const count = run.scores.hybrid?.[type]?.questions;
    row.append(el("td", "", count ? `${name} (${count})` : name));
    for (const method of METHODS) row.append(scoreCell(run.scores[method.key]?.[type]));
    body.append(row);
  }
  const nothing = el("tr");
  nothing.append(el("td", "", `Nothing to find: comes back empty (${run.scores.hybrid?.nothing?.questions ?? 0})`));
  for (const method of METHODS) nothing.append(scoreCell(run.scores[method.key]?.nothing));
  body.append(nothing);
  table.append(body);

  const latency = el("div", "an-stats");
  for (const method of METHODS) {
    const time = run.latency?.[method.key];
    latency.append(stat(`${method.label} search time`, time ? `${formatNumber(time.medianMs)} ms` : "–", time ? `slowest ${formatNumber(time.slowestMs)} ms` : ""));
  }

  const ran = new Date(run.ranAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const parts = [
    el("p", "an-note", `Top-5 recall on ${run.questions} made-up questions · ${run.model} · cutoff ${run.settings.cutoff} · ${ran}`),
    table,
    latency,
  ];
  if (run.hybridMisses?.length) {
    const misses = el("details", "an-table-toggle");
    misses.append(el("summary", "", `Hybrid misses (${run.hybridMisses.length})`));
    const list = el("ul", "an-misses");
    for (const miss of run.hybridMisses) {
      list.append(el("li", "", `“${miss.query}”: expected ${miss.expected.join(", ") || "nothing"}, got ${miss.got.join(", ") || "nothing"}`));
    }
    misses.append(list);
    parts.push(misses);
  }
  fill("an-scores", ...parts);
}

function renderSweep(evaluation) {
  const run = evaluation.latest;
  const series = [
    { key: "recall", label: "Found the answer (top 5)", color: color(1) },
    { key: "empty", label: "Nothing-to-find came back empty", color: color(2) },
  ];
  const points = run.cutoffSweep.map((row) => ({
    x: row.cutoff,
    label: `Cutoff ${row.cutoff.toFixed(3)}`,
    recall: row.hybrid.answerable?.recall_at_5 ?? null,
    empty: row.hybrid.nothing?.empty_rate ?? null,
  }));
  const box = byId("an-sweep");
  const chart = el("div", "an-plot");
  chart.setAttribute("aria-label", "Hybrid search quality at each similarity cutoff");
  const note = el("p", "an-note", `Hybrid search. Current cutoff ${run.settings.cutoff}; best on this set ${run.bestCutoff}.`);
  box.replaceChildren(
    note,
    legend(series),
    chart,
    dataTable(["Cutoff", "Found", "Empty when nothing to find"], points.map((p) => [p.x.toFixed(3), formatPercent(p.recall), formatPercent(p.empty)])),
  );
  lines(chart, points, series, { marker: { x: run.settings.cutoff, label: "now" }, xFormat: (x) => x.toFixed(2) });
}

function renderHistory(evaluation) {
  const history = evaluation.history;
  if (history.length < 2) return unavailable("an-history", "Each evaluation run is added here, so changes can be compared over time.");
  const series = METHODS.map((method, index) => ({ ...method, color: color(index + 1) }));
  const points = history.map((run, index) => ({
    ...run,
    x: index,
    label: new Date(run.ranAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
  }));
  const box = byId("an-history");
  const chart = el("div", "an-plot");
  chart.setAttribute("aria-label", "Top-5 recall per evaluation run");
  box.replaceChildren(
    legend(series),
    chart,
    dataTable(["Run", "Words", "Meaning", "Hybrid", "Cutoff"], points.map((p) => [p.label, formatPercent(p.words), formatPercent(p.meaning), formatPercent(p.hybrid), p.cutoff])),
  );
  lines(chart, points, series, { xFormat: (x) => `#${x + 1}` });
}

function renderEvaluation(data) {
  const evaluation = data.evaluation;
  if (!evaluation) {
    const help = el("div", "an-empty");
    help.append(
      el("p", "", "No evaluation has run yet. It needs pgvector and a throwaway test database, then:"),
      el("code", "an-code", "TEST_DATABASE_URL=… venv/bin/python -m scripts.eval_search"),
    );
    fill("an-scores", help);
    unavailable("an-sweep", "Shows up after the first evaluation.");
    unavailable("an-history", "Shows up after the first evaluation.");
    return;
  }
  renderScores(evaluation);
  renderSweep(evaluation);
  renderHistory(evaluation);
}

function render(data) {
  renderKpis(data);
  renderDaily(data);
  renderModels(data);
  renderTools(data);
  renderTasks(data);
  renderCalls(data);
  renderAlarms(data);
  renderCoverage(data);
  renderEvaluation(data);
}

async function load(days) {
  for (const button of rangeButtons) button.setAttribute("aria-pressed", String(Number(button.dataset.days) === days));
  status.textContent = latest ? "" : "Loading…";
  try {
    latest = await requestJson("GET", `/api/analytics?days=${days}`);
    if (latest.theme) document.documentElement.dataset.theme = latest.theme;
    status.textContent = "";
    render(latest);
  } catch (error) {
    status.textContent = `Couldn't load analytics: ${error.message}`;
  }
}

for (const button of rangeButtons) {
  button.addEventListener("click", () => {
    const days = Number(button.dataset.days);
    saveDays(days);
    load(days);
  });
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => latest && render(latest), 150);
});

load(readDays());
