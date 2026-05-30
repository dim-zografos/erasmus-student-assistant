const form = document.querySelector("#ask-form");
const questionInput = document.querySelector("#question");
const askButton = document.querySelector("#ask-button");
const messages = document.querySelector("#messages");
const sourcesEl = document.querySelector("#sources");
const agreementsEl = document.querySelector("#agreements");
const statusEl = document.querySelector("#status");

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    const docs = data.counts?.scraped_documents ?? 0;
    const agreements = data.counts?.erasmus_agreements ?? 0;
    statusEl.textContent = `${docs} docs, ${agreements} agreements`;
  } catch {
    statusEl.textContent = "Backend unavailable";
  }
}

function addMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  article.appendChild(bubble);
  messages.appendChild(article);
  messages.scrollTop = messages.scrollHeight;
}

function renderSources(sources) {
  sourcesEl.innerHTML = "";
  sourcesEl.className = sources.length ? "list" : "list empty";
  if (!sources.length) {
    sourcesEl.textContent = "No sources returned.";
    return;
  }

  sources.forEach((source, index) => {
    const item = document.createElement("article");
    item.className = "item";
    item.innerHTML = `
      <div class="item-title">S${index + 1}. ${escapeHtml(source.title || "Stored source")}</div>
      <div class="item-meta">${escapeHtml(source.university_name || source.university_key || "")} ${escapeHtml(source.category || "")}</div>
      <div class="item-snippet">${escapeHtml(source.snippet || "")}</div>
      <div class="item-meta"><a href="${escapeAttr(source.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(source.source_url)}</a></div>
    `;
    sourcesEl.appendChild(item);
  });
}

function renderAgreements(agreements) {
  agreementsEl.innerHTML = "";
  agreementsEl.className = agreements.length ? "list" : "list empty";
  if (!agreements.length) {
    agreementsEl.textContent = "No agreement rows returned.";
    return;
  }

  agreements.forEach((agreement, index) => {
    const item = document.createElement("article");
    item.className = "item";
    const department = agreement.department ? `<div class="item-meta">Department: ${escapeHtml(agreement.department)}</div>` : "";
    const deadline = agreement.deadline ? `<div class="item-meta">Deadline: ${escapeHtml(agreement.deadline)}</div>` : "";
    item.innerHTML = `
      <div class="item-title">A${index + 1}. ${escapeHtml(agreement.partner_university || "Partner university")}</div>
      <div class="item-meta">${escapeHtml(agreement.partner_country || "")} from ${escapeHtml(agreement.home_university || "")}</div>
      ${department}
      ${deadline}
      <div class="item-snippet">${escapeHtml(agreement.evidence_text || "")}</div>
      <span class="tag">${escapeHtml(agreement.confidence || "stored")}</span>
    `;
    agreementsEl.appendChild(item);
  });
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  addMessage("user", question);
  questionInput.value = "";
  askButton.disabled = true;
  askButton.textContent = "Thinking";

  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, max_sources: 8 }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Request failed");
    }
    addMessage("assistant", data.answer);
    renderSources(data.sources || []);
    renderAgreements(data.agreements || []);
  } catch (error) {
    addMessage("assistant", `Sorry, I could not answer this request. ${error.message}`);
  } finally {
    askButton.disabled = false;
    askButton.textContent = "Ask";
  }
});

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

function renderMarkdown(value) {
  const lines = String(value ?? "").replaceAll("\r\n", "\n").split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${formatInline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      closeList();
      continue;
    }

    const bullet = line.match(/^[-*]\s+(.+)$/);
    const numbered = line.match(/^\d+\.\s+(.+)$/);

    if (bullet || numbered) {
      flushParagraph();
      const nextType = bullet ? "ul" : "ol";
      if (listType !== nextType) {
        closeList();
        html.push(`<${nextType}>`);
        listType = nextType;
      }
      html.push(`<li>${formatInline((bullet || numbered)[1])}</li>`);
      continue;
    }

    closeList();
    paragraph.push(line);
  }

  flushParagraph();
  closeList();
  return html.join("");
}

function formatInline(value) {
  let text = escapeHtml(value);
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  text = text.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return text;
}

loadHealth();
