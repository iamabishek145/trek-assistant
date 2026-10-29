"""
Trek Assistant — FastAPI server.

POST /chat      answers a traveller's message using the agency info (via RAG)
                and the conversation history the client sends along.
                Claude has two tools: save_lead (booking details -> database)
                and request_handoff (alert the team to take over).
GET  /leads     lists captured leads     (agency only: X-Admin-Key header)
GET  /handoffs  lists handoff requests   (agency only: X-Admin-Key header)
GET  /demo      sample agency website with the chat widget (static/).
GET  /search     debug: which agency sections retrieval picks (admin only)
GET  /debug/ip  shows which IP the rate limiter sees for you

Run:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/demo, or chat with: python chat_cli.py
"""

import os
import secrets
import time
from pathlib import Path
from typing import Literal

import anthropic
from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator

from leads import init_db, list_handoffs, list_leads, save_handoff, save_lead
from notify import send_alert
import ratelimit
from rag import build_index, load_chunks, pinned_chunks, search, trek_names, use_rag

load_dotenv()  # reads ANTHROPIC_API_KEY from your .env file


# timeout: give up on a stuck call after 30 s; the SDK retries twice on errors
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=30, max_retries=2)
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
- Ask for all missing details together in one short message.
- As soon as you have all 5, call the save_lead tool. Never call it with a
  missing, guessed or placeholder value.
