# Trek Assistant

An AI booking assistant for trekking agencies in Nepal. It answers traveller questions from the agency's own information and captures booking leads.

**Stack:** Python · FastAPI · Claude API · (coming) RAG with Chroma/Supabase · WhatsApp Cloud API

## Status
- [x] Day 1 — FastAPI server + Claude chat endpoint
- [ ] Week 2 — RAG over agency itineraries and FAQs
- [ ] Week 3 — Lead capture (Supabase), human handoff, web chat widget
- [ ] Week 4 — Deploy, WhatsApp, demo video

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then paste your API key into .env
uvicorn main:app --reload
```
Open http://127.0.0.1:8000/docs and try `POST /chat` with:
```json
{ "message": "Which trek is best for beginners in March?" }
```
