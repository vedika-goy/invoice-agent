"""File locations used by the engine, the app and the sample scripts."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATABASE_PATH = PROJECT_ROOT / "data" / "runtime" / "invoice_agent.sqlite"
SEED_DATA_FOLDER = PROJECT_ROOT / "data" / "seed"
SAMPLES_FOLDER = PROJECT_ROOT / "samples"
SAMPLE_INVOICES_FOLDER = SAMPLES_FOLDER / "invoices"
SAMPLE_SPECS_PATH = SAMPLES_FOLDER / "invoice_specs.json"
EXPECTED_RESULTS_PATH = SAMPLES_FOLDER / "expected.csv"
DIAGRAMS_FOLDER = PROJECT_ROOT / "assets" / "diagrams"
