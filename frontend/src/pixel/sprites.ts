export const CELL = 24;
export const POSES = { idle: 0, run: 1, jump: 5, wave: 6 } as const;

const palettes = {
  artemis: { hair: "#674051", cloth: "#e4ecd5", shade: "#9baf9b", accent: "#428c69" },
  athena: { hair: "#cca079", cloth: "#d8e3f7", shade: "#8b9bc5", accent: "#5870a6" },
  apollo: { hair: "#bc743c", cloth: "#ffe0a4", shade: "#c8905e", accent: "#aa5557" },
  zeus: { hair: "#d0c9d9", cloth: "#f0e9f5", shade: "#ac99bd", accent: "#746293" },
};

export function makeSpriteSheet(deity: keyof typeof palettes = "artemis") {
  const sheet = document.createElement("canvas");
  sheet.width = 8 * CELL;
  sheet.height = CELL;
  const ctx = sheet.getContext("2d");
  if (!ctx) return null;

  const ink = "#241f36";
  const gold = "#fadd99";
  const skin = "#f1ac83";
  const { hair, cloth, shade, accent } = palettes[deity];

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

    const legTop = 17 + bob;
    const backFoot = jumping ? 20 : 21;
    const frontFoot = jumping ? 19 : 21;
    for (const [hip, foot, footY] of [[10, 10 - stride, backFoot], [14, 14 + stride, frontFoot]]) {
      const knee = Math.round((hip + foot) / 2);
      pixel(ink, Math.min(hip, knee) - 1, legTop, Math.abs(hip - knee) + 3, 2);
      pixel(ink, Math.min(knee, foot) - 1, legTop + 2, Math.abs(knee - foot) + 3, footY - legTop - 1);
      pixel(skin, knee, legTop + 1, 1, 2);
      pixel(skin, foot, legTop + 2, 1, footY - legTop - 1);
      pixel(ink, foot - 1, footY + 1, 4, 2);
      pixel("#926352", foot, footY + 1, 2, 1);
    }

    pixel(ink, 10, 11 + bob, 6, 5);
    pixel(ink, 9, 16 + bob, 8, 3);
    pixel(cloth, 11, 11 + bob, 4, 5);
    pixel(accent, 10, 15 + bob, 6, 1);
    pixel(cloth, 10, 16 + bob, 6, 2);
    pixel(shade, 12, 16 + bob, 1, 2);
    pixel(ink, 8, 12 + bob, 2, 4);
    pixel(skin, 9, 13 + bob, 1, 2);
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

    // Profile and laurel.
    pixel(ink, 8, 5 + bob, 3, 6);
    pixel(hair, 8, 6 + bob, 2, 4);
    pixel(ink, 9, 3 + bob, 8, 9);
    pixel(hair, 9, 4 + bob, 7, 5);
    pixel(skin, 12, 6 + bob, 5, 5);
    pixel(ink, 16, 8 + bob, 2, 1);
    pixel("#a85354", 15, 10 + bob, 2, 1);
    pixel(accent, 9, 5 + bob, 6, 2);
    pixel(gold, 10, 4 + bob, 1, 1);
    pixel("#a2c98e", 11, 4 + bob, 3, 1);
    pixel("#a2c98e", 14, 3 + bob, 2, 1);

    if (deity === "artemis" && !waving) {
      pixel("#d3af79", 19, 10 + bob, 1, 10);
      pixel(gold, 20, 11 + bob, 1, 2);
      pixel(gold, 21, 13 + bob, 1, 4);
      pixel(gold, 20, 17 + bob, 1, 2);
    } else if (deity === "athena") {
      pixel("#a55d65", 9, 2 + bob, 5, 2);
      pixel(gold, 9, 4 + bob, 8, 2);
      pixel(gold, 20, 5 + bob, 1, 15);
      pixel(cloth, 19, 5 + bob, 3, 2);
      pixel(ink, 6, 12 + bob, 5, 6);
      pixel("#be9d67", 7, 13 + bob, 3, 4);
    } else if (deity === "apollo") {
      pixel(ink, 17, 12 + bob, 6, 7);
      pixel(gold, 18, 12 + bob, 1, 5);
      pixel(gold, 21, 12 + bob, 1, 5);
      pixel(cloth, 19, 14 + bob, 2, 1);
      pixel(gold, 18, 17 + bob, 4, 1);
    } else if (deity === "zeus") {
      pixel(hair, 12, 9 + bob, 5, 3);
      pixel(hair, 13, 12 + bob, 3, 1);
      pixel(gold, 21, 7 + bob, 2, 3);
      pixel(gold, 19, 10 + bob, 3, 2);
      pixel(gold, 20, 12 + bob, 1, 3);
    }
  }
  return sheet;
}
