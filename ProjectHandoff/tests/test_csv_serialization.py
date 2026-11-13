from __future__ import annotations

import pytest

from app.services.csvstore import (
    SCHEMAS,
    ConflictError,
    ValidationError,
    new_id,
    now_iso,
    parse_csv,
    serialize_rows,
)


def test_round_trip_preserves_special_characters():
    rows = [
        {
            "user_id": new_id(),
            "name": 'Olive "The Boss" Owner',
            "email": "a,b@test.dev",
            "role": "owner",
            "team_id": "team,1",
            "joined_at": now_iso(),
            "status": "active",
        },
        {
            "user_id": new_id(),
            "name": "Multi\nline\nname",
            "email": "quote's@x.dev",
            "role": "member",
            "team_id": "",
            "joined_at": now_iso(),
            "status": "active",
        },
    ]
    content = serialize_rows("users", rows)
    parsed = parse_csv("users", content)
    assert parsed == rows


def test_serialization_always_writes_canonical_header():
    content = serialize_rows("tasks", [])
    assert content.splitlines()[0] == ",".join(SCHEMAS["tasks"])


def test_commas_and_quotes_are_escaped_not_structural():
    import csv
    import io

    rows = [{"comment_id": "c1", "task_id": "t", "user_id": "u", "comment": 'a,b,"c"\nnew', "created_at": ""}]
    content = serialize_rows("comments", rows)
    records = list(csv.reader(io.StringIO(content, newline="")))
    assert len(records) == 2  # embedded newline stays inside one CSV record
    assert parse_csv("comments", content)[0]["comment"] == 'a,b,"c"\nnew'


def test_header_mismatch_raises_validation_error():
    with pytest.raises(ValidationError):
        parse_csv("users", "wrong,header\n1,2\n")


def test_blank_lines_are_skipped():
    content = serialize_rows("teams", []) + "\n\n"
    assert parse_csv("teams", content) == []


def test_extra_columns_rejected():
    with pytest.raises(ValidationError):
        parse_csv("teams", ",".join(SCHEMAS["teams"]) + ",extra\nt1,x,y,z,a,b,c,d\n")


def test_duplicate_ids_rejected_by_store_validation():
    from app.services.csvstore import _validate_ids

    with pytest.raises(ConflictError):
        _validate_ids("teams", [{"team_id": "t1"}, {"team_id": "t1"}])


def test_missing_id_rejected():
    from app.services.csvstore import _validate_ids

    with pytest.raises(ValidationError):
        _validate_ids("teams", [{"team_id": ""}])
