from invoice_engine.decision.config import BUYER_COMPANY_NAME

READING_MODEL_ID = "claude-opus-5-5"
READING_EFFORT = "medium"
READING_MAX_OUTPUT_TOKENS = 16000
READING_TIMEOUT_S = 120.0
# The SDK retries connection errors, timeouts, 429 and 5xx this many times, with backoff.
READING_MAX_RETRIES = 1
# A declined request is re-run on Anthropic's recommended fallback model inside the same call.
SERVER_SIDE_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# One retry when Claude's answer doesn't fit InvoiceReading; after that the invoice goes to review.
MAX_READING_ATTEMPTS = 2

READING_INSTRUCTIONS = f"""You read accounts-payable documents sent to {BUYER_COMPANY_NAME}.
Report what the document says, never what it should say: don't calculate, correct or infer values that \
aren't printed, and use null when something isn't on the document. For every value, copy the text you \
read it from into its quote field exactly as printed. Code checks your reading against the PDF and its \
arithmetic, so an honest null is better than a guess."""

READING_REQUEST = "Read this document."
