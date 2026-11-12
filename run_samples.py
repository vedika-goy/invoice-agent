"""Runs every step of samples/expected.csv and prints expected vs actual. Exits with 1 on any mismatch.

    set -a && source .env && set +a             # loads ANTHROPIC_API_KEY from .env into this shell
    .venv/bin/python run_samples.py             # Claude reads the PDFs; readings are saved, so later runs are instant
    .venv/bin/python run_samples.py --offline   # uses each sample's known reading; no AI call, no key needed

The online run also compares Claude's reading of each sample with the known one.
"""
import argparse
import os
import sys

from invoice_engine.config import DATABASE_PATH, SAMPLE_INVOICES_FOLDER
from invoice_engine.database.connection import IN_MEMORY_DATABASE, open_database_connection
from invoice_engine.decision.types import OUTCOME_LABELS
from invoice_engine.intake.service import build_file_fingerprint
from invoice_engine.reading.client import InvoiceReadingClient
from invoice_engine.reading.repository import SavedReadingRepository
from invoice_engine.reading.service import InvoiceReadingService, find_reading_differences
from invoice_engine.self_test.service import SelfTestStepResult, load_self_test_steps, run_self_test
from invoice_engine.utils.sample_invoices import build_expected_reading, load_sample_specs
from samples.ground_truth import GroundTruthReadingClient

API_KEY_VARIABLE = "ANTHROPIC_API_KEY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--offline", action="store_true", help="use the known readings instead of calling Claude")
    is_offline = parser.parse_args().offline
    if not is_offline and not os.environ.get(API_KEY_VARIABLE):
        print(f"{API_KEY_VARIABLE} isn't set. Paste your key into .env, then run:\n"
              "  set -a && source .env && set +a && .venv/bin/python run_samples.py\n"
              "Or run without the AI: .venv/bin/python run_samples.py --offline", file=sys.stderr)
        return 2
    # Offline readings go to a throwaway database, so the app never reuses them in place of Claude's.
    readings_connection = open_database_connection(IN_MEMORY_DATABASE if is_offline else DATABASE_PATH)
    reader = GroundTruthReadingClient() if is_offline else InvoiceReadingClient()
    saved_reading_repository = SavedReadingRepository(readings_connection)
    results = run_self_test(InvoiceReadingService(reader, saved_reading_repository), load_self_test_steps())
    _print_results(results)
    if not is_offline:
        _print_reading_accuracy(saved_reading_repository)
    return 0 if all(result.is_match for result in results) else 1


def _print_results(results: list[SelfTestStepResult]) -> None:
    for result in results:
        step = result.step
        expected = OUTCOME_LABELS[step.expected_outcome] if step.expected_outcome else "(data change)"
        actual = OUTCOME_LABELS[result.actual_outcome] if result.actual_outcome else ("(done)" if result.is_match else "-")
        print(f"{'OK  ' if result.is_match else 'FAIL'} {step.step_number:>2}  {step.action.value:<16} {step.target:<36} "
              f"expected {expected:<13} actual {actual}")
        if not result.is_match:
            print(f"        expected reasons {[code.value for code in step.expected_reason_codes]}")
            print(f"        actual reasons   {[code.value for code in result.actual_reason_codes]} {result.problem or ''}")
    print(f"\n{sum(result.is_match for result in results)} of {len(results)} steps match expected.csv")


def _print_reading_accuracy(saved_reading_repository: SavedReadingRepository) -> None:
    print("\nClaude's readings compared with the known values:")
    specs = load_sample_specs()
    for document in specs["documents"]:
        pdf_bytes = (SAMPLE_INVOICES_FOLDER / document["file_name"]).read_bytes()
        saved = saved_reading_repository.get_saved_reading(build_file_fingerprint(pdf_bytes))
        if saved is None:
            print(f"  -    {document['file_name']}: no saved reading (the read failed)")
            continue
        differences = find_reading_differences(build_expected_reading(document, specs["vendors"]), saved.reading)
        print(f"  {'OK  ' if not differences else 'DIFF'} {document['file_name']}" + (f": {', '.join(differences)}" if differences else ""))


if __name__ == "__main__":
    sys.exit(main())
