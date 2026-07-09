"""INV-3: No media blobs in Postgres — schema scan asserts no bytea/blob columns.

Media bytes go to R2/S3 via presigned direct upload. Postgres stores
object keys (pointers) only.
"""

from __future__ import annotations

import sqlalchemy as sa

from hero.storage.models import Base


def test_no_bytea_columns_in_schema() -> None:
    """No table in our schema should have BYTEA/BLOB/LargeBinary columns."""
    violations: list[str] = []

    for table_name, table in Base.metadata.tables.items():
        for column in table.columns:
            col_type = type(column.type)
            if col_type in (sa.LargeBinary, sa.BLOB):
                violations.append(f"{table_name}.{column.name} is {col_type.__name__}")
            # Also check the string representation for bytea
            type_str = str(column.type).upper()
            if "BYTEA" in type_str or "BLOB" in type_str:
                violations.append(f"{table_name}.{column.name} has type {column.type}")

    assert violations == [], (
        f"INV-3 VIOLATION: found blob/bytea columns in Postgres schema: {violations}"
    )


def test_media_table_has_no_content_column() -> None:
    """The media table should only have pointer columns, never content."""
    media_table = Base.metadata.tables["media"]
    column_names = {c.name for c in media_table.columns}

    # These column names would suggest storing actual content
    forbidden_names = {"content", "data", "blob", "binary", "bytes", "payload", "body"}
    violations = column_names & forbidden_names

    assert violations == set(), (
        f"INV-3 VIOLATION: media table has content-like columns: {violations}"
    )


def test_media_table_has_object_key() -> None:
    """The media table must have an object_key column for R2 pointers."""
    media_table = Base.metadata.tables["media"]
    column_names = {c.name for c in media_table.columns}
    assert "object_key" in column_names
