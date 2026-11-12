# Invoice agent: from PDF to decision

AI reads the invoice; plain rules decide. Every decision is one of Approved, Needs review, On hold or
Rejected, with the reasons, the numbers behind them, who handles it and what would unblock it.

## Run it

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest                      # unit tests + every sample scenario
.venv/bin/python run_samples.py --offline       # the sample script, without calling the AI
.venv/bin/python run_samples.py                 # the same with Claude reading the PDFs (needs ANTHROPIC_API_KEY)
.venv/bin/python -m samples.build_sample_pdfs   # rebuild the sample PDFs (needs Google Chrome)
```

The app reads the API key from `.env` locally (or from Streamlit secrets when deployed):

```bash
set -a && source .env && set +a && .venv/bin/streamlit run app.py
```

Pages: **Process an invoice** (live step view and the decision), **Dashboard** (totals, open work by owner, every
run with its audit trail), **How it decides** (process map, rules, design decisions, policy, editable data,
self-test). The sidebar's **Reset demo data** clears runs and reloads the CSVs; saved readings are kept.

## Where to start reading

- `invoice_engine/pipeline/service.py`: the process end to end: intake, the 7 steps, recording approvals once.
- `ui/pages/`: the three pages; `ui/components/` holds the live step log and the decision card.
- `invoice_engine/decision/config.py`: the rules table: outcome, owner, wording and the reason for each rule.
- `invoice_engine/policy/config.py`: the tolerances and the policy version.
- `samples/expected.csv`: every scenario, in order, with the outcome it should get and why.

## Glossary

- **Fingerprint**: SHA-256 of the file's bytes. The same file always opens its earlier run.
- **Saved reading**: the AI's reading of a file, kept by fingerprint so re-runs never call the AI again.
- **Ledger**: invoices already paid or approved; duplicate checks and billed-to-date read it.
- **Billed-to-date**: quantity already billed per PO line, never counting the invoice being re-run.
