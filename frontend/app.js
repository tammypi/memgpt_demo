const API_BASE = localStorage.getItem("drLiApiBase") || "http://localhost:8000";
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

async function presentAnswer(text, revealAnswer) {
  const currentSequence = ++renderSequence;
  let answerRevealed = false;
  const reveal = () => {
    if (answerRevealed) return;
    answerRevealed = true;
    revealAnswer();
  };
  if (!avatarEnabled || !voiceEnabled) {
    reveal();
    setDoctorState("", inferExpression(text));
    playStateVideo("idle");
    return;
  }
  setDoctorState("thinking", inferExpression(text));
  playStateVideo("thinking");
  try {
    const response = await fetch(`${API_BASE}/api/avatar/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "数字人渲染失败");
    reveal();
    let played = 0;
    let job = data;
    while (currentSequence === renderSequence) {
      while (played < job.segments.length) {
        await playAvatarSegment(job.segments[played].video_url, text, currentSequence);
        played += 1;
      }
      if (job.status === "succeeded") break;
      if (job.status === "failed") throw new Error(job.error || "本地数字人生成失败");
      await new Promise(resolve => setTimeout(resolve, 500));
      const poll = await fetch(`${API_BASE}/api/avatar/jobs/${job.job_id}`);
      job = await poll.json();
      if (!poll.ok) throw new Error(job.detail || "获取数字人任务失败");
    }
    stopAvatarVideo();
    setDoctorState("", inferExpression(text));
    playStateVideo("idle");
  } catch (error) {
    if (currentSequence === renderSequence) {
      stopAvatarVideo();
      reveal();
      setDoctorState("", "concerned");
      playStateVideo("idle");
      console.error(error);
    } else {
      reveal();
    }
  }
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
  renderSequence += 1;
  stopAvatarVideo();
  addMessage("user", text);
  input.value = "";
  input.style.height = "auto";
  sendButton.disabled = true;
  setDoctorState("thinking", inferExpression(text));
  playStateVideo("thinking");
  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "服务暂时不可用");
    await presentAnswer(data.answer, () => addMessage("doctor", data.answer));
  } catch (error) {
    const text = `抱歉，暂时无法连接诊室服务：${error.message}`;
    addMessage("doctor", text);
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
