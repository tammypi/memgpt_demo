const apiOverride = new URLSearchParams(window.location.search).get("api");
const API_BASE = apiOverride || `${window.location.protocol}//${window.location.hostname}:8000`;
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const portrait = document.querySelector("#portrait");
const stateVideo = document.querySelector("#stateVideo");
const avatarVideo = document.querySelector("#avatarVideo");
const statusText = document.querySelector("#statusText");
const soundWave = document.querySelector("#soundWave");
const messages = document.querySelector("#messages");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const micButton = document.querySelector("#micButton");
const sendButton = document.querySelector("#sendButton");
const speechHint = document.querySelector("#speechHint");
const soundToggle = document.querySelector("#soundToggle");
let voiceEnabled = true;
let recognition;
let avatarEnabled = false;
let renderSequence = 0;
let stateVideos = {};

function setDoctorState(state, expression = "warm") {
  portrait.classList.remove("speaking", "listening", "thinking", "expression-warm", "expression-happy", "expression-concerned");
  if (state) portrait.classList.add(state);
  portrait.classList.add(`expression-${expression}`);
  statusText.textContent = state === "speaking" ? "正在回答" : state === "listening" ? "正在聆听" : state === "thinking" ? "正在思考" : "在线候诊";
  soundWave.classList.toggle("active", state === "speaking");
}

function inferExpression(text) {
  if (/疼|痛|肿|出血|担心|严重|急|不舒服/.test(text)) return "concerned";
  if (/很好|放心|不用担心|没问题|恢复|开心|恭喜/.test(text)) return "happy";
  return "warm";
}

function stopAvatarVideo() {
  avatarVideo.oncanplay = null;
  avatarVideo.onended = null;
  avatarVideo.onerror = null;
  avatarVideo.pause();
  avatarVideo.removeAttribute("src");
  avatarVideo.load();
  portrait.classList.remove("answer-video-active");
}

function stopStateVideo() {
  stateVideo.oncanplay = null;
  stateVideo.onerror = null;
  stateVideo.pause();
  stateVideo.removeAttribute("src");
  stateVideo.dataset.state = "";
  stateVideo.load();
  portrait.classList.remove("state-video-active");
}

function playStateVideo(state) {
  const source = stateVideos[state];
  if (!source) {
    stopStateVideo();
    return;
  }
  if (stateVideo.dataset.state === state && stateVideo.src) {
    stateVideo.play().catch(() => stopStateVideo());
    return;
  }
  stopStateVideo();
  stateVideo.dataset.state = state;
  stateVideo.src = source;
  stateVideo.oncanplay = async () => {
    stateVideo.oncanplay = null;
    portrait.classList.add("state-video-active");
    try {
      await stateVideo.play();
    } catch (error) {
      stopStateVideo();
    }
  };
  stateVideo.onerror = () => stopStateVideo();
}

function avatarSpeechText(text) {
  return text
    .replace(/```[\s\S]*?```/g, "代码示例")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "图片")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_~`#>|-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function createAvatarJob(text) {
  const response = await fetch(`${API_BASE}/api/avatar/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "数字人渲染失败");
  return data;
}

async function playAvatarJob(jobPromise, text, sequence) {
  let job = await jobPromise;
  let played = 0;
  while (sequence === renderSequence) {
    while (played < job.segments.length) {
      await playAvatarSegment(job.segments[played].video_url, text, sequence);
        played += 1;
    }
    if (job.status === "succeeded") break;
    if (job.status === "failed") throw new Error(job.error || "本地数字人生成失败");
    await new Promise(resolve => setTimeout(resolve, 500));
    const poll = await fetch(`${API_BASE}/api/avatar/jobs/${job.job_id}`);
    job = await poll.json();
    if (!poll.ok) throw new Error(job.detail || "获取数字人任务失败");
  }
}

function startAvatarStream() {
  const stream = { sequence: ++renderSequence, buffer: "", playback: Promise.resolve() };
  stopAvatarVideo();
  if (avatarEnabled && voiceEnabled) {
    setDoctorState("thinking", "warm");
    playStateVideo("thinking");
  }
  return stream;
}

function enqueueAvatarText(stream, rawText) {
  const text = avatarSpeechText(rawText);
  if (!text || !avatarEnabled || !voiceEnabled || stream.sequence !== renderSequence) return;
  const jobPromise = createAvatarJob(text);
  jobPromise.catch(() => {});
  stream.playback = stream.playback.then(() => playAvatarJob(jobPromise, text, stream.sequence));
}

