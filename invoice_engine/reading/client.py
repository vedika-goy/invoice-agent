"""The only AI call in the process: Claude reads one PDF into an InvoiceReading."""
import base64
import logging

import anthropic
import pydantic

from invoice_engine.reading.config import (
    READING_EFFORT,
    READING_INSTRUCTIONS,
    READING_MAX_OUTPUT_TOKENS,
    READING_MAX_RETRIES,
    READING_MODEL_ID,
    READING_REQUEST,
    READING_TIMEOUT_S,
    SERVER_SIDE_FALLBACK_BETA,
)
from invoice_engine.reading.schemas import InvoiceReading
from invoice_engine.reading.types import ReadingResponseInvalidError, ReadingUnavailableError

logger = logging.getLogger(__name__)


class InvoiceReadingClient:
    def __init__(self, api_key: str | None = None) -> None:
        # api_key None: the SDK reads ANTHROPIC_API_KEY (or an `ant auth login` profile) from the environment.
        self._anthropic_client = anthropic.Anthropic(
            api_key=api_key, timeout=READING_TIMEOUT_S, max_retries=READING_MAX_RETRIES
        )

    @property
    def model_id(self) -> str:
        return READING_MODEL_ID

    def read_invoice(self, pdf_bytes: bytes) -> InvoiceReading:
        document_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
            },
        }
        try:
            response = self._anthropic_client.beta.messages.parse(
                model=READING_MODEL_ID,
                max_tokens=READING_MAX_OUTPUT_TOKENS,
                betas=[SERVER_SIDE_FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": READING_EFFORT},
                output_format=InvoiceReading,
                system=READING_INSTRUCTIONS,
                messages=[{"role": "user", "content": [document_block, {"type": "text", "text": READING_REQUEST}]}],
            )
        except pydantic.ValidationError as error:
            logger.warning("Claude's reading didn't fit the schema: %d errors", error.error_count())
            raise ReadingResponseInvalidError("the answer didn't fit the expected fields") from error
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as error:
            logger.warning("Claude unreachable after retries: %s", type(error).__name__)
            raise ReadingUnavailableError("the AI service didn't respond") from error
        except anthropic.APIStatusError as error:
            logger.error("Claude rejected the reading request: status=%s request_id=%s",
                         error.status_code, getattr(error, "request_id", None))
            raise ReadingUnavailableError(f"the AI service rejected the request (HTTP {error.status_code})") from error
        except anthropic.AnthropicError as error:
            logger.error("Claude client error: %s", type(error).__name__)
            raise ReadingUnavailableError("the AI service isn't configured (check the API key)") from error
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            logger.warning("Claude stopped early: stop_reason=%s request_id=%s",
                           response.stop_reason, getattr(response, "_request_id", None))
            raise ReadingResponseInvalidError(f"the AI stopped early ({response.stop_reason})")
        return response.parsed_output
