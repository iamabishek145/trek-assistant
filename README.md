# Trek Assistant

An AI booking assistant for trekking agencies in Nepal. It answers traveller questions from the agency's own information (treks, prices, permits, policies) and collects booking details.

**Stack:** Python · FastAPI · Claude API (Haiku, tool use) · ChromaDB (RAG) · SQLite · Telegram/Gmail alerts · vanilla JS widget (Shadow DOM) · *coming:* Supabase, WhatsApp Cloud API

**Try it:** run the server and open http://127.0.0.1:8000/demo, a sample agency site with the chat widget.

## How it works
0. **Widget:** an agency adds one line to their site: `<script src="https://SERVER/static/widget.js" data-name="Agency" data-color="#0f3d3e" defer></script>`. The widget lives in a Shadow DOM (the agency's CSS can't break it), escapes all bot output before rendering, keeps the chat across page reloads, and goes full-screen on phones. Pages can open it with a question: `TrekAssistant.open("Tell me about EBC")`.
1. The client sends a message plus the conversation history to `POST /chat`.
2. **Retrieval:** the agency info (`data/agency.md`) is split into sections.
   - **Pinned sections** (inclusions, booking rules, discounts) are sent with every question. Semantic search kept missing them because a question like "total for 6 people?" doesn't *sound* like a discount policy.
   - **Searchable sections** (treks, FAQs) live in ChromaDB. Search runs twice, on the new message alone and on recent context, so a fresh question isn't drowned out by the booking chat.
3. Claude answers using only that context, with a system prompt that blocks guessing, shows price math, applies group discounts, and collects booking details without re-asking.
4. **Lead capture (tool use):** once the traveller has given name, trek, dates, group size and contact, Claude calls a `save_lead` tool. The server validates the input with Pydantic (bad input goes back to Claude as an error so it asks the traveller), saves it to SQLite, and returns a booking reference. Same contact + trek + date updates the existing lead instead of duplicating it.
5. **Human handoff (tool use):** when a traveller asks for a person, has a complaint or an emergency, or wants something not in the agency info, Claude calls `request_handoff`. The server saves the reason, priority (normal/urgent), contact and the last messages, then alerts the team via Telegram and/or Gmail. Normal handoffs ask for a contact first; urgent ones (stranded, injured) fire immediately and give the agency's WhatsApp number. A failed alert never breaks the chat.
6. **Stateless server:** past tool calls aren't in the text history, so the client sends back the `lead_id` / `handoff_id` and the server tells Claude what already happened. The last round of the tool loop uses `tool_choice: none` so Claude always ends with a text reply.

## Status
- [x] Day 1: FastAPI server + Claude chat endpoint
- [x] Day 2: Answers grounded in an agency data file
- [x] Day 3: RAG with ChromaDB
- [x] Day 4: Conversation history, tighter prompt, pinned rule sections, CLI test client
- [x] Day 5: Lead capture with Claude tool use, SQLite, `GET /leads`
- [x] Day 6: Human handoff with urgency levels, Telegram/Gmail alerts, `GET /handoffs`
- [x] Day 7: Embeddable web chat widget + sample agency page (`/demo`)
- [x] Day 8: Security hardening: admin key, rate limits, input caps, fixed trek names
- [ ] Next: deploy (Render + Supabase), WhatsApp, demo video

## Security
- **Admin endpoints** (`/leads`, `/handoffs`, `/search`) need an `X-Admin-Key` header matching `ADMIN_KEY`; compared with `secrets.compare_digest` (constant time). If `ADMIN_KEY` isn't set they refuse everyone. In `/docs`, use the Authorize button.
- **Cost protection on `/chat`:** 20 messages per visitor per 10 min, 500 per day server-wide, 1,000-character messages, last 20 messages of history sent to Claude. Limits are in-memory (single process).
- **Tool input is validated**, not trusted: Pydantic checks every field, and `trek` must be one of the names in `data/agency.md`.
- **Widget output is escaped** before rendering, so a model reply can't inject HTML/JS into the agency's site.
- **CORS:** set `ALLOWED_ORIGINS` to the agency's domain in production.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then paste your API key into .env
uvicorn main:app --reload
```

Optional handoff alerts: fill in the Telegram or Gmail settings in `.env` (see `.env.example`), then run `python notify.py` to test. Without them, alerts print in the server terminal.

Open **http://127.0.0.1:8000/demo** to use the chat widget on a sample agency page.

Or chat from the terminal (in a second terminal, keeps history for you):
```bash
python chat_cli.py
```

Or open http://127.0.0.1:8000/docs and try `POST /chat`:
```json
{ "message": "Which trek is best for beginners in March?", "history": [] }
```

## Testing
`python chat_cli.py --test` runs 13 scripted conversations (price math across turns, solo vs group rate, inclusions, no guessing on availability, group discount, medical question, off-topic, step-by-step booking, one-message booking, incomplete booking that must not save, asking for a human, emergency on a trek, custom request). Run a subset with `--test 11 12` and prints the expected answer next to each reply.

Debug retrieval with `GET /search?q=your question`. See captured leads at `GET /leads` and handoffs at `GET /handoffs` (all three need the admin key). Every `save_lead` call is logged in the server terminal.

> The agency in `data/agency.md` is fictional; all prices are made up for testing.
