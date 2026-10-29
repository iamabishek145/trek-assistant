"""
chat_cli.py — talk to the Trek Assistant from the terminal.

The /chat endpoint is stateless: it only knows what you send it. This client
keeps the conversation history (and any saved lead / handoff id) and sends
it with every message, the same way a real chat widget or WhatsApp
integration will.

Start the server first (in another terminal):
    uvicorn main:app --reload

Then:
    python chat_cli.py            # chat yourself ('quit' to stop, 'reset' to start over)
    python chat_cli.py --test     # run all scripted test conversations
    python chat_cli.py --test 11  # run only test 11 (or e.g. --test 11 12)
"""

import sys

import httpx

API_URL = "http://127.0.0.1:8000/chat"


class Conversation:
    """One traveller's chat: history plus the ids the server gave us."""

    def __init__(self):
        self.history: list[dict] = []
        self.lead_id: int | None = None
        self.handoff_id: int | None = None

    def send(self, message: str) -> str:
        payload = {
            "message": message,
            "history": self.history,
            "lead_id": self.lead_id,
            "handoff_id": self.handoff_id,
        }
        r = httpx.post(API_URL, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()

        notes = ""
        if data.get("lead_id") and data["lead_id"] != self.lead_id:
            notes += f"\n  [lead saved to database: #{data['lead_id']}]"
        if data.get("handoff_id") and data["handoff_id"] != self.handoff_id:
            notes += f"\n  [handoff: team alerted, H-{data['handoff_id']}]"
        self.lead_id = data.get("lead_id")
        self.handoff_id = data.get("handoff_id")

        self.history.append({"role": "user", "content": message})
        self.history.append({"role": "assistant", "content": data["reply"]})
        return data["reply"] + notes


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
    ("Unknown info -> no guessing, no handoff",
     ["Do you have space on a Poon Hill trek starting 12 March?"],
     "A team member will confirm availability; no invented answer; NO handoff"),
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
      "2 people, starting 5 April", "My WhatsApp is +44 7700 900123",
      "Thanks! Can I rent sleeping bags there?"],
     "Never re-asks; [lead saved] ONLY after the WhatsApp message with a #reference; "
     "sleeping-bag answer: rent in Thamel ~USD 1-2/day, no apology, no new save"),
    ("Everything in one message",
     ["Hi, I'm Tom. Please book Poon Hill for 4 people starting 10 November. "
      "Email: tom@example.com"],
     "Saves straight away ([lead saved]), summary + #reference, price 4 x USD 450 = USD 1,800"),
    ("Incomplete booking must NOT save",
     ["Book EBC for me and my wife in October please"],
     "No [lead saved] line; asks for name and contact (max 2 things)"),
    ("Asks for a human",
     ["Can I talk to a real person please?", "Sure, it's anna@example.com"],
     "Asks for a contact first (no handoff yet); [handoff] after the email, reply gives H-reference"),
    ("Emergency on a trek",
     ["Help! Our guide didn't show up and we're stuck in Ghandruk with no transport"],
     "[handoff] straight away (URGENT in server log) + gives agency WhatsApp +977-9800000000"),
    ("Custom request not in our data",
     ["Can you organise a 21-day Manaslu circuit with a private cook?",
      "My WhatsApp is +977 9812345678",
      "Great, thanks!"],
     "Says it's not a listed trek, offers the team; [handoff] after the number; "
     "no second handoff on 'thanks'"),
]


def run_tests(only: list[int]) -> None:
    for i, (name, turns, expected) in enumerate(TESTS, 1):
        if only and i not in only:
            continue
        print(f"\n=== Test {i}: {name}")
        chat = Conversation()
        for message in turns:
            print(f"\n  YOU: {message}\n  BOT: {chat.send(message)}")
        print(f"  EXPECTED: {expected}")
    print("\nRead each reply against EXPECTED and note any that fail.")


def interactive() -> None:
    chat = Conversation()
    print("Trek Assistant — type 'quit' to stop, 'reset' to start a new traveller.")
    while True:
        message = input("\nYOU: ").strip()
        if message.lower() == "quit":
            break
        if message.lower() == "reset":
            chat = Conversation()
            print("(new conversation)")
            continue
        if message:
            print(f"BOT: {chat.send(message)}")


if __name__ == "__main__":
    try:
        if "--test" in sys.argv:
            run_tests([int(a) for a in sys.argv[2:] if a.isdigit()])
        else:
            interactive()
    except httpx.ConnectError:
        print("Can't reach the server. Start it first: uvicorn main:app --reload")
