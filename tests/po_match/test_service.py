from decimal import Decimal

from invoice_engine.decision.types import Outcome, ReasonCode
from invoice_engine.ledger.schemas import BilledToDate
from invoice_engine.po_match.service import match_purchase_order
from invoice_engine.reading.schemas import DocumentType
from tests.factories import build_test_facts, build_test_line, load_test_po_lines, load_test_vendors

PO_LINES = load_test_po_lines()
VENDORS_BY_ID = {vendor.vendor_id: vendor for vendor in load_test_vendors()}
GREENFIELD = VENDORS_BY_ID["V001"]


def _match(facts, vendor=GREENFIELD, billed=None, po_number_override=None):
    return match_purchase_order(facts, vendor, PO_LINES, VENDORS_BY_ID, billed or {}, po_number_override)


def _codes(facts, **kwargs) -> list[ReasonCode]:
    return sorted(finding.code for finding in _match(facts, **kwargs).step.findings)


def _billed(quantity: str) -> dict[tuple[str, int], BilledToDate]:
    return {("PO-2041", 1): BilledToDate(quantity=Decimal(quantity), amount=Decimal(quantity) * Decimal("4.20"))}


def test_clean_match_records_billable_lines():
    result = _match(build_test_facts())
    assert result.step.findings == []
    assert [(line.po_number, line.po_line, line.quantity) for line in result.billable_lines] == [("PO-2041", 1, Decimal(100))]


def test_price_more_than_2_percent_above_po_goes_to_the_requester():
    finding = _match(build_test_facts(lines=[build_test_line(unit_price="4.35")])).step.findings[0]
    assert (finding.code, finding.owner_name, finding.measured) == (ReasonCode.PRICE_ABOVE_PO, "Marco Diaz (Produce buyer)", "+3.6%")


def test_price_within_2_percent_passes():
    assert _codes(build_test_facts(lines=[build_test_line(unit_price="4.28")])) == []


def test_small_unplanned_charge_is_a_note_and_a_large_one_needs_review():
    assert _codes(build_test_facts(shipping=Decimal("40.00"))) == [ReasonCode.UNPLANNED_CHARGE_ALLOWED]
    fuel_line = build_test_line(line_number=2, description="Fuel surcharge", item_code=None, quantity="1", unit_price="120.00")
    assert _codes(build_test_facts(lines=[build_test_line(), fuel_line])) == [ReasonCode.UNPLANNED_CHARGE_OVER_ALLOWANCE]


def test_quantity_not_yet_received_is_held_for_receiving():
    finding = _match(build_test_facts(), billed=_billed("600")).step.findings[0]
    assert (finding.code, finding.outcome, finding.details["not_received"]) == (
        ReasonCode.QUANTITY_NOT_RECEIVED, Outcome.ON_HOLD, "100 bags")


def test_billing_past_the_ordered_quantity_is_over_billing_not_a_receiving_problem():
    assert _codes(build_test_facts(), billed=_billed("1000")) == [ReasonCode.PO_OVERBILLED]


def test_invalid_pos_go_to_procurement():
    assert _codes(build_test_facts(po_number="PO-9999")) == [ReasonCode.PO_NOT_FOUND]
    assert _codes(build_test_facts(po_number="PO-2050")) == [ReasonCode.PO_OTHER_VENDOR]
    assert _codes(build_test_facts(po_number="PO-1962")) == [ReasonCode.PO_CLOSED]


def test_po_number_matches_however_it_is_written():
    assert _codes(build_test_facts(po_number="P.O. #2041")) == []


def test_currency_different_from_the_po_needs_review():
    assert _codes(build_test_facts(currency_code="EUR")) == [ReasonCode.CURRENCY_MISMATCH]


def test_one_fitting_po_is_suggested_and_never_used_automatically():
    result = _match(build_test_facts(po_number=None))
    finding = result.step.findings[0]
    assert (finding.code, finding.details["po_number"]) == (ReasonCode.NO_PO_LIKELY_PO_FOUND, "PO-2041")
    assert result.billable_lines == []


def test_two_equally_fitting_pos_suggest_neither():
    platters = build_test_facts(vendor_name="Maple Street Bakery", po_number=None, total=Decimal("760.00"),
                                lines=[build_test_line(description="Assorted pastry platters", item_code=None,
                                                       quantity="20", unit_price="38.00")])
    assert _codes(platters, vendor=VENDORS_BY_ID["V005"]) == [ReasonCode.NO_PO_SEVERAL_POS_FIT]


def test_no_fitting_po_says_so():
    odd_item = build_test_facts(po_number=None, lines=[build_test_line(description="Dragon fruit", item_code=None)])
    assert _codes(odd_item) == [ReasonCode.NO_PO_NO_PO_FITS]


def test_reviewer_chosen_po_is_checked_like_a_printed_one():
    assert _codes(build_test_facts(po_number=None), po_number_override="PO-2041") == []


def test_credit_notes_are_not_matched_to_a_po():
    assert _match(build_test_facts(document_type=DocumentType.CREDIT_NOTE)).step.status == "skipped"
