// Say IT — frontend logic.
// Flow: input screen -> POST /api/generate -> poll GET /api/jobs/<id> -> result screen.
"use strict";

const $ = (selector) => document.querySelector(selector);
const POLL_INTERVAL_MS = 1000;
const STEP_ORDER = ["generating", "images", "publishing", "done"];

const els = {
  screens: {
    input: $("#screen-input"),
    loading: $("#screen-loading"),
    result: $("#screen-result"),
  },
  form: $("#prompt-form"),
  prompt: $("#prompt"),
  counter: $("#counter"),
  generate: $("#generate"),
  mic: $("#mic"),
  lang: $("#lang"),
  voiceStatus: $("#voice-status"),
  loadingMessage: $("#loading-message"),
  progress: document.querySelector(".progress"),
  progressBar: $("#progress-bar"),
  progressChars: $("#progress-chars"),
  progressTime: $("#progress-time"),
  steps: document.querySelectorAll("#steps li"),
  loadingPrompt: $("#loading-prompt"),
  loadingError: $("#loading-error"),
  loadingErrorText: $("#loading-error-text"),
  resultTitle: $("#result-title"),
  previewFrame: $("#preview-frame"),
  preview: $("#preview"),
  frameUrl: $("#frame-url"),
  openTab: $("#open-tab"),
  siteUrl: $("#site-url"),
  warning: $("#warning"),
  qr: $("#qr"),
  qrDownload: $("#qr-download"),
  toast: $("#toast"),
};

let pollTimer = null;

// ---------- Helpers ----------
function showScreen(name) {
  for (const [key, el] of Object.entries(els.screens)) {
    el.classList.toggle("active", key === name);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

let toastTimer = null;
function toast(message, isError = false) {
  els.toast.textContent = message;
  els.toast.classList.toggle("error", isError);
  els.toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => els.toast.classList.remove("show"), 3500);
}

function updateCounter() {
  els.counter.textContent = `${els.prompt.value.length} / 2000`;
}

async function errorMessage(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
  } catch (_) { /* not JSON */ }
  if (response.status === 422) return "Опишите сайт подробнее (от 3 до 2000 символов).";
  return `Ошибка сервера (${response.status}). Попробуйте ещё раз.`;
}

// ---------- Voice input (Web Speech API) ----------
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;

function setupVoice() {
  if (!SpeechRecognition) {
    els.mic.disabled = true;
    els.mic.title = "Голосовой ввод поддерживается в Chrome, Edge и Safari";
    els.voiceStatus.textContent = "Голос: откройте в Chrome или Edge";
    return;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;

  let baseText = "";

  recognition.onstart = () => {
    listening = true;
    baseText = els.prompt.value.trim() ? els.prompt.value.trim() + " " : "";
    els.mic.classList.add("listening");
    els.mic.setAttribute("aria-pressed", "true");
    els.voiceStatus.textContent = "Слушаю… говорите";
  };

  recognition.onresult = (event) => {
    let finalText = "";
    let interim = "";
    for (let i = 0; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) finalText += result[0].transcript;
      else interim += result[0].transcript;
    }
    els.prompt.value = (baseText + finalText + interim).slice(0, 2000);
    updateCounter();
  };

  recognition.onerror = (event) => {
    const messages = {
      "not-allowed": "Разрешите доступ к микрофону в настройках браузера",
      "service-not-allowed": "Распознавание речи недоступно (нужен HTTPS или localhost)",
      "no-speech": "Не слышно речи — попробуйте ещё раз",
      "network": "Для распознавания речи нужен интернет",
    };
    if (event.error !== "aborted") toast(messages[event.error] || "Ошибка распознавания речи", true);
  };

  recognition.onend = () => {
    listening = false;
    els.mic.classList.remove("listening");
    els.mic.setAttribute("aria-pressed", "false");
    els.voiceStatus.textContent = "";
  };

  els.mic.addEventListener("click", () => {
    if (listening) {
      recognition.stop();
      return;
    }
    recognition.lang = els.lang.value;
    try {
      recognition.start();
    } catch (_) {
      // start() throws if a session is still closing; ignore the double click.
    }
  });
}

