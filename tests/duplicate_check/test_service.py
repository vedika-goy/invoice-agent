from datetime import date
from decimal import Decimal

import pytest

from invoice_engine.decision.types import ReasonCode
from invoice_engine.duplicate_check.service import KnownInvoice, check_duplicates, normalize_invoice_number
from tests.factories import build_test_facts, load_test_vendor

GREENFIELD = load_test_vendor("V001")


def _known(invoice_number: str = "INV-00873", invoice_date: date = date(2026, 10, 20), total: str = "420.00",
           vendor_id: str = "V001") -> KnownInvoice:
    return KnownInvoice(vendor_id=vendor_id, invoice_number=invoice_number, invoice_date=invoice_date,
                        total=Decimal(total), status_label="paid on 2026-11-01")


def _codes(facts, known_invoices) -> list[ReasonCode]:
    return [finding.code for finding in check_duplicates(facts, GREENFIELD, known_invoices).findings]


@pytest.mark.parametrize("printed, expected", [("INV-00873", "873"), ("873", "873"), ("inv 873", "873"),
                                               ("GP-10452", "10452"), ("IB-24-0917", "240917")])
def test_invoice_numbers_compare_without_prefix_and_leading_zeros(printed, expected):
    assert normalize_invoice_number(printed) == expected


def test_same_number_written_differently_is_a_confirmed_duplicate():
    assert _codes(build_test_facts(invoice_number="873"), [_known()]) == [ReasonCode.DUPLICATE_CONFIRMED]


def test_same_number_with_a_different_prefix_is_only_a_possible_duplicate():
    assert _codes(build_test_facts(invoice_number="CR-873", total=Decimal("1.00")), [_known()]) == [ReasonCode.POSSIBLE_DUPLICATE]


def test_same_amount_within_30_days_is_a_possible_duplicate():
    assert _codes(build_test_facts(invoice_number="GP-1"), [_known(invoice_date=date(2026, 10, 10))]) == [ReasonCode.POSSIBLE_DUPLICATE]


def test_same_amount_outside_30_days_is_not_a_duplicate():
    assert _codes(build_test_facts(invoice_number="GP-1"), [_known(invoice_date=date(2026, 9, 1))]) == []


def test_other_vendors_invoices_are_never_duplicates():
    assert _codes(build_test_facts(invoice_number="873"), [_known(vendor_id="V003")]) == []


def test_skipped_when_the_vendor_is_unknown():
    assert check_duplicates(build_test_facts(), None, [_known()]).status == "skipped"
