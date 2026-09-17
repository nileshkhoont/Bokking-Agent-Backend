from datetime import datetime

from app.core.constants import AppointmentStatus
from app.models.appointment import Appointment
from app.schemas.common import PageParams

ACTIVE_STATUSES = [AppointmentStatus.booked, AppointmentStatus.rescheduled]


class AppointmentRepository:
    async def get_by_id(self, appointment_id: str) -> Appointment | None:
        appointment = await Appointment.get(appointment_id)
        if appointment is None or appointment.is_deleted:
            return None
        return appointment

    async def get_active_for_person(self, person_id: str) -> Appointment | None:
        """The person's current active (booked/rescheduled) appointment, if any — this is what
        inbound-call handling checks first (PDF §2.1: "Agent checks whether the person already
        has an appointment").
        """
        return (
            await Appointment.find(
                Appointment.person_id == person_id,
                Appointment.is_deleted == False,  # noqa: E712
                {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
            )
            .sort(-Appointment.appointment_datetime)
            .first_or_none()
        )

    async def exists_active_at(
        self, appointment_datetime: datetime, exclude_appointment_id: str | None = None
    ) -> bool:
        query: dict = {
            "appointment_datetime": appointment_datetime,
            "status": {"$in": [s.value for s in ACTIVE_STATUSES]},
            "is_deleted": False,
        }
        if exclude_appointment_id:
            query["_id"] = {"$ne": exclude_appointment_id}
        return await Appointment.find(query).count() > 0

    async def list_for_person(self, person_id: str) -> list[Appointment]:
        return (
            await Appointment.find(
                Appointment.person_id == person_id, Appointment.is_deleted == False  # noqa: E712
            )
            .sort(-Appointment.appointment_datetime)
            .to_list()
        )

    async def list_filtered(
        self, page: PageParams, status: AppointmentStatus | None = None
    ) -> tuple[list[Appointment], int]:
        conditions: list = [Appointment.is_deleted == False]  # noqa: E712
        if status:
            conditions.append(Appointment.status == status)

        query = Appointment.find(*conditions)
        total = await query.count()
        items = (
            await query.sort(-Appointment.appointment_datetime)
            .skip(page.skip)
            .limit(page.page_size)
            .to_list()
        )
        return items, total

    async def list_booked_for_scheduling(self, person_id: str | None = None) -> list[Appointment]:
        """Feeds the admin's schedule-call form's "pick from already booked appointments" list
        (PDF §3.1).
        """
        conditions: list = [
            Appointment.is_deleted == False,  # noqa: E712
            {"status": {"$in": [s.value for s in ACTIVE_STATUSES]}},
        ]
        if person_id:
            conditions.append(Appointment.person_id == person_id)
        return await Appointment.find(*conditions).sort(-Appointment.appointment_datetime).to_list()


appointment_repository = AppointmentRepository()