- After save_lead succeeds, summarise the details and the total price in one
  line, give the booking reference (e.g. #12), and say a team member will
  contact them to confirm availability and the deposit.
- Past tool calls are not shown in the conversation. If an earlier message of
  yours gives a booking reference, that save really happened: don't call
  save_lead again and don't apologise for it, unless the traveller changes
  one of the details.

Handing over to a human:
- Call request_handoff when the traveller asks for a real person, has a
  problem or complaint, has an emergency during a trek, or wants something
  that isn't in the agency information (e.g. a custom itinerary or a trek
  we don't list).
- Don't hand off for normal questions about prices, dates or availability:
  collect the booking details instead.
- Before calling it, make sure you have a contact (WhatsApp or email) so the
  team can reach them. If it's missing, ask for it once.
- Emergencies (stranded, injured, unsafe, guide missing): call it straight
  away with priority "urgent", even without a contact, and give the agency
  WhatsApp number from the agency information.
- After it succeeds, say a team member will contact them soon and give the
  handoff reference (e.g. H-3).
- If an earlier message of yours already gives a handoff reference, don't
  call request_handoff again.

Safety:
- For altitude sickness or medical questions, give the agency's guidance and
  recommend they consult a doctor before the trek.
- If asked about something unrelated to trekking with us, politely steer back."""

TREK_NAMES = trek_names()  # e.g. ["Poon Hill Trek", ...] from data/agency.md

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
            "trek": {
                "type": "string",
                "enum": TREK_NAMES,  # Claude must pick one of these exact names
                "description": "The trek, exactly as named in the agency information",
            },
            "start_date": {"type": "string", "description": "Travel start date as the traveller gave it, e.g. '5 April'"},
            "group_size": {"type": "integer", "description": "Number of trekkers, including the traveller"},
            "contact": {"type": "string", "description": "WhatsApp number or email address"},
            "notes": {"type": "string", "description": "Optional: special requests, e.g. female guide"},
        },
        "required": ["name", "trek", "start_date", "group_size", "contact"],
    },
}

REQUEST_HANDOFF_TOOL = {
    "name": "request_handoff",
    "description": (
        "Alert the agency team so a human takes over this conversation. Use "
        "when the traveller asks for a person, has a problem, complaint or "
        "emergency, or wants something not covered in the agency information."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "One sentence the team can act on"},
            "priority": {
                "type": "string",
                "enum": ["normal", "urgent"],
                "description": "urgent ONLY for safety problems or a traveller stuck on a trek",
            },
            "name": {"type": "string", "description": "Traveller's name, if known"},
            "contact": {"type": "string", "description": "WhatsApp number or email, if known"},
        },
        "required": ["reason", "priority"],
    },
}

TOOLS = [SAVE_LEAD_TOOL, REQUEST_HANDOFF_TOOL]
MAX_TOOL_ROUNDS = 3  # safety limit so a confused model can't loop forever
MAX_HISTORY = 20     # only send the last 20 messages to Claude (cost control)

app = FastAPI(title="Trek Assistant")

# The widget can be embedded on an agency's own website (a different domain),
# so the browser needs CORS permission to call /chat. "*" is fine for local
# development; before deploying, set ALLOWED_ORIGINS to the agency's domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.getenv("ALLOWED_ORIGINS") or "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
init_db()  # create the tables if needed (Supabase, or leads.db locally)

# Small agency file -> send all of it with every message (fast, nothing to
# miss). Big file -> RAG: pinned rules + search. See rag.py for the reasoning.
USE_RAG = use_rag()
if USE_RAG:
    CHUNK_COUNT = build_index()  # load trek + FAQ chunks into ChromaDB
    PINNED = pinned_chunks()     # rule sections, sent with every question
else:
    AGENCY_INFO = "\n\n---\n\n".join(load_chunks())
print(f"[startup] knowledge mode: {'RAG' if USE_RAG else 'full context'}")


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(max_length=1000)  # stops huge (expensive) messages
    history: list[Message] = []
    lead_id: int | None = None     # the client sends these back once saved,
    handoff_id: int | None = None  # because the server remembers nothing


class ChatResponse(BaseModel):
    reply: str
    lead_id: int | None = None     # set once a lead is saved
    handoff_id: int | None = None  # set once the team has been alerted


class Lead(BaseModel):
    """Our own check on what Claude sends. We don't trust tool input blindly."""
    name: str = Field(min_length=1)
    trek: str = Field(min_length=1)
    start_date: str = Field(min_length=1)
    group_size: int = Field(ge=1, le=50)
    contact: str = Field(min_length=5)
    notes: str = ""

    @field_validator("trek")
    @classmethod
    def known_trek(cls, value: str) -> str:
        if value not in TREK_NAMES:
            raise ValueError(f"must be one of {TREK_NAMES}")
        return value


class Handoff(BaseModel):
    reason: str = Field(min_length=5)
    priority: Literal["normal", "urgent"]
    name: str = ""
    contact: str = ""


def run_save_lead(tool_input: dict) -> tuple[str, bool, int | None]:
    """Run the save_lead tool. Returns (message for Claude, is_error, lead_id)."""
    try:
        lead = Lead(**tool_input)
    except ValidationError as e:
        problems = ", ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
        # Sent back to Claude as an error, so it asks the traveller to fix it
        return f"Not saved. Fix these with the traveller first: {problems}", True, None
    try:
        lead_id = save_lead(**lead.model_dump())
    except Exception as e:
        # Database down (e.g. Supabase paused)? Don't lose the customer:
        # send the booking straight to the team instead.
        print(f"[error] save_lead failed: {type(e).__name__}: {e}")
        details = "\n".join(f"{k}: {v}" for k, v in lead.model_dump().items() if v)
        if send_alert("⚠️ Booking NOT saved (database error)", details):
            return ("The database had a problem, but the booking details were sent "
                    "to the team directly. There's no reference number; tell the "
                    "traveller a team member will contact them."), False, None
        return ("Saving failed. Apologise and ask the traveller to message the "
                "agency on WhatsApp directly."), True, None
    return f"Saved. Booking reference: #{lead_id}", False, lead_id


def run_request_handoff(tool_input: dict, transcript: str) -> tuple[str, bool, int | None]:
    """Save the handoff and alert the team. Returns (message for Claude, is_error, id)."""
    try:
        handoff = Handoff(**tool_input)
    except ValidationError as e:
        problems = ", ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
        return f"Not saved: {problems}", True, None
    try:
        handoff_id = save_handoff(**handoff.model_dump(), transcript=transcript)
    except Exception as e:
        # The alert matters more than the database row: still send it
        print(f"[error] save_handoff failed: {type(e).__name__}: {e}")
        handoff_id = None
    ref = f"H-{handoff_id}" if handoff_id else "H-? (not saved)"

    icon = "🚨 URGENT" if handoff.priority == "urgent" else "🙋"
    who = " ".join(filter(None, [handoff.name, f"({handoff.contact})" if handoff.contact else ""]))
    alerted = send_alert(
        subject=f"{icon} Handoff {ref}: {handoff.reason}",
        text=(f"Traveller: {who or 'unknown, no contact given'}\n"
              f"Reason: {handoff.reason}\n\nLast messages:\n{transcript}"),
    )
    if not handoff_id and not alerted:
        return ("Alerting the team failed. Apologise and give the agency WhatsApp "
                "number so they can contact the team directly."), True, None
    if not handoff_id:
        return "Team alerted (no reference number available).", False, None
    return f"Team alerted. Handoff reference: H-{handoff_id}", False, handoff_id


def make_transcript(history: list[Message], message: str) -> str:
    """The last few messages, so the human sees the context."""
    lines = [f"{'Traveller' if m.role == 'user' else 'Bot'}: {m.content[:300]}"
             for m in history[-6:]]
    lines.append(f"Traveller: {message}")
    return "\n".join(lines)


def retrieve(message: str, history: list[Message]) -> list[str]:
    """Search twice and merge: once with just the new message (so a fresh
    question like 'can I rent sleeping bags?' isn't drowned out by the booking
    chat), once with recent context (so 'how much for 3 of us?' still finds
    the trek being discussed)."""
    recent = " ".join([m.content for m in history[-4:]] + [message])
    found = search(message, k=3) + search(recent, k=3)
    return list(dict.fromkeys(found))  # drop duplicates, keep order


# ---------- security helpers (Day 8)

admin_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def require_admin(key: str | None = Security(admin_key_header)):
    """Only the agency (who knows ADMIN_KEY) may read leads and handoffs."""
    expected = os.getenv("ADMIN_KEY")
    if not expected:
        raise HTTPException(503, "Set ADMIN_KEY in .env to use this endpoint")
    # compare_digest takes the same time whether 1 or 30 characters match,
    # so an attacker can't guess the key character by character
    if not key or not secrets.compare_digest(key, expected):
        raise HTTPException(401, "Missing or wrong X-Admin-Key")


def client_ip(request: Request) -> str:
    """The visitor's IP, for rate limiting.

    On Render the direct connection is Render's proxy, so the real IP comes
    from headers. Render's edge (Cloudflare) sets True-Client-IP /
    CF-Connecting-IP itself and overwrites any value a visitor sends, so
    those can't be faked. X-Forwarded-For CAN be faked (visitors can add
    their own entries), so it's only a fallback.
    """
    for header in ("true-client-ip", "cf-connecting-ip"):
        if request.headers.get(header):
            return request.headers[header].strip()
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else request.client.host


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")
    blocked = ratelimit.check(client_ip(request))
    if blocked:
        raise HTTPException(status_code=429, detail=blocked)
    req.history = req.history[-MAX_HISTORY:]
    started = time.perf_counter()

    if USE_RAG:
        context = "\n\n---\n\n".join(PINNED + retrieve(req.message, req.history))
    else:
        context = AGENCY_INFO
    retrieval_s = time.perf_counter() - started

    # The system prompt is sent as blocks. The big first block (instructions +
    # agency info) is the same for every message in full-context mode, so we
    # mark it for prompt caching: Anthropic can reuse it, which is faster and
    # cheaper. The small per-conversation notes go in a separate block.
    main_block = {"type": "text",
                  "text": SYSTEM_PROMPT + "\n\nUse ONLY this agency information:\n" + context}
    if not USE_RAG:
        main_block["cache_control"] = {"type": "ephemeral"}
    system = [main_block]
    notes = []
    if req.lead_id:
        # The server is stateless: this is how it knows a save already happened
        notes.append(f"This traveller's booking is ALREADY SAVED as #{req.lead_id}. "
                     "Only call save_lead again if they change a detail.")
    if req.handoff_id:
        notes.append(f"The team was ALREADY ALERTED (handoff H-{req.handoff_id}). "
                     "Don't call request_handoff again; reassure them someone is coming.")
    if notes:
        system.append({"type": "text", "text": "\n".join(notes)})

    messages = [m.model_dump() for m in req.history]
    messages.append({"role": "user", "content": req.message})
    lead_id, handoff_id = req.lead_id, req.handoff_id

    # The tool-use loop:
    # 1. Ask Claude. 2. If it wants a tool, run it and send back the result.
    # 3. Repeat until Claude answers in plain text. On the last round we
    #    forbid tools (tool_choice none) so Claude MUST reply in words.
    claude_s, tools_s, calls = 0.0, 0.0, 0
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        last_round = round_number == MAX_TOOL_ROUNDS
        t = time.perf_counter()
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=500,
                system=system,
                tools=TOOLS,
                tool_choice={"type": "none"} if last_round else {"type": "auto"},
                messages=messages,
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            # Claude overloaded / unreachable: a friendly message, not a crash
            print(f"[error] Claude API: {type(e).__name__}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Our assistant is busy right now. Please try again in a moment.",
            )
        claude_s += time.perf_counter() - t
        calls += 1
        if response.stop_reason != "tool_use":
            break
        t = time.perf_counter()

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "save_lead":
                text, is_error, saved_id = run_save_lead(block.input)
                lead_id = saved_id or lead_id
            elif block.name == "request_handoff":
                transcript = make_transcript(req.history, req.message)
                text, is_error, saved_id = run_request_handoff(block.input, transcript)
                handoff_id = saved_id or handoff_id
            else:
                text, is_error = f"Unknown tool {block.name}", True
            print(f"[tool] {block.name} {block.input} -> {text}")  # server log
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": text,
                "is_error": is_error,
            })
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
        tools_s += time.perf_counter() - t

    # One log line per message, so we can see where the time goes
    print(f"[timing] total {time.perf_counter() - started:.1f}s | "
          f"retrieval {retrieval_s:.2f}s | claude {claude_s:.1f}s ({calls} call(s)) | "
          f"tools {tools_s:.1f}s")
    reply = "".join(b.text for b in response.content if b.type == "text").strip()
    if not reply:
        reply = "Sorry, something went wrong on our side. A team member will follow up."
    return ChatResponse(reply=reply, lead_id=lead_id, handoff_id=handoff_id)


@app.get("/demo")
def demo_page():
    """A sample agency website with the chat widget on it."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/leads", dependencies=[Depends(require_admin)])
def get_leads():
    return {"leads": list_leads()}


@app.get("/handoffs", dependencies=[Depends(require_admin)])
def get_handoffs():
    return {"handoffs": list_handoffs()}


@app.get("/search", dependencies=[Depends(require_admin)])
def search_chunks(q: str):
    if not USE_RAG:
        return {"mode": "full context: every section is sent with every message"}
    return {"chunks_indexed": CHUNK_COUNT, "results": search(q)}


@app.get("/debug/ip")
def debug_ip(request: Request):
    """Shows the IP the rate limiter uses for YOU (and the headers it came
    from). Only reflects your own request, so it's safe to leave public."""
    return {
        "rate_limit_key": client_ip(request),
        "true_client_ip": request.headers.get("true-client-ip"),
        "cf_connecting_ip": request.headers.get("cf-connecting-ip"),
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
    }