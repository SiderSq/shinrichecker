// Handle avatar load failures without inline handlers racing DOMContentLoaded.
document.addEventListener(
  "error",
  (event) => {
    if (
      event.target instanceof HTMLImageElement &&
      event.target.classList.contains("player-avatar-img")
    ) {
      event.target.classList.add("avatar-failed");
    }
  },
  true,
);
// Shinri Reviews Ranker - 16-Player Match Evaluator Frontend Logic

document.addEventListener("DOMContentLoaded", () => {
  // All API calls carry the session token supplied by the local server.
  const apiToken =
    document.querySelector('meta[name="shinri-token"]')?.content || "";
  function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("X-Shinri-Token", apiToken);
    return fetch(url, { ...options, headers });
  }
  const themeButton = document.getElementById("btn-theme");
  const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    themeButton.textContent = theme === "dark" ? "Светлая тема" : "Тёмная тема";
    themeButton.setAttribute("aria-pressed", String(theme === "dark"));
  }
  try {
    applyTheme(
      localStorage.getItem("shinri_theme") ||
        (themeMedia.matches ? "dark" : "light"),
    );
  } catch {
    applyTheme(themeMedia.matches ? "dark" : "light");
  }
  themeButton.addEventListener("click", () => {
    const next =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      localStorage.setItem("shinri_theme", next);
    } catch {
      /* Private browser. */
    }
  });
  // Elements
  const statusBadge = document.getElementById("status-badge");
  const statusText = document.getElementById("status-text");
  const btnRefreshDb = document.getElementById("btn-refresh-db");
  const btnImportDb = document.getElementById("btn-import-db");

  // Tabs
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  // Inputs
  const playersInput = document.getElementById("players-input");
  const chatLogInput = document.getElementById("chat-log-input");
  const btnSampleChat = document.getElementById("btn-sample-chat");
  const btnExtractChat = document.getElementById("btn-extract-chat");

  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const fileInfo = document.getElementById("file-info");
  const fileName = document.getElementById("file-name");
  const btnRemoveFile = document.getElementById("btn-remove-file");

  // OCR Elements
  const ocrDropZone = document.getElementById("ocr-drop-zone");
  const ocrFileInput = document.getElementById("ocr-file-input");
  const ocrPreviewContainer = document.getElementById("ocr-preview-container");
  const ocrPreviewImg = document.getElementById("ocr-preview-img");
  const ocrImageSize = document.getElementById("ocr-image-size");
  const btnClearOcr = document.getElementById("btn-clear-ocr");
  const ocrStatusBar = document.getElementById("ocr-status-bar");
  const ocrStatusText = document.getElementById("ocr-status-text");
  const ocrResultsSummary = document.getElementById("ocr-results-summary");
  const ocrFoundBadge = document.getElementById("ocr-found-badge");
  const btnApplyOcr = document.getElementById("btn-apply-ocr");
  const btnPasteOcr = document.getElementById("btn-paste-ocr");
  const ocrChipsContainer = document.getElementById("ocr-chips-container");
  const ocrAddPlayerInput = document.getElementById("ocr-add-player-input");
  const btnOcrAddPlayer = document.getElementById("btn-ocr-add-player");
  const btnOcrCalcNow = document.getElementById("btn-ocr-calc-now");
  const btnCopyOcrList = document.getElementById("btn-copy-ocr-list");
  const ocrEngineBadge = document.getElementById("ocr-engine-badge");
  let ocrCandidates = [];
  let ocrRecognizedPlayers = [];
  let ocrController = null;
  let ocrRequestId = 0;
  let rankController = null;
  let rankRequestId = 0;
  function syncOcrSelection() {
    ocrRecognizedPlayers = ocrCandidates
      .filter((c) => !c.needs_review || c.confirmed)
      .map((c) => (c.player_id ? `#${c.player_id}` : c.matched_name));
  }

  // Toolbar & Helpers
  const btnSampleData = document.getElementById("btn-sample-data");
  const btnDedupInput = document.getElementById("btn-dedup-input");
  const btnClearInput = document.getElementById("btn-clear-input");
  const matchCounter = document.getElementById("match-counter");
  const matchCounterText = document.getElementById("match-counter-text");

  // Config
  const selectRankingMode = document.getElementById("select-ranking-mode");
  const selectStrategy = document.getElementById("select-strategy");
  const btnCalculate = document.getElementById("btn-calculate");

  // Results
  const resultsSection = document.getElementById("results-section");
  const validationBanner = document.getElementById("validation-banner");
  const resultsMeta = document.getElementById("results-meta");
  const matchPlayersList = document.getElementById("match-players-list");
  const btnSortDesc = document.getElementById("btn-sort-desc");
  const btnSortAsc = document.getElementById("btn-sort-asc");
  const playerFilterInput = document.getElementById("player-filter-input");
  const btnClearFilter = document.getElementById("btn-clear-filter");
  const btnCopyRoster = document.getElementById("btn-copy-roster");

  // Modals
  const importModal = document.getElementById("import-modal");
  const btnCloseModal = document.getElementById("btn-close-modal");
  const btnSubmitImport = document.getElementById("btn-submit-import");
  const importFileInput = document.getElementById("import-file-input");

  const playerModal = document.getElementById("player-modal");
  const btnClosePlayerModal = document.getElementById("btn-close-player-modal");
  const modalPlayerName = document.getElementById("modal-player-name");
  const modalPlayerId = document.getElementById("modal-player-id");
  const modalAvatar = document.getElementById("modal-avatar");
  const modalPlayerBody = document.getElementById("modal-player-body");

  const toastContainer = document.getElementById("toast-container");

  // State
  let currentMatchPlayers = [];
  let currentSortOrder = "desc"; // "desc" (best->worst) or "asc" (worst->best)

  // Default SVG avatar placeholder for missing/broken images
  const DEFAULT_AVATAR_SVG = "/default_avatar.svg";

  window.handleAvatarError = function (img) {
    if (!img) return;
    img.onerror = null;
    img.classList.add("avatar-failed");
  };

  document.querySelectorAll(".player-avatar-img").forEach((img) => {
    if (img.complete && !img.naturalWidth) img.classList.add("avatar-failed");
  });
  // Standard 16-Player Sample Match Roster
  const SAMPLE_16_PLAYERS = [
    "mercyflower^-^",
    "Hunk",
    "FallenAngel",
    "BaobabBack",
    "LaFilozofo",
    "blossoms.",
    "TheRedEyes",
    "DIZEY",
    "fantikkss",
    "Zeranix",
    "cucumber",
    "Bun|dimebag",
    "Pateti",
    "Alex",
    "NonExistentPlayer_999",
    "pssy",
  ].join("\n");

  // 1. Initial Status Check
  fetchStatus();

  async function fetchStatus() {
    try {
      const resp = await apiFetch("/api/status");
      const data = await resp.json();
      if (data.status === "ok") {
        statusBadge.className = "status-badge ready";
        const total = (data.total_players || 0).toLocaleString("ru-RU");
        const src = data.offline_mode
          ? "Оффлайн"
          : data.data_source?.startsWith("network")
            ? "Онлайн"
            : "Кэш";
        statusText.textContent = `База: ${total} игроков (${src})`;
      } else {
        statusBadge.className = "status-badge error";
        statusText.textContent = "Ошибка базы";
      }
    } catch {
      statusBadge.className = "status-badge error";
      statusText.textContent = "Сервер недоступен";
    }
  }

  // 2. Input Counter & Validation
  function countInputPlayers() {
    const raw = playersInput.value;
    if (!raw.trim()) {
      matchCounter.className = "match-counter-pill counter-empty";
      matchCounterText.textContent = "0 / 16 участников";
      return 0;
    }
    const lines = raw
      .split("\n")
      .map((l) => l.trim())
      .filter(
        (l) =>
          l.length > 0 &&
          !l.startsWith("//") &&
          (!l.startsWith("#") || /^#\s*\d+$/.test(l)),
      );

    let count = 0;
    if (
      lines.length === 1 &&
      (lines[0].includes(",") || lines[0].includes(";"))
    ) {
      count = lines[0]
        .split(/[,;]/)
        .map((s) => s.trim())
        .filter(Boolean).length;
    } else {
      count = lines.length;
    }

    if (count === 16) {
      matchCounter.className = "match-counter-pill counter-ready";
      matchCounterText.textContent = "16 / 16 участников (Готово к проверке)";
    } else if (count > 0 && count < 16) {
      matchCounter.className = "match-counter-pill counter-warning";
      matchCounterText.textContent = `${count} / 16 участников (еще ${16 - count})`;
    } else {
      matchCounter.className = "match-counter-pill counter-warning";
      matchCounterText.textContent = `${count} / 16 участников (+${count - 16})`;
    }
    return count;
  }

  const checkLiveEval = document.getElementById("check-live-eval");
  let countDebounceTimer = null;
  let liveEvalTimer = null;

  function debouncedCountInputPlayers() {
    if (countDebounceTimer) clearTimeout(countDebounceTimer);
    countDebounceTimer = setTimeout(() => {
      const count = countInputPlayers();
      if (liveEvalTimer) clearTimeout(liveEvalTimer);
      // Live Evaluation: if exactly 16 players and live-eval is checked, calculate automatically
      if (count === 16 && checkLiveEval && checkLiveEval.checked) {
        if (liveEvalTimer) clearTimeout(liveEvalTimer);
        liveEvalTimer = setTimeout(() => {
          calculateRatings(true); // isLive = true (background quiet mode)
        }, 350);
      }
    }, 40);
  }

  playersInput.addEventListener("input", debouncedCountInputPlayers);

  // 3. Tab Switching
  function switchToTab(tabId) {
    tabBtns.forEach((b) => {
      if (b.dataset.tab === tabId) {
        b.classList.add("active");
      } else {
        b.classList.remove("active");
      }
    });
    tabContents.forEach((c) => {
      if (c.id === tabId) {
        c.classList.add("active");
      } else {
        c.classList.remove("active");
      }
    });
  }

  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      switchToTab(btn.dataset.tab);
    });
  });

  // 3b. OCR Handlers & Chips Management
  function updateOcrSummary() {
    if (!ocrFoundBadge) return;
    const total = ocrCandidates.length;
    const exactCount = ocrCandidates.filter((c) => c.similarity >= 0.99).length;
    const correctedCount = ocrCandidates.filter((c) => c.corrected).length;
    const reviewCount = ocrCandidates.filter(
      (c) => c.needs_review && !c.confirmed,
    ).length;
    let note = `Распознано игроков: ${total}`;
    if (correctedCount > 0) {
      note += ` (${exactCount} точно, ${correctedCount} исправлений предложено)`;
    }
    ocrFoundBadge.textContent = `${note} • к проверке: ${reviewCount}`;
    ocrFoundBadge.classList.toggle("needs-review", reviewCount > 0);
  }

  function renderOcrChips() {
    if (!ocrChipsContainer) return;
    ocrChipsContainer.innerHTML = "";

    ocrCandidates.forEach((candidate, idx) => {
      const chip = document.createElement("div");
      chip.className = "ocr-chip";

      if (candidate.needs_review && !candidate.confirmed)
        chip.classList.add("chip-review");
      let statusLabel = "Точное совпадение";
      let statusTitle = "Точное совпадение в базе";
      if (candidate.similarity >= 0.99) {
        chip.classList.add("chip-exact");
      } else if (candidate.corrected) {
        chip.classList.add("chip-corrected");
        statusLabel = "Исправление OCR";
        statusTitle = `Предложено исправление: ${candidate.raw_ocr} → ${candidate.matched_name} (${Math.round(candidate.similarity * 100)}%)`;
      } else {
        statusLabel = "Нет профиля";
        statusTitle = "Новичок / нет в базе";
      }

      if (candidate.needs_review && !candidate.confirmed)
        statusLabel = "Требует проверки";
      else if (candidate.confirmed) statusLabel = "Подтверждено";

      const iconSpan = document.createElement("span");
      iconSpan.className = "chip-status-label";
      iconSpan.textContent = statusLabel;
      iconSpan.title = statusTitle;

      const nameSpan = document.createElement("span");
      nameSpan.className = "chip-name";
      nameSpan.textContent = candidate.matched_name;
      nameSpan.title = `${candidate.matched_name} (${statusTitle})`;

      const removeBtn = document.createElement("button");
      removeBtn.className = "chip-remove";
      removeBtn.innerHTML = "×";
      removeBtn.type = "button";
      removeBtn.title = `Исключить ${candidate.matched_name}`;
      removeBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        ocrCandidates.splice(idx, 1);
        syncOcrSelection();
        playersInput.value = ocrRecognizedPlayers.join("\n");
        countInputPlayers();
        updateOcrSummary();
        renderOcrChips();
      });

      chip.appendChild(iconSpan);
      chip.appendChild(nameSpan);
      chip.appendChild(removeBtn);
      if (candidate.needs_review && !candidate.confirmed) {
        const reason = document.createElement("span");
        reason.className = "ocr-review-reason";
        reason.textContent = `${candidate.review_reason} • исходно: ${candidate.raw_ocr}`;
        chip.appendChild(reason);
        if (candidate.alternatives?.length) {
          const select = document.createElement("select");
          select.className = "ocr-candidate-select";
          select.setAttribute(
            "aria-label",
            `Выбор профиля для ${candidate.raw_ocr}`,
          );
          const original = new Option("Оставить исходный текст", "");
          select.add(original);
          candidate.alternatives.forEach((a) =>
            select.add(
              new Option(
                `${a.name} · ID ${a.id} · ${Math.round(a.similarity * 100)}%`,
                String(a.id),
              ),
            ),
          );
          select.value = candidate.player_id ? String(candidate.player_id) : "";
          select.addEventListener("change", () => {
            const selected = candidate.alternatives.find(
              (a) => String(a.id) === select.value,
            );
            candidate.player_id = selected?.id || null;
            candidate.matched_name = selected?.name || candidate.raw_ocr;
          });
          chip.appendChild(select);
        }
        const confirm = document.createElement("button");
        confirm.type = "button";
        confirm.className = "btn btn-secondary btn-sm";
        confirm.textContent = "Подтвердить";
        confirm.addEventListener("click", () => {
          candidate.confirmed = true;
          syncOcrSelection();
          playersInput.value = ocrRecognizedPlayers.join("\n");
          countInputPlayers();
          updateOcrSummary();
          renderOcrChips();
        });
        chip.appendChild(confirm);
      }
      ocrChipsContainer.appendChild(chip);
    });
  }

  function addManualOcrPlayer() {
    if (!ocrAddPlayerInput) return;
    const name = ocrAddPlayerInput.value.trim();
    if (!name) return;
    if (
      ocrCandidates.some(
        (c) => c.matched_name.toLowerCase() === name.toLowerCase(),
      )
    ) {
      showToast("Игрок уже есть в списке", "warning");
      return;
    }
    ocrCandidates.push({
      raw_ocr: name,
      matched_name: name,
      player_id: null,
      avg: null,
      count: 0,
      similarity: 1.0,
      corrected: false,
    });
    syncOcrSelection();
    playersInput.value = ocrRecognizedPlayers.join("\n");
    countInputPlayers();
    updateOcrSummary();
    renderOcrChips();
    ocrAddPlayerInput.value = "";
    showToast(`Игрок "${name}" добавлен`, "success");
  }

  function handleOcrFile(file, autoRank = true) {
    if (
      !file ||
      (!file.type.startsWith("image/") &&
        !file.name.match(/\.(png|jpe?g|bmp|webp)$/i))
    ) {
      showToast(
        "Пожалуйста, выберите файл изображения (PNG, JPG, BMP)",
        "warning",
      );
      return;
    }

    if (file.size > 8 * 1024 * 1024) {
      showToast(
        "Изображение больше 8 МБ. Уменьшите размер или обрежьте область с никами.",
        "error",
      );
      return;
    }
    if (ocrController) ocrController.abort();
    ocrController = new AbortController();
    const requestId = ++ocrRequestId;
    const reader = new FileReader();
    reader.onload = async (e) => {
      if (requestId !== ocrRequestId) return;
      const controller = ocrController;
      const timeoutId = setTimeout(() => controller.abort(), 30000);
      const dataUrl = e.target.result;
      ocrPreviewImg.src = dataUrl;
      ocrPreviewContainer.classList.remove("hidden");
      ocrDropZone.classList.add("hidden");
      ocrStatusBar.classList.remove("hidden");
      ocrResultsSummary.classList.add("hidden");
      document.getElementById("ocr-spinner").classList.remove("hidden");
      ocrStatusText.textContent = "Распознавание локальным OCR-движком…";

      const img = new Image();
      img.onload = () => {
        ocrImageSize.textContent = `${img.width}×${img.height} px`;
      };
      img.src = dataUrl;

      try {
        const resp = await apiFetch("/api/ocr-process", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ocrController.signal,
          body: JSON.stringify({
            image: dataUrl,
            layout: document.getElementById("ocr-layout").value,
          }),
        });
        const resData = await resp.json();
        if (requestId !== ocrRequestId) return;
        if (!resp.ok || resData.error)
          throw new Error(resData.error || "Ошибка OCR");
        ocrEngineBadge.textContent =
          resData.engine === "tesseract"
            ? "Локальный Tesseract"
            : "Windows OCR";
        document.getElementById("ocr-raw-text").textContent =
          resData.raw_ocr || "";
        if (resData.candidates && resData.candidates.length > 0) {
          ocrCandidates = resData.candidates;
          syncOcrSelection();

          ocrStatusBar.classList.add("hidden");
          ocrResultsSummary.classList.remove("hidden");

          updateOcrSummary();
          renderOcrChips();

          // Auto-fill players input with recognized names
          playersInput.value = ocrRecognizedPlayers.join("\n");
          countInputPlayers();

          // One-Step Auto-Scan: automatically run ranking if enabled
          if (
            autoRank &&
            checkLiveEval &&
            checkLiveEval.checked &&
            !ocrCandidates.some((c) => c.needs_review && !c.confirmed)
          ) {
            switchToTab("tab-text");
            await calculateRatings(false);
            showToast(
              `Сквозная оценка: ${ocrRecognizedPlayers.length} игроков распознано и рассчитано!`,
              "success",
            );
          } else {
            showToast(
              `Найдено кандидатов: ${ocrCandidates.length}. Подтверждено: ${ocrRecognizedPlayers.length}.`,
              "success",
            );
          }
        } else {
          ocrStatusBar.classList.remove("hidden");
          document.getElementById("ocr-spinner").classList.add("hidden");
          ocrStatusText.textContent =
            "Ники не найдены. Выберите макет «Текст» или обрежьте скриншот до области с никами.";
          showToast("Текст на скриншоте не распознан как никнеймы", "warning");
        }
      } catch (err) {
        if (requestId !== ocrRequestId) return;
        document.getElementById("ocr-spinner").classList.add("hidden");
        ocrStatusBar.classList.remove("hidden");
        ocrStatusText.textContent = "Ошибка OCR: " + err.message;
        showToast(
          "Ошибка распознавания: " +
            (err.name === "AbortError"
              ? "Время ожидания истекло; обрежьте скриншот и попробуйте снова"
              : err.message),
          "danger",
        );
      } finally {
        clearTimeout(timeoutId);
      }
    };
    reader.readAsDataURL(file);
  }

  if (ocrDropZone) {
    ocrDropZone.addEventListener("click", () => ocrFileInput.click());
    ocrDropZone.addEventListener("dragover", (e) => {
      e.preventDefault();
      ocrDropZone.style.borderColor = "var(--accent-blue)";
    });
    ocrDropZone.addEventListener("dragleave", () => {
      ocrDropZone.style.borderColor = "";
    });
    ocrDropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      ocrDropZone.style.borderColor = "";
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleOcrFile(e.dataTransfer.files[0]);
      }
    });
  }

  if (ocrFileInput) {
    ocrFileInput.addEventListener("change", (e) => {
      if (e.target.files && e.target.files[0]) {
        handleOcrFile(e.target.files[0]);
      }
    });
  }

  if (btnClearOcr) {
    btnClearOcr.addEventListener("click", () => {
      ++ocrRequestId;
      if (ocrController) ocrController.abort();
      ocrPreviewImg.src = "";
      ocrPreviewContainer.classList.add("hidden");
      ocrDropZone.classList.remove("hidden");
      ocrFileInput.value = "";
      ocrCandidates = [];
      ocrRecognizedPlayers = [];
      if (ocrChipsContainer) ocrChipsContainer.innerHTML = "";
    });
  }

  if (btnApplyOcr) {
    btnApplyOcr.addEventListener("click", () => {
      if (ocrRecognizedPlayers.length > 0) {
        playersInput.value = ocrRecognizedPlayers.join("\n");
        countInputPlayers();
        switchToTab("tab-text");
        showToast("Ники перенесены в список матча", "success");
      }
    });
  }

  if (btnOcrAddPlayer) {
    btnOcrAddPlayer.addEventListener("click", addManualOcrPlayer);
  }
  if (ocrAddPlayerInput) {
    ocrAddPlayerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addManualOcrPlayer();
      }
    });
  }

  if (btnOcrCalcNow) {
    btnOcrCalcNow.addEventListener("click", () => {
      if (ocrRecognizedPlayers.length === 0) {
        showToast("Нет участников для расчёта рейтинга", "warning");
        return;
      }
      playersInput.value = ocrRecognizedPlayers.join("\n");
      countInputPlayers();
      switchToTab("tab-text");
      calculateRatings(false);
    });
  }

  if (btnCopyOcrList) {
    btnCopyOcrList.addEventListener("click", async () => {
      if (ocrRecognizedPlayers.length === 0) {
        showToast("Список игроков пуст", "warning");
        return;
      }
      const listText = ocrRecognizedPlayers.join("\n");
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(listText);
        } else {
          const ta = document.createElement("textarea");
          ta.value = listText;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        showToast(
          `Скопировано ${ocrRecognizedPlayers.length} игроков в буфер`,
          "success",
        );
      } catch (err) {
        showToast("Ошибка копирования в буфер", "danger");
      }
    });
  }

  if (btnPasteOcr) {
    btnPasteOcr.addEventListener("click", async () => {
      try {
        if (navigator.clipboard && navigator.clipboard.read) {
          const items = await navigator.clipboard.read();
          for (const item of items) {
            for (const type of item.types) {
              if (type.startsWith("image/")) {
                const blob = await item.getType(type);
                handleOcrFile(blob);
                return;
              }
            }
          }
          showToast(
            "В буфере обмена нет изображения. Сделайте скриншот (Win+Shift+S) и нажмите Ctrl+V",
            "warning",
          );
        } else {
          showToast("Нажмите Ctrl+V для вставки скриншота из буфера", "info");
        }
      } catch (err) {
        showToast("Нажмите Ctrl+V для вставки скриншота из буфера", "info");
      }
    });
  }

  // Global Clipboard Image Paste (Ctrl+V) anywhere in window
  window.addEventListener("paste", (e) => {
    const items = (e.clipboardData || e.originalEvent.clipboardData).items;
    for (let index in items) {
      const item = items[index];
      if (item.kind === "file" && item.type.startsWith("image/")) {
        e.preventDefault();
        const blob = item.getAsFile();
        switchToTab("tab-ocr");
        handleOcrFile(blob);
        showToast("Скриншот получен из буфера обмена!", "info");
        return;
      }
    }
  });

  // Global Window Drag & Drop for images and text files
  window.addEventListener("dragover", (e) => {
    e.preventDefault();
  });

  window.addEventListener("drop", (e) => {
    if (e.target.closest("#drop-zone") || e.target.closest("#ocr-drop-zone")) {
      return;
    }
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      if (
        file.type.startsWith("image/") ||
        file.name.match(/\.(png|jpe?g|bmp|webp)$/i)
      ) {
        switchToTab("tab-ocr");
        handleOcrFile(file);
      } else if (file.name.endsWith(".txt") || file.name.endsWith(".csv")) {
        switchToTab("tab-file");
        handleFile(file);
      }
    }
  });

  // 4. Quick Helpers
  btnSampleData.addEventListener("click", () => {
    playersInput.value = SAMPLE_16_PLAYERS;
    countInputPlayers();
    showToast("Загружен тестовый матч на 16 игроков", "info");
    // Switch to first tab
    tabBtns[0].click();
  });

  btnDedupInput.addEventListener("click", () => {
    const lines = playersInput.value.split("\n");
    const seen = new Set();
    const deduped = [];
    for (const l of lines) {
      const trimmed = l.trim();
      if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith("//")) {
        deduped.push(l);
        continue;
      }
      const key = trimmed.toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        deduped.push(trimmed);
      }
    }
    playersInput.value = deduped.join("\n");
    countInputPlayers();
    showToast("Повторяющиеся строки удалены", "info");
  });

  btnClearInput.addEventListener("click", () => {
    playersInput.value = "";
    countInputPlayers();
    resultsSection.classList.add("hidden");
  });

  // 5. Chat Log Parser
  btnSampleChat.addEventListener("click", () => {
    chatLogInput.value = `[18:40:12] Hunk вошел в комнату
[18:40:15] mercyflower^-^ вошла в комнату
Комната #1 (16/16): BaobabBack, FallenAngel, LaFilozofo, blossoms., TheRedEyes, DIZEY, fantikkss, Zeranix, cucumber, Bun|dimebag, Pateti, Alex, pssy, NonExistentPlayer_999
[18:41:00] FallenAngel: начинаем матч!`;
  });

  btnExtractChat.addEventListener("click", async () => {
    const text = chatLogInput.value.trim();
    if (!text) {
      showToast("Вставьте текст чата для извлечения", "error");
      return;
    }
    try {
      const resp = await apiFetch("/api/parse-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await resp.json();
      if (data.players && data.players.length > 0) {
        playersInput.value = data.players.join("\n");
        countInputPlayers();
        tabBtns[0].click();
        showToast(`Извлечено ${data.players.length} участников`, "success");
      } else {
        showToast("Не удалось найти участников в тексте лога", "error");
      }
    } catch {
      showToast("Ошибка при обработке лога", "error");
    }
  });

  // 6. File Drop / Upload
  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      handleFile(fileInput.files[0]);
    }
  });

  btnRemoveFile.addEventListener("click", () => {
    fileInput.value = "";
    fileInfo.classList.add("hidden");
    dropZone.classList.remove("hidden");
  });

  function handleFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
      playersInput.value = e.target.result;
      countInputPlayers();
      tabBtns[0].click();
      showToast(`Файл "${file.name}" загружен`, "success");
    };
    reader.onerror = () => showToast("Ошибка чтения файла", "error");
    reader.readAsText(file, "UTF-8");

    fileName.textContent = file.name;
    fileInfo.classList.remove("hidden");
    dropZone.classList.add("hidden");
  }

  // 7. Calculate Match Ratings
  btnCalculate.addEventListener("click", () => calculateRatings(false));

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      calculateRatings(false);
    }
  });

  async function calculateRatings(isLive = false) {
    const rawText = playersInput.value.trim();
    if (!rawText) {
      if (!isLive) {
        showToast("Введите список участников матча (16 игроков)", "error");
        playersInput.focus();
      }
      return;
    }

    if (rankController) rankController.abort();
    rankController = new AbortController();
    const requestId = ++rankRequestId;
    const controller = rankController;
    const timeoutId = setTimeout(() => controller.abort(), 20000);
    document.getElementById("rank-status").textContent =
      "Рассчитываем рейтинг…";
    document.getElementById("results-empty").classList.add("hidden");
    if (!isLive) {
      btnCalculate.disabled = true;
      btnCalculate.innerHTML = "Обработка и расчет оценок...";
    }

    try {
      const resp = await apiFetch("/api/rank", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: rankController.signal,
        body: JSON.stringify({
          text: rawText,
          ranking_mode: selectRankingMode.value,
          ambiguous_strategy: selectStrategy.value,
          sort_order: currentSortOrder,
          is_live: isLive,
        }),
      });

      const data = await resp.json();
      if (requestId !== rankRequestId) return;
      if (!resp.ok || data.error) {
        throw new Error(data.error || "Ошибка расчета рейтинга");
      }

      currentMatchPlayers = data.players || data.match_players || [];
      document.getElementById("rank-status").textContent = "Рейтинг обновлён";
      const summary = data.summary || {};
      document.getElementById("metric-found").textContent = String(
        data.participant_count ??
          currentMatchPlayers.filter((p) =>
            ["matched", "unrated"].includes(p.status),
          ).length,
      );
      document.getElementById("metric-rated").textContent = String(
        currentMatchPlayers.filter((p) => p.status === "matched").length,
      );
      document.getElementById("metric-review").textContent = String(
        (summary.ambiguous_count || 0) +
          (summary.missing_count || 0) +
          (summary.duplicates_count || 0),
      );
      renderResults(data, !isLive);

      if (!isLive) {
        showToast(
          `Успешно рассчитано: ${currentMatchPlayers.length} участников`,
          "success",
        );
      }
      saveMatchToHistory(rawText, currentMatchPlayers.length);
    } catch (err) {
      if (requestId !== rankRequestId) return;
      document.getElementById("rank-status").textContent =
        err.name === "AbortError"
          ? "Расчёт отменён или время ожидания истекло"
          : err.message;
      if (!currentMatchPlayers.length)
        document.getElementById("results-empty").classList.remove("hidden");
      if (!isLive && err.name !== "AbortError") showToast(err.message, "error");
    } finally {
      clearTimeout(timeoutId);
      if (requestId === rankRequestId) {
        btnCalculate.disabled = false;
      }
      if (requestId === rankRequestId && !isLive) {
        btnCalculate.disabled = false;
        btnCalculate.innerHTML =
          'Рассчитать рейтинг матча <span class="btn-kbd-badge"><kbd>Ctrl</kbd>+<kbd>Enter</kbd></span>';
      }
    }
  }

  // 8. Render Results
  function renderResults(reportData, shouldScroll = true) {
    resultsSection.classList.remove("hidden");

    // Validation Banner
    const totalCount = currentMatchPlayers.length;
    const missingCount = currentMatchPlayers.filter(
      (p) => p.status === "missing",
    ).length;
    const unratedCount = currentMatchPlayers.filter(
      (p) => p.status === "unrated",
    ).length;

    let bannerHtml = "";
    const unresolvedCount = currentMatchPlayers.filter((p) =>
      ["ambiguous", "duplicate"].includes(p.status),
    ).length;
    if (reportData.is_16_match && unratedCount === 0 && unresolvedCount === 0) {
      bannerHtml = `<div class="banner-success">Идеальный матч: все 16 участников найдены в базе и имеют оценки.</div>`;
    } else {
      const notes = [];
      if (totalCount !== 16) {
        notes.push(`Введено участников: <strong>${totalCount}</strong> из 16.`);
      }
      if (missingCount > 0) {
        notes.push(`Не найдено в базе: <strong>${missingCount}</strong>.`);
      }
      if (unresolvedCount > 0)
        notes.push(`Требуют проверки: <strong>${unresolvedCount}</strong>.`);
      if (unratedCount > 0) {
        notes.push(`Без истории оценок: <strong>${unratedCount}</strong>.`);
      }
      bannerHtml = `<div class="banner-warning">Требует внимания: ${notes.join(" • ")} Все участники отображены в едином списке.</div>`;
    }

    validationBanner.className = `validation-banner ${reportData.is_16_match && unratedCount === 0 && unresolvedCount === 0 ? "state-success" : "state-warning"}`;
    validationBanner.innerHTML = bannerHtml;
    validationBanner.classList.remove("hidden");

    // Meta text
    const rated = currentMatchPlayers.filter(
      (p) => p.avg_rating !== null && p.status === "matched",
    );
    const avgScore =
      rated.length > 0
        ? (
            rated.reduce((acc, p) => acc + (p.avg_rating || 0), 0) /
            rated.length
          ).toFixed(2)
        : "-";
    resultsMeta.textContent = `Участников: ${totalCount} • Средний балл лобби: ${avgScore}`;

    // Apply sorting & render
    sortAndRenderList();

    // Scroll to results smoothly if not in live background mode
    if (shouldScroll) {
      resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // 9. Two-Way Sorting & Rendering
  btnSortDesc.addEventListener("click", () => {
    if (currentSortOrder === "desc") return;
    currentSortOrder = "desc";
    btnSortDesc.classList.add("active");
    btnSortAsc.classList.remove("active");
    sortAndRenderList();
  });

  btnSortAsc.addEventListener("click", () => {
    if (currentSortOrder === "asc") return;
    currentSortOrder = "asc";
    btnSortAsc.classList.add("active");
    btnSortDesc.classList.remove("active");
    sortAndRenderList();
  });

  selectRankingMode.addEventListener("change", () => {
    if (currentMatchPlayers.length > 0) {
      sortAndRenderList();
    }
  });

  function sortAndRenderList() {
    const isBayesian = selectRankingMode.value === "bayesian";

    // Partition rated vs unrated/missing
    const rated = currentMatchPlayers.filter(
      (p) =>
        p.status === "matched" &&
        (isBayesian
          ? p.bayesian_score !== null && p.bayesian_score !== undefined
          : p.avg_rating !== null && p.avg_rating !== undefined),
    );
    const unratedOrMissing = currentMatchPlayers.filter(
      (p) => !rated.includes(p),
    );

    if (currentSortOrder === "asc") {
      // Worst to best (ascending rating)
      rated.sort((a, b) => {
        const scoreA = isBayesian
          ? (a.bayesian_score ?? 999)
          : (a.avg_rating ?? 999);
        const scoreB = isBayesian
          ? (b.bayesian_score ?? 999)
          : (b.avg_rating ?? 999);
        if (scoreA !== scoreB) return scoreA - scoreB;
        if ((b.reviews_count || 0) !== (a.reviews_count || 0)) {
          return (b.reviews_count || 0) - (a.reviews_count || 0);
        }
        return (a.player_id || 0) - (b.player_id || 0);
      });
    } else {
      // Best to worst (descending rating)
      rated.sort((a, b) => {
        const scoreA = isBayesian
          ? (a.bayesian_score ?? -1)
          : (a.avg_rating ?? -1);
        const scoreB = isBayesian
          ? (b.bayesian_score ?? -1)
          : (b.avg_rating ?? -1);
        if (scoreB !== scoreA) return scoreB - scoreA;
        if ((b.reviews_count || 0) !== (a.reviews_count || 0)) {
          return (b.reviews_count || 0) - (a.reviews_count || 0);
        }
        return (a.player_id || 0) - (b.player_id || 0);
      });
    }

    const sortedCombined = [...rated, ...unratedOrMissing];

    // Renumber ranks 1..N
    sortedCombined.forEach((p, idx) => {
      p.rank = idx + 1;
    });

    currentMatchPlayers = sortedCombined;
    renderPlayerRows(currentMatchPlayers);
  }

  // 10. Filter Search
  let filterDebounceTimer = null;
  playerFilterInput.addEventListener("input", () => {
    const q = playerFilterInput.value.trim().toLowerCase();
    if (q) {
      btnClearFilter.classList.remove("hidden");
    } else {
      btnClearFilter.classList.add("hidden");
    }
    if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
    filterDebounceTimer = setTimeout(() => filterAndRender(q), 40);
  });

  btnClearFilter.addEventListener("click", () => {
    playerFilterInput.value = "";
    btnClearFilter.classList.add("hidden");
    filterAndRender("");
  });

  function filterAndRender(query) {
    if (!query) {
      sortAndRenderList();
      return;
    }
    const filtered = currentMatchPlayers.filter((p) => {
      const name = (p.name || "").toLowerCase();
      const input = (p.original_input || "").toLowerCase();
      const id = String(p.player_id || "");
      return (
        name.includes(query) || input.includes(query) || id.includes(query)
      );
    });
    renderPlayerRows(filtered);
  }

  // Delegated click listener for player rows (attached once)
  matchPlayersList.addEventListener("click", (e) => {
    const swapBtn = e.target.closest(".btn-swap-player");
    if (swapBtn) {
      e.stopPropagation();
      const pName = swapBtn.dataset.playerName;
      if (pName) openSwapModal(pName);
      return;
    }
    if (e.target.tagName === "A" || e.target.closest("a")) return;
    const row = e.target.closest(".player-row");
    if (!row) return;
    const pid = row.dataset.playerId;
    const name = row.dataset.playerName;
    if (pid) {
      openPlayerModal(pid, name);
    }
  });

  function renderPlayerRows(players) {
    if (players.length === 0) {
      matchPlayersList.innerHTML = `<div class="list-empty-state">Участники не найдены по запросу</div>`;
      return;
    }

    const rowsHtml = players
      .map((p) => {
        const rankClass =
          currentSortOrder === "desc"
            ? p.rank === 1
              ? "rank-1"
              : p.rank === 2
                ? "rank-2"
                : p.rank === 3
                  ? "rank-3"
                  : ""
            : p.rank === 1
              ? "rank-worst-1"
              : p.rank === 2
                ? "rank-worst-2"
                : p.rank === 3
                  ? "rank-worst-3"
                  : "";
        const isBayesian = selectRankingMode.value === "bayesian";
        const displayScore = isBayesian ? p.bayesian_score : p.avg_rating;

        let scoreBadgeClass = "score-none";
        let scoreText = "-";
        if (displayScore !== null && displayScore !== undefined) {
          scoreText = `Балл ${Number(displayScore).toFixed(2)}`;
          if (displayScore >= 4.5) scoreBadgeClass = "score-high";
          else if (displayScore >= 3.5) scoreBadgeClass = "score-medium";
          else if (displayScore >= 2.5) scoreBadgeClass = "score-low";
          else scoreBadgeClass = "score-danger";
        }

        let statusBadge = "";
        if (p.status === "unrated") {
          statusBadge = `<span class="player-status-badge badge-unrated">Нет оценок</span>`;
        } else if (p.status === "missing") {
          statusBadge = `<span class="player-status-badge badge-missing">Не найден</span>`;
        } else if (p.status === "ambiguous") {
          statusBadge = `<span class="player-status-badge badge-ambiguous">Нужна проверка</span>`;
        } else if (p.status === "duplicate") {
          statusBadge = `<span class="player-status-badge badge-duplicate">Повтор</span>`;
        } else {
          statusBadge = `<span class="player-status-badge badge-matched">В рейтинге</span>`;
        }

        const rawAvg =
          p.avg_rating !== null && p.avg_rating !== undefined
            ? Number(p.avg_rating).toFixed(2)
            : "-";
        const count = p.reviews_count || 0;
        const avatarSrc = p.avatar_url || DEFAULT_AVATAR_SVG;

        const profileLink = p.player_id
          ? `<a href="https://shinrireviews.com/p/${p.player_id}" target="_blank" rel="noopener noreferrer" class="player-name" title="Открыть профиль на сайте">${escapeHtml(p.name)}</a>`
          : `<span class="player-name">${escapeHtml(p.name)}</span>`;

        const idTag = p.player_id
          ? `<span class="player-id-tag">#${p.player_id}</span>`
          : "";
        const noteTag = p.note
          ? `<span class="player-note" title="${escapeHtml(p.note)}">${escapeHtml(p.note)}</span>`
          : "";

        return `
        <div class="player-row" data-player-id="${p.player_id || ""}" data-player-name="${escapeHtml(p.name)}">
          <div class="player-rank ${rankClass}">#${p.rank}</div>
          <div class="player-avatar-wrap">
            <img class="player-avatar-img" 
                 src="${escapeHtml(avatarSrc)}" 
                 alt="" 
                 loading="lazy" 
>
          </div>
          <div class="player-info-cell">
            <div class="player-name-wrap">
              ${profileLink}
              ${idTag}
              ${statusBadge}
              <button class="btn-swap-player" data-player-name="${escapeHtml(p.name)}" title="Заменить этого игрока другим">Заменить</button>
            </div>
            ${noteTag}
          </div>
          <div class="player-score-cell">
            <div class="score-badge ${scoreBadgeClass}">${scoreText}</div>
            <div class="score-meta">Ср: ${rawAvg} • Отзывов: ${count}</div>
          </div>
        </div>
      `;
      })
      .join("");

    matchPlayersList.innerHTML = rowsHtml;
  }

  // 11. Copy Match Roster
  btnCopyRoster.addEventListener("click", () => {
    if (currentMatchPlayers.length === 0) {
      showToast("Список игроков пуст", "error");
      return;
    }
    const lines = [
      `Состав матча DRO (16 игроков) - Shinri Reviews:`,
      `Порядок: ${currentSortOrder === "desc" ? "От лучших к худшим" : "От худших к лучшим"}\n`,
    ];

    currentMatchPlayers.forEach((p) => {
      const score =
        p.bayesian_score !== null ? `${p.bayesian_score.toFixed(2)}` : "-";
      const raw = p.avg_rating !== null ? `${p.avg_rating.toFixed(2)}` : "-";
      lines.push(
        `#${p.rank} ${p.name} — Рейтинг: ${score} (ср: ${raw}, отзывов: ${p.reviews_count || 0})`,
      );
    });

    navigator.clipboard
      .writeText(lines.join("\n"))
      .then(() => {
        showToast("Список матча скопирован в буфер обмена!", "success");
      })
      .catch(() => {
        showToast("Не удалось скопировать в буфер", "error");
      });
  });

  // 12. Player Details Modal
  async function openPlayerModal(playerId, playerName) {
    modalPlayerName.textContent = playerName || `Игрок #${playerId}`;
    modalPlayerId.textContent = `ID: ${playerId}`;
    modalAvatar.classList.remove("avatar-failed");
    modalAvatar.src = DEFAULT_AVATAR_SVG;
    modalPlayerBody.innerHTML = `<div class="loading-spinner">Загрузка отзывов игрока #${playerId}...</div>`;
    playerModal.classList.remove("hidden");

    try {
      const resp = await apiFetch(`/api/player-details?id=${playerId}`);
      const data = await resp.json();
      if (!resp.ok || data.error) {
        throw new Error(data.error || "Не удалось загрузить отзывы");
      }

      if (data.player && data.player.avatar_url) {
        modalAvatar.classList.remove("avatar-failed");
        modalAvatar.src = data.player.avatar_url;
      }

      if (data.details?.available === false) {
        modalPlayerBody.textContent =
          data.details.message || "Отзывы временно недоступны";
        return;
      }
      const reviews = (data.details && data.details.reviews) || [];
      if (reviews.length === 0) {
        modalPlayerBody.innerHTML = `<p class="modal-desc">Для этого игрока пока нет текстовых отзывов на сайте.</p>`;
        return;
      }

      const revHtml = reviews
        .slice(0, 10)
        .map(
          (r) => `
        <div class="review-item">
          <div class="review-header">
            <span class="review-author">${escapeHtml(r.author || "Аноним")} ${r.verified ? "· подтверждён" : ""}</span>
            <span class="review-stars">Оценка: ${r.rating || 5}</span>
          </div>
          <div class="review-text">${escapeHtml(r.text || "")}</div>
        </div>
      `,
        )
        .join("");

      modalPlayerBody.innerHTML = `
        <div class="modal-desc">Отзывы сообщества (${reviews.length}):</div>
        ${revHtml}
      `;
    } catch (err) {
      modalPlayerBody.innerHTML = `<div class="text-danger">Ошибка: ${escapeHtml(err.message)}</div>`;
    }
  }

  btnClosePlayerModal.addEventListener("click", () =>
    playerModal.classList.add("hidden"),
  );
  playerModal.addEventListener("click", (e) => {
    if (e.target === playerModal) playerModal.classList.add("hidden");
  });

  // 13. Refresh & Import Database
  btnRefreshDb.addEventListener("click", async () => {
    btnRefreshDb.disabled = true;
    statusText.textContent = "Обновление базы...";
    try {
      const resp = await apiFetch("/api/refresh", { method: "POST" });
      const data = await resp.json();
      if (data.status === "ok") {
        showToast(
          `База обновлена! Всего игроков: ${data.total_players}`,
          "success",
        );
        fetchStatus();
      } else {
        showToast(data.error || "Ошибка обновления", "error");
      }
    } catch {
      showToast("Сервер не ответил на запрос обновления", "error");
    } finally {
      btnRefreshDb.disabled = false;
    }
  });

  btnImportDb.addEventListener("click", () =>
    importModal.classList.remove("hidden"),
  );
  btnCloseModal.addEventListener("click", () =>
    importModal.classList.add("hidden"),
  );
  importModal.addEventListener("click", (e) => {
    if (e.target === importModal) importModal.classList.add("hidden");
  });

  btnSubmitImport.addEventListener("click", () => {
    if (!importFileInput.files.length) {
      showToast("Выберите JSON-файл для импорта", "error");
      return;
    }
    const reader = new FileReader();
    reader.onload = async (e) => {
      try {
        const resp = await apiFetch("/api/import-cache", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ data: e.target.result }),
        });
        const data = await resp.json();
        if (data.status === "ok") {
          showToast(
            `Успешно импортировано ${data.imported_count} игроков`,
            "success",
          );
          importModal.classList.add("hidden");
          fetchStatus();
        } else {
          showToast(data.error || "Ошибка импорта", "error");
        }
      } catch {
        showToast("Сбой при отправке данных на сервер", "error");
      }
    };
    reader.readAsText(importFileInput.files[0], "UTF-8");
  });

  // 14. Match History
  const matchHistoryBar = document.getElementById("match-history-bar");
  const historyPills = document.getElementById("history-pills");
  const btnClearHistory = document.getElementById("btn-clear-history");

  function saveMatchToHistory(rawText, count) {
    if (!rawText || count < 2) return;
    try {
      const history = JSON.parse(
        localStorage.getItem("shinri_match_history") || "[]",
      );
      const trimmed = rawText.trim();
      const filtered = history.filter((h) => h.text.trim() !== trimmed);
      const timeStr = new Date().toLocaleTimeString("ru-RU", {
        hour: "2-digit",
        minute: "2-digit",
      });
      filtered.unshift({
        text: trimmed,
        count: count,
        time: timeStr,
      });
      localStorage.setItem(
        "shinri_match_history",
        JSON.stringify(filtered.slice(0, 8)),
      );
      renderMatchHistory();
    } catch {}
  }

  function renderMatchHistory() {
    if (!matchHistoryBar || !historyPills) return;
    try {
      const history = JSON.parse(
        localStorage.getItem("shinri_match_history") || "[]",
      );
      if (history.length === 0) {
        matchHistoryBar.classList.add("hidden");
        return;
      }
      matchHistoryBar.classList.remove("hidden");
      historyPills.innerHTML = history
        .map(
          (h, idx) => `
        <button class="history-pill" data-history-idx="${idx}" title="${escapeHtml(h.time)} (${Number(h.count) || 0} игроков)">
          ${escapeHtml(h.time)} (${Number(h.count) || 0} игр.)
        </button>
      `,
        )
        .join("");
    } catch {
      matchHistoryBar.classList.add("hidden");
    }
  }

  if (historyPills) {
    historyPills.addEventListener("click", (e) => {
      const pill = e.target.closest(".history-pill");
      if (!pill) return;
      const idx = Number(pill.dataset.historyIdx);
      try {
        const history = JSON.parse(
          localStorage.getItem("shinri_match_history") || "[]",
        );
        if (history[idx]) {
          playersInput.value = history[idx].text;
          countInputPlayers();
          calculateRatings(false);
          showToast(`Загружен матч из истории (${history[idx].time})`, "info");
        }
      } catch {}
    });
  }

  if (btnClearHistory) {
    btnClearHistory.addEventListener("click", () => {
      localStorage.removeItem("shinri_match_history");
      renderMatchHistory();
      showToast("История матчей очищена", "info");
    });
  }

  // Initial history render
  renderMatchHistory();

  // 15. Quick Swap Player Modal
  let playerToSwapName = "";
  const swapModal = document.getElementById("swap-modal");
  const btnCloseSwapModal = document.getElementById("btn-close-swap-modal");
  const btnCancelSwap = document.getElementById("btn-cancel-swap");
  const btnConfirmSwap = document.getElementById("btn-confirm-swap");
  const swapNewPlayerInput = document.getElementById("swap-new-player-input");
  const swapModalDesc = document.getElementById("swap-modal-desc");

  function openSwapModal(playerName) {
    playerToSwapName = playerName;
    if (swapModalDesc) {
      swapModalDesc.innerHTML = `Заменить игрока <strong>${escapeHtml(playerName)}</strong> в текущем составе:`;
    }
    if (swapNewPlayerInput) {
      swapNewPlayerInput.value = "";
    }
    if (swapModal) {
      swapModal.classList.remove("hidden");
      setTimeout(() => swapNewPlayerInput && swapNewPlayerInput.focus(), 60);
    }
  }

  function closeSwapModal() {
    if (swapModal) swapModal.classList.add("hidden");
    playerToSwapName = "";
  }

  if (btnConfirmSwap) {
    btnConfirmSwap.addEventListener("click", () => {
      const newName = swapNewPlayerInput ? swapNewPlayerInput.value.trim() : "";
      if (!newName) {
        showToast("Введите никнейм или ID нового игрока", "warning");
        return;
      }
      const lines = playersInput.value.split("\n");
      let replaced = false;
      const newLines = lines.map((line) => {
        if (
          !replaced &&
          line.trim().toLowerCase() === playerToSwapName.toLowerCase()
        ) {
          replaced = true;
          return newName;
        }
        return line;
      });
      if (!replaced) {
        newLines.push(newName);
      }
      playersInput.value = newLines.join("\n");
      countInputPlayers();
      closeSwapModal();
      calculateRatings(false);
      showToast(`Заменен игрок: ${playerToSwapName} → ${newName}`, "success");
    });
  }

  if (swapNewPlayerInput) {
    swapNewPlayerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        btnConfirmSwap.click();
      } else if (e.key === "Escape") {
        closeSwapModal();
      }
    });
  }

  if (btnCloseSwapModal)
    btnCloseSwapModal.addEventListener("click", closeSwapModal);
  if (btnCancelSwap) btnCancelSwap.addEventListener("click", closeSwapModal);
  if (swapModal) {
    swapModal.addEventListener("click", (e) => {
      if (e.target === swapModal) closeSwapModal();
    });
  }

  // Dialogs retain keyboard focus and restore it on close.
  const dialogs = [...document.querySelectorAll(".modal-overlay")];
  let previousFocus = null;
  dialogs.forEach((dialog) =>
    new MutationObserver(() => {
      if (!dialog.classList.contains("hidden")) {
        previousFocus = document.activeElement;
        dialog.querySelector("input, button, [tabindex]")?.focus();
      } else if (previousFocus instanceof HTMLElement) previousFocus.focus();
    }).observe(dialog, { attributes: true, attributeFilter: ["class"] }),
  );
  document.addEventListener("keydown", (event) => {
    const dialog = dialogs.find((d) => !d.classList.contains("hidden"));
    if (!dialog) return;
    if (event.key === "Escape") dialog.classList.add("hidden");
    if (event.key !== "Tab") return;
    const focusable = [
      ...dialog.querySelectorAll(
        'button, input, select, a[href], [tabindex="0"]',
      ),
    ].filter((e) => !e.disabled);
    const first = focusable[0],
      last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
  [dropZone, ocrDropZone].forEach((zone) => {
    zone.tabIndex = 0;
    zone.setAttribute("role", "button");
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        zone.click();
      }
    });
  });
  // 16. Toast Helpers
  function showToast(message, type = "info") {
    if (type === "danger") type = "error";
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.replaceChildren(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(10px)";
      toast.style.transition = "all 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});
