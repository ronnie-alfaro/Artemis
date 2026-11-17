export function buildScenery(ctx: CanvasRenderingContext2D, width: number, height: number, light: boolean) {
  const ground = Math.floor(height * .84);
  const [sky, dusk, mist, hill, woods, grass] = light
    ? ["#5c6382", "#837a9a", "#b798a4", "#665f7b", "#425b60", "#355655"]
    : ["#212540", "#393754", "#655673", "#44435f", "#2b414b", "#233b44"];
  const block = (color: string, x: number, y: number, w: number, h: number) => {
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);
  };
  let seed = 5637;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };

  const horizon = Math.floor(height * .40);
  block(sky, 0, 0, width, height);
  block(dusk, 0, horizon, width, height);
  block(mist, 0, Math.floor(height * .65), width, height);
  for (let i = 0; i < Math.ceil(width / 4); i++) {
    block(i % 8 === 0 ? "#ffe7bb" : "#a9a3bd",
      Math.floor(random() * width), Math.floor(random() * horizon), 1, 1);
  }

  const moonX = Math.round(width * .71);
  const moonY = Math.round(height * .28);
  const radius = Math.min(14, Math.floor(height * .14));
  for (let y = -radius; y <= radius; y++) {
    const outside = Math.floor(Math.sqrt(radius * radius - y * y));
    const innerY = y + Math.round(radius * .27);
    const inside = Math.floor(Math.sqrt(Math.max(0, radius * radius - innerY * innerY)));
    const end = Math.min(moonX + outside + 1, moonX + Math.round(radius * .55) - inside);
    block("#ffe6ad", moonX - outside, moonY + y, Math.max(0, end - (moonX - outside)), 1);
  }

  for (let x = 0; x < width; x += 3) {
    const slope = Math.min(x % 91, 91 - (x % 91));
    const crest = ground - 16 - Math.round(slope * .54);
    block(hill, x, crest, 3, ground - crest);
  }
  for (let x = -5; x < width; x += 8 + Math.floor(random() * 10)) {
    const size = 12 + Math.floor(random() * 25);
    for (let y = 0; y < size; y += 2) {
      const span = 1 + Math.floor(y * .18);
      block(woods, x - span, ground - size + y, span * 2 + 1, 2);
    }
  }

  // Small temple with a stepped pediment, columns and colored stone.
  const center = Math.round(width * .34);
  const templeHeight = Math.min(33, Math.floor(height * .31));
  const lintel = ground - templeHeight;
  for (let y = 0; y < 7; y++) block("#deb997", center - 3 - y * 2, lintel + y, 7 + y * 4, 1);
  block("#e8cba4", center - 18, lintel + 7, 37, 3);
  block("#333748", center - 14, lintel + 10, 29, templeHeight - 11);
  for (let x = center - 14; x <= center + 13; x += 9) {
    block("#c9a588", x, lintel + 10, 3, templeHeight - 11);
    block("#ebc6a0", x, lintel + 11, 1, templeHeight - 13);
  }
  block("#b68f7e", center - 18, ground - 2, 37, 2);
  block(grass, 0, ground, width, height - ground);
  block("#598071", 0, ground, width, 1);
  for (let x = 0; x < width; x += 3) {
    const y = ground + 2 + Math.floor(random() * Math.max(1, height - ground - 2));
    block(x % 5 === 0 ? "#86a088" : woods, x, y, 2, 1);
  }
}
