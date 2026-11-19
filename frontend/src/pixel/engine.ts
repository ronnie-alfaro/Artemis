import { CELL, makeDeerSheet, makeSpriteSheet, POSES } from "./sprites";

type Behavior = keyof typeof POSES;
const runningSpeed = 102;
const jumpDuration = .66;
const interval = 1000 / 24;

function drawFrame(context: CanvasRenderingContext2D, atlas: HTMLCanvasElement, frame: number, face: number) {
  context.clearRect(0, 0, CELL, CELL);
  context.save();
  context.translate(face === -1 ? CELL : 0, 0);
  context.scale(face, 1);
  context.drawImage(atlas, frame * CELL, 0, CELL, CELL, 0, 0, CELL, CELL);
  context.restore();
}

export function mountArtemis(canvas: HTMLCanvasElement, deer: HTMLCanvasElement, host: HTMLElement, reduced: boolean) {
  if (typeof ResizeObserver === "undefined") return;
  const ctx = canvas.getContext("2d");
  const deerCtx = deer.getContext("2d");
  const atlas = makeSpriteSheet();
  const deerAtlas = makeDeerSheet();
  if (!ctx || !deerCtx || !atlas || !deerAtlas) return;

  const artemisContext = ctx;
  const deerContext = deerCtx;
  const artemisFrames = atlas;
  const deerFrames = deerAtlas;
  const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  let width = 0;
  let size = 0;
  let lead = 0;
  let x = 0;
  let direction: 1 | -1 = 1;
  let behavior: Behavior = "run";
  let elapsed = 0;
  let duration = 1.4;
  let previous = 0;
  let request = 0;
  let lastFrame = -1;
  let lastDeerFrame = -1;
  let lastDirection = 0;
  let deerDistance = 0;

  function draw(mode: Behavior, face: number, deerX: number) {
    const index = POSES[mode] + (
      mode === "run" ? Math.floor(elapsed * 11) % 4
      : mode === "wave" ? Math.floor(elapsed * 5) % 2 : 0
    );
    const deerFrame = mode === "run" || mode === "jump" ? 1 + Math.floor(deerDistance / 8) % 4 : 0;
    if (index !== lastFrame || face !== lastDirection) {
      drawFrame(artemisContext, artemisFrames, index, face);
      lastFrame = index;
    }
    if (deerFrame !== lastDeerFrame || face !== lastDirection) {
      drawFrame(deerContext, deerFrames, deerFrame, face);
      lastDeerFrame = deerFrame;
    }
    lastDirection = face;
    const offset = mode === "jump" ? Math.sin(Math.PI * elapsed / jumpDuration) * 27 : 0;
    canvas.style.transform = `translate(${Math.round(x)}px, ${-Math.round(offset)}px)`;
    deer.style.transform = `translateX(${Math.round(deerX)}px)`;
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
        const distance = runningSpeed * (behavior === "jump" ? .7 : 1) * dt;
        deerDistance += distance;
        x += direction * distance;
        if (direction === 1 && x >= width + lead) {
          direction = -1;
          x = width + lead;
        } else if (direction === -1 && x <= -size - lead) {
          direction = 1;
          x = -size - lead;
        }
      }
      draw(behavior, direction, x + direction * lead);
    }
    request = requestAnimationFrame(step);
  }

  function syncMotion() {
    cancelAnimationFrame(request);
    previous = 0;
    if (reduced || motion?.matches || width < size * 2) {
      x = Math.max(0, width - size);
      draw("idle", -1, Math.max(0, x - size));
    } else if (!document.hidden) {
      draw(behavior, direction, x + direction * lead);
      request = requestAnimationFrame(step);
    }
  }

  const observer = new ResizeObserver(() => {
    width = host.clientWidth;
    size = canvas.clientWidth;
    lead = Math.round(size * 1.25);
    x = Math.min(x, width + lead);
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
