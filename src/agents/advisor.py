"""Pivony Advisor CLI — multi-tenant RAG (platform + sector)."""

from __future__ import annotations

import os
import sys
import textwrap

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.dirname(_BASE)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from core.config import CREDS_PATH, DEFAULT_SECTOR
from core.rag import build_embeddings, build_llm, create_qdrant_client, invoke_advisor

if not os.path.exists(CREDS_PATH):
    print(f"ERROR: google_creds.json not found at {CREDS_PATH}")
    sys.exit(1)

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDS_PATH


def print_answer(question: str, answer: str, sector: str) -> None:
    width = 72
    print("\n" + "=" * width)
    print(f" PIVONY ADVISOR ({sector})")
    print("=" * width)
    print("\nQuestion:")
    print(textwrap.fill(question, width=width))
    print("\n" + "-" * width)
    print("Answer:")
    print(textwrap.fill(answer, width=width))
    print("\n" + "=" * width + "\n")


def main() -> None:
    sector = os.environ.get("PIVONY_SECTOR", DEFAULT_SECTOR)
    print(f"Pivony Advisor — sector={sector}")

    try:
        embeddings = build_embeddings()
        client = create_qdrant_client()
        llm = build_llm()
    except Exception as exc:
        print(f"ERROR: Failed to initialize: {exc}")
        sys.exit(1)

    test_question = os.environ.get(
        "TEST_QUESTION",
        "Pivony platformu hangi teknolojileri kullanıyor ve ne işe yarar?",
    )
    print("Invoking RAG chain...")
    answer = invoke_advisor(
        test_question,
        sector_slug=sector,
        embeddings=embeddings,
        client=client,
        llm=llm,
    )
    print_answer(test_question, answer, sector)


if __name__ == "__main__":
    main()
