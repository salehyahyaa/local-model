// Sends uncaught browser errors to the server so they end up in logs/app.log with everything else.
const MAX_REPORTS_PER_PAGE = 20;

let reportsSent = 0;

function report(message, stack) {
  if (reportsSent >= MAX_REPORTS_PER_PAGE) return;
  reportsSent += 1;
  fetch("/api/client-errors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: String(message), stack: String(stack ?? "") }),
  }).catch(() => {});
}

window.addEventListener("error", (event) => report(event.message, event.error?.stack));
window.addEventListener("unhandledrejection", (event) => report(event.reason?.message ?? event.reason, event.reason?.stack));
