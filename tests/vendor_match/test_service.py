from invoice_engine.decision.types import Outcome, ReasonCode
from invoice_engine.vendor_match.service import VendorMatchMethod, check_vendor, find_vendor
from tests.factories import build_test_facts, load_test_vendors

VENDORS = load_test_vendors()


def _finding_codes(facts) -> set[ReasonCode]:
    return {finding.code for finding in check_vendor(facts, find_vendor(facts, VENDORS)).findings}


def test_tax_id_wins_even_when_the_printed_name_differs():
    match = find_vendor(build_test_facts(vendor_name="GPC Farms"), VENDORS)
    assert (match.vendor.vendor_id, match.method) == ("V001", VendorMatchMethod.TAX_ID)


def test_name_matches_exactly_when_only_the_legal_form_differs():
    match = find_vendor(build_test_facts(vendor_tax_id=None, vendor_name="Greenfield Produce Company"), VENDORS)
    assert (match.vendor.vendor_id, match.method) == ("V001", VendorMatchMethod.EXACT_NAME)


def test_lookalike_name_without_tax_id_needs_vendor_master_review():
    facts = build_test_facts(vendor_tax_id=None, vendor_name="Greenfeild Produce Co.")
    assert _finding_codes(facts) == {ReasonCode.VENDOR_SIMILAR_NAME_ONLY}


def test_unknown_vendor_needs_review():
    facts = build_test_facts(vendor_tax_id="11-1111111", vendor_name="Totally New Supplier")
    assert _finding_codes(facts) == {ReasonCode.VENDOR_NOT_FOUND}


def test_blocked_vendor_is_rejected():
    facts = build_test_facts(vendor_tax_id="62-7713054", vendor_name="Quickserve Vending", bank_account_last4="2287")
    step = check_vendor(facts, find_vendor(facts, VENDORS))
    assert [(finding.code, finding.outcome) for finding in step.findings] == [(ReasonCode.VENDOR_BLOCKED, Outcome.REJECTED)]


def test_changed_bank_account_is_held_for_treasury_with_the_phone_on_file():
    step = check_vendor(build_test_facts(bank_account_last4="9907"), find_vendor(build_test_facts(), VENDORS))
    finding = step.findings[0]
    assert (finding.code, finding.outcome) == (ReasonCode.BANK_ACCOUNT_CHANGED, Outcome.ON_HOLD)
    assert "(831) 555-0142" in finding.unblock_action


def test_no_bank_details_on_the_invoice_pays_the_account_on_file():
    assert _finding_codes(build_test_facts(bank_account_last4=None)) == set()
