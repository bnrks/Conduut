from src.agent.artifacts import (
    MAX_ARTIFACT_COLUMNS,
    MAX_ARTIFACT_ROWS,
    artifact_table_from_rows,
)


def test_artifact_table_truncates_large_rows_and_columns():
    rows = [
        {f"Column {column}": f"value-{row}-{column}" for column in range(20)} for row in range(20)
    ]

    table = artifact_table_from_rows(rows)

    assert table is not None
    assert len(table.columns) == MAX_ARTIFACT_COLUMNS
    assert len(table.rows) == MAX_ARTIFACT_ROWS
    assert table.totalRows == 20
    assert table.truncated is True
    assert isinstance(table.rows[0], dict)


def test_artifact_table_removes_secret_like_fields():
    table = artifact_table_from_rows(
        [
            {
                "email": "person@example.com",
                "access_token": "secret-token",
                "nested": {"refresh_token": "secret-refresh", "visible": "ok"},
            }
        ]
    )

    assert table is not None
    assert "access_token" not in table.columns
    assert table.rows[0]["email"] == "person@example.com"
    assert "secret-refresh" not in table.rows[0]["nested"]
    assert "visible" in table.rows[0]["nested"]
