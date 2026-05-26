readme_content = """# pivony-advisor

An advanced, cloud-agnostic Customer Support & Advisor system utilizing a **RAG (Retrieval-Augmented Generation)** architecture. This project leverages **LangGraph** for agentic state management, **Google Vertex AI** for enterprise-grade embeddings and LLM capabilities, and an open-source **Qdrant** vector database hosted on Google Cloud Platform (GCP) to prevent vendor lock-in.

---

## 🏗️ Architecture Overview

The system operates through an event-driven and agentic workflow:
1. **Data Ingestion:** Document assets (PDF, TXT, DOCX) are securely stored in a **Google Cloud Storage (GCS) Bucket**.
2. **Vectorization:** Documents are processed, chunked, and transformed into high-dimensional vectors via **Vertex AI (`text-embedding-004`)**.
3. **Vector Storage:** Embeddings are indexed into a self-hosted **Qdrant** instance running on a GCP Compute Engine VM via Docker.
4. **Agentic Orchestration:** **LangGraph** manages the stateful, iterative reasoning loops, evaluating context relevance before passing data to the LLM.
5. **Generation:** **Gemini 1.5 Flash/Pro** synthesizes accurate, context-backed responses for the end user.

---

## 📂 Repository Structure

```text
pivony-advisor/
├── .gitignore
├── README.md
├── requirements.txt
├── config/
│   └── google_creds.json      # Local GCP key (ignored by Git for security)
├── docker/
│   └── qdrant-setup.sh        # Backup of shell commands used to set up Qdrant on the server
└── src/
    ├── data/
    │   └── ingest.py          # Reads from GCS, vectorizes via Vertex AI, and loads into Qdrant
    ├── agents/
    │   └── advisor_graph.py   # Core logic: LangGraph agent state/workflows and Gemini LLM calls
    └── main.py                # App entry point (e.g., FastAPI backend or Streamlit UI)
