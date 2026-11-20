import { useEffect, useRef } from "react";
import { mountArtemis } from "./engine";
import { CELL } from "./sprites";

export function ArtemisMascot({ reduced }: { reduced: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const deer = useRef<HTMLCanvasElement>(null);
  const arrow = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (host.current && canvas.current && deer.current && arrow.current) {
      return mountArtemis(canvas.current, deer.current, arrow.current, host.current, reduced);
    }
  }, [reduced]);

  return <div className="artemis-mascot" ref={host} aria-hidden="true">
    <canvas ref={deer} width={CELL} height={CELL}/>
    <span className="mascot-arrow" ref={arrow} hidden/>
    <canvas ref={canvas} width={CELL} height={CELL}/>
  </div>;
}
