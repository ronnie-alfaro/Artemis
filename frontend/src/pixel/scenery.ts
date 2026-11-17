export function buildScenery(width: number, height: number, light: boolean) {
  const layer = document.createElement("canvas");
  layer.width = width;
  layer.height = height;
  const ctx = layer.getContext("2d");
  const ground = Math.floor(height * 0.81);
  if (!ctx) return { layer, ground };

  const colors = light
    ? ["#5b5b97", "#777aae", "#a5a2c4", "#515880", "#434867", "#676383"]
    : ["#1d1e3b", "#2a2950", "#55416b", "#333858", "#262942", "#43405b"];
  const block = (color: string, x: number, y: number, w: number, h: number) => {
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);
  };

  let seed = 5637;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };

  block(colors[0], 0, 0, width, height);
  block(colors[1], 0, Math.floor(height * .31), width, height);
  block(colors[2], 0, Math.floor(height * .61), width, height);
  for (let i = 0; i < Math.ceil(width / 3); i++) {
    const x = Math.floor(random() * width);
    const y = Math.floor(random() * height * .63);
    block(i % 5 === 0 ? "#ffe2aa" : "#b8b7dc", x, y, i % 11 === 0 ? 2 : 1, 1);
  }

  const planetX = Math.round(width * .73);
  const planetY = Math.round(height * .29);
  const radius = Math.min(22, Math.floor(height * .17));
  for (let y = -radius; y <= radius; y++) {
    const half = Math.floor(Math.sqrt(radius * radius - y * y));
    block(y < 3 ? "#f5bc97" : y < 11 ? "#e69284" : "#c96e7e",
      planetX - half, planetY + y, half * 2 + 1, 1);
  }
  for (let i = -radius; i <= radius; i++) {
    const y = planetY + Math.floor(i * .19) + 4;
    block("#ffe2a6", planetX + i * 2, y, 2, 1);
  }

  for (let x = 0; x < width; x += 3) {
    const distance = Math.min(x % 61, 61 - (x % 61));
    const far = ground - 12 - Math.floor(distance * .46);
    const near = ground - 4 - Math.floor((1 + Math.sin(x * .18)) * 3);
    block(colors[3], x, far, 3, ground - far);
    block(colors[4], x, near, 3, ground - near);
  }

  const base = Math.floor(width * .19);
  block("#22263b", base - 4, ground - 18, 34, 18);
  block("#394461", base, ground - 23, 24, 5);
  block("#7984a0", base + 2, ground - 24, 20, 2);
  block("#1b2339", base + 3, ground - 16, 19, 7);
  for (let i = 0; i < 3; i++) block("#82dcce", base + 5 + i * 6, ground - 14, 4, 3);
  block("#737c99", base + 24, ground - 37, 2, 19);
  block("#d8a6a5", base + 20, ground - 34, 10, 2);
  block("#f5cf9a", base + 24, ground - 38, 2, 2);

  block(colors[5], 0, ground, width, height - ground);
  block("#877a94", 0, ground, width, 2);
  for (let x = 2; x < width; x += 4) {
    const y = ground + 5 + Math.floor(random() * Math.max(1, height - ground - 5));
    block(x % 3 ? colors[4] : "#95899f", x, y, x % 3 + 1, 1);
  }
  return { layer, ground };
}
