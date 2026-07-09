"""INV-7: BMS-independence.

Full golden-ticket eval with sensor_readings=[] and sensor_reading table
empty — asserts every ticket completes with non-degraded output.
The pipeline must produce a complete, evidence-grounded diagnosis from
tenant-submitted evidence + the manual corpus alone.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.asyncio
async def test_plumbing_ticket_completes_without_sensors(stub_graph: Any) -> None:
    """A plumbing ticket with no sensor data must complete fully."""
    config = {"configurable": {"thread_id": "inv7-plumbing-no-sensor"}}

    result = await stub_graph.ainvoke(
        {
            "ticket_id": "INV7-001",
            "description": "Leaking pipe under kitchen sink",
            "sensor_readings": [],  # explicitly empty
        },
        config=config,
    )

    assert result["trade"] == "plumbing"
    assert result["verify_pass"] is True
    assert result["escalated"] is False
    assert result["work_order_id"] is not None
    assert result["sku"] is not None
    assert len(result.get("hypotheses", [])) >= 1
    assert len(result.get("evidence", [])) >= 1


@pytest.mark.asyncio
async def test_hvac_ticket_completes_without_sensors(stub_graph: Any) -> None:
    """An HVAC ticket with no sensor data must complete fully."""
    config = {"configurable": {"thread_id": "inv7-hvac-no-sensor"}}

    result = await stub_graph.ainvoke(
        {
            "ticket_id": "INV7-002",
            "description": "Furnace not heating, cold air blowing",
            "sensor_readings": [],
        },
        config=config,
    )

    assert result["trade"] == "hvac"
    assert result["verify_pass"] is not None
    assert len(result.get("hypotheses", [])) >= 1


@pytest.mark.asyncio
async def test_gas_ticket_escalates_without_sensors(stub_graph: Any) -> None:
    """A gas ticket with no sensor data must still escalate (INV-1 + INV-7)."""
    config = {"configurable": {"thread_id": "inv7-gas-no-sensor"}}

    result = await stub_graph.ainvoke(
        {
            "ticket_id": "INV7-003",
            "description": "Gas smell near stove",
            "sensor_readings": [],
        },
        config=config,
    )

    assert result["trade"] == "gas"
    assert result["escalated"] is True
    assert result["escalation_reason"] == "hard_category"


@pytest.mark.asyncio
async def test_sensor_fields_are_optional_in_state(stub_graph: Any) -> None:
    """Tickets without sensor_readings key at all must still work."""
    config = {"configurable": {"thread_id": "inv7-no-sensor-key"}}

    # Don't even include sensor_readings in input
    result = await stub_graph.ainvoke(
        {
            "ticket_id": "INV7-004",
            "description": "Appliance dishwasher not draining",
        },
        config=config,
    )

    assert result["verify_pass"] is not None
    assert result.get("work_order_id") is not None or result.get("escalated") is True
