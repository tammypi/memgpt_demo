const API_BASE = localStorage.getItem("drLiApiBase") || "http://localhost:8000";
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const portrait = document.querySelector("#portrait");
const mouth = portrait.querySelector(".mouth");
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
let mouthTimer;

function setDoctorState(state, expression = "warm") {
  portrait.className = `portrait ${state || ""} expression-${expression}`;
  statusText.textContent = state === "speaking" ? "正在回答" : state === "listening" ? "正在聆听" : state === "thinking" ? "正在思考" : "在线候诊";
  soundWave.classList.toggle("active", state === "speaking");
  if (state !== "speaking") mouth.style.setProperty("--open", 0);
}

function inferExpression(text) {
  if (/疼|痛|肿|出血|担心|严重|急|不舒服/.test(text)) return "concerned";
  if (/很好|放心|不用担心|没问题|恢复|开心|恭喜/.test(text)) return "happy";
  return "warm";
}

function animateMouth(active) {
  clearInterval(mouthTimer);
  if (!active) {
    mouth.style.setProperty("--open", 0);
    return;
  }
  mouthTimer = setInterval(() => {
    mouth.style.setProperty("--open", (0.24 + Math.random() * 0.76).toFixed(2));
  }, 85);
}

function selectChineseVoice() {
  const voices = speechSynthesis.getVoices();
  return voices.find(voice => /zh-CN/i.test(voice.lang) && /female|xiaoxiao|huihui|tingting|女/i.test(voice.name))
    || voices.find(voice => /zh-CN/i.test(voice.lang))
    || voices.find(voice => /^zh/i.test(voice.lang));
}

function speak(text) {
  if (!voiceEnabled || !("speechSynthesis" in window)) {
    setDoctorState("", inferExpression(text));
    return;
  }
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 0.96;
  utterance.pitch = 1.08;
  const voice = selectChineseVoice();
  if (voice) utterance.voice = voice;
  utterance.onstart = () => { setDoctorState("speaking", inferExpression(text)); animateMouth(true); };
  utterance.onboundary = event => {
    if (event.name === "word" || event.name === "sentence") {
      mouth.style.setProperty("--open", (0.35 + Math.random() * 0.65).toFixed(2));
    }
  };
  utterance.onpause = () => animateMouth(false);
  utterance.onresume = () => animateMouth(true);
  utterance.onend = utterance.onerror = () => { animateMouth(false); setDoctorState("", inferExpression(text)); };
  speechSynthesis.speak(utterance);
}

function addMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}-message`;
  const content = document.createElement("div");
  const meta = document.createElement("small");
  const paragraph = document.createElement("p");
  meta.textContent = role === "doctor" ? "李医生 · 刚刚" : "你 · 刚刚";
  paragraph.textContent = text;
  content.append(meta, paragraph);
  if (role === "doctor") {
    const avatar = document.createElement("span");
    avatar.className = "mini-avatar";
    avatar.innerHTML = '<img src="assets/doctor-li.png" alt="">';
    article.append(avatar);
  }
  article.append(content);
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
}

async function sendMessage(message) {
  const text = message.trim();
  if (!text || sendButton.disabled) return;
  speechSynthesis?.cancel();
  addMessage("user", text);
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  setDoctorState("thinking", inferExpression(text));
  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "服务暂时不可用");
    addMessage("doctor", data.answer);
    speak(data.answer);
  } catch (error) {
    const text = `抱歉，暂时无法连接诊室服务：${error.message}`;
    addMessage("doctor", text);
    setDoctorState("", "concerned");
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
    speechSynthesis?.cancel();
    micButton.classList.add("recording");
    speechHint.hidden = false;
    setDoctorState("listening", "warm");
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
    if (!sendButton.disabled) setDoctorState("", "warm");
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
  if (!voiceEnabled) { speechSynthesis?.cancel(); animateMouth(false); setDoctorState("", "warm"); }
});
window.addEventListener("beforeunload", () => speechSynthesis?.cancel());
setupRecognition();
speechSynthesis?.getVoices();
