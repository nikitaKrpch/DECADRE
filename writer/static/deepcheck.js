/* Assistant de rédaction — AI deep check (owner: P4)
 *
 * Decadre.deepcheck.run(text) → Promise<{ issues, unlocated }> from POST /rediger/api/deep-check.
 * Rejects on any error: main.js then shows the "IA indisponible" state and the rest keeps working.
 */
(function () {
  "use strict";
  const D = (window.Decadre = window.Decadre || {});

  async function run(text) {
    const res = await fetch("/rediger/api/deep-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return { issues: data.issues || [], unlocated: data.unlocated || [] };
  }

  D.deepcheck = { run };
})();
