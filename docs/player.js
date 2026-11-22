(() => {
  // =========================================================================
  // Audifly Web Player — YouTube IFrame + Live Radio Browser + Local Web Audio
  // =========================================================================
  const STORAGE_KEY = "audifly_web_playlists_v1";
  const STARTER_PLAYLISTS = {
    "Favorilerim": [
      { id: "jfKfPfyJRdk", title: "lofi hip hop radio 📚 beats to relax/study to", artist: "Lofi Girl", thumb: "https://i.ytimg.com/vi/jfKfPfyJRdk/hqdefault.jpg", source: "youtube" },
      { id: "4xDzrJKXOOY", title: "synthwave radio 🌌 beats to chill/game to", artist: "Lofi Girl", thumb: "https://i.ytimg.com/vi/4xDzrJKXOOY/hqdefault.jpg", source: "youtube" },
    ],
  };

  let playlists = loadPlaylists();
  let activePl = Object.keys(playlists)[0] || "Favorilerim";
  let localTracks = [];
  let radioStations = [];

  // Playback state
  let engineKind = null; // "youtube" | "audio"
  let currentTrack = null;
  let currentListType = null; // "playlist" | "local" | "radio"
  let currentIndex = -1;
  let isPlaying = false;
  let shuffle = false;
  let repeat = "off"; // off | all | one
  let volume = 80;
  let muted = false;

  const SOUND_MODES = {
    normal:     { rate: 1.00, low: 0,  high: 0,  c1: "#a980f9", c2: "#00d2ff" },
    slowed:     { rate: 0.84, low: 6,  high: -5, c1: "#8b5cf6", c2: "#5b21b6" },
    speed_up:   { rate: 1.18, low: 3,  high: 3,  c1: "#00d2ff", c2: "#5ce1a6" },
    nightcore:  { rate: 1.25, low: 2,  high: 6,  c1: "#ff6b8a", c2: "#c084fc" },
    bass_boost: { rate: 1.00, low: 11, high: 1,  c1: "#ff9f1c", c2: "#a980f9" },
  };
  let curSoundMode = "normal";

  // DOM refs
  const audioEl = document.getElementById("htmlAudio");
  const pbCover = document.getElementById("pbCover");
  const pbTitle = document.getElementById("pbTitle");
  const pbArtist = document.getElementById("pbArtist");
  const btnPlay = document.getElementById("btnPlay");
  const pbSeek = document.getElementById("pbSeek");
  const pbCur = document.getElementById("pbCur");
  const pbDur = document.getElementById("pbDur");
  const pbVol = document.getElementById("pbVol");
  const btnMute = document.getElementById("btnMute");
  const toastEl = document.getElementById("toast");
  const ytPip = document.getElementById("ytPip");

  let toastTimer = null;
  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3200);
  }

  function loadPlaylists() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object" && Object.keys(parsed).length) return parsed;
      }
    } catch (_) {}
    return JSON.parse(JSON.stringify(STARTER_PLAYLISTS));
  }
  function savePlaylists() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(playlists)); } catch (_) {}
  }

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(sec / 60), s = sec % 60;
    return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  }
  function esc(str) {
    return String(str || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // =========================================================================
  // Web Audio API (Real EQ + FFT Analyser for Local Files)
  // =========================================================================
  let waCtx = null, waSrc = null, waLow = null, waHigh = null, waAnalyser = null;
  function ensureWebAudio() {
    if (waCtx) return;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      waCtx = new Ctx();
      waSrc = waCtx.createMediaElementSource(audioEl);
      waLow = waCtx.createBiquadFilter();
      waLow.type = "lowshelf";
      waLow.frequency.value = 180;
      waHigh = waCtx.createBiquadFilter();
      waHigh.type = "highshelf";
      waHigh.frequency.value = 3200;
      waAnalyser = waCtx.createAnalyser();
      waAnalyser.fftSize = 64;
      waSrc.connect(waLow);
      waLow.connect(waHigh);
      waHigh.connect(waAnalyser);
      waAnalyser.connect(waCtx.destination);
      applySoundModeToAudio();
    } catch (_) {}
  }

  function applySoundModeToAudio() {
    const m = SOUND_MODES[curSoundMode] || SOUND_MODES.normal;
    if (engineKind === "audio") {
      try {
        audioEl.playbackRate = currentListType === "radio" ? 1.0 : m.rate;
        audioEl.preservesPitch = curSoundMode === "normal" || curSoundMode === "bass_boost";
      } catch (_) {}
      if (waCtx && waLow && waHigh) {
        waLow.gain.setTargetAtTime(m.low, waCtx.currentTime, 0.05);
        waHigh.gain.setTargetAtTime(m.high, waCtx.currentTime, 0.05);
      }
    } else if (engineKind === "youtube" && ytPlayer && ytReady) {
      try { ytPlayer.setPlaybackRate(m.rate); } catch (_) {}
    }
  }

  // =========================================================================
  // YouTube IFrame API
  // =========================================================================
  let ytPlayer = null;
  let ytReady = false;
  let pendingYtId = null;

  window.onYouTubeIframeAPIReady = () => {
    ytPlayer = new YT.Player("ytPlayerMount", {
      width: "240",
      height: "135",
      playerVars: { playsinline: 1, modestbranding: 1, rel: 0 },
      events: {
        onReady: () => {
          ytReady = true;
          ytPlayer.setVolume(muted ? 0 : volume);
          if (pendingYtId) {
            const id = pendingYtId; pendingYtId = null;
            ytPlayer.loadVideoById(id);
            applySoundModeToAudio();
          }
        },
        onStateChange: (e) => {
          if (engineKind !== "youtube") return;
          if (e.data === YT.PlayerState.PLAYING) {
            isPlaying = true;
            syncPlayBtn();
            applySoundModeToAudio();
          } else if (e.data === YT.PlayerState.PAUSED) {
            isPlaying = false;
            syncPlayBtn();
          } else if (e.data === YT.PlayerState.ENDED) {
            onTrackEnded();
          }
        },
      },
    });
  };

  document.getElementById("ytPipToggle")?.addEventListener("click", () => {
    ytPip?.classList.toggle("mini");
  });

  // =========================================================================
  // Playback Control
  // =========================================================================
  function stopBoth() {
    try { audioEl.pause(); } catch (_) {}
    if (ytPlayer && ytReady) {
      try { ytPlayer.stopVideo(); } catch (_) {}
    }
  }

  function playTrack(track, listType, idx) {
    stopBoth();
    currentTrack = track;
    currentListType = listType;
    currentIndex = idx;

    pbTitle.textContent = track.title || "Bilinmeyen Şarkı";
    pbArtist.textContent = track.artist || (listType === "radio" ? "📻 Canlı Radyo" : "Audifly Web");
    if (track.thumb) {
      pbCover.innerHTML = `<img src="${esc(track.thumb)}" alt="">`;
    } else {
      pbCover.textContent = listType === "radio" ? "📻" : "♪";
    }

    if (track.source === "youtube") {
      engineKind = "youtube";
      ytPip.hidden = false;
      if (ytReady && ytPlayer) {
        ytPlayer.loadVideoById(track.id);
        ytPlayer.setVolume(muted ? 0 : volume);
      } else {
        pendingYtId = track.id;
      }
      isPlaying = true;
    } else {
      engineKind = "audio";
      ytPip.hidden = true;
      if (listType === "local") {
        ensureWebAudio();
        if (waCtx && waCtx.state === "suspended") waCtx.resume();
      }
      audioEl.src = track.url;
      audioEl.volume = muted ? 0 : (volume / 100);
      applySoundModeToAudio();
      audioEl.play().catch(() => showToast("⚠️ Bu akış tarayıcı tarafından engellendi veya açılamadı."));
      isPlaying = true;
    }
    syncPlayBtn();
    renderPlaylists();
    renderLocalList();
    renderRadioGrid();
  }

  function syncPlayBtn() {
    btnPlay.textContent = isPlaying ? "⏸" : "▶";
  }

  function togglePlay() {
    if (!currentTrack) {
      const songs = playlists[activePl] || [];
      if (songs.length) playTrack(songs[0], "playlist", 0);
      return;
    }
    if (engineKind === "youtube" && ytPlayer && ytReady) {
      if (isPlaying) ytPlayer.pauseVideo();
      else ytPlayer.playVideo();
    } else if (engineKind === "audio") {
      if (audioEl.paused) {
        if (waCtx && waCtx.state === "suspended") waCtx.resume();
        audioEl.play().catch(() => {});
        isPlaying = true;
      } else {
        audioEl.pause();
        isPlaying = false;
      }
      syncPlayBtn();
    }
  }

  function getActiveList() {
    if (currentListType === "playlist") return playlists[activePl] || [];
    if (currentListType === "local") return localTracks;
    if (currentListType === "radio") return radioStations;
    return [];
  }

  function playNext(auto = false) {
    const list = getActiveList();
    if (!list.length) return;
    if (auto && repeat === "one") {
      playTrack(list[currentIndex], currentListType, currentIndex);
      return;
    }
    let nextIdx = shuffle
      ? Math.floor(Math.random() * list.length)
      : currentIndex + 1;
    if (nextIdx >= list.length) {
      if (repeat === "all" || !auto) nextIdx = 0;
      else { isPlaying = false; syncPlayBtn(); return; }
    }
    playTrack(list[nextIdx], currentListType, nextIdx);
  }

  function playPrev() {
    const list = getActiveList();
    if (!list.length) return;
    const prevIdx = (currentIndex - 1 + list.length) % list.length;
    playTrack(list[prevIdx], currentListType, prevIdx);
  }

  function onTrackEnded() {
    playNext(true);
  }

  audioEl.addEventListener("ended", onTrackEnded);
  audioEl.addEventListener("play", () => { isPlaying = true; syncPlayBtn(); });
  audioEl.addEventListener("pause", () => { isPlaying = false; syncPlayBtn(); });

  // Progress updater
  let seeking = false;
  pbSeek.addEventListener("pointerdown", () => { seeking = true; });
  pbSeek.addEventListener("change", () => {
    seeking = false;
    const frac = Number(pbSeek.value) / 1000;
    if (engineKind === "youtube" && ytPlayer && ytReady) {
      const dur = ytPlayer.getDuration() || 0;
      if (dur > 0) ytPlayer.seekTo(frac * dur, true);
    } else if (engineKind === "audio" && isFinite(audioEl.duration) && audioEl.duration > 0) {
      audioEl.currentTime = frac * audioEl.duration;
    }
  });

  setInterval(() => {
    if (seeking || !currentTrack) return;
    if (currentListType === "radio") {
      pbCur.textContent = "CANLI";
      pbDur.textContent = "";
      pbSeek.value = 1000;
      return;
    }
    let cur = 0, dur = 0;
    if (engineKind === "youtube" && ytPlayer && ytReady) {
      cur = ytPlayer.getCurrentTime ? ytPlayer.getCurrentTime() : 0;
      dur = ytPlayer.getDuration ? ytPlayer.getDuration() : 0;
    } else if (engineKind === "audio") {
      cur = audioEl.currentTime || 0;
      dur = isFinite(audioEl.duration) ? audioEl.duration : 0;
    }
    pbCur.textContent = fmt(cur);
    pbDur.textContent = fmt(dur);
    pbSeek.value = dur > 0 ? Math.min(1000, Math.round((cur / dur) * 1000)) : 0;
  }, 500);

  // Volume & transport buttons
  pbVol.addEventListener("input", () => {
    volume = Number(pbVol.value);
    muted = volume === 0;
    btnMute.textContent = muted ? "🔇" : "🔊";
    audioEl.volume = muted ? 0 : volume / 100;
    if (ytPlayer && ytReady) ytPlayer.setVolume(muted ? 0 : volume);
  });
  btnMute.addEventListener("click", () => {
    muted = !muted;
    btnMute.textContent = muted ? "🔇" : "🔊";
    audioEl.volume = muted ? 0 : volume / 100;
    if (ytPlayer && ytReady) ytPlayer.setVolume(muted ? 0 : volume);
  });
  btnPlay.addEventListener("click", togglePlay);
  document.getElementById("btnNext").addEventListener("click", () => playNext(false));
  document.getElementById("btnPrev").addEventListener("click", playPrev);
  const btnShuffle = document.getElementById("btnShuffle");
  btnShuffle.addEventListener("click", () => {
    shuffle = !shuffle;
    btnShuffle.classList.toggle("active", shuffle);
  });
  const btnRepeat = document.getElementById("btnRepeat");
  btnRepeat.addEventListener("click", () => {
    repeat = repeat === "off" ? "all" : (repeat === "all" ? "one" : "off");
    btnRepeat.textContent = repeat === "one" ? "🔂" : "🔁";
    btnRepeat.classList.toggle("active", repeat !== "off");
  });

  // Sound mode pills
  document.querySelectorAll(".sm-pill").forEach(btn => {
    btn.addEventListener("click", () => {
      curSoundMode = btn.dataset.mode;
      document.querySelectorAll(".sm-pill").forEach(b => b.classList.toggle("active", b === btn));
      applySoundModeToAudio();
      showToast(`🎧 Ses Modu: ${btn.textContent}`);
    });
  });

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight") playNext(false);
    else if (e.code === "ArrowLeft") playPrev();
  });

  // =========================================================================
  // Navigation & Playlists
  // =========================================================================
  function switchView(name) {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === name));
    document.querySelectorAll(".view").forEach(v => v.classList.toggle("active", v.id === `view-${name}`));
    if (name === "radio" && !radioStations.length) fetchRadio("TR", "");
  }
  document.querySelectorAll(".nav-item").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));

  function renderPlaylists() {
    const sb = document.getElementById("playlistList");
    sb.innerHTML = Object.entries(playlists).map(([name, songs]) => `
      <div class="pl-item ${name === activePl ? "active" : ""}" data-pl="${esc(name)}">
        <span>📂 ${esc(name)}</span>
        <span class="cnt">${songs.length}</span>
      </div>`).join("");
    sb.querySelectorAll(".pl-item").forEach(el => {
      el.addEventListener("click", () => {
        activePl = el.dataset.pl;
        switchView("playlist");
        renderPlaylists();
      });
    });

    const songs = playlists[activePl] || [];
    document.getElementById("plTitle").textContent = activePl;
    document.getElementById("plSubtitle").textContent = `${songs.length} şarkı • Tarayıcında güvenle saklanır`;
    const listEl = document.getElementById("trackList");
    if (!songs.length) {
      listEl.innerHTML = `<div class="empty-box">Bu liste henüz boş.<br>Yukarıdaki kutuya herhangi bir YouTube linki yapıştırıp ekleyebilirsin!</div>`;
      return;
    }
    listEl.innerHTML = songs.map((s, i) => {
      const isCur = currentListType === "playlist" && currentIndex === i && currentTrack && currentTrack.id === s.id;
      return `
        <div class="track-row ${isCur ? "playing" : ""}" data-idx="${i}">
          <div class="tr-idx">${isCur && isPlaying ? "▶" : i + 1}</div>
          <div class="tr-thumb">${s.thumb ? `<img src="${esc(s.thumb)}" alt="">` : "🎵"}</div>
          <div class="tr-main">
            <div class="tr-title">${esc(s.title)}</div>
            <div class="tr-sub">${esc(s.artist)}</div>
          </div>
          <span class="tr-badge">YouTube</span>
          <button class="tr-del" data-del="${i}" title="Listeden kaldır">✕</button>
        </div>`;
    }).join("");
    listEl.querySelectorAll(".track-row").forEach(row => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".tr-del")) return;
        const idx = Number(row.dataset.idx);
        playTrack(songs[idx], "playlist", idx);
      });
    });
    listEl.querySelectorAll(".tr-del").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.del);
        playlists[activePl].splice(idx, 1);
        savePlaylists();
        renderPlaylists();
      });
    });
  }

  document.getElementById("newPlaylistBtn").addEventListener("click", () => {
    const name = prompt("Yeni çalma listesi adı:");
    if (!name || !name.trim()) return;
    const clean = name.trim();
    if (!playlists[clean]) playlists[clean] = [];
    activePl = clean;
    savePlaylists();
    switchView("playlist");
    renderPlaylists();
  });

  document.getElementById("plPlayAll").addEventListener("click", () => {
    const songs = playlists[activePl] || [];
    if (songs.length) playTrack(songs[0], "playlist", 0);
  });
  document.getElementById("plShuffleBtn").addEventListener("click", () => {
    shuffle = true;
    btnShuffle.classList.add("active");
    const songs = playlists[activePl] || [];
    if (songs.length) playTrack(songs[Math.floor(Math.random() * songs.length)], "playlist", 0);
  });

  // YouTube URL parser + oEmbed metadata fetch
  function extractYoutubeId(raw) {
    const s = (raw || "").trim();
    if (/^[a-zA-Z0-9_-]{11}$/.test(s)) return s;
    const m = s.match(/(?:v=|youtu\.be\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})/);
    return m ? m[1] : null;
  }

  document.getElementById("ytAddForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("ytUrlInput");
    const id = extractYoutubeId(input.value);
    if (!id) {
      showToast("⚠️ Geçerli bir YouTube şarkı linki yapıştır (ör. https://youtu.be/...)");
      return;
    }
    input.value = "";
    let title = `YouTube Parça (${id})`;
    let artist = "YouTube";
    try {
      const r = await fetch(`https://www.youtube.com/oembed?format=json&url=${encodeURIComponent("https://www.youtube.com/watch?v=" + id)}`);
      if (r.ok) {
        const meta = await r.json();
        title = meta.title || title;
        artist = meta.author_name || artist;
      }
    } catch (_) {}
    const track = {
      id, title, artist,
      thumb: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
      source: "youtube",
    };
    playlists[activePl] = playlists[activePl] || [];
    playlists[activePl].push(track);
    savePlaylists();
    switchView("playlist");
    renderPlaylists();
    playTrack(track, "playlist", playlists[activePl].length - 1);
    showToast(`✓ "${title}" eklendi ve çalınıyor!`);
  });

  // =========================================================================
  // Live Radio (Radio Browser API — CORS friendly!)
  // =========================================================================
  async function fetchRadio(country = "", tag = "", query = "") {
    const status = document.getElementById("radioStatus");
    status.textContent = "📡 Canlı radyo istasyonları getiriliyor…";
    const params = new URLSearchParams({ limit: "24", hidebroken: "true", order: "clickcount", reverse: "true" });
    if (country) params.set("countrycode", country);
    if (tag) params.set("tag", tag);
    if (query) params.set("name", query);

    const endpoints = [
      "https://de1.api.radio-browser.info/json/stations/search?",
      "https://all.api.radio-browser.info/json/stations/search?",
    ];
    let data = [];
    for (const ep of endpoints) {
      try {
        const r = await fetch(ep + params.toString());
        if (r.ok) { data = await r.json(); break; }
      } catch (_) {}
    }
    radioStations = (data || [])
      .filter(s => s.url_resolved && s.url_resolved.startsWith("https://"))
      .map(s => ({
        id: s.stationuuid,
        title: (s.name || "Radyo").trim(),
        artist: [s.country, s.tags ? s.tags.split(",").slice(0, 2).join(", ") : ""].filter(Boolean).join(" • "),
        thumb: s.favicon || "",
        url: s.url_resolved,
        source: "radio",
      }));
    status.textContent = radioStations.length
      ? `📡 ${radioStations.length} canlı istasyon hazır — çalmak için tıkla`
      : "⚠️ İstasyon bulunamadı, başka bir filtre dene.";
    renderRadioGrid();
  }

  function renderRadioGrid() {
    const grid = document.getElementById("radioGrid");
    if (!grid) return;
    grid.innerHTML = radioStations.map((st, i) => {
      const isCur = currentListType === "radio" && currentTrack && currentTrack.id === st.id;
      return `
        <div class="radio-card ${isCur ? "playing" : ""}" data-ridx="${i}">
          <div class="rc-icon">${st.thumb ? `<img src="${esc(st.thumb)}" onerror="this.remove()" alt="">` : "📻"}</div>
          <div class="rc-meta">
            <div class="rc-name">${esc(st.title)}</div>
            <div class="rc-sub">${esc(st.artist || "Canlı Yayın")}</div>
          </div>
        </div>`;
    }).join("");
    grid.querySelectorAll(".radio-card").forEach(card => {
      card.addEventListener("click", () => {
        const idx = Number(card.dataset.ridx);
        playTrack(radioStations[idx], "radio", idx);
      });
    });
  }

  document.querySelectorAll("#radioChips .chip").forEach(ch => {
    ch.addEventListener("click", () => {
      document.querySelectorAll("#radioChips .chip").forEach(c => c.classList.remove("active"));
      ch.classList.add("active");
      fetchRadio(ch.dataset.country || "", ch.dataset.tag || "", "");
    });
  });
  document.getElementById("radioSearchForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = document.getElementById("radioQuery").value.trim();
    fetchRadio("", "", q);
  });

  // =========================================================================
  // Local Audio Files (Drag & Drop)
  // =========================================================================
  function addLocalFiles(fileList) {
    const files = Array.from(fileList || []).filter(f => f.type.startsWith("audio/") || /\.(mp3|wav|flac|ogg|m4a)$/i.test(f.name));
    if (!files.length) return;
    const startIdx = localTracks.length;
    files.forEach(f => {
      localTracks.push({
        id: "local:" + f.name + ":" + f.size,
        title: f.name.replace(/\.[^.]+$/, ""),
        artist: "Yerel Ses Dosyası",
        thumb: "",
        url: URL.createObjectURL(f),
        source: "local",
      });
    });
    renderLocalList();
    playTrack(localTracks[startIdx], "local", startIdx);
    showToast(`💽 ${files.length} yerel ses dosyası eklendi!`);
  }

  function renderLocalList() {
    const host = document.getElementById("localTrackList");
    if (!host) return;
    if (!localTracks.length) { host.innerHTML = ""; return; }
    host.innerHTML = localTracks.map((s, i) => {
      const isCur = currentListType === "local" && currentIndex === i;
      return `
        <div class="track-row ${isCur ? "playing" : ""}" data-lidx="${i}">
          <div class="tr-idx">${isCur && isPlaying ? "▶" : i + 1}</div>
          <div class="tr-thumb">💽</div>
          <div class="tr-main">
            <div class="tr-title">${esc(s.title)}</div>
            <div class="tr-sub">${esc(s.artist)}</div>
          </div>
          <span class="tr-badge">Web Audio EQ</span>
          <span></span>
        </div>`;
    }).join("");
    host.querySelectorAll(".track-row").forEach(r => {
      r.addEventListener("click", () => {
        const idx = Number(r.dataset.lidx);
        playTrack(localTracks[idx], "local", idx);
      });
    });
  }

  const dropZone = document.getElementById("dropZone");
  document.getElementById("localFileInput").addEventListener("change", (e) => addLocalFiles(e.target.files));
  ["dragenter", "dragover"].forEach(ev => dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach(ev => dropZone.addEventListener(ev, (e) => { e.preventDefault(); dropZone.classList.remove("dragover"); }));
  dropZone.addEventListener("drop", (e) => addLocalFiles(e.dataTransfer.files));

  // =========================================================================
  // Live Mini Visualizer (Real FFT for local audio, smooth reactive for YT/Radio)
  // =========================================================================
  const vizCanvas = document.getElementById("pbViz");
  const vCtx = vizCanvas ? vizCanvas.getContext("2d") : null;
  let vPhase = 0;
  const freqData = new Uint8Array(32);

  function drawMiniViz() {
    if (vCtx && vizCanvas) {
      const w = vizCanvas.width, h = vizCanvas.height;
      vCtx.clearRect(0, 0, w, h);
      const m = SOUND_MODES[curSoundMode] || SOUND_MODES.normal;
      const g = vCtx.createLinearGradient(0, 0, w, 0);
      g.addColorStop(0, m.c1);
      g.addColorStop(1, m.c2);
      vCtx.fillStyle = g;

      const bars = 18;
      const step = w / bars;
      if (isPlaying && engineKind === "audio" && waAnalyser && currentListType === "local") {
        waAnalyser.getByteFrequencyData(freqData);
        for (let i = 0; i < bars; i++) {
          const val = (freqData[i] || 0) / 255;
          const bh = Math.max(3, val * (h - 2));
          vCtx.fillRect(i * step + 1, h - bh, step - 2.5, bh);
        }
      } else {
        if (isPlaying) vPhase += 0.1 * m.rate;
        for (let i = 0; i < bars; i++) {
          const val = isPlaying ? (0.35 + 0.45 * Math.abs(Math.sin(vPhase + i * 0.45))) : 0.1;
          const bh = Math.max(3, val * (h - 2));
          vCtx.fillRect(i * step + 1, h - bh, step - 2.5, bh);
        }
      }
    }
    requestAnimationFrame(drawMiniViz);
  }
  drawMiniViz();

  // Init
  renderPlaylists();
})();
