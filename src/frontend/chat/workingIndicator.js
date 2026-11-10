// A little honey bear that looks around while a reply is on its way, with how long it's been working.

const BEAR_SVG = `
<svg class="working-bear" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
  <g fill="#FFC72C">
    <circle cx="5.4" cy="5.6" r="3.4"/>
    <circle cx="18.6" cy="5.6" r="3.4"/>
    <circle cx="12" cy="13.2" r="9.6"/>
  </g>
  <g class="working-bear-eyes" fill="#1c1208">
    <ellipse cx="8.9" cy="11.6" rx="1.55" ry="2.25"/>
    <ellipse cx="15.1" cy="11.6" rx="1.55" ry="2.25"/>
    <ellipse cx="12" cy="16.6" rx="1.9" ry="1.3"/>
  </g>
</svg>`;

function describe(seconds) {
  return `Working for ${seconds}s`;
}

/** Shows the bear in a reply bubble until the reply's first words arrive. Returns a function that removes it. */
export function showWorking(bubble) {
  const startedAt = Date.now();
  const indicator = document.createElement("div");
  indicator.className = "working";
  indicator.setAttribute("role", "status");
  indicator.innerHTML = BEAR_SVG;
  const label = document.createElement("span");
  label.className = "working-label";
  label.textContent = describe(0);
  indicator.append(label);
  bubble.querySelector(".message-text").after(indicator);

  const timer = setInterval(() => {
    label.textContent = describe(Math.floor((Date.now() - startedAt) / 1000));
  }, 1000);

  return () => {
    clearInterval(timer);
    indicator.remove();
  };
}
