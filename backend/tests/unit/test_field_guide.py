"""The capability rules the frontend evaluates come from here."""

from __future__ import annotations

from app.preprocessing.field_guide import (
    blocking_capability_gaps,
    compute_capabilities,
    missing_required_fields,
)


def capability(mapping: dict, key: str) -> dict:
    return next(c for c in compute_capabilities(mapping) if c["key"] == key)


def test_revenue_may_come_from_quantity_times_price():
    mapping = {"occurred_at": "Date", "quantity": "Qty", "unit_price": "Price"}
    assert capability(mapping, "sales_analytics")["enabled"] is True


def test_missing_revenue_path_explains_both_options():
    mapping = {"occurred_at": "Date", "quantity": "Qty"}
    result = capability(mapping, "sales_analytics")
    assert result["enabled"] is False
    assert result["missing"] == ["revenue or quantity + unit_price"]


def test_segmentation_needs_customer_invoice_and_date():
    mapping = {"occurred_at": "Date", "revenue": "Sales", "invoice_id": "Invoice"}
    assert capability(mapping, "segmentation")["missing"] == ["customer_id"]


def test_required_field_and_blocking_gap_detection():
    assert missing_required_fields({"revenue": "Sales"}) == ["occurred_at"]
    assert blocking_capability_gaps({"occurred_at": "Date", "revenue": "Sales"}) == []
