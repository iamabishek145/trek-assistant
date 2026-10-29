"""
Trek Assistant — Day 1
A tiny FastAPI server that sends a message to Claude and returns the reply.

Run:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/docs and try the /chat endpoint.
"""

import os
from pathlib import Path
from typing import Literal
from rag import build_index, search

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
- Check the "What's included" section before saying something costs extra.
  Permits, guide, porter, teahouse meals and trailhead transport are included.

Booking:
- When a traveller shows interest in booking, ask for any missing details:
  name, trek, travel dates and group size. Ask for at most 2 things at a time.
- Don't repeat questions the traveller already answered earlier in the chat.

Safety:
- For altitude sickness or medical questions, give the agency's guidance and
  recommend they consult a doctor before the trek.
- If asked about something unrelated to trekking with us, politely steer back."""

app = FastAPI(title="Trek Assistant")
CHUNK_COUNT = build_index()  # load agency chunks into ChromaDB at startup


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
    chunks = search(" ".join(recent))
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
