export const CELL = 16;
export const FRAMES = 4;

const suits = [
  { shell: "#f8ddae", shade: "#b58879", light: "#fff4d6", glass: "#50cfbc" },
  { shell: "#f59279", shade: "#b9545f", light: "#ffd0a0", glass: "#fae49b" },
  { shell: "#90d9ca", shade: "#438ba2", light: "#d7fff0", glass: "#fff0c0" },
] as const;

export function makeSpriteSheet() {
  const sheet = document.createElement("canvas");
  sheet.width = CELL * FRAMES;
  sheet.height = CELL * suits.length;
  const ctx = sheet.getContext("2d");
  if (!ctx) return null;

  suits.forEach((suit, row) => {
    for (let frame = 0; frame < FRAMES; frame++) {
      const pixel = (color: string, x: number, y: number, w: number, h: number) => {
        ctx.fillStyle = color;
        ctx.fillRect(frame * CELL + x, row * CELL + y, w, h);
      };
      const outline = "#241e36";
      if (row === 2) {
        const bob = frame === 1 || frame === 3 ? 1 : 0;
        pixel(outline, 3, 5 + bob, 10, 8);
        pixel(suit.shade, 4, 6 + bob, 8, 6);
        pixel(suit.shell, 5, 6 + bob, 7, 4);
        pixel(suit.glass, 8, 7 + bob, 3, 2);
        pixel(suit.light, 7, 3 + bob, 1, 3);
        pixel(suit.light, 7, 2 + bob, 2, 1);
        pixel(outline, 4, 13 + bob, 3, 1);
        pixel(outline, 9, 13 + bob, 3, 1);
        pixel(suit.shell, 5 + frame % 2, 15, 5, 1);
        continue;
      }

      const stride = [0, 2, 0, -2][frame];
      const bob = frame === 2 ? 1 : 0;
      pixel(outline, 4, 13, 7, 2);
      pixel(suit.shade, 5 - stride, 14, 3, 2);
      pixel(suit.shell, 8 + stride, 14, 3, 2);
      pixel(outline, 2, 7 + bob, 4, 5);
      pixel(suit.shade, 3, 8 + bob, 3, 3);
      pixel(outline, 4, 7 + bob, 8, 7);
      pixel(suit.shell, 5, 8 + bob, 6, 5);
      pixel(suit.shade, 5, 12 + bob, 6, 1);
      pixel(suit.light, 7, 9 + bob, 2, 2);
      pixel(outline, 5, 1 + bob, 7, 7);
      pixel(outline, 4, 3 + bob, 9, 4);
      pixel(suit.shell, 6, 2 + bob, 5, 5);
      pixel(suit.light, 6, 2 + bob, 4, 1);
      pixel(suit.shade, 5, 4 + bob, 2, 3);
      pixel(suit.glass, 8, 4 + bob, 4, 2);
      pixel(suit.light, 9, 4 + bob, 1, 1);
      pixel(suit.shell, 11, 9 + bob, 2, 3);
    }
  });
  return sheet;
}
