const P = import.meta.env.DEV ? "" : "";

function formatApiError(status, text) {
  const t = (text || "").trim();
  if (!t) return `HTTP ${status}`;
  try {
    const j = JSON.parse(t);
    if (j.detail != null) return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    if (j.message != null) return String(j.message);
  } catch {
    /* plain text */
  }
  return t.length > 500 ? `${t.slice(0, 500)}…` : t;
}

export async function api(path, opts = {}) {
  const r = await fetch(`${P}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...opts.headers },
  });
  const text = await r.text();
  if (!r.ok) throw new Error(formatApiError(r.status, text));
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
