from beanie import PydanticObjectId

from app.models.person import Person
from app.schemas.common import PageParams
from app.utils.validators import strip_unresolved_placeholder


class PersonRepository:
    async def get_by_id(self, person_id: str) -> Person | None:
        if not PydanticObjectId.is_valid(person_id):
            return None
        person = await Person.get(person_id)
        if person is None or person.is_deleted:
            return None
        return person

    async def get_many_by_ids(self, person_ids: set[str]) -> dict[str, Person]:
        """Batch lookup for list endpoints (calls/appointments/call-schedules) that need to show
        the person's name/phone next to each row without an N+1 query per row. Silently skips any
        id that isn't a well-formed ObjectId — a bad id on one row (e.g. a corrupt legacy record)
        must not take down the whole list.
        """
        object_ids = [PydanticObjectId(pid) for pid in person_ids if PydanticObjectId.is_valid(pid)]
        if not object_ids:
            return {}
        persons = await Person.find({"_id": {"$in": object_ids}}).to_list()
        return {str(p.id): p for p in persons}

    async def get_by_phone(self, phone_number: str) -> Person | None:
        return await Person.find_one(
            Person.phone_number == phone_number, Person.is_deleted == False  # noqa: E712
        )

    async def get_or_create_by_phone(self, phone_number: str, full_name: str | None = None) -> Person:
        """Used both by the inbound call.started webhook handler (we don't know the caller's
        name yet, so a placeholder is used until the agent's identify_person tool call updates
        it) and by that identify_person tool itself.
        """
        # A name is only ever *replaced* by another real name. Anything still shaped like an
        # unsubstituted `{{token}}` is treated as "no name given" (see utils/validators.py):
        # on 2026-09-22 this overwrote a real caller's name with the literal "{{full_name}}",
        # and because agent-tool writes don't go through the admin PATCH endpoint there was no
        # audit-log entry to trace it by.
        full_name = strip_unresolved_placeholder(full_name)

        existing = await self.get_by_phone(phone_number)
        if existing:
            if full_name and existing.full_name != full_name:
                existing.full_name = full_name
                await existing.save()
            return existing

        person = Person(full_name=full_name or phone_number, phone_number=phone_number)
        await person.insert()
        return person

    async def search(self, query: str | None, page: PageParams) -> tuple[list[Person], int]:
        filter_query = Person.find(Person.is_deleted == False)  # noqa: E712
        if query:
            filter_query = Person.find(
                Person.is_deleted == False,  # noqa: E712
                {"$or": [{"$text": {"$search": query}}, {"phone_number": {"$regex": query}}]},
            )

        total = await filter_query.count()
        items = (
            await filter_query.sort(-Person.created_at)
            .skip(page.skip)
            .limit(page.page_size)
            .to_list()
        )
        return items, total


person_repository = PersonRepository()
