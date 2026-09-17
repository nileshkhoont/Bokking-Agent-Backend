from collections.abc import Sequence
from typing import TypeVar

from app.schemas.common import Page, PageParams

T = TypeVar("T")


def build_page(items: Sequence[T], total: int, params: PageParams) -> Page[T]:
    return Page(items=list(items), total=total, page=params.page, page_size=params.page_size)
