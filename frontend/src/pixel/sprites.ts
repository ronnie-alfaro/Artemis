export const CELL = 24;
export const POSES = { idle: 0, run: 1, jump: 5, wave: 6 } as const;

export function makeSpriteSheet() {
  const sheet = document.createElement("canvas");
  sheet.width = 8 * CELL;
  sheet.height = CELL;
  const ctx = sheet.getContext("2d");
  if (!ctx) return null;

  const ink = "#241f36";
  const hair = "#674051";
  const gold = "#fadd99";
  const skin = "#f1ac83";
  const cloth = "#e4ecd5";
  const shade = "#9baf9b";
  const green = "#428c69";

  for (let frame = 0; frame < 8; frame++) {
    const pixel = (color: string, x: number, y: number, w: number, h: number) => {
      ctx.fillStyle = color;
      ctx.fillRect(frame * CELL + x, y, w, h);
    };
    const running = frame >= POSES.run && frame < POSES.jump;
    const jumping = frame === POSES.jump;
    const waving = frame >= POSES.wave;
    const phase = frame - POSES.run;
    const stride = running ? [-3, -1, 3, 1][phase] : 0;
    const bob = Number(running && (phase === 1 || phase === 3));

    // Bow, string, and traveling cloak sit behind the figure.
    pixel("#d3af79", 5, 9 + bob, 1, 11);
    pixel(ink, 4, 9 + bob, 1, 2);
    pixel(gold, 3, 11 + bob, 1, 7);
    pixel("#b67750", 4, 11 + bob, 1, 7);
    pixel(gold, 4, 18 + bob, 1, 2);
    pixel(ink, 6, 13 + bob, 5, 6);
    pixel(green, running ? 5 : 7, 13 + bob, 5, 5);

    // Sandals and asymmetric steps. The first foot is behind the tunic.
    pixel(ink, 8 - stride, jumping ? 19 : 20, 4, 3);
    pixel(skin, 9 - stride, jumping ? 19 : 20, 2, 2);
    pixel(ink, 13 + stride, jumping ? 18 : 21, 4, 3);
    pixel(skin, 14 + stride, jumping ? 18 : 21, 2, 2);
    pixel("#926352", 14 + stride, jumping ? 20 : 23, 3, 1);

    // Belt, tunic and front arm.
    pixel(ink, 9, 11 + bob, 8, 8);
    pixel(shade, 9, 16 + bob, 8, 3);
    pixel(cloth, 10, 11 + bob, 6, 7);
    pixel(gold, 10, 15 + bob, 6, 1);
    pixel(shade, 12, 17 + bob, 2, 2);
    pixel(ink, 16, 12 + bob, 2, 4);
    if (waving) {
      const reach = frame - POSES.wave;
      pixel(ink, 17, 12, 4, 2);
      pixel(ink, 19 + reach, 8, 2, 5);
      pixel(skin, 18, 12, 2, 1);
      pixel(skin, 20 + reach, 8, 1, 4);
      pixel(gold, 22, 5 + reach * 2, 1, 2);
    } else {
      pixel(shade, 16, 12 + bob, 2, 1);
      pixel(skin, 16, 13 + bob, 2, 2);
      pixel(skin, 17, 14 + bob, 2, 1);
    }

    // Profile, mischievous grin, and laurel.
    pixel(ink, 7, 5 + bob, 4, 7);
    pixel(hair, 7, 6 + bob, 3, 4);
    pixel(ink, 9, 3 + bob, 8, 9);
    pixel(hair, 9, 4 + bob, 7, 5);
    pixel(skin, 12, 6 + bob, 5, 5);
    pixel(ink, 16, 8 + bob, 2, 1);
    pixel("#a85354", 15, 10 + bob, 2, 1);
    pixel(green, 8, 5 + bob, 7, 2);
    pixel(gold, 10, 4 + bob, 1, 1);
    pixel("#a2c98e", 11, 4 + bob, 3, 1);
    pixel("#a2c98e", 14, 3 + bob, 2, 1);
  }
  return sheet;
}
