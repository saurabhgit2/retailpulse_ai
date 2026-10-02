"""The canonical fields RetailPulse understands, and the rules for what each
analysis needs.

This module is the single source of truth. The API serves it at
GET /datasets/field-guide, and the frontend only *evaluates* the rules, so
adding a field or changing a requirement is a one-file change here.
"""

from __future__ import annotations

from typing import Any

# status: required   - processing cannot start without it
#         recommended - enables a major capability
#         optional    - nice to have
CANONICAL_FIELDS: list[dict[str, Any]] = [
    {
        "key": "occurred_at",
        "label": "Transaction date/time",
        "status": "required",
        "expected_type": "datetime",
        "description": "When the sale happened. Needed for every time-based analysis.",
        "synonyms": ["date", "orderdate", "invoicedate", "transactiondate", "salesdate",
                     "timestamp", "datetime"],
        "example": "2010-12-01 08:26:00",
    },
    {
        "key": "quantity",
        "label": "Quantity",
        "status": "recommended",
        "expected_type": "numeric",
        "description": "Units sold on the line. Needed for demand forecasting. "
                       "Negative values are treated as returns.",
        "synonyms": ["quantity", "qty", "units", "unitssold", "volume"],
        "example": "6",
    },
    {
        "key": "unit_price",
        "label": "Unit price",
        "status": "recommended",
        "expected_type": "numeric",
        "description": "Price per unit. With quantity, lets revenue be calculated when there "
                       "is no revenue column.",
        "synonyms": ["price", "unitprice", "sellingprice"],
        "example": "2.55",
    },
    {
        "key": "revenue",
        "label": "Revenue (line total)",
        "status": "recommended",
        "expected_type": "numeric",
        "description": "Sales value of the line. If missing, it is derived as "
                       "quantity x unit price.",
        "synonyms": ["sales", "revenue", "amount", "total", "linetotal", "salesamount"],
        "example": "15.30",
    },
    {
        "key": "product_code",
        "label": "Product code / SKU",
        "status": "recommended",
        "expected_type": "any",
        "description": "Identifies the product. Needed for product analytics, SKU forecasts "
                       "and basket analysis.",
        "synonyms": ["stockcode", "sku", "productid", "itemcode", "productcode"],
        "example": "85123A",
    },
    {
        "key": "product_name",
        "label": "Product name",
        "status": "optional",
        "expected_type": "any",
        "description": "Readable product label shown in charts and tables.",
        "synonyms": ["description", "productname", "item", "itemname"],
        "example": "WHITE HANGING HEART T-LIGHT HOLDER",
    },
    {
        "key": "invoice_id",
        "label": "Invoice / order ID",
        "status": "recommended",
        "expected_type": "any",
        "description": "Groups lines into orders. Needed for order counts, average order value "
                       "and baskets.",
        "synonyms": ["invoice", "invoiceno", "orderid", "transactionid", "receipt"],
        "example": "536365",
    },
    {
        "key": "customer_id",
        "label": "Customer ID",
        "status": "recommended",
        "expected_type": "any",
        "description": "Pseudonymous customer identifier. Needed for RFM segmentation.",
        "synonyms": ["customerid", "customer", "clientid", "memberid"],
        "example": "17850",
    },
    {
        "key": "category",
        "label": "Category",
        "status": "optional",
        "expected_type": "any",
        "description": "Product category, for category-level analysis and entropy.",
        "synonyms": ["category", "productcategory", "department"],
        "example": "Home decor",
    },
    {
        "key": "region",
        "label": "Region / country / store",
        "status": "optional",
        "expected_type": "any",
        "description": "Where the sale happened. Enables region breakdowns and filters.",
        "synonyms": ["country", "region", "store", "storeid", "location", "state"],
        "example": "United Kingdom",
    },
    {
        "key": "discount",
        "label": "Discount / promotion",
        "status": "optional",
        "expected_type": "numeric",
        "description": "Discount amount or promotion flag, for promotion analysis.",
        "synonyms": ["discount", "promo", "promotion", "markdown"],
        "example": "0.10",
    },
]

