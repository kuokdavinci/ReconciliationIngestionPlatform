export function getActorName(state) {
  return (state.actor || "Administrator").trim() || "Administrator";
}

export function withActorHeaders(state, headers = {}) {
  return {
    ...headers,
    "X-Actor": getActorName(state),
  };
}

export function fetchJson(path) {
  return fetch(path, { headers: { Accept: "application/json" } }).then(r => {
    if (!r.ok) return r.text().then(t => { throw new Error("HTTP " + r.status + ": " + t.slice(0, 180)); });
    return r.json();
  });
}

export function executeCopilotAction(state, actionKey) {
  return fetch(`/api/v1/copilot/actions/${encodeURIComponent(actionKey)}`, {
    method: "POST",
    headers: withActorHeaders(state, { "Content-Type": "application/json", Accept: "application/json" }),
    body: JSON.stringify({
      partner: state.partner,
      date: state.date,
      reviewedBy: getActorName(state),
    }),
  }).then(r => r.json().then(body => {
    if (!r.ok) throw new Error(body.detail || "Copilot action failed");
    return body;
  }));
}