// ---------- Generation ----------
async function startGeneration(prompt) {
  if (listening) recognition.stop();
  els.generate.disabled = true;
  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
    });
    if (!response.ok) {
      toast(await errorMessage(response), true);
      return;
    }
    const { job_id: jobId } = await response.json();
    resetLoading(prompt);
    showScreen("loading");
    poll(jobId);
  } catch (_) {
    toast("Нет связи с сервером. Проверьте, что он запущен.", true);
  } finally {
    els.generate.disabled = false;
  }
}

function resetLoading(prompt) {
  els.loadingPrompt.textContent = `«${prompt}»`;
  els.loadingError.hidden = true;
  els.loadingMessage.textContent = "Отправляем запрос…";
  els.progressChars.textContent = "";
  els.progressTime.textContent = "0 с";
  setProgress(2);
  els.steps.forEach((li) => li.classList.remove("active", "done"));
}

function setProgress(value) {
  els.progressBar.style.width = `${value}%`;
  els.progress.setAttribute("aria-valuenow", String(value));
}

function renderSteps(status) {
  const current = STEP_ORDER.indexOf(status);
  els.steps.forEach((li) => {
    const index = STEP_ORDER.indexOf(li.dataset.step);
    li.classList.toggle("done", current > index || status === "done");
    li.classList.toggle("active", current === index && status !== "done");
  });
}

function poll(jobId) {
  clearTimeout(pollTimer);
  const tick = async () => {
    let job;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
      if (!response.ok) throw new Error(await errorMessage(response));
      job = await response.json();
    } catch (err) {
      // Temporary network hiccup: keep polling.
      pollTimer = setTimeout(tick, POLL_INTERVAL_MS * 2);
      return;
    }

    els.loadingMessage.textContent = job.message;
    els.progressTime.textContent = `${Math.round(job.elapsed_seconds)} с`;
    if (job.chars) {
      els.progressChars.textContent = `написано ${job.chars.toLocaleString("ru-RU")} символов кода`;
    }
    setProgress(job.progress);
    renderSteps(job.status);

    if (job.status === "done") {
      setTimeout(() => showResult(job.result), 500);
      return;
    }
    if (job.status === "error") {
      els.loadingError.hidden = false;
      els.loadingErrorText.textContent = job.error;
      return;
    }
    pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
  };
  tick();
}

// ---------- Result ----------
function showResult(result) {
  els.resultTitle.textContent = result.title;
  document.title = `${result.title} — Say IT`;
  els.preview.src = result.preview_url;
  els.frameUrl.textContent = result.url;
  els.openTab.href = result.url;
  els.siteUrl.value = result.url;
  els.qr.src = result.qr_data_url;
  els.qrDownload.href = result.qr_download_url;
  els.qrDownload.setAttribute("download", `say-it-${result.site_id}.png`);
  els.warning.hidden = !result.warning;
  els.warning.textContent = result.warning || "";
  setDevice("desktop");
  showScreen("result");
}

function setDevice(device) {
  els.previewFrame.dataset.device = device;
  document.querySelectorAll(".device").forEach((btn) => {
    const active = btn.dataset.device === device;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
}

async function copyLink() {
  const url = els.siteUrl.value;
  try {
    await navigator.clipboard.writeText(url);
  } catch (_) {
    // Clipboard API needs HTTPS; fall back to selecting the text.
    els.siteUrl.select();
    document.execCommand("copy");
  }
  toast("Ссылка скопирована ✓");
}

// ---------- Wiring ----------
els.prompt.addEventListener("input", updateCounter);

els.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    els.form.requestSubmit();
  }
});

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = els.prompt.value.trim();
  if (prompt.length < 3) {
    toast("Опишите сайт — голосом 🎤 или текстом", true);
    els.prompt.focus();
    return;
  }
  startGeneration(prompt);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    els.prompt.value = chip.dataset.example;
    updateCounter();
    els.prompt.focus();
  });
});

document.querySelectorAll(".device").forEach((btn) => {
  btn.addEventListener("click", () => setDevice(btn.dataset.device));
});

$("#copy").addEventListener("click", copyLink);
$("#retry").addEventListener("click", () => startGeneration(els.prompt.value.trim()));
$("#back-edit").addEventListener("click", () => showScreen("input"));
$("#new-site").addEventListener("click", () => {
  els.preview.src = "about:blank";
  document.title = "Say IT — сайт за минуту голосом";
  showScreen("input");
  els.prompt.focus();
});

setupVoice();
updateCounter();
