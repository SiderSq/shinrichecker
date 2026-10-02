/* Tests the real local server; OCR output below is a mocked engine contract. */
const { chromium } = require("playwright");
const { spawn } = require("node:child_process");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const project = path.join(__dirname, "..");
const output = process.env.SHINRI_QA_DIR;
const failures = [];
// Digits, # IDs, punctuation and user-supplied nicknames must remain intact.
const authoredSymbols =
  /[\p{Extended_Pictographic}\p{Emoji_Presentation}\uFE0F★✓⇄◎◐●]/u;
for (const relative of [
  "main.py",
  "shinri_ranker/cli.py",
  "shinri_ranker/analytics.py",
  "shinri_ranker/matcher.py",
  "shinri_ranker/exporter.py",
  "shinri_ranker/static/index.html",
  "shinri_ranker/static/app.js",
]) {
  assert.doesNotMatch(
    fs.readFileSync(path.join(project, relative), "utf8"),
    authoredSymbols,
    relative,
  );
}
async function assertUiText(page) {
  const text = await page.evaluate(() =>
    [
      document.body.innerText,
      ...Array.from(
        document.querySelectorAll("[title], [placeholder], [aria-label]"),
        (e) =>
          [
            e.title,
            e.getAttribute("placeholder"),
            e.getAttribute("aria-label"),
          ].join(" "),
      ),
    ].join("\n"),
  );
  assert.doesNotMatch(text, authoredSymbols, "Authored interface symbols");
}
async function snapshot(page, name) {
  await assertUiText(page);
  if (!output) return;
  fs.mkdirSync(output, { recursive: true });
  const avatar =
    "data:image/svg+xml;charset=utf-8," +
    encodeURIComponent(
      fs.readFileSync(
        path.join(project, "shinri_ranker/static/default_avatar.svg"),
        "utf8",
      ),
    );
  const css = fs
    .readFileSync(path.join(project, "shinri_ranker/static/style.css"), "utf8")
    .replace(
      /url\(["']?\/static\/default_avatar.svg["']?\)/g,
      `url("${avatar}")`,
    );
  await page.evaluate(() => {
    document.querySelectorAll(".toast").forEach((e) => e.remove());
    document
      .querySelectorAll("textarea")
      .forEach((e) => (e.textContent = e.value));
    document.querySelectorAll("input").forEach((e) => {
      e.setAttribute("value", e.value);
      if (["checkbox", "radio"].includes(e.type))
        e.toggleAttribute("checked", e.checked);
    });
    document
      .querySelectorAll("select option")
      .forEach((e) => e.toggleAttribute("selected", e.selected));
  });
  let html = await page.content();
  html = html
    .replace(/<link rel="stylesheet"[^>]+>/, `<style>${css}</style>`)
    .replace(/<script src="\/static\/app.js"><\/script>/, "")
    .replace(/<link rel="icon"[^>]+>/, "")
    .replace(
      /src="(?:https:\/\/shinrireviews.com[^" ]*|\/default_avatar.svg|)"/g,
      `src="${avatar}"`,
    );
  fs.writeFileSync(path.join(output, `${name}.html`), html);
  await page.screenshot({
    path: path.join(output, `${name}.png`),
    fullPage: true,
  });
}

