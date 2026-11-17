import { CELL, makeSpriteSheet, POSES } from "./sprites";

type Behavior = keyof typeof POSES;
const runningSpeed = 102;
const jumpDuration = .66;
const interval = 1000 / 24;

export function mountArtemis(canvas: HTMLCanvasElement, host: HTMLElement, reduced: boolean) {
  if (typeof ResizeObserver === "undefined") return;
  const ctx = canvas.getContext("2d");
  const atlas = makeSpriteSheet();
  if (!ctx || !atlas) return;

  ctx.imageSmoothingEnabled = false;
  const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let limit = 0;
  let x = 0;
  let direction: 1 | -1 = 1;
  let behavior: Behavior = "run";
  let elapsed = 0;
  let duration = 1.4;
  let previous = 0;
  let request = 0;
  let lastFrame = -1;
  let lastDirection = 0;

  function draw(mode: Behavior, face: number) {
    const index = POSES[mode] + (
      mode === "run" ? Math.floor(elapsed * 11) % 4
      : mode === "wave" ? Math.floor(elapsed * 5) % 2 : 0
    );
    if (ctx && atlas && (index !== lastFrame || face !== lastDirection)) {
      ctx.clearRect(0, 0, CELL, CELL);
      ctx.save();
      ctx.translate(face === -1 ? CELL : 0, 0);
      ctx.scale(face, 1);
      ctx.drawImage(atlas, index * CELL, 0, CELL, CELL, 0, 0, CELL, CELL);
      ctx.restore();
      lastFrame = index;
      lastDirection = face;
    }
    const offset = mode === "jump" ? Math.sin(Math.PI * elapsed / jumpDuration) * 27 : 0;
    canvas.style.transform = `translate(${Math.round(x)}px, ${-Math.round(offset)}px)`;
  }

  function chooseNext() {
    const choice = Math.random();
    behavior = behavior === "run"
      ? choice < .49 ? "jump" : choice < .91 ? "wave" : "idle"
      : "run";
    duration = behavior === "run" ? 1.3 + Math.random() * 2.3
      : behavior === "jump" ? jumpDuration : behavior === "wave" ? 1.15 : .55;
    elapsed = 0;
  }

  function step(now: number) {
    if (!previous) previous = now;
    const delta = now - previous;
    if (delta >= interval) {
      const remainder = delta % interval;
      const dt = Math.min((delta - remainder) / 1000, .075);
      previous = now - remainder;
      elapsed += dt;
      if (elapsed >= duration) chooseNext();
      if (behavior === "run" || behavior === "jump") {
        x += direction * runningSpeed * (behavior === "jump" ? .7 : 1) * dt;
        if (x <= 0 || x >= limit) {
          direction = x <= 0 ? 1 : -1;
          x = Math.min(limit, Math.max(0, x));
          elapsed = 0;
          behavior = "wave";
          duration = 1.15;
        }
      }
      draw(behavior, direction);
    }
    request = requestAnimationFrame(step);
  }

  function syncMotion() {
    cancelAnimationFrame(request);
    previous = 0;
    if (reduced || motion?.matches) {
      x = limit;
      draw("idle", -1);
    } else if (!document.hidden && limit > 0) {
      request = requestAnimationFrame(step);
    }
  }

  const observer = new ResizeObserver(() => {
    limit = Math.max(0, host.clientWidth - canvas.clientWidth);
    x = Math.min(x, limit);
    draw(behavior, direction);
    syncMotion();
  });
  observer.observe(host);
  motion?.addEventListener("change", syncMotion);
  document.addEventListener("visibilitychange", syncMotion);
  return () => {
    observer.disconnect();
    motion?.removeEventListener("change", syncMotion);
    document.removeEventListener("visibilitychange", syncMotion);
    cancelAnimationFrame(request);
  };
}
