"""
Trek Assistant — FastAPI server.
POST /chat: answers a traveller's message using the agency info (via RAG)
and the conversation history the client sends along.

Run:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/docs and try the /chat endpoint.
"""

import os
from typing import Literal
from rag import build_index, pinned_chunks, search

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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
- Once you have all 5, summarise them in one line and say a team member will
  contact them to confirm availability and the deposit.

Safety:
- For altitude sickness or medical questions, give the agency's guidance and
  recommend they consult a doctor before the trek.
- If asked about something unrelated to trekking with us, politely steer back."""

app = FastAPI(title="Trek Assistant")
CHUNK_COUNT = build_index()  # load trek + FAQ chunks into ChromaDB at startup
PINNED = pinned_chunks()  # rule sections, sent with every question


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[Message] = []

class ChatResponse(BaseModel):
    reply: str

@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")
    recent = [m.content for m in req.history[-4:]] + [req.message]
    chunks = PINNED + search(" ".join(recent))
    context = "\n\n---\n\n".join(chunks)
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT + "\n\nUse ONLY this agency information:\n" + context,
        messages=[m.model_dump() for m in req.history]
        + [{"role": "user", "content": req.message}],
    )
    reply = "".join(block.text for block in response.content if block.type == "text")
    return ChatResponse(reply=reply)

@app.get("/search")
def search_chunks(q: str):
    return {"chunks_indexed": CHUNK_COUNT, "results": search(q)}
