# Trek Assistant

An AI booking assistant for trekking agencies in Nepal. It answers traveller questions from the agency's own information (treks, prices, permits, policies) and collects booking details.

**Stack:** Python · FastAPI · Claude API (Haiku) · ChromaDB (RAG) · *coming:* SQLite/Supabase leads, WhatsApp Cloud API

## How it works
1. The client sends a message plus the conversation history to `POST /chat`.
2. **Retrieval:** the agency info (`data/agency.md`) is split into sections.
   - **Pinned sections** (inclusions, booking rules, discounts) are sent with every question. Semantic search kept missing them because a question like "total for 6 people?" doesn't *sound* like a discount policy.
   - **Searchable sections** (treks, FAQs) live in ChromaDB; the 4 closest to the recent conversation are retrieved.
3. Claude answers using only that context, with a system prompt that blocks guessing, shows price math, applies group discounts, and collects booking details without re-asking.

## Status
- [x] Day 1: FastAPI server + Claude chat endpoint
- [x] Day 2: Answers grounded in an agency data file
- [x] Day 3: RAG with ChromaDB
- [x] Day 4: Conversation history, tighter prompt, pinned rule sections, CLI test client
- [ ] Day 5: Lead capture with Claude tool use (save bookings to a database)
- [ ] Next: human handoff, web chat widget, deploy, WhatsApp, demo video

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then paste your API key into .env
uvicorn main:app --reload
```

Chat from the terminal (in a second terminal, keeps history for you):
```bash
python chat_cli.py
```

Or open http://127.0.0.1:8000/docs and try `POST /chat`:
```json
{ "message": "Which trek is best for beginners in March?", "history": [] }
```

## Testing
`python chat_cli.py --test` runs 8 scripted conversations (price math across turns, solo vs group rate, inclusions, no guessing on availability, group discount, medical question, off-topic, full booking flow) and prints the expected answer next to each reply.

Debug retrieval with `GET /search?q=your question` to see which sections were retrieved.

> The agency in `data/agency.md` is fictional; all prices are made up for testing.
