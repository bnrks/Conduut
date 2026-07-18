"""PII-safe request logging for the n8n client."""

from src.n8n_client import _request_payload_summary


def test_request_payload_summary_keeps_shape_but_not_workflow_values():
    payload = {
        "name": "Customer reminder",
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {
                    "sendTo": "person@example.com",
                    "subject": "Private subject",
                    "message": "Private body",
                },
            }
        ],
        "connections": {"Send Email": {"main": [[]]}},
    }

    summary = _request_payload_summary(payload)

    assert summary == {
        "keys": ["connections", "name", "nodes"],
        "node_count": 1,
        "node_types": ["n8n-nodes-base.gmail"],
        "connection_source_count": 1,
    }
    assert "person@example.com" not in repr(summary)
    assert "Private" not in repr(summary)


def test_request_payload_summary_does_not_log_runtime_input_values():
    summary = _request_payload_summary(
        {"input": {"email": "person@example.com"}, "rows": [{"input": {"secret": "x"}}]}
    )

    assert summary == {"keys": ["input", "rows"], "row_count": 1}
