"""LLM narrative from audit artifact - NVIDIA NIM OpenAI-compatible API."""

import json

from unie_cortex.config import settings
from unie_cortex.integrations.nim_chat import nim_post_chat_completions


async def generate_narrative_from_artifact(
    artifact: dict,
    *,
    store=None,
    capability: str = "audit_narrative",
    tenant_id: str | None = None,
    engagement_id: str | None = None,
    run_id: str | None = None,
) -> tuple[str | None, str]:
    """
    Returns (narrative_text, source).
    source: nim | skipped_no_key | error_*
    """
    system = (
        "You are a warehouse operations auditor. Summarize ONLY the JSON facts provided. "
        "Do not invent dollar amounts or counts. Cite figures exactly as given. "
        "Highlight discrepancies, bottlenecks, and money opportunities for a 3PL prospect."
    )
    user = json.dumps(artifact, default=str)[:120000]
    out = await nim_post_chat_completions(
        settings,
        capability=capability,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=2048,
        store=store,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        run_id=run_id,
    )
    if out.source == "skipped_no_key":
        return None, "skipped_no_key"
    if out.source == "nim" and out.content:
        return out.content, "nim"
    if out.source.startswith("error_http_"):
        return None, out.source
    if out.source == "error_empty":
        return None, "error_empty"
    return None, out.source


def fallback_narrative(artifact: dict) -> str:
    """Template when NIM unavailable."""
    lines = [
        "## Audit summary (deterministic)",
        f"- Label cost module: {artifact.get('label_cost', {}).get('status', 'n/a')}",
        f"- Throughput module: {artifact.get('throughput', {}).get('status', 'n/a')}",
        f"- Money opportunity (USD range): {artifact.get('money_opportunities_usd', {})}",
    ]
    for f in artifact.get("findings") or []:
        lines.append(f"- **{f.get('type')}**: {f.get('message', '')}")
    return "\n".join(lines)
