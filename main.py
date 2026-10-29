"""
Trek Assistant — FastAPI server.

POST /chat   answers a traveller's message using the agency info (via RAG)
             and the conversation history the client sends along. When the
             traveller has given all booking details, Claude calls the
             save_lead tool and the lead is stored in SQLite.
GET  /leads  lists captured leads (for the agency).
GET  /search debug: shows which agency sections retrieval picks.

Run:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/docs, or chat with: python chat_cli.py
"""

import os
from typing import Literal

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from leads import init_db, list_leads, save_lead
from rag import build_index, pinned_chunks, search

load_dotenv()  # reads ANTHROPIC_API_KEY from your .env file


client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-haiku-5-5"

SYSTEM_PROMPT = """You are the friendly booking assistant for Himalaya Trails Demo,
a trekking agency in Kathmandu, Nepal.

How to answer:
- Answer only from the agency information provided below. If something
  isn't covered there, say a team member will confirm it. Never guess.
- Never invent prices, dates, availability or policies.
- Keep answers short and clear (2-4 sentences), in plain friendly English.
- Prices are in USD. Use the group rate for 2+ people and the solo rate for 1.
  When you calculate a total, show the math (e.g. 3 x USD 450 = USD 1,350).
- Before giving a total, check the booking section for group discounts and
  apply any that fit (e.g. 7 x USD 720 = USD 5,040, minus 10% = USD 4,536).
- The 20% deposit is part of the total price, not an extra charge.
- Check the "What's included" section before saying something costs extra.
  Permits, guide, porter, teahouse meals and trailhead transport are included.

Booking:
- To book, you need 5 details: name, trek, travel dates, group size, and a
  contact (WhatsApp number or email).
- Before asking anything, re-read the whole conversation. Never ask again for
  a detail the traveller already gave, and never ask them to re-confirm it.
- Ask only for missing details, and never more than 2 per message, even if
  more are missing. Ask for the rest in your next message.
- As soon as you have all 5, call the save_lead tool. Never call it with a
  missing, guessed or placeholder value.
- After save_lead succeeds, summarise the details and the total price in one
  line, give the booking reference (e.g. #12), and say a team member will
  contact them to confirm availability and the deposit.
- Past tool calls are not shown in the conversation. If an earlier message of
  yours gives a booking reference, that save really happened: don't call
  save_lead again and don't apologise for it, unless the traveller changes
  one of the details.

Safety:
- For altitude sickness or medical questions, give the agency's guidance and
  recommend they consult a doctor before the trek.
- If asked about something unrelated to trekking with us, politely steer back."""

# The tool Claude can call. Claude never touches the database itself: it
# only asks us to run save_lead with these fields, and our code does the rest.
SAVE_LEAD_TOOL = {
    "name": "save_lead",
    "description": (
        "Save a traveller's booking request so the agency team can follow up. "
        "Call this only once the traveller has given ALL of: name, trek, "
        "travel start date, group size and a contact (WhatsApp or email)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Traveller's name"},
            "trek": {"type": "string", "description": "Full trek name, e.g. 'Langtang Valley Trek'"},
            "start_date": {"type": "string", "description": "Travel start date as the traveller gave it, e.g. '5 April'"},
            "group_size": {"type": "integer", "description": "Number of trekkers, including the traveller"},
            "contact": {"type": "string", "description": "WhatsApp number or email address"},
            "notes": {"type": "string", "description": "Optional: special requests, e.g. female guide"},
        },
        "required": ["name", "trek", "start_date", "group_size", "contact"],
    },
}

MAX_TOOL_ROUNDS = 3  # safety limit so a confused model can't loop forever

app = FastAPI(title="Trek Assistant")
init_db()                    # create leads.db + table if needed
CHUNK_COUNT = build_index()  # load trek + FAQ chunks into ChromaDB at startup
PINNED = pinned_chunks()     # rule sections, sent with every question


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[Message] = []
    lead_id: int | None = None  # the client sends this back once a lead is saved


class ChatResponse(BaseModel):
    reply: str
    lead_id: int | None = None  # set when this message created/updated a lead


class Lead(BaseModel):
    """Our own check on what Claude sends. We don't trust tool input blindly."""
    name: str = Field(min_length=1)
    trek: str = Field(min_length=1)
    start_date: str = Field(min_length=1)
    group_size: int = Field(ge=1, le=50)
    contact: str = Field(min_length=5)
    notes: str = ""


def run_save_lead(tool_input: dict) -> tuple[str, bool, int | None]:
    """Run the save_lead tool. Returns (message for Claude, is_error, lead_id)."""
    try:
        lead = Lead(**tool_input)
    except ValidationError as e:
        problems = ", ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
        # Sent back to Claude as an error, so it asks the traveller to fix it
        return f"Not saved. Fix these with the traveller first: {problems}", True, None
    lead_id = save_lead(**lead.model_dump())
    return f"Saved. Booking reference: #{lead_id}", False, lead_id


def retrieve(message: str, history: list[Message]) -> list[str]:
    """Search twice and merge: once with just the new message (so a fresh
    question like 'can I rent sleeping bags?' isn't drowned out by the booking
    chat), once with recent context (so 'how much for 3 of us?' still finds
    the trek being discussed)."""
    recent = " ".join([m.content for m in history[-4:]] + [message])
    found = search(message, k=3) + search(recent, k=3)
    return list(dict.fromkeys(found))  # drop duplicates, keep order


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")

    context = "\n\n---\n\n".join(PINNED + retrieve(req.message, req.history))
    system = SYSTEM_PROMPT + "\n\nUse ONLY this agency information:\n" + context
    if req.lead_id:
        # The server is stateless: this is how it knows a save already happened
        system += (f"\n\nThis traveller's booking is ALREADY SAVED as #{req.lead_id}. "
                   "Only call save_lead again if they change a detail.")

    messages = [m.model_dump() for m in req.history]
    messages.append({"role": "user", "content": req.message})
    lead_id = req.lead_id

    # The tool-use loop:
    # 1. Ask Claude. 2. If it wants a tool, run it and send back the result.
    # 3. Repeat until Claude answers in plain text. On the last round we
    #    forbid tools (tool_choice none) so Claude MUST reply in words.
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        last_round = round_number == MAX_TOOL_ROUNDS
        response = client.messages.create(
            model=MODEL,
            max_tokens=500,
            system=system,
            tools=[SAVE_LEAD_TOOL],
            tool_choice={"type": "none"} if last_round else {"type": "auto"},
            messages=messages,
        )
        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "save_lead":
                text, is_error, saved_id = run_save_lead(block.input)
                print(f"[tool] save_lead {block.input} -> {text}")  # server log
                lead_id = saved_id or lead_id
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": text,
                    "is_error": is_error,
                })
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    reply = "".join(b.text for b in response.content if b.type == "text").strip()
    if not reply:
        reply = "Sorry, something went wrong on our side. A team member will follow up."
    return ChatResponse(reply=reply, lead_id=lead_id)


@app.get("/leads")
def get_leads():
    # TODO before deploying: protect this with an admin key
    return {"leads": list_leads()}


@app.get("/search")
def search_chunks(q: str):
    return {"chunks_indexed": CHUNK_COUNT, "results": search(q)
}