(async () => {
  const server = spawn(
    process.env.PYTHON || "python",
    [path.join(__dirname, "ui_fixture.py")],
    { cwd: project },
  );
  let browser;
  try {
    const url = await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error("Fixture startup timeout")),
        10000,
      );
      server.once("error", reject);
      server.once("exit", (code) =>
        reject(new Error(`Fixture exited ${code}`)),
      );
      server.stdout.once("data", (data) => {
        clearTimeout(timeout);
        resolve(data.toString().trim());
      });
      server.stderr.on("data", (data) => process.stderr.write(data));
    });
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CHROMIUM_PATH
        ? { executablePath: process.env.CHROMIUM_PATH }
        : {}),
    });
    const page = await browser.newPage({
      viewport: { width: 1280, height: 960 },
    });
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "clipboard", {
        value: {
          writeText: async (text) => {
            window.__copiedText = text;
          },
        },
        configurable: true,
      });
    });
    page.on("pageerror", (error) => failures.push(error.message));
    await page.route("https://shinrireviews.com/**", (route) => route.abort());
    await page.goto(url);
    await page.waitForSelector(".status-badge.ready");
    assert.match(await page.locator("#status-text").innerText(), /16 игроков/);
    await page
      .locator("#players-input")
      .fill(Array.from({ length: 16 }, (_, i) => `#${i + 1}`).join("\n"));
    await page.waitForSelector(".player-row");
    assert.equal(await page.locator(".player-row").count(), 16);
    assert.match(
      await page.locator("#validation-banner").innerText(),
      /Идеальный матч/,
    );
    assert.equal(await page.locator("#metric-found").innerText(), "16");
    await page.locator("#btn-copy-roster").click();
    await page.waitForFunction(() => window.__copiedText?.includes("Hunk"));
    assert.doesNotMatch(
      await page.evaluate(() => window.__copiedText),
      authoredSymbols,
    );
    assert.match(
      await page.locator(".score-badge").first().innerText(),
      /Балл 4\.65/,
    );
    await assertUiText(page);
    // Theme, sort, filter and modal keyboard controls.
    await page.locator("#btn-theme").click();
    await page.locator("#btn-sort-asc").click();
    await page.locator("#player-filter-input").fill("Hunk");
    await page.waitForFunction(
      () => document.querySelectorAll(".player-row").length === 1,
    );
    await page.locator(".player-row").click();
    await page.waitForSelector("#player-modal:not(.hidden)");
    await page.waitForFunction(() =>
      document
        .querySelector("#modal-player-body")
        .textContent.includes("оффлайн"),
    );
    await snapshot(page, "modal-desktop");
    await page.keyboard.press("Escape");
    // Actual review layout uses a textual rating, not a star.
    await page.route("**/api/player-details?*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          details: {
            available: true,
            reviews: [
              {
                author: "Reviewer",
                rating: 4,
                text: "Тестовый отзыв",
                verified: true,
              },
            ],
          },
        }),
      }),
    );
    await page.locator(".player-row").click();
    await page.waitForSelector(".review-stars");
    assert.equal(await page.locator(".review-stars").innerText(), "Оценка: 4");
    await assertUiText(page);
    await page.keyboard.press("Escape");
    await page.unroute("**/api/player-details?*");
    await page.locator(".btn-swap-player").click();
    await page.waitForSelector("#swap-modal:not(.hidden)");
    assert.match(
      await page.locator("#swap-title").innerText(),
      /Быстрая замена/,
    );
    await assertUiText(page);
    await page.locator("#btn-cancel-swap").click();
    assert.ok(
      await page
        .locator("#swap-modal")
        .evaluate((e) => e.classList.contains("hidden")),
    );

    await page.locator("#btn-clear-filter").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".player-row").length === 16,
    );
    // Duplicate rows cannot pass readiness.
    await page.locator("#check-live-eval").uncheck();
    await page.locator("#players-input").fill(Array(16).fill("#1").join("\n"));
    await page.locator("#btn-calculate").click();
    await page.waitForFunction(
      () => document.querySelector("#metric-found").textContent === "1",
    );
    assert.doesNotMatch(
      await page.locator("#validation-banner").innerText(),
      /Идеальный матч/,
    );
    // Slow old responses must not overwrite a newer request.
    let count = 0;
    await page.route("**/api/rank", async (route) => {
      const body = route.request().postDataJSON();
      if (count++ === 0) {
        await new Promise((resolve) => setTimeout(resolve, 400));
        try {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              players: [
                {
                  name: "STALE",
                  rank: 1,
                  status: "missing",
                  avg_rating: null,
                  bayesian_score: null,
                },
              ],
              summary: {},
            }),
          });
        } catch {}
      } else await route.continue();
    });
    await page.locator("#players-input").fill("#1");
    await page.locator("#btn-calculate").click();
    await page.locator("#players-input").fill("#2");
    await page.keyboard.press("Control+Enter");
    await page.waitForFunction(
      () =>
        document.querySelector(".player-name")?.textContent ===
        "mercyflower^-^",
    );
    await page.waitForTimeout(500);
    assert.equal(
      await page.locator(".player-name").innerText(),
      "mercyflower^-^",
    );
    await page.unroute("**/api/rank");
    // OCR weak match requires explicit confirmation and forwards a stable ID.
    let latestOcrRequest;
    let ocrRequests = 0;
    await page.route("**/api/ocr-process", (route) => {
      latestOcrRequest = route.request().postDataJSON();
      ocrRequests += 1;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          engine: "windows_native",
          cache_hit: ocrRequests > 1,
          raw_ocr: "Hunck",
          candidates: [
            {
              raw_ocr: "Hunck",
              matched_name: "Hunk",
              player_id: 1,
              similarity: 0.75,
              corrected: true,
              needs_review: true,
              review_reason: "Проверьте исправление OCR",
              alternatives: [{ id: 1, name: "Hunk", similarity: 0.75 }],
            },
          ],
        }),
      });
    });
    await page.locator("#tab-btn-ocr").click();
    const png = Buffer.from(
      "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",
      "base64",
    );
    await page.locator("#ocr-file-input").setInputFiles({
      name: "fixture.png",
      mimeType: "image/png",
      buffer: png,
    });
    await page.waitForSelector(".chip-review");
    assert.equal(
      await page.locator(".chip-status-label").innerText(),
      "Требует проверки",
    );
    await snapshot(page, "ocr-review-desktop");
    await page.setViewportSize({ width: 390, height: 960 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    await snapshot(page, "ocr-review-mobile");
    await page.setViewportSize({ width: 1280, height: 960 });
    assert.equal(await page.locator("#players-input").inputValue(), "");
    await page
      .locator(".chip-review button", { hasText: "Подтвердить" })
      .click();
    assert.equal(await page.locator("#players-input").inputValue(), "#1");
    assert.equal(
      await page.locator(".chip-status-label").innerText(),
      "Подтверждено",
    );
    await page.locator("#btn-ocr-calc-now").click();
    await page.waitForFunction(
      () => document.querySelector(".player-name")?.textContent === "Hunk",
    );
    // Optional ROI: keyboard coordinates, pointer selection and invalid bounds.
    await page.locator("#tab-btn-ocr").click();
    await page.locator("#ocr-select-region-first").check();
    const callsBeforeStaging = ocrRequests;
    await page
      .locator("#ocr-file-input")
      .setInputFiles({ name: "roi.png", mimeType: "image/png", buffer: png });
    await page.waitForFunction(() =>
      document
        .querySelector("#ocr-status-text")
        .textContent.includes("OCR ещё не запускался"),
    );
    assert.equal(
      ocrRequests,
      callsBeforeStaging,
      "Region-first must not scan the whole image",
    );
    assert.ok(await page.locator("#ocr-use-region").isChecked());
    for (const [id, value] of [
      ["x", "10"],
      ["y", "20"],
      ["width", "60"],
      ["height", "50"],
    ]) {
      await page.locator(`#roi-${id}`).fill(value);
    }
    await page.locator("#btn-ocr-region-run").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#ocr-engine-badge")
        .textContent.includes("из кэша"),
    );
    assert.deepEqual(latestOcrRequest.roi, {
      x: 0.1,
      y: 0.2,
      width: 0.6,
      height: 0.5,
    });
    assert.equal(
      await page.locator("#ocr-image-size").innerText(),
      "720×440 px",
    );
    assert.ok(await page.locator("#ocr-region-selection").isVisible());
    await snapshot(page, "ocr-region-desktop");
    await page.setViewportSize({ width: 390, height: 960 });
    await snapshot(page, "ocr-region-mobile");
    await page.locator("#ocr-preview-img").scrollIntoViewIfNeeded();
    const box = await page.locator("#ocr-preview-img").boundingBox();
    await page.mouse.move(box.x + box.width * 0.1, box.y + box.height * 0.2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.8, {
      steps: 5,
    });
    await page.mouse.up();
    assert.ok(
      Math.abs(Number(await page.locator("#roi-width").inputValue()) - 60) <
        0.2,
    );
    assert.ok(
      Math.abs(Number(await page.locator("#roi-height").inputValue()) - 60) <
        0.2,
      "Pointer drag must change the prior 50% height",
    );
    await page.setViewportSize({ width: 1280, height: 960 });
    await page.locator("#roi-x").fill("90");
    const countBeforeInvalid = ocrRequests;
    await page.locator("#btn-ocr-region-run").click();
    assert.equal(ocrRequests, countBeforeInvalid);
    await page.locator("#ocr-use-region").uncheck();
    const fullImageRequest = page.waitForRequest("**/api/ocr-process");
    const fullImageResponse = page.waitForResponse("**/api/ocr-process");
    await page.locator("#btn-ocr-region-run").click();
    assert.equal((await fullImageRequest).postDataJSON().roi, null);
    await fullImageResponse;
    await page.waitForFunction(
      () =>
        !document
          .querySelector("#ocr-results-summary")
          .classList.contains("hidden"),
    );
    await page.unroute("**/api/ocr-process");
    await page.locator("#ocr-select-region-first").uncheck();
    // Real missing-engine error is readable and the spinner stops.
    await page.locator("#tab-btn-ocr").click();
    await page.locator("#btn-clear-ocr").click();
    await page.route("**/api/ocr-process", (route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: "OCR-движок не установлен. Введите ники вручную.",
        }),
      }),
    );
    await page
      .locator("#ocr-file-input")
      .setInputFiles({ name: "error.png", mimeType: "image/png", buffer: png });
    await page.waitForFunction(() =>
      document
        .querySelector("#ocr-status-text")
        .textContent.includes("не установлен"),
    );
    assert.ok(
      await page
        .locator("#ocr-spinner")
        .evaluate((e) => e.classList.contains("hidden")),
    );
    await snapshot(page, "ocr-error-desktop");
    await page.unroute("**/api/ocr-process");
    // Removing authored emoji must not remove emoji supplied by the user.
    await page.locator('[data-tab="tab-text"]').click();
    const suppliedName = "Player" + String.fromCodePoint(0x1f600) + "^-^";
    await page.locator("#players-input").fill(suppliedName);
    assert.equal(
      await page.locator("#players-input").inputValue(),
      suppliedName,
    );
    await page.close();
    // Snapshot the actual rendered states for visual inspection.
    for (const width of [1280, 390]) {
      const preview = await browser.newPage({
        viewport: { width, height: 960 },
      });
      preview.on("pageerror", (e) => failures.push(e.message));
      await preview.route("https://shinrireviews.com/**", (route) =>
        route.abort(),
      );
      await preview.goto(url);
      await preview.waitForSelector(".status-badge.ready");
      for (const theme of ["light", "dark"]) {
        await preview.evaluate((theme) => {
          document.documentElement.dataset.theme = theme;
          document.querySelector("#btn-theme").textContent =
            theme === "dark" ? "Светлая тема" : "Тёмная тема";
        }, theme);
        await preview.evaluate(() =>
          document.querySelectorAll(".toast").forEach((e) => e.remove()),
        );
        assert.ok(
          await preview.evaluate(
            () => document.documentElement.scrollWidth <= window.innerWidth,
          ),
          `Overflow ${width} ${theme}`,
        );
        await snapshot(preview, `empty-${width}-${theme}`);
      }
      await preview.locator("#check-live-eval").uncheck();
      await preview
        .locator("#players-input")
        .fill(Array.from({ length: 16 }, (_, i) => `#${i + 1}`).join("\n"));
      await preview
        .locator(width === 390 ? "#btn-mobile-calculate" : "#btn-calculate")
        .click();
      await preview.waitForSelector(".player-row");
      assert.ok(
        await preview.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth,
        ),
        `Result overflow ${width}`,
      );
      await preview.evaluate(() =>
        document.querySelectorAll(".toast").forEach((e) => e.remove()),
      );
      await snapshot(preview, `results-${width}`);
      assert.equal(
        await preview.locator("#input-settings").getAttribute("open"),
        null,
      );
      await preview.locator("#input-settings > summary").click();
      assert.ok(await preview.locator("#select-ranking-mode").isVisible());
      await snapshot(preview, `settings-expanded-${width}`);
      await preview.locator("#input-settings > summary").click();
      const originalHeight = (
        await preview.locator(".player-row").first().boundingBox()
      ).height;
      await preview.locator("#select-density").selectOption("compact");
      const compactHeight = (
        await preview.locator(".player-row").first().boundingBox()
      ).height;
      assert.ok(
        compactHeight < originalHeight,
        "Compact rows should be shorter",
      );
      assert.equal(await preview.locator(".player-row").count(), 16);
      assert.equal(await preview.locator(".score-meta").count(), 16);
      await snapshot(preview, `results-compact-${width}`);
      await preview.reload();
      assert.equal(
        await preview.locator("#select-density").inputValue(),
        "compact",
      );
      await preview.locator("#check-live-eval").uncheck();
      await preview.locator("#players-input").fill("#1\nDefinitelyNotAPlayer");
      await preview
        .locator(width === 390 ? "#btn-mobile-calculate" : "#btn-calculate")
        .click();
      await preview.waitForSelector(".review-section-title");
      assert.match(
        await preview.locator(".review-section-title").innerText(),
        /Требуют проверки · 1/,
      );
      assert.equal(await preview.locator(".player-row").count(), 2);
      assert.equal(
        await preview.locator(".player-name").first().innerText(),
        "DefinitelyNotAPlayer",
      );
      assert.equal(
        await preview.locator(".player-rank").first().innerText(),
        "#2",
      );
      assert.equal(await preview.locator("#metric-found").innerText(), "1");
      await snapshot(preview, `attention-${width}`);
      if (width === 390) {
        await preview.evaluate(() =>
          window.scrollTo(0, document.body.scrollHeight),
        );
        const bar = await preview.locator("#mobile-action-bar").boundingBox();
        assert.ok(bar && Math.abs(bar.y + bar.height - 960) < 1);
        await preview.locator('.player-row[data-player-id="1"]').click();
        assert.ok(await preview.locator("#mobile-action-bar").isHidden());
        await preview.keyboard.press("Escape");
        assert.ok(await preview.locator("#mobile-action-bar").isVisible());
      }
      await preview.close();
    }
    assert.deepEqual(failures, [], "Browser runtime errors");
    console.log(
      "UI checks passed: live IDs, duplicate validation, theme/sort/search/modal, stale responses, OCR confirmation, OCR errors, desktop/mobile overflow, emoji-free authored labels and unchanged user text, ROI coordinates/drag/bounds, compact view persistence, attention grouping, mobile fixed actions.",
    );
  } finally {
    if (browser) await browser.close();
    server.kill("SIGTERM");
  }
})()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
