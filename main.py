"""
Trek Assistant — Day 1
A tiny FastAPI server that sends a message to Claude and returns the reply.

Run:
    uvicorn main:app --reload
Then open http://127.0.0.1:8000/docs and try the /chat endpoint.
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()  # reads ANTHROPIC_API_KEY from your .env file

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL = "claude-haiku-5-5"

SYSTEM_PROMPT = """You are the friendly booking assistant for Himalaya Trails Demo,
a trekking agency in Kathmandu, Nepal.
- Answer questions about treks, seasons, difficulty, permits and packing.
- Keep answers short and clear (3-5 sentences).
- If you don't know something specific (exact prices, availability),
  say a team member will confirm, and ask for the traveller's name,
  dates and group size.
- Never invent prices or dates."""

app = FastAPI(title="Trek Assistant")


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty")

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": req.message}],
    )
    return ChatResponse(reply=response.content[0].text)
