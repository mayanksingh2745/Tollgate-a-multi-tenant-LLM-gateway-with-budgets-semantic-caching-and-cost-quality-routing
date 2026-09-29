import json
import uuid

import pytest
from pydantic import ValidationError
from tollgate_core.usage import DeadLetterPayload, UsageEventPayload
from tollgate_core.usage_metrics import UsageMetrics


def test_usage_event_payload_valid():
    event_id = uuid.uuid4()
    t_id = uuid.uuid4()
    p_id = uuid.uuid4()
    key_id = uuid.uuid4()

    payload = UsageEventPayload(
        event_id=event_id,
        event_version=1,
        request_id="req_test_123",
        reservation_id="res_test_456",
        tenant_id=t_id,
        project_id=p_id,
        api_key_id=key_id,
        provider="openai",
        model="gpt-4o",
        stream=False,
        status="success",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost=2500,
        actual_cost=2000,
        latency_ms=125.5,
        attempt_count=1,
        fallback_used=False,
    )

    assert payload.event_id == event_id
    assert payload.event_version == 1
    assert payload.actual_cost == 2000
    assert payload.estimated_cost == 2500
    assert payload.status == "success"

    # Test serialization to stream entry
    stream_entry = payload.to_stream_entry()
    assert "data" in stream_entry
    raw_data = json.loads(stream_entry["data"])
    assert raw_data["request_id"] == "req_test_123"
    assert raw_data["actual_cost"] == 2000

    # Test deserialization from stream entry
    reconstructed = UsageEventPayload.from_stream_entry(stream_entry)
    assert reconstructed.event_id == event_id
    assert reconstructed.request_id == "req_test_123"
    assert reconstructed.total_tokens == 150


def test_usage_event_unsupported_version():
    with pytest.raises(ValidationError) as exc:
        UsageEventPayload(
            event_version=2,  # Unsupported version
            request_id="req_v2",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            provider="openai",
            model="gpt-4o",
            status="success",
        )
    assert "Unsupported event version: 2" in str(exc.value)


def test_usage_event_validation_failures():
    # Missing required tenant_id
    with pytest.raises(ValidationError):
        UsageEventPayload(
            request_id="req_1",
            provider="openai",
            model="gpt-4o",
            status="success",
        )

    # Negative tokens
    with pytest.raises(ValidationError):
        UsageEventPayload(
            request_id="req_1",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            provider="openai",
            model="gpt-4o",
            status="success",
            input_tokens=-10,
        )

    # Invalid status
    with pytest.raises(ValidationError):
        UsageEventPayload(
            request_id="req_1",
            tenant_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            provider="openai",
            model="gpt-4o",
            status="invalid_status",  # type: ignore
        )


def test_dead_letter_payload():
    dl = DeadLetterPayload(
        original_event_id=str(uuid.uuid4()),
        failure_reason="Malformed JSON token stream",
        failure_type="validation_error",
        original_payload='{"broken": true}',
    )
    entry = dl.to_stream_entry()
    assert "data" in entry
    parsed = json.loads(entry["data"])
    assert parsed["failure_type"] == "validation_error"
    assert parsed["failure_reason"] == "Malformed JSON token stream"


def test_usage_metrics_tracker():
    tracker = UsageMetrics()
    assert tracker.get_count("usage_events_published_total") == 0
    tracker.increment("usage_events_published_total", 5)
    assert tracker.get_count("usage_events_published_total") == 5

    tracker.record_latency(120.5)
    tracker.record_latency(80.2)
    tracker.record_batch_size(25)

    all_metrics = tracker.get_all()
    assert all_metrics["usage_events_published_total"] == 5

    tracker.reset()
    assert tracker.get_count("usage_events_published_total") == 0
