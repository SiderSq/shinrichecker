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
    document
      .querySelectorAll("input")
      .forEach((e) => e.setAttribute("value", e.value));
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
    await page.route("**/api/ocr-process", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          engine: "windows_native",
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
      }),
    );
    await page.locator("#tab-btn-ocr").click();
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6QlsAAAAASUVORK5CYII=",
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
    await page.unroute("**/api/ocr-process");
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
      await preview.locator("#btn-calculate").click();
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
      await preview.close();
    }
    assert.deepEqual(failures, [], "Browser runtime errors");
    console.log(
      "UI checks passed: live IDs, duplicate validation, theme/sort/search/modal, stale responses, OCR confirmation, OCR errors, desktop/mobile overflow, emoji-free authored labels and unchanged user text.",
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
