import re

E164_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")

# An Edesy "Custom Function" Request Body is a template like {"full_name": "{{full_name}}"}.
# When the LLM doesn't fill an optional parameter, Edesy does NOT drop that key — it posts the
# token through verbatim, so we receive the literal string "{{full_name}}" as if it were a value.
# (Proven 2026-09-22: appointment 6ab231d28faf632c4b6b04b4 ended up with notes "Cancelled:
# {{reason}}", written by our own cancel endpoint from a call whose transcript shows the model
# passed no `reason` at all; the same mechanism overwrote person 6ab0c5c603797df05d8d31bf's real
# name "Harsh" with the literal "{{full_name}}".) Anything still shaped like an unsubstituted
# template token is therefore an absent value, never real caller data.
UNRESOLVED_TEMPLATE_TOKEN = re.compile(r"^\s*\{\{[^{}]*\}\}\s*$")


def is_valid_e164(phone_number: str) -> bool:
    return bool(E164_PATTERN.match(phone_number))


def is_unresolved_placeholder(value: str | None) -> bool:
    return value is not None and bool(UNRESOLVED_TEMPLATE_TOKEN.match(value))


def strip_unresolved_placeholder(value: str | None) -> str | None:
    """Collapse an unsubstituted `{{token}}` down to None so it's treated as "not provided"."""
    return None if is_unresolved_placeholder(value) else value
