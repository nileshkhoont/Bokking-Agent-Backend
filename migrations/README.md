# migrations/

MongoDB + Beanie don't require schema migrations the way a SQL ORM does — new optional fields on a
`Document` just start appearing on newly-written documents, and `db/init_db.py` (re)applies index
and `$jsonSchema` validator changes idempotently on every startup.

This folder is reserved for one-off **data** migration scripts (backfilling a new field on
existing documents, renaming a field across a collection, etc.) if one is ever needed — none exist
yet because the schema hasn't changed since collections were first populated.
