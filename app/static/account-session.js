"use strict";
// Full navigation discards the prior user's in-memory project/document state.
// Never persist the session cookie, password or account content in Web Storage.
async function accountSession() {
  const response = await fetch("/api/auth/me", {cache: "no-store"});
  if (response.status === 404) return; // Existing single-workspace deployments.
  if (response.status === 401) { location.replace("/login"); return; }
  if (!response.ok) return;
  const account = await response.json();
  document.querySelector("#account-name").textContent = account.username;
  document.querySelector("#account-controls").hidden = false;
  document.querySelector("#account-logout").onclick = async () => {
    try {
      await api("/api/auth/logout", {method: "POST"});
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith("insightforge-beta-event:")) sessionStorage.removeItem(key);
      }
      document.body.replaceChildren();
      location.replace("/login");
    } catch (error) { showApiError(error); }
  };
  document.querySelector("#account-new-project").onclick = async () => {
    const title = prompt("项目名称");
    if (!title?.trim()) return;
    try {
      const project = await api("/api/projects", {method: "POST", body: JSON.stringify({title: title.trim(), summary: title.trim()})});
      await loadProjects();
      await loadProject(project.id);
    } catch (error) { showApiError(error); }
  };
}
window.addEventListener("pageshow", (event) => { if (event.persisted) location.reload(); });
accountSession().catch(() => { /* API errors remain visible in the normal loading path. */ });
