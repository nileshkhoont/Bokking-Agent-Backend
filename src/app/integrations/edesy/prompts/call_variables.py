"""Per-call template variables sent alongside `context` on outbound `place_call` requests, for
Vani's dashboard-level `{{variable}}` prompt substitution (Agent editor -> Agent Instructions ->
Variables). Whether Vani's real API field for this is named `variables` is inferred from the
dashboard calling the feature "Variables" — not confirmed against real documentation, since none
is available (see integrations/edesy/schemas.py's EdesyPlaceCallRequest docstring). Verify with a
real outbound call once credits allow, by checking whether the agent actually speaks the caller's
name/appointment details instead of a literal "{{person_name}}".

The upcoming/expired decision is computed here, in UTC-aware Python, rather than left to the LLM —
language models have no reliable notion of "today's date" mid-conversation, so doing date math in
the prompt would be guesswork. This mirrors render_admin_instructions_context's approach of
pre-rendering call-specific text server-side instead of asking the agent to derive it.
"""

from datetime import UTC, datetime

from app.models.appointment import Appointment
from app.models.person import Person
from app.utils.datetime_utils import format_ist_human


def build_call_variables(person: Person, appointment: Appointment | None) -> dict[str, str]:
    if appointment is None:
        previous_status = "none"
        previous_datetime_ist = ""
    elif appointment.appointment_datetime > datetime.now(UTC):
        previous_status = "upcoming"
        previous_datetime_ist = format_ist_human(appointment.appointment_datetime)
    else:
        previous_status = "expired"
        previous_datetime_ist = format_ist_human(appointment.appointment_datetime)

    return {
        "person_name": person.full_name or "",
        "phone_number": person.phone_number,
        "previous_appointment_status": previous_status,
        "previous_appointment_datetime_ist": previous_datetime_ist,
    }


__all__ = ["build_call_variables"]
