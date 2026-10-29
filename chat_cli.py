"""
chat_cli.py — Day 4: talk to the Trek Assistant from the terminal.

The /chat endpoint is stateless: it only knows what you send it. This client
keeps the conversation history and sends it with every message, the same
way a real chat widget or WhatsApp integration will.

Start the server first (in another terminal):
    uvicorn main:app --reload

Then:
    python chat_cli.py          # chat yourself (type 'quit' to stop, 'reset' to start over)
    python chat_cli.py --test   # run the scripted test conversations below
"""

import sys

import httpx

API_URL = "http://127.0.0.1:8000/chat"


def send(message: str, history: list[dict]) -> str:
    """Send one message plus the history so far, return the bot's reply."""
    r = httpx.post(API_URL, json={"message": message, "history": history}, timeout=60)
    r.raise_for_status()
    return r.json()["reply"]


def run_conversation(turns: list[str]) -> None:
    """Play a list of user messages, carrying history between them."""
    history: list[dict] = []
    for message in turns:
        reply = send(message, history)
        print(f"\n  YOU: {message}\n  BOT: {reply}")
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})


# Each test: (name, user messages in order, what a correct answer looks like)
TESTS = [
    ("Price math uses history",
     ["Tell me about the Poon Hill trek", "How much for 3 of us?"],
     "3 x USD 450 = USD 1,350 (it must remember we mean Poon Hill)"),
    ("Solo rate",
     ["I'm travelling alone. How much is Everest Base Camp?"],
     "USD 1,900, Lukla flights included"),
    ("Included items",
     ["Do I pay extra for permits on the ABC trek?"],
     "No: permits are included (ACAP, TIMS)"),
    ("Unknown info -> no guessing",
     ["Do you have space on a Poon Hill trek starting 12 March?"],
     "A team member will confirm availability; no invented answer"),
    ("Group discount",
     ["We are 6 friends. What's the total for Annapurna Base Camp?"],
     "6 x USD 890 = USD 5,340, minus 10% = USD 4,806"),
    ("Medical question",
     ["I have asthma. Can I do Everest Base Camp?"],
     "Agency altitude guidance + recommend seeing a doctor"),
    ("Off-topic",
     ["Can you write me a poem about Kathmandu?"],
     "Politely steers back to trekking"),
    ("Booking flow, no repeated questions",
     ["I want to book the Langtang trek", "I'm Sarah",
      "2 people, starting 5 April", "My WhatsApp is +44 7700 900123"],
     "Max 2 questions at a time, never re-asks a detail, ends with a one-line summary"),
]


def run_tests() -> None:
    for i, (name, turns, expected) in enumerate(TESTS, 1):
        print(f"\n=== Test {i}: {name}")
        run_conversation(turns)
        print(f"  EXPECTED: {expected}")
    print("\nRead each reply against EXPECTED and note any that fail.")


def interactive() -> None:
    history: list[dict] = []
    print("Trek Assistant — type 'quit' to stop, 'reset' to clear history.")
    while True:
        message = input("\nYOU: ").strip()
        if message.lower() == "quit":
            break
        if message.lower() == "reset":
            history = []
            print("(history cleared)")
            continue
        if not message:
            continue
        reply = send(message, history)
        print(f"BOT: {reply}")
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    try:
        run_tests() if "--test" in sys.argv else interactive()
    except httpx.ConnectError:
        print("Can't reach the server. Start it first: uvicorn main:app --reload")
