
from app.models.person import Person
from app.schemas.common import PageParams


class PersonRepository:
    async def get_by_id(self, person_id: str) -> Person | None:
        person = await Person.get(person_id)
        if person is None or person.is_deleted:
            return None
        return person

    async def get_by_phone(self, phone_number: str) -> Person | None:
        return await Person.find_one(
            Person.phone_number == phone_number, Person.is_deleted == False  # noqa: E712
        )

    async def get_or_create_by_phone(self, phone_number: str, full_name: str | None = None) -> Person:
        """Used both by the inbound call.started webhook handler (we don't know the caller's
        name yet, so a placeholder is used until the agent's identify_person tool call updates
        it) and by that identify_person tool itself.
        """
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
