import { buildScenery } from "./scenery";
import { CELL, FRAMES, makeSpriteSheet } from "./sprites";

type Behavior = "walk" | "idle" | "hop";
type Actor = {
  x: number;
  direction: 1 | -1;
  speed: number;
  elapsed: number;
  duration: number;
  behavior: Behavior;
  sprite: number;
};

function changeBehavior(actor: Actor) {
  const choice = Math.random();
  actor.behavior = choice < .55 ? "walk" : choice < .87 ? "idle" : "hop";
  actor.elapsed = 0;
  actor.duration = actor.behavior === "hop" ? .62 : 1.1 + Math.random() * 2.8;
  if (actor.behavior === "walk" && Math.random() < .38) {
    actor.direction = actor.direction === 1 ? -1 : 1;
  }
}

function advance(actor: Actor, dt: number, width: number) {
  actor.elapsed += dt;
  if (actor.elapsed >= actor.duration) changeBehavior(actor);
  const velocity = actor.behavior === "idle" ? 0 : actor.speed;
  actor.x += velocity * actor.direction * dt;
  const end = width - CELL - 3;
  if (actor.x < 3 || actor.x > end) {
    actor.x = Math.min(end, Math.max(3, actor.x));
    actor.direction = actor.direction === 1 ? -1 : 1;
  }
}

export function mountPixelScene(
  canvas: HTMLCanvasElement, host: HTMLElement, { reduced, light }: {
    reduced: boolean; light: boolean;
  },
) {
  if (typeof ResizeObserver === "undefined") return;
  const context = canvas.getContext("2d", { alpha: false });
  const atlas = makeSpriteSheet();
  if (!context || !atlas) return;

  let actors: Actor[] = [];
  let scenery: ReturnType<typeof buildScenery> | undefined;
  let visible = true;
  let previous = 0;
  let request = 0;
  const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");

  function draw() {
    if (!scenery || !context || !atlas) return;
    context.drawImage(scenery.layer, 0, 0);
    for (const actor of actors) {
      const jump = actor.behavior === "hop"
        ? Math.round(Math.sin(Math.PI * actor.elapsed / actor.duration) * 7) : 0;
      const frame = actor.behavior === "walk" ? Math.floor(actor.elapsed * 8) % FRAMES : 0;
      const x = Math.round(actor.x);
      const y = scenery.ground - CELL + 1;
      context.fillStyle = "#211e36";
      context.fillRect(x + 4, y + CELL, 8, 1);
      context.save();
      context.translate(x + (actor.direction === -1 ? CELL : 0), y - jump);
      context.scale(actor.direction, 1);
      context.drawImage(atlas, frame * CELL, actor.sprite * CELL, CELL, CELL, 0, 0, CELL, CELL);
      context.restore();
    }
  }

  function frame(now: number) {
    if (!previous) previous = now;
    const delta = now - previous;
    const interval = 1000 / 24;
    if (delta >= interval) {
      const remainder = delta % interval;
      const dt = Math.min((delta - remainder) / 1000, .075);
      for (const actor of actors) advance(actor, dt, canvas.width);
      draw();
      previous = now - remainder;
    }
    request = requestAnimationFrame(frame);
  }

  function refreshMotion() {
    cancelAnimationFrame(request);
    previous = 0;
    if (reduced || motion?.matches) {
      for (const actor of actors) actor.behavior = "idle";
      draw();
    } else if (visible && !document.hidden && scenery) {
      request = requestAnimationFrame(frame);
    }
  }

  function resize() {
    const scale = host.clientWidth < 370 ? 2 : 3;
    const width = Math.min(320, Math.floor(host.clientWidth / scale));
    const height = Math.min(200, Math.floor(host.clientHeight / scale));
    if (width < 32 || height < 32) return;
    if (scenery && canvas.width === width && canvas.height === height) return;
    const lastWidth = canvas.width;
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = `${width * scale}px`;
    canvas.style.height = `${height * scale}px`;
    if (context) context.imageSmoothingEnabled = false;
    scenery = buildScenery(width, height, light);
    const count = width < 120 ? 2 : 3;
    actors = Array.from({ length: count }, (_, index) => {
      const prior = actors[index];
      return prior ? { ...prior, x: prior.x * width / lastWidth } : {
        x: width * (.27 + index * .24), direction: index % 2 ? -1 : 1,
        speed: 9 + index * 3, elapsed: 0, duration: 1 + index * .7,
        behavior: index % 2 ? "idle" : "walk", sprite: index,
      };
    });
    draw();
    refreshMotion();
  }

  const size = new ResizeObserver(resize);
  size.observe(host);
  const intersection = typeof IntersectionObserver === "undefined" ? undefined
    : new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      refreshMotion();
    });
  intersection?.observe(host);
  motion?.addEventListener("change", refreshMotion);
  document.addEventListener("visibilitychange", refreshMotion);
  resize();
  return () => {
    size.disconnect();
    intersection?.disconnect();
    motion?.removeEventListener("change", refreshMotion);
    document.removeEventListener("visibilitychange", refreshMotion);
    cancelAnimationFrame(request);
  };
}
