from datetime import datetime

from beanie import PydanticObjectId

from app.core.constants import CallOutcome, CallStatus, CallType
from app.models.call import Call
from app.schemas.common import PageParams


class CallRepository:
    async def get_by_id(self, call_id: str) -> Call | None:
        if not PydanticObjectId.is_valid(call_id):
            return None
        call = await Call.get(call_id)
        if call is None or call.is_deleted:
            return None
        return call

    async def get_by_edesy_call_id(self, edesy_call_id: str) -> Call | None:
        return await Call.find_one(Call.edesy_call_id == edesy_call_id)

    async def list_filtered(
        self,
        page: PageParams,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        call_type: CallType | None = None,
        call_status: CallStatus | None = None,
        outcome: CallOutcome | None = None,
        person_id: str | None = None,
        person_ids: list[str] | None = None,
    ) -> tuple[list[Call], int]:
        conditions: list = [Call.is_deleted == False]  # noqa: E712
        if call_type:
            conditions.append(Call.call_type == call_type)
        if call_status:
            conditions.append(Call.call_status == call_status)
        if outcome:
            conditions.append(Call.outcome == outcome)
        if person_id:
            conditions.append(Call.person_id == person_id)
        if person_ids is not None:
            conditions.append({"person_id": {"$in": person_ids}})
        if date_from or date_to:
            range_query: dict = {}
            if date_from:
                range_query["$gte"] = date_from
            if date_to:
                range_query["$lte"] = date_to
            conditions.append({"start_time": range_query})

        query = Call.find(*conditions)
        total = await query.count()
        items = (
            await query.sort(-Call.start_time).skip(page.skip).limit(page.page_size).to_list()
        )
        return items, total

    async def list_for_person(self, person_id: str) -> list[Call]:
        return (
            await Call.find(Call.person_id == person_id, Call.is_deleted == False)  # noqa: E712
            .sort(-Call.start_time)
            .to_list()
        )

    async def count_by(self, **conditions) -> int:
        return await Call.find(Call.is_deleted == False, conditions).count()  # noqa: E712


call_repository = CallRepository()
