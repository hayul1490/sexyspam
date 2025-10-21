const form = document.getElementById("chatForm");
const messageInput = document.getElementById("message");
const consoleDiv = document.getElementById("console");

function appendLine(text, cls="ai") {
  const d = document.createElement("div");
  d.className = "line " + cls;
  d.textContent = text;
  consoleDiv.appendChild(d);
  consoleDiv.scrollTop = consoleDiv.scrollHeight;
}

async function sendMessage(text) {
  appendLine("> " + text, "user");
  appendLine("… thinking", "ai");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text})
    });
    const data = await r.json();
    // remove the '... thinking' line
    const last = consoleDiv.querySelectorAll(".line.ai");
    if (last.length) last[last.length -1].remove();
    if (data.reply) {
      appendLine("AI: " + data.reply, "ai");
    } else {
      appendLine("AI: (응답 없음)", "ai");
    }
  } catch (e) {
    const last = consoleDiv.querySelectorAll(".line.ai");
    if (last.length) last[last.length -1].remove();
    appendLine("AI: 호출 중 오류가 발생했어.", "ai");
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const v = messageInput.value.trim();
  if (!v) return;
  sendMessage(v);
  messageInput.value = "";
});
