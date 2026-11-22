(() => {
  const REPO = "mustie38/audifly";
  const RELEASE_FALLBACK = `https://github.com/${REPO}/releases/latest`;

  // 1) Canlı GitHub Release bilgisi (en son AudiflySetup.exe linkini otomatik çeker)
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
        if (navVer) navVer.textContent = tag;
      }
      ["navDownload", "heroDownload", "footerDownload"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.href = dlUrl;
      });
      if (tag) {
        const info = document.getElementById("releaseInfo");
        const sizeMb = exe && exe.size ? ` • ${(exe.size / (1024 * 1024)).toFixed(1)} MB` : "";
        if (info) info.textContent = `Windows 10 / 11 (64-bit) • ${tag}${sizeMb}`;
      }
    } catch (_) {
      // Rate-limit veya offline durumda fallback link zaten hazır
    }
  }
  loadLatestRelease();

  // 2) Etkileşimli Hero Neon Spektrum & Ses Modu Önizlemesi
  const canvas = document.getElementById("heroViz");
  const ctx = canvas ? canvas.getContext("2d") : null;
  const playBtn = document.getElementById("mockPlay");
  const vocalBtn = document.getElementById("mockVocal");
  const modeTag = document.getElementById("mockModeTag");
  const mockFill = document.getElementById("mockFill");
  const mockCur = document.getElementById("mockCur");

  let playing = true;
  let vocalActive = false;
  let phase = 0;
  let progressSec = 84;
  const totalSec = 222;

  const MODES = {
    normal:     { label: "🎵 Normal • 1.00x",     speed: 0.08, bass: 1.0, treble: 1.0, c1: "#a980f9", c2: "#00d2ff" },
    slowed:     { label: "🌙 Slowed • 0.84x",     speed: 0.045, bass: 1.35, treble: 0.72, c1: "#8b5cf6", c2: "#5b21b6" },
    speed_up:   { label: "⚡ Speed Up • 1.18x",   speed: 0.125, bass: 1.15, treble: 1.2, c1: "#00d2ff", c2: "#5ce1a6" },
    nightcore:  { label: "✨ Nightcore • 1.25x",  speed: 0.155, bass: 1.05, treble: 1.4, c1: "#ff6b8a", c2: "#c084fc" },
    bass_boost: { label: "🔊 Bass Boost • 1.00x", speed: 0.085, bass: 1.65, treble: 0.95, c1: "#ff9f1c", c2: "#a980f9" },
  };
  let curMode = MODES.normal;

  document.querySelectorAll(".mode-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mode-pill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const key = btn.dataset.mode;
      if (MODES[key]) {
        curMode = MODES[key];
        if (modeTag) modeTag.textContent = curMode.label;
      }
    });
  });

  if (playBtn) {
    playBtn.addEventListener("click", () => {
      playing = !playing;
      playBtn.textContent = playing ? "⏸" : "▶";
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
    if (!playing) return;
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

      if (playing) phase += curMode.speed;
      const step = w / BARS;
      const barW = Math.max(3, step - 3.5);

      for (let i = 0; i < BARS; i++) {
        const norm = i / (BARS - 1);
        const weight = norm < 0.35 ? curMode.bass : (norm > 0.65 ? curMode.treble : 1.0);
        const vocalDip = vocalActive && norm > 0.3 && norm < 0.7 ? 0.55 : 1.0;
        const target = playing
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

  // 3) TR <-> EN Dil Değiştirici
  const EN = {
    nav_features: "Features",
    nav_modes: "Sound Modes",
    nav_install: "Install",
    nav_faq: "FAQ",
    btn_download_short: "Download",
    hero_badge: "Open Source • 100% Free • Zero Ads",
    hero_title: 'Desktop music experience, <span class="grad-text">without limits.</span>',
    hero_sub: "Bring YouTube, Spotify, and local playlists together; download offline, switch to <strong>Slowed / Speed Up / Nightcore</strong> in one click, control via QR from your phone, and listen together with friends.",
    btn_download_win: "Download for Windows (.exe)",
    btn_github: "View on GitHub →",
    hero_meta_tests: "405+ Automated Tests",
    hero_meta_local: "100% Local Data",
    stat_free: "Forever free & ad-free",
    stat_eq: "Live EQ, Vocal Remover & 6 Sound Modes",
    stat_connect: "Zero-Install Phone Web Remote",
    stat_privacy: "Local storage — zero tracking",
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

  let lang = "tr";
  const langBtn = document.getElementById("langToggle");
  if (langBtn) {
    langBtn.addEventListener("click", () => {
      lang = lang === "tr" ? "en" : "tr";
      langBtn.textContent = lang === "tr" ? "EN" : "TR";
      document.documentElement.lang = lang;
      const dict = lang === "tr" ? TR : EN;
      document.querySelectorAll("[data-i18n]").forEach(el => {
        const k = el.dataset.i18n;
        if (dict[k]) el.innerHTML = dict[k];
      });
    });
  }

  const yr = document.getElementById("year");
  if (yr) yr.textContent = String(new Date().getFullYear());
})();
