import { ARCHERY, CELL, makeDeerSheet, makeSpriteSheet, POSES } from "./sprites";

const artemisSpeed = 112;
const firstShot = .7;
const shotInterval = 2.1;
const drawTime = .26;
const arrowSpeed = 440;
const interval = 1000 / 24;

function drawFrame(context: CanvasRenderingContext2D, atlas: HTMLCanvasElement, frame: number, face: number) {
  context.clearRect(0, 0, CELL, CELL);
  context.save();
  context.translate(face === -1 ? CELL : 0, 0);
  context.scale(face, 1);
  context.drawImage(atlas, frame * CELL, 0, CELL, CELL, 0, 0, CELL, CELL);
  context.restore();
}

export function mountArtemis(canvas: HTMLCanvasElement, deer: HTMLCanvasElement, arrow: HTMLElement, host: HTMLElement, reduced: boolean) {
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
  let direction: 1 | -1 = 1;
  let elapsed = 0;
  let previous = 0;
  let request = 0;
  let lastFrame = -1;
  let lastDeerFrame = -1;
  let lastDirection = 0;
  let nextShot = firstShot;
  let flight: { x: number; y: number; age: number } | undefined;

  function position(distance: number) {
    return direction === 1 ? distance - size : width - distance;
  }

  function draw(frame: number, deerFrame: number, x: number, deerX: number, face: number) {
    if (frame !== lastFrame || face !== lastDirection) {
      drawFrame(artemisContext, artemisFrames, frame, face);
      lastFrame = frame;
    }
    if (deerFrame !== lastDeerFrame || face !== lastDirection) {
      drawFrame(deerContext, deerFrames, deerFrame, face);
      lastDeerFrame = deerFrame;
    }
    lastDirection = face;
    canvas.style.transform = `translateX(${Math.round(x)}px)`;
    deer.style.transform = `translateX(${Math.round(deerX)}px)`;
  }

  function drawChase() {
    const distance = artemisSpeed * elapsed;
    const x = position(distance);
    const deerDistance = distance + size * .85 + 19 * elapsed + 8 * Math.sin(elapsed * 1.6);
    const stride = Math.floor(elapsed * 12) % 4;
    const bob = stride % 2;
    const handX = x + size * (direction === 1 ? 21 / CELL : 3 / CELL);
    if (elapsed >= nextShot) {
      if (handX > 0 && handX < width) {
        flight = { x: handX, y: size * (11.5 - bob) / CELL - 2.5, age: 0 };
      }
      nextShot += shotInterval;
    }

    const aiming = nextShot - elapsed <= drawTime;
    const releasing = nextShot - elapsed >= shotInterval - .14;
    const frame = aiming ? ARCHERY.draw + stride : releasing ? ARCHERY.release + stride : POSES.run + stride;
    draw(frame, 1 + Math.floor(deerDistance / 7) % 4, x, position(deerDistance), direction);
  }

  function drawArrow(dt: number) {
    if (flight) {
      const t = flight.age;
      const x = flight.x + direction * arrowSpeed * t;
      // The arrow rises slightly on release and drops toward the ground.
      const y = flight.y + 28 * t - 135 * t * t;
      if (x < -18 || x > width + 18 || y <= 0) {
        flight = undefined;
      } else {
        const angle = Math.atan2(270 * t - 28, arrowSpeed);
        arrow.style.transform = `translate(${x}px, ${-y}px) scaleX(${direction}) rotate(${angle}rad)`;
        flight.age += dt;
      }
    }
    arrow.hidden = !flight;
  }

  function step(now: number) {
    if (!previous) previous = now;
    const delta = now - previous;
    if (delta >= interval) {
      const remainder = delta % interval;
      const dt = Math.min((delta - remainder) / 1000, .075);
      previous = now - remainder;
      elapsed += dt;
      if (artemisSpeed * elapsed >= width + size && !flight) {
        direction = direction === 1 ? -1 : 1;
        elapsed = 0;
        nextShot = firstShot;
      }
      drawChase();
      drawArrow(dt);
    }
    request = requestAnimationFrame(step);
  }

  function syncMotion() {
    cancelAnimationFrame(request);
    previous = 0;
    if (reduced || motion?.matches || width < size * 2) {
      elapsed = 0;
      nextShot = firstShot;
      flight = undefined;
      arrow.hidden = true;
      const x = Math.max(0, width - size);
      draw(POSES.idle, 0, x, Math.max(0, x - size), -1);
    } else if (!document.hidden) {
      drawChase();
      request = requestAnimationFrame(step);
    }
  }

  const observer = new ResizeObserver(() => {
    width = host.clientWidth;
    size = canvas.clientWidth;
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
