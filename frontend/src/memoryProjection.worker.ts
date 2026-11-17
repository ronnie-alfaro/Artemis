import { cosine, UMAP } from "umap-js/dist/umap";

self.onmessage = ({ data: vectors }: MessageEvent<number[][]>) => {
  try {
    let seed = 59813;
    const random = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const coordinates = new UMAP({
      nNeighbors: Math.min(15, vectors.length - 1),
      distanceFn: cosine,
      random,
    }).fit(vectors);
    if (!coordinates.every(point => point.every(Number.isFinite))) throw new Error();
    self.postMessage(coordinates);
  } catch {
    self.postMessage(null);
  }
};
