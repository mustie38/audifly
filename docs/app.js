(() => {
  const REPO = "mustie38/audifly";
  const RELEASE_FALLBACK = `https://github.com/${REPO}/releases/latest`;

  // 1) Canlı GitHub Release bilgisi + Dosya Boyutu + SHA-256 Checksum
  async function loadLatestRelease() {
    try {
      const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`);
      if (!res.ok) return;
      const data = await res.json();
      const tag = data.tag_name || "";
      const assets = Array.isArray(data.assets) ? data.assets : [];
      const exe = assets.find(a => /\.exe$/i.test(a.name || ""));
      const dlUrl = exe ? exe.browser_download_url : (data.html_url || RELEASE_FALLBACK);

      if (tag) {
        const navVer = document.getElementById("navVersion");
        const metaVer = document.getElementById("metaVersion");
        if (navVer) navVer.textContent = tag;
        if (metaVer) metaVer.textContent = tag;
      }
      ["navDownload", "heroDownload", "footerDownload"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.href = dlUrl;
      });
      const metaRel = document.getElementById("metaReleases");
      if (metaRel && data.html_url) metaRel.href = data.html_url;

      if (exe && exe.size) {
        const metaSize = document.getElementById("metaSize");
        if (metaSize) metaSize.textContent = `${(exe.size / (1024 * 1024)).toFixed(1)} MB`;
      }
      if (exe && exe.digest) {
        const sha = String(exe.digest).replace(/^sha256:/i, "");
        const shaEl = document.getElementById("metaSha");
        const copyBtn = document.getElementById("copyShaBtn");
        if (shaEl) shaEl.textContent = sha;
        if (copyBtn) {
          copyBtn.hidden = false;
          copyBtn.onclick = () => {
            navigator.clipboard?.writeText(sha);
            copyBtn.textContent = "✓";
            setTimeout(() => { copyBtn.textContent = currentLang === "en" ? "Copy" : "Kopyala"; }, 1400);
          };
        }
      }
    } catch (_) {
      // Rate-limit veya offline durumda fallback değerler kalır
    }
  }
  loadLatestRelease();

  // 2) Ses Modu Profilleri (Audifly ile birebir aynı hız ve 10-band EQ değerleri)
  const FREQS = ["60Hz", "170Hz", "310Hz", "600Hz", "1kHz", "3kHz", "6kHz", "12kHz", "14kHz", "16kHz"];
  const MODES = {
    normal: {
      label: "🎵 Normal", rate: 1.00, speed: 0.08, bass: 1.0, treble: 1.0,
      lowShelf: 0, highShelf: 0, c1: "#a980f9", c2: "#00d2ff",
      bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      tr: "Orijinal tempo (1.00x) ve düz ekolayzer",
      en: "Original tempo (1.00x) and flat equalizer",
    },
    slowed: {
      label: "🌙 Slowed", rate: 0.84, speed: 0.045, bass: 1.35, treble: 0.72,
      lowShelf: 6, highShelf: -5, c1: "#8b5cf6", c2: "#5b21b6",
      bands: [4.5, 3.5, 2.0, 0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -3.5],
      tr: "Yavaşlatılmış (0.84x) ve sıcak derin bas tonu",
      en: "Slowed down (0.84x) with warm, dreamy bass",
    },
    speed_up: {
      label: "⚡ Speed Up", rate: 1.18, speed: 0.125, bass: 1.15, treble: 1.2,
      lowShelf: 3, highShelf: 3.5, c1: "#00d2ff", c2: "#5ce1a6",
      bands: [2.0, 1.5, 0.5, 0.0, 1.0, 2.0, 2.5, 2.0, 1.5, 1.0],
      tr: "Hızlandırılmış (1.18x) ve enerjik pop dengesi",
      en: "Sped up (1.18x) with punchy pop clarity",
    },
    nightcore: {
      label: "✨ Nightcore", rate: 1.25, speed: 0.155, bass: 1.05, treble: 1.4,
      lowShelf: 2, highShelf: 6, c1: "#ff6b8a", c2: "#c084fc",
      bands: [1.0, 1.5, 1.0, 0.5, 1.5, 2.5, 3.5, 4.5, 4.0, 3.5],
      tr: "Yüksek tempo (1.25x) ve parlak tiz vurgusu",
      en: "High tempo (1.25x) with bright energetic treble",
    },
    bass_boost: {
      label: "🔊 Bass Boost", rate: 1.00, speed: 0.085, bass: 1.65, treble: 0.95,
      lowShelf: 11, highShelf: 1, c1: "#ff9f1c", c2: "#a980f9",
      bands: [8.0, 7.0, 5.0, 2.0, 0.0, -0.5, 0.0, 1.0, 1.5, 1.0],
      tr: "Orijinal hızda güçlü alt frekans ve derin bas",
      en: "Deep sub-bass boost at original speed",
    },
    night_mode: {
      label: "🌌 Gece Modu", rate: 1.00, speed: 0.065, bass: 0.65, treble: 0.9,
      lowShelf: -8, highShelf: -2, c1: "#5ce1a6", c2: "#3b82f6",
      bands: [-5.0, -4.0, -2.0, 1.0, 2.5, 3.0, 2.0, 0.5, -1.0, -2.0],
      tr: "Kısık bas ve net vokal — gece/komşu dostu",
      en: "Soft bass and clear vocals — late-night friendly",
    },
  };

  let curModeKey = "normal";
  let curMode = MODES.normal;
  let currentLang = "tr";

  // 3) 10-Band EQ Çubuklarını Oluştur & Güncelle
  const eqHost = document.getElementById("demoEqBars");
  const eqFills = [];
  if (eqHost) {
    FREQS.forEach((f) => {
      const col = document.createElement("div");
      col.className = "eq-col";
      col.innerHTML = `<div class="eq-bar-track"><div class="eq-bar-fill"></div></div><span class="eq-freq">${f}</span>`;
      eqHost.appendChild(col);
      eqFills.push(col.querySelector(".eq-bar-fill"));
    });
  }

  function updateModeUI() {
    const modeTag = document.getElementById("mockModeTag");
    if (modeTag) modeTag.textContent = `${curMode.label} • ${curMode.rate.toFixed(2)}x`;
    const nameEl = document.getElementById("demoModeName");
    const rateEl = document.getElementById("demoRate");
    const descEl = document.getElementById("demoDesc");
    if (nameEl) nameEl.textContent = curMode.label;
    if (rateEl) rateEl.textContent = `${curMode.rate.toFixed(2)}x`;
    if (descEl) descEl.textContent = currentLang === "en" ? curMode.en : curMode.tr;

    curMode.bands.forEach((db, i) => {
      if (eqFills[i]) {
        const pct = Math.max(12, Math.min(100, ((db + 10) / 20) * 100));
        eqFills[i].style.height = `${pct}%`;
      }
    });
    if (audioCtx && lowFilter && highFilter) {
      lowFilter.gain.setTargetAtTime(curMode.lowShelf, audioCtx.currentTime, 0.06);
      highFilter.gain.setTargetAtTime(curMode.highShelf, audioCtx.currentTime, 0.06);
    }
  }

  document.querySelectorAll(".mode-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.mode;
      if (!MODES[key]) return;
      curModeKey = key;
      curMode = MODES[key];
      document.querySelectorAll(".mode-pill").forEach(b => {
        b.classList.toggle("active", b.dataset.mode === key);
      });
      updateModeUI();
      if (demoPlaying) restartStepTimer();
    });
  });

  // 4) Canlı Web Audio API Sentezleyici (Before / After Ses Demosu)
  let audioCtx = null;
  let lowFilter = null;
  let highFilter = null;
  let masterGain = null;
  let demoPlaying = false;
  let stepTimer = null;
  let stepIdx = 0;

  // Am7 -> Fmaj7 -> Cmaj7 -> G6 sıcak synth akor yürüyüşü
  const CHORDS = [
    [220.0, 261.63, 329.63, 392.0],
    [174.61, 220.0, 261.63, 329.63],
    [130.81, 196.0, 246.94, 329.63],
    [196.0, 246.94, 293.66, 329.63],
  ];

  function ensureAudio() {
    if (audioCtx) return;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    audioCtx = new Ctx();
    lowFilter = audioCtx.createBiquadFilter();
    lowFilter.type = "lowshelf";
    lowFilter.frequency.value = 180;
    lowFilter.gain.value = curMode.lowShelf;

    highFilter = audioCtx.createBiquadFilter();
    highFilter.type = "highshelf";
    highFilter.frequency.value = 3200;
    highFilter.gain.value = curMode.highShelf;

    masterGain = audioCtx.createGain();
    masterGain.gain.value = 0.22;

    lowFilter.connect(highFilter);
    highFilter.connect(masterGain);
    masterGain.connect(audioCtx.destination);
  }

  function playStep() {
    if (!demoPlaying || !audioCtx) return;
    const now = audioCtx.currentTime;
    const pitchScale = curMode.rate;
    const beat = stepIdx % 8;

    // Kick (0, 4)
    if (beat === 0 || beat === 4) {
      const osc = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(125 * pitchScale, now);
      osc.frequency.exponentialRampToValueAtTime(42 * pitchScale, now + 0.14);
      g.gain.setValueAtTime(0.75, now);
      g.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
      osc.connect(g);
      g.connect(lowFilter);
      osc.start(now);
      osc.stop(now + 0.19);
    }

    // Pad chord on beat 0
    if (beat === 0) {
      const chord = CHORDS[Math.floor(stepIdx / 8) % CHORDS.length];
      chord.forEach(freq => {
        const osc = audioCtx.createOscillator();
        const g = audioCtx.createGain();
        osc.type = "triangle";
        osc.frequency.setValueAtTime(freq * pitchScale, now);
        g.gain.setValueAtTime(0.001, now);
        g.gain.linearRampToValueAtTime(0.11, now + 0.08);
        g.gain.exponentialRampToValueAtTime(0.001, now + (1.7 / curMode.rate));
        osc.connect(g);
        g.connect(lowFilter);
        osc.start(now);
        osc.stop(now + (1.8 / curMode.rate));
      });
    }

    // Crisp arpeggio bell on off-beats
    if (beat % 2 === 1) {
      const chord = CHORDS[Math.floor(stepIdx / 8) % CHORDS.length];
      const note = chord[(beat >> 1) % chord.length] * 2 * pitchScale;
      const osc = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(note, now);
      g.gain.setValueAtTime(0.09, now);
      g.gain.exponentialRampToValueAtTime(0.001, now + 0.22);
      osc.connect(g);
      g.connect(lowFilter);
      osc.start(now);
      osc.stop(now + 0.24);
    }

    stepIdx++;
  }

  function restartStepTimer() {
    if (stepTimer) clearInterval(stepTimer);
    const intervalMs = Math.max(120, Math.round(240 / curMode.rate));
    stepTimer = setInterval(playStep, intervalMs);
  }

  const demoAudioBtn = document.getElementById("demoAudioBtn");
  function syncDemoBtnText() {
    if (!demoAudioBtn) return;
    if (demoPlaying) {
      demoAudioBtn.textContent = currentLang === "en" ? "⏹ Stop Live Audio Demo" : "⏹ Canlı Ses Demosunu Durdur";
    } else {
      demoAudioBtn.textContent = currentLang === "en" ? "▶ Start Live Audio Demo" : "▶ Canlı Ses Demosunu Başlat";
    }
  }
  if (demoAudioBtn) {
    demoAudioBtn.addEventListener("click", async () => {
      if (!demoPlaying) {
        ensureAudio();
        if (audioCtx.state === "suspended") await audioCtx.resume();
        demoPlaying = true;
        playStep();
        restartStepTimer();
      } else {
        demoPlaying = false;
        if (stepTimer) clearInterval(stepTimer);
      }
      syncDemoBtnText();
    });
  }

  // 5) Hero Canlı Neon Spektrum
  const canvas = document.getElementById("heroViz");
  const ctx = canvas ? canvas.getContext("2d") : null;
  const playBtn = document.getElementById("mockPlay");
  const vocalBtn = document.getElementById("mockVocal");
  const mockFill = document.getElementById("mockFill");
  const mockCur = document.getElementById("mockCur");

  let vizPlaying = true;
  let vocalActive = false;
  let phase = 0;
  let progressSec = 84;
  const totalSec = 222;

  if (playBtn) {
    playBtn.addEventListener("click", () => {
      vizPlaying = !vizPlaying;
      playBtn.textContent = vizPlaying ? "⏸" : "▶";
    });
  }
  if (vocalBtn) {
    vocalBtn.addEventListener("click", () => {
      vocalActive = !vocalActive;
      vocalBtn.classList.toggle("active", vocalActive);
    });
  }

  const BARS = 36;
  const levels = new Array(BARS).fill(0.15);
  function fmtSec(s) {
    const m = Math.floor(s / 60), r = Math.floor(s % 60);
    return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
  }
  setInterval(() => {
    if (!vizPlaying) return;
    progressSec = (progressSec + 1) % totalSec;
    if (mockFill) mockFill.style.width = `${(progressSec / totalSec) * 100}%`;
    if (mockCur) mockCur.textContent = fmtSec(progressSec);
  }, 1000);

  function drawViz() {
    if (ctx && canvas) {
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const grad = ctx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, curMode.c1);
      grad.addColorStop(1, curMode.c2);
      ctx.fillStyle = grad;

      if (vizPlaying) phase += curMode.speed;
      const step = w / BARS;
      const barW = Math.max(3, step - 3.5);

      for (let i = 0; i < BARS; i++) {
        const norm = i / (BARS - 1);
        const weight = norm < 0.35 ? curMode.bass : (norm > 0.65 ? curMode.treble : 1.0);
        const vocalDip = vocalActive && norm > 0.3 && norm < 0.7 ? 0.55 : 1.0;
        const target = vizPlaying
          ? Math.min(0.96, Math.max(0.1,
              (0.42 + 0.32 * Math.sin(phase * 1.4 + i * 0.42) + 0.22 * Math.cos(phase * 0.9 - i * 0.25)) * weight * vocalDip
            ))
          : 0.08;
        levels[i] += (target - levels[i]) * 0.22;
        const bh = Math.max(4, levels[i] * (h - 6));
        const x = i * step + 1.5;
        const y = h - bh;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, bh, 3);
        ctx.fill();
      }
    }
    requestAnimationFrame(drawViz);
  }
  drawViz();

  // 6) Ekran Görüntüsü Lightbox
  const lb = document.getElementById("lightbox");
  const lbImg = document.getElementById("lbImg");
  const lbClose = document.getElementById("lbClose");
  document.querySelectorAll(".shot-card[data-zoom]").forEach(card => {
    card.addEventListener("click", () => {
      if (!lb || !lbImg) return;
      lbImg.src = card.dataset.zoom;
      lb.hidden = false;
    });
  });
  if (lbClose) lbClose.addEventListener("click", () => { if (lb) lb.hidden = true; });
  if (lb) lb.addEventListener("click", (e) => { if (e.target === lb) lb.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && lb) lb.hidden = true; });

  // 7) Otomatik Tarayıcı Dili Algılama + TR | EN Anahtarı
  const EN = {
    nav_screens: "Screenshots",
    nav_features: "Features",
    nav_modes: "Sound Modes",
    nav_install: "Install",
    nav_faq: "FAQ",
    btn_download_short: "Download",
    hero_badge: "Open Source • 100% Free • Zero Ads",
    hero_title: 'Desktop music experience, <span class="grad-text">without limits.</span>',
    hero_sub: "Bring YouTube, Spotify, and local playlists together; download offline, switch to <strong>Slowed / Speed Up / Nightcore</strong> in one click, control via QR from your phone, and listen together with friends.",
    btn_download_win: "Download for Windows (.exe)",
    btn_try_audio: "🎧 Try Sound Modes",
    meta_type: "Windows 10/11 (64-bit) Installer (.exe)",
    meta_all_files: "All Files",
    meta_sha_loading: "Verifiable on GitHub Releases",
    btn_copy: "Copy",
    stat_free: "Forever free & ad-free",
    stat_eq: "Live EQ, Vocal Remover & 6 Sound Modes",
    stat_connect: "Zero-Install Phone Web Remote",
    stat_tests: "Automated tests verifying stability",
    scr_kicker: "REAL SCREENSHOTS",
    scr_title: "How Audifly actually looks on Windows",
    scr_sub: "Real captures straight from the Audifly Qt desktop app — click any screenshot to zoom.",
    shot1_t: "🎚️ 10-Band Equalizer & One-Click Sound Modes",
    shot1_d: "Slowed, Speed Up, Nightcore, Bass Boost, Night Mode, Crossfade, and Vocal Remover in one window.",
    shot2_t: "📱 Audifly Connect (QR Phone Remote)",
    shot2_d: "Scan the QR code with your phone — control playback, volume, queue, and playlists with zero app install.",
    shot3_t: "🖥️ Transparent Desktop Widget (Rainmeter Style)",
    shot3_d: "Hides the main window; floating glass desktop card with live spectrum visualizer.",
    shot4_t: "🖼️ Shareable Lyric Card (PNG)",
    shot4_d: "Generate a 720×900 aesthetic card from your favorite lyrics and paste straight into Discord or Stories.",
    modes_kicker: "LIVE AUDIO DEMO (BEFORE / AFTER)",
    modes_title: "Test Sound Modes live in your browser",
    modes_sub: "Start the live Web Audio synth demo below and switch modes to hear the tempo + EQ difference instantly.",
    demo_play: "▶ Start Live Audio Demo",
    feat_kicker: "FEATURES",
    feat_title: "Everything you wish your desktop music player had",
    feat_sub: "Lightweight, fast, and obsessively crafted for pure listening pleasure.",
    f1_title: "Audifly Connect — QR Phone Web Remote",
    f1_desc: "Scan the QR code from your phone — control playback, volume, queue, and browse all playlists from your couch with zero app installation.",
    f2_title: "One-Click Sound Effect Modes",
    f2_desc: "Play any track live in <strong>Slowed</strong>, <strong>Speed Up</strong>, <strong>Nightcore</strong>, <strong>Bass Boost</strong>, or neighbor-friendly <strong>Night Mode</strong>.",
    f3_title: "Rainmeter Desktop Widget & Gaming HUD",
    f3_desc: "Floating transparent glass desktop widget (auto-hides main window) plus a sleek corner Gaming HUD overlay.",
    f4_title: "Live Karaoke & Shareable Lyric Cards",
    f4_desc: "Fullscreen synced Karaoke, one-click <strong>Vocal Remover (Instrumental)</strong>, and copyable PNG lyric cards for Discord, WhatsApp, or Stories.",
    f5_title: "Listen Together (Live Room Sync)",
    f5_desc: "Create a private room with friends featuring a shared queue, live chat, emoji reactions, and millisecond-accurate playback sync.",
    f6_title: "Smart Library, Polisher & Spotlight (Ctrl + K)",
    f6_desc: "Import Spotify, YouTube, M3U, and local MP3/FLAC files; download offline. Clean <code>(Official Video)</code>, <code>[4K]</code>, and <code>- Topic</code> junk in one click.",
    inst_kicker: "READY IN 30 SECONDS",
    inst_title: "Install & Quick Start",
    s1_title: "Download the Installer",
    s1_desc: "Click <strong>Download for Windows</strong> above. VLC audio engine and FFmpeg are bundled — no extra setup needed.",
    s2_title: "Passwordless Quick Start",
    s2_desc: "No account required on first launch: click <strong>⚡ Quick Start</strong> and jump straight into your music.",
    s3_title: "Import Playlists & Enjoy",
    s3_desc: "Paste any public Spotify or YouTube playlist link, download offline, or discover new tracks in Explore.",
    faq_kicker: "FAQ",
    faq_title: "Frequently Asked Questions",
    q1: "Is Audifly really 100% free and safe?",
    a1: "Yes. Audifly is completely open source with zero ads, subscriptions, or telemetry. All playlists and settings stay locally on your PC.",
    q2: "What if Windows SmartScreen shows a warning?",
    a2: "Because independent open-source builds don't carry a paid code-signing certificate, Windows may show a SmartScreen prompt on first run. Click 'More info → Run anyway' or inspect/build directly from GitHub.",
    q3: "Do I need a Spotify developer key to import playlists?",
    a3: "No! Any public Spotify playlist can be imported directly by pasting its link — no login or API key needed.",
    q4: "How does Audifly Connect (Phone Remote) work?",
    a4: "Click the 📱 phone icon in Audifly to start a secure local Wi-Fi web remote and scan the QR code with your phone camera.",
    cta_title: "Ready to upgrade your desktop music?",
    cta_sub: "Fast, modern, open source, and completely under your control.",
    foot_note: "Open-source desktop music player",
    foot_releases: "Releases",
    foot_issues: "Report Issue",
  };

  const TR = {};
  document.querySelectorAll("[data-i18n]").forEach(el => {
    TR[el.dataset.i18n] = el.innerHTML;
  });

  function setLang(lang, persist = true) {
    currentLang = lang === "en" ? "en" : "tr";
    document.documentElement.lang = currentLang;
    if (persist) {
      try { localStorage.setItem("audifly_site_lang", currentLang); } catch (_) {}
    }
    document.getElementById("langTR")?.classList.toggle("active", currentLang === "tr");
    document.getElementById("langEN")?.classList.toggle("active", currentLang === "en");
    const dict = currentLang === "tr" ? TR : EN;
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const k = el.dataset.i18n;
      if (dict[k]) el.innerHTML = dict[k];
    });
    updateModeUI();
    syncDemoBtnText();
  }

  document.getElementById("langTR")?.addEventListener("click", () => setLang("tr"));
  document.getElementById("langEN")?.addEventListener("click", () => setLang("en"));

  // Kayıtlı dil yoksa tarayıcı dilini otomatik algıla
  let initialLang = "tr";
  try {
    const saved = localStorage.getItem("audifly_site_lang");
    if (saved === "tr" || saved === "en") initialLang = saved;
    else if (navigator.language && !navigator.language.toLowerCase().startsWith("tr")) initialLang = "en";
  } catch (_) {}
  setLang(initialLang, false);

  const yr = document.getElementById("year");
  if (yr) yr.textContent = String(new Date().getFullYear());
})();
