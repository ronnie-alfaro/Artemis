import { useEffect, useRef } from "react";
import { mountPixelScene } from "./engine";

export function PixelScene({ reduced, light }: { reduced: boolean; light: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (host.current && canvas.current) {
      return mountPixelScene(canvas.current, host.current, { reduced, light });
    }
  }, [reduced, light]);

  return <div className="pixel-scene" ref={host} aria-hidden="true">
    <canvas ref={canvas}/>
  </div>;
}
