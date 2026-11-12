"""Make plain text safe to show through Streamlit's Markdown renderer."""

# Streamlit renders $...$ as LaTeX and ~~...~~ as strikethrough, which would garble "$4.20 vs PO $4.20".
_MARKDOWN_ESCAPES = str.maketrans({"$": r"\$", "~": r"\~", "*": r"\*", "_": r"\_", "`": r"\`"})


def escape_markdown(text: str) -> str:
    return text.translate(_MARKDOWN_ESCAPES)
