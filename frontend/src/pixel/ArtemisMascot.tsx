import { useEffect, useRef } from "react";
import { mountArtemis } from "./engine";
import { CELL } from "./sprites";

export function ArtemisMascot({ reduced }: { reduced: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (host.current && canvas.current) return mountArtemis(canvas.current, host.current, reduced);
  }, [reduced]);

  return <div className="artemis-mascot" ref={host} aria-hidden="true">
    <canvas ref={canvas} width={CELL} height={CELL}/>
  </div>;
}