# A capability is enabled when every field in requires_all is mapped AND at
# least one group in requires_one_of is fully mapped.
CAPABILITIES: list[dict[str, Any]] = [
    {
        "key": "sales_analytics",
        "label": "Sales KPIs and trends",
        "required": True,  # processing is refused unless this is possible
        "requires_all": ["occurred_at"],
        "requires_one_of": [["revenue"], ["quantity", "unit_price"]],
    },
    {"key": "demand_forecasting", "label": "Demand forecasting",
     "requires_all": ["occurred_at", "quantity"]},
    {"key": "product_analytics", "label": "Product analytics", "requires_all": ["product_code"]},
    {"key": "order_metrics", "label": "Orders and average order value",
     "requires_all": ["invoice_id"]},
    {
        "key": "segmentation",
        "label": "Customer segmentation (RFM)",
        "requires_all": ["customer_id", "invoice_id", "occurred_at"],
        "requires_one_of": [["revenue"], ["quantity", "unit_price"]],
    },
    {"key": "association_rules", "label": "Basket analysis (association rules)",
     "requires_all": ["invoice_id", "product_code"]},
    {"key": "category_analysis", "label": "Category analysis", "requires_all": ["category"]},
    {"key": "region_analysis", "label": "Region analysis", "requires_all": ["region"]},
    {"key": "promotion_analysis", "label": "Promotion analysis", "requires_all": ["discount"]},
]

FIELD_KEYS = [field["key"] for field in CANONICAL_FIELDS]
FIELDS_BY_KEY = {field["key"]: field for field in CANONICAL_FIELDS}

# Stock codes that are fees or adjustments rather than products. Online Retail II
# uses these for postage, bank charges, Amazon fees, manual adjustments and
# bad-debt write-offs. Configurable per dataset, not hard-coded into the pipeline.
NON_PRODUCT_CODES = [
    "POST", "DOT", "M", "D", "C2", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "B", "S", "PADS", "ADJUST",
]

DEFAULT_CLEANING_OPTIONS: dict[str, Any] = {
    "date_format": None,               # 'iso' | 'dmy' | 'mdy'; confirmed by the user
    "drop_exact_duplicates": True,
    "exclude_non_product_codes": True,
    "non_product_codes": NON_PRODUCT_CODES,
    "outlier_method": "robust_z",
    "outlier_threshold": 5.0,
    "currency": "GBP",
}

TEMPLATE_CSV = (
    "invoice_id,occurred_at,product_code,product_name,quantity,unit_price,revenue,"
    "customer_id,category,region,discount\n"
    "EXAMPLE-1001,2024-03-04 09:15:00,SKU-001,EXAMPLE CERAMIC MUG,4,3.50,14.00,C-0001,"
    "Kitchen,North,0\n"
    "EXAMPLE-1001,2024-03-04 09:15:00,SKU-014,EXAMPLE LINEN TEA TOWEL,2,4.25,8.50,C-0001,"
    "Kitchen,North,0\n"
    "EXAMPLE-1002,2024-03-04 11:02:00,SKU-007,EXAMPLE SCENTED CANDLE,1,9.99,9.99,,"
    "Home decor,South,0.10\n"
)


def compute_capabilities(mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    """Which analyses this mapping supports, and what is missing for the rest."""
    results = []
    for capability in CAPABILITIES:
        missing = [f for f in capability.get("requires_all", []) if not mapping.get(f)]

        groups = capability.get("requires_one_of", [])
        if groups and not any(all(mapping.get(f) for f in group) for group in groups):
            missing.append(" or ".join(" + ".join(group) for group in groups))

        results.append(
            {
                "key": capability["key"],
                "label": capability["label"],
                "enabled": not missing,
                "missing": missing,
            }
        )
    return results


def missing_required_fields(mapping: dict[str, str | None]) -> list[str]:
    return [f["key"] for f in CANONICAL_FIELDS if f["status"] == "required" and not mapping.get(f["key"])]


def blocking_capability_gaps(mapping: dict[str, str | None]) -> list[str]:
    """Missing pieces of capabilities marked required (currently: sales analytics)."""
    required_keys = {c["key"] for c in CAPABILITIES if c.get("required")}
    gaps: list[str] = []
    for capability in compute_capabilities(mapping):
        if capability["key"] in required_keys and not capability["enabled"]:
            gaps.extend(capability["missing"])
    return gaps


def field_guide_document() -> dict[str, Any]:
    """The payload served by GET /datasets/field-guide."""
    return {"fields": CANONICAL_FIELDS, "capabilities": CAPABILITIES}
