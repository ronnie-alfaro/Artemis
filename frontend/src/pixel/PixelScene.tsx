import { useEffect, useRef } from "react";
import { buildScenery } from "./scenery";
import { CELL, makeSpriteSheet } from "./sprites";

const deities = ["athena", "apollo", "zeus"] as const;

function SceneFigure({ deity }: { deity: typeof deities[number] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    const sheet = context && makeSpriteSheet(deity);
    if (sheet) context.drawImage(sheet, 0, 0);
  }, [deity]);

  return <div className={`scene-figure scene-figure--${deity}`}>
    <canvas ref={canvas} width={8 * CELL} height={CELL}/>
  </div>;
}

export function PixelScene({ light }: { light: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const container = host.current;
    const surface = canvas.current;
    if (!container || !surface || typeof ResizeObserver === "undefined") return;
    const context = surface.getContext("2d", { alpha: false });
    if (!context) return;
    const observer = new ResizeObserver(() => {
      const scale = container.clientWidth < 370 ? 2 : 3;
      const width = Math.floor(container.clientWidth / scale);
      const height = Math.floor(container.clientHeight / scale);
      if (!width || !height) return;
      surface.width = width;
      surface.height = height;
      surface.style.width = `${width * scale}px`;
      surface.style.height = `${height * scale}px`;
      context.imageSmoothingEnabled = false;
      buildScenery(context, width, height, light);
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [light]);

  return <div className="pixel-scene" ref={host} aria-hidden="true">
    <canvas ref={canvas}/>
    {deities.map(deity => <SceneFigure key={deity} deity={deity}/>)}
  </div>;
}
