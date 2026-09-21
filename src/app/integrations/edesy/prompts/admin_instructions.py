"""Per-call rendering helpers for the Edesy agent's conversation context.

The agent itself (prompt, greeting, language) is created and edited directly in the Edesy
dashboard, not from this codebase — see workers/tasks/outbound_call_task.py for how
`render_admin_instructions_context` below feeds into the per-call `context` sent to Edesy's
`place_call`.
"""


def render_admin_instructions_context(admin_instructions: str | None) -> str:
    """Formats optional admin instructions into the per-call `context` payload sent to
    integrations.edesy.client.place_call — not part of the static system prompt itself, since
    these vary call-to-call (folder-structure doc: "admin instructions" reach the conversation via
    call context, not by editing the prompt).
    """
    if not admin_instructions:
        return ""
    return f"Admin instructions for this call: {admin_instructions.strip()}"
