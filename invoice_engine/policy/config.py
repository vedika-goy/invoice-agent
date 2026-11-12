"""AP policy values every decision is checked against. Each decision records POLICY_VERSION."""
from decimal import Decimal

# Change the version whenever a value below changes, so old decisions stay explainable.
POLICY_VERSION = "2026-11-v1"

PRICE_TOLERANCE_PERCENT = Decimal("2")
UNPLANNED_CHARGE_ALLOWANCE_USD = Decimal("75")
DUPLICATE_WINDOW_DAYS = 30
DUPLICATE_AMOUNT_TOLERANCE_USD = Decimal("1")
ROUNDING_TOLERANCE_PER_LINE_USD = Decimal("0.01")
APPROVAL_LIMIT_USD = Decimal("25000")

VENDOR_NAME_MIN_SIMILARITY_PERCENT = 85
LINE_DESCRIPTION_MIN_SIMILARITY_PERCENT = 80

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_PAGE_COUNT = 20
