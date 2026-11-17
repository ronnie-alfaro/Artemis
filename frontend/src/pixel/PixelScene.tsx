import { useEffect, useRef } from "react";
import { buildScenery } from "./scenery";

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
  </div>;
}