function feedAvatarStream(stream, delta) {
  stream.buffer += delta;
  const parts = stream.buffer.split(/(?<=[。！？!?\n])/);
  stream.buffer = parts.pop() || "";
  for (const part of parts) enqueueAvatarText(stream, part);
}

function finishAvatarStream(stream) {
  enqueueAvatarText(stream, stream.buffer);
  stream.buffer = "";
  stream.playback.then(() => {
    if (stream.sequence !== renderSequence) return;
    stopAvatarVideo();
    setDoctorState("", "warm");
    playStateVideo("idle");
  }).catch(error => {
    if (stream.sequence === renderSequence) {
      stopAvatarVideo();
      setDoctorState("", "concerned");
      playStateVideo("idle");
      console.error(error);
    }
  });
}

async function playAvatarSegment(url, text, sequence) {
  if (sequence !== renderSequence) return;
  stopAvatarVideo();
  avatarVideo.src = `${API_BASE}${url}`;
  await new Promise((resolve, reject) => {
    avatarVideo.oncanplay = resolve;
    avatarVideo.onerror = () => reject(new Error("数字人片段加载失败"));
    avatarVideo.load();
  });
  if (sequence !== renderSequence) return;
  stopStateVideo();
  portrait.classList.add("answer-video-active");
  setDoctorState("speaking", inferExpression(text));
  await avatarVideo.play();
  await new Promise((resolve, reject) => {
    const cancelTimer = setInterval(() => {
      if (sequence !== renderSequence) finish(resolve);
    }, 100);
    const finish = callback => {
      clearInterval(cancelTimer);
      avatarVideo.onended = null;
      avatarVideo.onerror = null;
      callback();
    };
    avatarVideo.onended = () => finish(resolve);
    avatarVideo.onerror = () => finish(() => reject(new Error("数字人片段播放失败")));
  });
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function renderInlineMarkdown(text) {
  const code = [];
  let html = escapeHtml(text).replace(/`([^`\n]+)`/g, (_, value) => {
    code.push(`<code>${value}</code>`);
    return `\u0000${code.length - 1}\u0000`;
  });
  html = html
    .replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, '<img src="$2" alt="$1" loading="lazy">')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
  return html.replace(/\u0000(\d+)\u0000/g, (_, index) => code[Number(index)]);
}

function renderMarkdown(markdown) {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  const output = [];
  let paragraph = [];
  let listType = "";
  let quote = [];
  let inCode = false;
  let codeLanguage = "";
  let codeLines = [];
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${renderInlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (listType) output.push(`</${listType}>`);
    listType = "";
  };
  const flushQuote = () => {
    if (quote.length) output.push(`<blockquote>${renderMarkdown(quote.join("\n"))}</blockquote>`);
    quote = [];
  };

  for (const line of lines) {
    const fence = line.match(/^\s*```\s*([\w-]*)/);
    if (fence) {
      if (inCode) {
        output.push(`<pre><code${codeLanguage ? ` class="language-${codeLanguage}"` : ""}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        codeLanguage = "";
        inCode = false;
      } else {
        flushParagraph(); closeList(); flushQuote();
        inCode = true;
        codeLanguage = fence[1];
      }
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    const quoteMatch = line.match(/^>\s?(.*)$/);
    if (quoteMatch) { flushParagraph(); closeList(); quote.push(quoteMatch[1]); continue; }
    flushQuote();
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1].length;
      output.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { flushParagraph(); closeList(); output.push("<hr>"); continue; }
    const list = line.match(/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/);
    if (list) {
      flushParagraph();
      const nextType = list[2] ? "ol" : "ul";
      if (listType !== nextType) { closeList(); output.push(`<${nextType}>`); listType = nextType; }
      output.push(`<li>${renderInlineMarkdown(list[3])}</li>`);
      continue;
    }
    closeList();
    if (!line.trim()) flushParagraph(); else paragraph.push(line);
  }
  if (inCode) output.push(`<pre><code${codeLanguage ? ` class="language-${codeLanguage}"` : ""}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  flushParagraph(); closeList(); flushQuote();
  return output.join("");
}

function addMessage(role, text = "") {
  const article = document.createElement("article");
  article.className = `message ${role}-message`;
  const content = document.createElement("div");
  const meta = document.createElement("small");
  const body = document.createElement("div");
  body.className = "message-body";
  meta.textContent = role === "doctor" ? "李医生 · 刚刚" : "你 · 刚刚";
  if (role === "doctor") body.innerHTML = renderMarkdown(text);
  else body.textContent = text;
  content.append(meta, body);
  if (role === "doctor") {
    const avatar = document.createElement("span");
    avatar.className = "mini-avatar";
    avatar.innerHTML = '<img src="assets/doctor-li.png" alt="">';
    article.append(avatar);
  }
  article.append(content);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return body;
}

function chatWebSocketUrl() {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/chat/ws";
  url.search = "";
  url.hash = "";
  return url.toString();
}

function streamChat(message, onDelta) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(chatWebSocketUrl());
    let settled = false;
    socket.onopen = () => socket.send(JSON.stringify({ message }));
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === "delta") onDelta(data.content || "");
      if (data.type === "done") { settled = true; resolve(data); socket.close(); }
      if (data.type === "error") { settled = true; reject(new Error(data.message || "服务暂时不可用")); socket.close(); }
    };
    socket.onerror = () => { if (!settled) reject(new Error("WebSocket 连接失败")); };
    socket.onclose = () => { if (!settled) reject(new Error("回答流意外中断")); };
  });
}

