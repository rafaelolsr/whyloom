from pathlib import Path

from whyloom.records import discover_records

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_parse_records_is_deterministic():
    first, first_diagnostics = discover_records(FIXTURE)
    second, second_diagnostics = discover_records(FIXTURE)
    assert not first_diagnostics
    assert not second_diagnostics
    assert [record.model_dump() for record in first] == [record.model_dump() for record in second]
    assert {record.id for record in first} == {"DEC-0001", "CON-0001"}

