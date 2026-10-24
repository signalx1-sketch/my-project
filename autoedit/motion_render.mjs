// 모션 그래픽 카드(HTML)를 프레임 단위로 찍어서 mp4로 만든다.
// 사용법: node motion_render.mjs jobs.json
// jobs.json: [{"html": "카드.html", "out": "카드.mp4", "seconds": 1.8, "fps": 30}, ...]
// 각 HTML은 window.seek(t)를 제공해야 한다 (t초 시점의 화면으로 맞춘다).
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

for (const job of jobs) {
  await page.goto(pathToFileURL(job.html).href);
  await page.evaluate(() => document.fonts.ready);
  const fps = job.fps || 30;
  const frames = Math.round(job.seconds * fps);
  const ff = spawn("ffmpeg", ["-v", "error", "-y", "-f", "image2pipe", "-framerate", String(fps), "-c:v", "png",
    "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", job.out],
    { stdio: ["pipe", "inherit", "inherit"] });
  for (let f = 0; f < frames; f++) {
    await page.evaluate((t) => window.seek(t), f / fps);
    const png = await page.screenshot({ type: "png" });
    if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once("drain", r));
  }
  ff.stdin.end();
  await new Promise((r, j) => ff.on("close", (c) => (c === 0 ? r() : j(new Error(`ffmpeg ${c}`)))));
  process.stdout.write(`.`);
}
await browser.close();
process.stdout.write("\n");
