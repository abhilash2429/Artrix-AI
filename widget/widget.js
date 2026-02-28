/**
 * Artrix AI — Embeddable Chat Widget
 *
 * Single JS file. No framework. No build step.
 * Enterprises add one <script> tag to embed.
 *
 * Config via data attributes:
 *   data-api-key       — tenant API key (required)
 *   data-persona       — agent persona name (default "Assistant")
 *   data-primary-color — brand color for theming (default "#0066FF")
 *   data-position      — widget position (bottom-right | bottom-left)
 */

(function () {
  "use strict";

  // --- Read config from script tag ---
  const scriptTag = document.currentScript;
  const CONFIG = {
    apiKey: scriptTag.getAttribute("data-api-key") || "",
    apiUrl: (scriptTag.getAttribute("data-api-url") || "").replace(/\/$/, ""),
    persona: scriptTag.getAttribute("data-persona") || "Assistant",
    primaryColor: scriptTag.getAttribute("data-primary-color") || "#0066FF",
    position: scriptTag.getAttribute("data-position") || "bottom-right",
  };

  let sessionId = sessionStorage.getItem("agent_session_id");
  let isOpen = false;
  let isEscalated = false;

  // --- Load marked.js for markdown rendering ---
  const markedScript = document.createElement("script");
  markedScript.src =
    "https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js";
  document.head.appendChild(markedScript);

  // --- Inject CSS ---
  const posRight = CONFIG.position !== "bottom-left";
  const style = document.createElement("style");
  style.textContent = `
    :root {
      --agent-primary: ${CONFIG.primaryColor};
      --agent-radius: 12px;
      --agent-shadow: 0 4px 24px rgba(0,0,0,0.12);
    }
    #artrix-widget-btn {
      position: fixed; ${posRight ? "right" : "left"}: 20px; bottom: 20px;
      width: 56px; height: 56px; border-radius: 50%; border: none; cursor: pointer;
      background: var(--agent-primary); color: #fff; font-size: 24px;
      box-shadow: var(--agent-shadow); z-index: 99999;
      display: flex; align-items: center; justify-content: center; transition: transform 0.2s;
    }
    #artrix-widget-btn:hover { transform: scale(1.1); }
    #artrix-chat-container {
      position: fixed; ${posRight ? "right" : "left"}: 20px; bottom: 90px;
      width: 380px; max-height: 520px; border-radius: var(--agent-radius); overflow: hidden;
      box-shadow: var(--agent-shadow); z-index: 99999; display: none;
      flex-direction: column; background: #fff; font-family: system-ui, -apple-system, sans-serif;
    }
    #artrix-chat-container.open { display: flex; }
    #artrix-chat-header {
      background: var(--agent-primary); color: #fff; padding: 14px 16px; font-weight: 600; font-size: 15px;
      display: flex; justify-content: space-between; align-items: center;
    }
    #artrix-chat-header button { background: none; border: none; color: #fff; font-size: 18px; cursor: pointer; padding: 4px 8px; }
    #artrix-chat-messages {
      flex: 1; overflow-y: auto; padding: 12px 16px; min-height: 300px; max-height: 380px;
    }
    .artrix-msg { margin-bottom: 10px; max-width: 85%; padding: 10px 14px; border-radius: var(--agent-radius); font-size: 14px; line-height: 1.5; word-wrap: break-word; }
    .artrix-msg.user { background: var(--agent-primary); color: #fff; margin-left: auto; border-bottom-right-radius: 4px; }
    .artrix-msg.assistant { background: #f0f0f0; color: #333; border-bottom-left-radius: 4px; }
    .artrix-msg.assistant p { margin: 0 0 8px 0; }
    .artrix-msg.assistant p:last-child { margin-bottom: 0; }
    .artrix-msg.assistant ul, .artrix-msg.assistant ol { margin: 4px 0; padding-left: 20px; }
    .artrix-msg.assistant code { background: #e0e0e0; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
    .artrix-msg.system { background: #fff3cd; color: #856404; text-align: center; max-width: 100%; font-size: 13px; }
    .artrix-escalation-banner {
      background: var(--agent-primary); color: #fff; text-align: center;
      padding: 10px 16px; font-size: 13px; font-weight: 600;
    }
    .artrix-typing { display: flex; align-items: center; gap: 4px; padding: 8px 14px; }
    .artrix-typing-dot {
      width: 8px; height: 8px; background: #999; border-radius: 50%;
      animation: artrix-bounce 1.4s infinite ease-in-out both;
    }
    .artrix-typing-dot:nth-child(1) { animation-delay: -0.32s; }
    .artrix-typing-dot:nth-child(2) { animation-delay: -0.16s; }
    @keyframes artrix-bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }
    #artrix-chat-input-area {
      display: flex; border-top: 1px solid #eee; padding: 8px;
    }
    #artrix-chat-input {
      flex: 1; border: 1px solid #ddd; border-radius: 8px; padding: 10px 12px; font-size: 14px; outline: none;
    }
    #artrix-chat-input:focus { border-color: var(--agent-primary); }
    #artrix-chat-input:disabled { background: #f5f5f5; cursor: not-allowed; }
    #artrix-chat-send {
      margin-left: 8px; background: var(--agent-primary); color: #fff; border: none; border-radius: 8px;
      padding: 10px 16px; cursor: pointer; font-size: 14px; font-weight: 600;
    }
    #artrix-chat-send:disabled { opacity: 0.5; cursor: not-allowed; }
    @media (max-width: 480px) {
      #artrix-chat-container {
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        width: 100%; max-height: 100%; border-radius: 0;
      }
      #artrix-chat-messages { max-height: calc(100vh - 120px); min-height: auto; flex: 1; }
    }
  `;
  document.head.appendChild(style);

  // --- Build DOM ---
  const btn = document.createElement("button");
  btn.id = "artrix-widget-btn";
  btn.innerHTML = "\uD83D\uDCAC";
  btn.onclick = toggleWidget;
  document.body.appendChild(btn);

  const container = document.createElement("div");
  container.id = "artrix-chat-container";
  container.innerHTML = [
    '<div id="artrix-chat-header">',
    "  <span>" + CONFIG.persona + "</span>",
    '  <button id="artrix-close-btn">\u2715</button>',
    "</div>",
    '<div id="artrix-chat-messages"></div>',
    '<div id="artrix-chat-input-area">',
    '  <input id="artrix-chat-input" type="text" placeholder="Type a message..." autocomplete="off" />',
    '  <button id="artrix-chat-send">Send</button>',
    "</div>",
  ].join("\n");
  document.body.appendChild(container);

  // Event listeners
  document.getElementById("artrix-close-btn").addEventListener("click", closeWidget);
  document.getElementById("artrix-chat-send").addEventListener("click", sendMessage);
  document.getElementById("artrix-chat-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // --- Functions ---
  function toggleWidget() {
    isOpen = !isOpen;
    container.classList.toggle("open", isOpen);
  }

  function closeWidget() {
    isOpen = false;
    container.classList.remove("open");
    // End session on close — strictly gated on sessionStorage presence
    var storedSessionId = sessionStorage.getItem("agent_session_id");
    if (storedSessionId) {
      fetch(CONFIG.apiUrl + "/v1/session/" + storedSessionId + "/end", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": CONFIG.apiKey },
        body: JSON.stringify({}),
      }).catch(function () {});
      sessionStorage.removeItem("agent_session_id");
      sessionId = null;
    }
  }

  function addMessage(role, content) {
    var msgs = document.getElementById("artrix-chat-messages");
    var div = document.createElement("div");
    div.className = "artrix-msg " + role;
    if (role === "assistant" && typeof window.marked !== "undefined") {
      div.innerHTML = window.marked.parse(content);
    } else {
      div.textContent = content;
    }
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function showTyping() {
    var msgs = document.getElementById("artrix-chat-messages");
    var div = document.createElement("div");
    div.className = "artrix-typing";
    div.id = "artrix-typing-indicator";
    div.innerHTML =
      '<div class="artrix-typing-dot"></div>' +
      '<div class="artrix-typing-dot"></div>' +
      '<div class="artrix-typing-dot"></div>';
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function hideTyping() {
    var el = document.getElementById("artrix-typing-indicator");
    if (el) el.remove();
  }

  function showEscalationBanner() {
    isEscalated = true;
    var inputArea = document.getElementById("artrix-chat-input-area");
    var banner = document.createElement("div");
    banner.className = "artrix-escalation-banner";
    banner.textContent = "Connecting you to a human agent...";
    inputArea.parentNode.insertBefore(banner, inputArea);
    // Disable input
    document.getElementById("artrix-chat-input").disabled = true;
    document.getElementById("artrix-chat-send").disabled = true;
  }

  async function ensureSession() {
    if (sessionId) return sessionId;
    try {
      var res = await fetch(CONFIG.apiUrl + "/v1/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": CONFIG.apiKey },
        body: JSON.stringify({}),
      });
      var data = await res.json();
      sessionId = data.session_id;
      sessionStorage.setItem("agent_session_id", sessionId);
      return sessionId;
    } catch (err) {
      addMessage("system", "Something went wrong. Please try again.");
      return null;
    }
  }

  async function sendMessage() {
    if (isEscalated) return;

    var input = document.getElementById("artrix-chat-input");
    var sendBtn = document.getElementById("artrix-chat-send");
    var text = input.value.trim();
    if (!text) return;

    input.value = "";
    sendBtn.disabled = true;
    addMessage("user", text);

    var sid = await ensureSession();
    if (!sid) {
      sendBtn.disabled = false;
      return;
    }

    showTyping();
    try {
      var res = await fetch(CONFIG.apiUrl + "/v1/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": CONFIG.apiKey },
        body: JSON.stringify({ session_id: sid, message: text, stream: false }),
      });
      var data = await res.json();
      hideTyping();

      if (data.response) {
        addMessage("assistant", data.response);
      }
      if (data.escalation_required) {
        showEscalationBanner();
      }
    } catch (err) {
      hideTyping();
      addMessage("system", "Something went wrong. Please try again.");
    }
    if (!isEscalated) {
      sendBtn.disabled = false;
    }
  }

  // Expose for external access
  window.__artrixSend = sendMessage;

  // End session on page unload — strictly gated on sessionStorage
  window.addEventListener("beforeunload", function () {
    var storedSessionId = sessionStorage.getItem("agent_session_id");
    if (storedSessionId) {
      navigator.sendBeacon(
        CONFIG.apiUrl + "/v1/session/" + storedSessionId + "/end",
        new Blob([JSON.stringify({})], { type: "application/json" })
      );
    }
  });
})();
