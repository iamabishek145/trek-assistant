/*
 * widget.js — Day 7: Trek Assistant chat widget.
 *
 * An agency adds ONE line to their website:
 *   <script src="https://YOUR-SERVER/static/widget.js"
 *           data-name="Himalaya Trails" data-color="#0f3d3e" defer></script>
 *
 * - Talks to POST /chat on the same server the script came from.
 * - Keeps history + lead_id + handoff_id (the server is stateless).
 * - Lives inside a Shadow DOM, so the agency's CSS can't break the widget
 *   and the widget's CSS can't break their site.
 * - Pages can open it with a question: TrekAssistant.open("Tell me about EBC")
 */
(function () {
  const script = document.currentScript;
  const API_URL = new URL("/chat", script.src).href;
  const NAME = script.dataset.name || "Trek Assistant";
  const COLOR = script.dataset.color || "#0f3d3e";
  const STORAGE_KEY = "trek-assistant-chat";
  const GREETING =
    `Namaste! 🙏 I'm the ${NAME} assistant. Ask me about treks, prices, ` +
    `seasons or permits, or I can start a booking for you.`;
  const SUGGESTIONS = [
    "Which trek is best for beginners?",
    "How much is Everest Base Camp?",
    "Talk to a real person",
  ];

  // ---------- state (saved per browser tab, so a page reload keeps the chat)
  let state = { history: [], lead_id: null, handoff_id: null, log: [] };
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY));
    if (saved) state = saved;
  } catch (e) { /* storage blocked: just start fresh */ }
  const save = () => {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
  };
  let busy = false;

  // ---------- build the widget inside a Shadow DOM
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
  <style>
    :host { all: initial; }
    * { box-sizing: border-box; font-family: "DM Sans", system-ui, -apple-system, sans-serif; }
    .launcher {
      position: fixed; right: 20px; bottom: 20px; z-index: 2147483000;
      height: 56px; padding: 0 20px 0 16px; border: 0; border-radius: 28px;
      background: ${COLOR}; color: #fff; font-size: 15px; font-weight: 600;
      display: flex; align-items: center; gap: 10px; cursor: pointer;
      box-shadow: 0 10px 30px rgba(0,0,0,.25); transition: transform .15s;
    }
    .launcher:hover { transform: translateY(-2px); }
    .launcher svg { width: 24px; height: 24px; }
    .panel {
      position: fixed; right: 20px; bottom: 88px; z-index: 2147483000;
      width: 380px; height: min(620px, calc(100vh - 110px));
      background: #fff; border-radius: 18px; overflow: hidden;
      display: none; flex-direction: column;
      box-shadow: 0 20px 60px rgba(0,0,0,.28);
    }
    .panel.open { display: flex; animation: rise .2s ease-out; }
    @keyframes rise { from { opacity: 0; transform: translateY(12px); } }
    header {
      background: ${COLOR}; color: #fff; padding: 14px 14px 14px 16px;
      display: flex; align-items: center; gap: 12px;
    }
    .avatar {
      width: 38px; height: 38px; border-radius: 50%; flex: none;
      background: rgba(255,255,255,.16); display: grid; place-items: center; font-size: 20px;
    }
    .title { flex: 1; min-width: 0; }
    .title b { display: block; font-size: 15px; }
    .title span { font-size: 12px; opacity: .8; }
    .title span::before {
      content: ""; display: inline-block; width: 7px; height: 7px; margin-right: 6px;
      border-radius: 50%; background: #5ee08a; vertical-align: 1px;
    }
    .icon-btn {
      border: 0; background: transparent; color: #fff; cursor: pointer;
      width: 34px; height: 34px; border-radius: 8px; font-size: 18px; opacity: .85;
    }
    .icon-btn:hover { background: rgba(255,255,255,.15); opacity: 1; }
    .messages {
      flex: 1; overflow-y: auto; padding: 16px; background: #f5f3ef;
      display: flex; flex-direction: column; gap: 10px;
    }
    .msg {
      max-width: 85%; padding: 10px 13px; border-radius: 16px;
      font-size: 14px; line-height: 1.45; color: #1f2328; word-wrap: break-word;
    }
    .bot { background: #fff; border-bottom-left-radius: 4px; align-self: flex-start;
           box-shadow: 0 1px 2px rgba(0,0,0,.06); }
    .user { background: ${COLOR}; color: #fff; border-bottom-right-radius: 4px; align-self: flex-end; }
    .note {
      align-self: center; font-size: 12px; font-weight: 600; color: #1d6b3a;
      background: #e3f4e8; padding: 6px 12px; border-radius: 999px; text-align: center;
    }
    .note.handoff { color: #8a4b00; background: #fdf0dc; }
    .error { align-self: center; font-size: 12px; color: #a1281e; background: #fde8e6;
             padding: 6px 12px; border-radius: 999px; }
    .typing { display: flex; gap: 4px; padding: 14px; }
    .typing i { width: 7px; height: 7px; border-radius: 50%; background: #9aa0a6;
                animation: blink 1.2s infinite; }
    .typing i:nth-child(2) { animation-delay: .2s; }
    .typing i:nth-child(3) { animation-delay: .4s; }
    @keyframes blink { 0%, 60%, 100% { opacity: .3; } 30% { opacity: 1; } }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 16px 10px; background: #f5f3ef; }
    .chips:empty { display: none; }
    .chip {
      border: 1px solid ${COLOR}55; background: #fff; color: ${COLOR};
      border-radius: 999px; padding: 7px 12px; font-size: 13px; cursor: pointer;
    }
    .chip:hover { background: ${COLOR}12; }
    form { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #ebe8e2; background: #fff; }
    textarea {
      flex: 1; resize: none; border: 1px solid #dcd8d0; border-radius: 12px;
      padding: 10px 12px; font-size: 14px; line-height: 1.4; max-height: 110px; outline: none;
      color: #1f2328; background: #fff;
    }
    textarea:focus { border-color: ${COLOR}; }
    .send {
      width: 42px; border: 0; border-radius: 12px; background: ${COLOR}; color: #fff;
      cursor: pointer; display: grid; place-items: center; flex: none;
    }
    .send:disabled { opacity: .45; cursor: default; }
    .send svg { width: 18px; height: 18px; }
    .fineprint { font-size: 11px; color: #8a8f98; text-align: center; padding: 0 12px 10px; background: #fff; }
    @media (max-width: 480px) {
      .panel { right: 0; bottom: 0; width: 100vw; height: 100dvh; border-radius: 0; }
      .launcher.hidden-mobile { display: none; }
    }
  </style>

  <button class="launcher" aria-label="Chat with ${NAME}">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
         stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>
    <span>Plan your trek</span>
  </button>

  <section class="panel" role="dialog" aria-label="Chat with ${NAME}">
    <header>
      <div class="avatar">🏔️</div>
      <div class="title"><b>${NAME}</b><span>AI assistant · online 24/7</span></div>
      <button class="icon-btn reset" title="Start a new chat" aria-label="Start a new chat">↺</button>
      <button class="icon-btn close" title="Close" aria-label="Close chat">✕</button>
    </header>
    <div class="messages" aria-live="polite"></div>
    <div class="chips"></div>
    <form>
      <textarea rows="1" placeholder="Ask about treks, prices, dates…" aria-label="Your message"></textarea>
      <button class="send" type="submit" aria-label="Send">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 20.5 21 12 3 3.5l.02 6.6L15 12 3.02 13.9z"/></svg>
      </button>
    </form>
    <div class="fineprint">AI assistant · a team member confirms every booking</div>
  </section>`;

  const $ = (sel) => root.querySelector(sel);
  const launcher = $(".launcher"), panel = $(".panel"), messages = $(".messages");
  const chips = $(".chips"), form = $("form"), input = $("textarea"), sendBtn = $(".send");

  // ---------- rendering
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function formatBot(text) {
    // Safe mini-markdown: escape first, then allow **bold** and line breaks
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }
  function renderItem(item) {
    const el = document.createElement("div");
    el.className = item.type === "note" ? `note ${item.kind || ""}` : item.type === "error" ? "error" : `msg ${item.type}`;
    if (item.type === "bot") el.innerHTML = formatBot(item.text);
    else el.textContent = item.text;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
  }
  function renderAll() {
    messages.innerHTML = "";
    renderItem({ type: "bot", text: GREETING }); // shown, but not sent to the API
    state.log.forEach(renderItem);
    chips.innerHTML = "";
    if (!state.history.length) {
      SUGGESTIONS.forEach((s) => {
        const b = document.createElement("button");
        b.className = "chip"; b.type = "button"; b.textContent = s;
        b.onclick = () => send(s);
        chips.appendChild(b);
      });
    }
  }
  function addItem(item) { state.log.push(item); renderItem(item); save(); }

  let typingEl = null;
  function showTyping(on) {
    if (on) {
      typingEl = document.createElement("div");
      typingEl.className = "msg bot typing";
      typingEl.innerHTML = "<i></i><i></i><i></i>";
      messages.appendChild(typingEl);
      messages.scrollTop = messages.scrollHeight;
    } else if (typingEl) { typingEl.remove(); typingEl = null; }
  }

  // ---------- talking to the server
  async function send(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true; sendBtn.disabled = true; chips.innerHTML = "";
    input.value = ""; autoGrow();
    addItem({ type: "user", text });
    showTyping(true);
    try {
      const r = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text, history: state.history,
          lead_id: state.lead_id, handoff_id: state.handoff_id,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        // 429 = rate limited, 422 = message too long: show a friendly reason
        const reason = typeof data.detail === "string" ? data.detail
          : r.status === 422 ? "That message is too long. Please shorten it." : null;
        throw new Error(reason || `HTTP ${r.status}`);
      }
      showTyping(false);
      state.history.push({ role: "user", content: text }, { role: "assistant", content: data.reply });
      addItem({ type: "bot", text: data.reply });
      if (data.lead_id && data.lead_id !== state.lead_id)
        addItem({ type: "note", text: `✓ Booking request sent to the team · ref #${data.lead_id}` });
      if (data.handoff_id && data.handoff_id !== state.handoff_id)
        addItem({ type: "note", kind: "handoff", text: `A team member has been alerted · H-${data.handoff_id}` });
      state.lead_id = data.lead_id ?? state.lead_id;
      state.handoff_id = data.handoff_id ?? state.handoff_id;
      save();
    } catch (e) {
      showTyping(false);
      const friendly = e.message && !e.message.startsWith("HTTP") && !e.message.includes("fetch");
      addItem({ type: "error", text: friendly ? e.message : "Couldn't reach the assistant. Please try again." });
    } finally {
      busy = false; sendBtn.disabled = false; input.focus();
    }
  }

  // ---------- open / close / input
  function open(question) {
    panel.classList.add("open");
    launcher.classList.add("hidden-mobile");
    if (question) send(question); else input.focus();
  }
  function close() {
    panel.classList.remove("open");
    launcher.classList.remove("hidden-mobile");
  }
  function autoGrow() { input.style.height = "auto"; input.style.height = input.scrollHeight + "px"; }

  launcher.onclick = () => (panel.classList.contains("open") ? close() : open());
  $(".close").onclick = close;
  $(".reset").onclick = () => {
    state = { history: [], lead_id: null, handoff_id: null, log: [] };
    save(); renderAll(); input.focus();
  };
  form.onsubmit = (e) => { e.preventDefault(); send(input.value); };
  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });

  renderAll();
  window.TrekAssistant = { open, close };
})();