async function sendMessage(message) {
  const text = message.trim();
  if (!text || sendButton.disabled) return;
  renderSequence += 1;
  stopAvatarVideo();
  addMessage("user", text);
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  setDoctorState("thinking", inferExpression(text));
  playStateVideo("thinking");
  const answerBody = addMessage("doctor");
  answerBody.classList.add("typing");
  const avatarStream = startAvatarStream();
  let answer = "";
  try {
    const result = await streamChat(text, delta => {
      answer += delta;
      answerBody.innerHTML = renderMarkdown(answer);
      messages.scrollTop = messages.scrollHeight;
      feedAvatarStream(avatarStream, delta);
    });
    answer = result.answer || answer;
    answerBody.innerHTML = renderMarkdown(answer);
    answerBody.classList.remove("typing");
    finishAvatarStream(avatarStream);
  } catch (error) {
    answerBody.classList.remove("typing");
    answerBody.innerHTML = renderMarkdown(answer || `抱歉，暂时无法连接诊室服务：${error.message}`);
    renderSequence += 1;
    setDoctorState("", "concerned");
    playStateVideo("idle");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

function setupRecognition() {
  if (!SpeechRecognition) {
    micButton.disabled = true;
    micButton.title = "当前浏览器不支持语音识别，请使用 Chrome 或 Edge";
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = "zh-CN";
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onstart = () => {
    micButton.classList.add("recording");
    speechHint.hidden = false;
    setDoctorState("listening", "warm");
    playStateVideo("listening");
  };
  recognition.onresult = event => {
    let transcript = "";
    for (let index = event.resultIndex; index < event.results.length; index += 1) transcript += event.results[index][0].transcript;
    input.value = transcript;
    if (event.results[event.results.length - 1].isFinal) sendMessage(transcript);
  };
  recognition.onerror = event => {
    if (event.error !== "no-speech" && event.error !== "aborted") addMessage("doctor", "没有听清楚，可以再说一次，或直接输入文字。 ");
  };
  recognition.onend = () => {
    micButton.classList.remove("recording");
    speechHint.hidden = true;
    if (!sendButton.disabled) {
      setDoctorState("", "warm");
      playStateVideo("idle");
    }
  };
}

form.addEventListener("submit", event => { event.preventDefault(); sendMessage(input.value); });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 130)}px`; });
input.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(input.value); }
});
micButton.addEventListener("click", () => {
  if (!recognition) return;
  if (micButton.classList.contains("recording")) recognition.stop(); else recognition.start();
});
soundToggle.addEventListener("click", () => {
  voiceEnabled = !voiceEnabled;
  soundToggle.classList.toggle("active", voiceEnabled);
  if (!voiceEnabled) {
    renderSequence += 1;
    stopAvatarVideo();
    setDoctorState("", "warm");
    playStateVideo("idle");
  }
});
window.addEventListener("beforeunload", () => { stopAvatarVideo(); stopStateVideo(); });
fetch(`${API_BASE}/api/avatar/config`)
  .then(response => response.ok ? response.json() : { enabled: false })
  .then(config => {
    avatarEnabled = Boolean(config.enabled);
    stateVideos = config.state_videos || {};
    playStateVideo("idle");
  })
  .catch(() => { avatarEnabled = false; });
setupRecognition();
