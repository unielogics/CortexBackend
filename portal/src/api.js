const P = import.meta.env.DEV ? "" : "";

export async function api(path, opts = {}) {
  const r = await fetch(`${P}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...opts.headers },
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
