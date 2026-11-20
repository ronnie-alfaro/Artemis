export const CELL = 24;
export const POSES = { idle: 0, run: 1, jump: 5, wave: 6 } as const;

export const ARCHERY = { draw: 8, release: 12 } as const;

const palettes = {
  artemis: { hair: "#834b52", cloth: "#eaf3e5", shade: "#a2c4b0", accent: "#327c71" },
  athena: { hair: "#cca079", cloth: "#d8e3f7", shade: "#8b9bc5", accent: "#5870a6" },
  apollo: { hair: "#bc743c", cloth: "#ffe0a4", shade: "#c8905e", accent: "#aa5557" },
  zeus: { hair: "#d0c9d9", cloth: "#f0e9f5", shade: "#ac99bd", accent: "#746293" },
};

export function makeSpriteSheet(deity: keyof typeof palettes = "artemis") {
  const sheet = document.createElement("canvas");
  const frameCount = deity === "artemis" ? 16 : 8;
  sheet.width = frameCount * CELL;
  sheet.height = CELL;
  const ctx = sheet.getContext("2d");
  if (!ctx) return null;

  const ink = "#241f36";
  const gold = "#fadd99";
  const skin = "#f1ac83";
  const { hair, cloth, shade, accent } = palettes[deity];

  for (let frame = 0; frame < frameCount; frame++) {
    const pixel = (color: string, x: number, y: number, w: number, h: number) => {
      ctx.fillStyle = color;
      ctx.fillRect(frame * CELL + x, y, w, h);
    };
    const aiming = frame >= ARCHERY.draw;
    const drawn = aiming && frame < ARCHERY.release;
    const running = aiming || (frame >= POSES.run && frame < POSES.jump);
    const jumping = frame === POSES.jump;
    const waving = frame >= POSES.wave && !aiming;
    const phase = aiming ? (frame - ARCHERY.draw) % 4 : frame - POSES.run;
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
    if (aiming) {
      pixel(ink, 15, 11 + bob, 6, 3);
      pixel(skin, 16, 12 + bob, 4, 1);
      if (drawn) {
        pixel(skin, 14, 11 + bob, 2, 1);
        pixel(cloth, 16, 10 + bob, 3, 1);
      }
    } else if (waving) {
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

    if (deity === "artemis") {
      const trail = running ? 2 + bob : 1;
      pixel(ink, 7 - trail, 8 + bob, 3 + trail, 4);
      pixel(hair, 7 - trail, 9 + bob, 3 + trail, 2);
      pixel(accent, 8, 10 + bob, 2, 1);
      pixel(gold, 14, 15 + bob, 1, 1);
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
      if (aiming) {
        pixel("#d3af79", 19, 8 + bob, 1, 2);
        pixel("#d3af79", 19, 16 + bob, 1, 2);
        pixel(gold, 20, 9 + bob, 1, 2);
        pixel(gold, 21, 11 + bob, 1, 4);
        pixel(gold, 20, 15 + bob, 1, 2);
        if (drawn) {
          pixel(cloth, 17, 10 + bob, 1, 2);
          pixel(cloth, 17, 14 + bob, 1, 2);
          pixel(gold, 15, 12 + bob, 9, 1);
        } else {
          pixel(cloth, 19, 10 + bob, 1, 6);
        }
        continue;
      }
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

export function makeDeerSheet() {
  const sheet = document.createElement("canvas");
  sheet.width = CELL * 8;
  sheet.height = CELL;
  const context = sheet.getContext("2d");
  if (!context) return null;

  const outline = "#352232";
  const coat = "#b56e49";
  const light = "#edc49b";
  for (let frame = 0; frame < 5; frame++) {
    const pixel = (color: string, x: number, y: number, w: number, h: number) => {
      context.fillStyle = color;
      context.fillRect(frame * CELL + x, y, w, h);
    };
    const stride = [0, -3, -1, 3, 1][frame];
    const lift = frame === 2 || frame === 4 ? 1 : 0;
    for (const [hip, direction] of [[6, -1], [13, 1]]) {
      pixel(outline, hip, 16 - lift, 2, 5);
      pixel(outline, hip + direction * stride, 20 - lift, 2, 3);
      pixel(coat, hip, 16 - lift, 1, 4);
      pixel(coat, Math.min(hip, hip + direction * stride), 19 - lift, Math.abs(stride) + 1, 1);
    }
    pixel(outline, 3, 11 - lift, 14, 7);
    pixel(coat, 4, 12 - lift, 12, 5);
    pixel(light, 5, 13 - lift, 2, 1);
    pixel(light, 9, 14 - lift, 1, 1);
    pixel(light, 12, 13 - lift, 1, 1);
    pixel(outline, 1, 10 - lift, 4, 3);
    pixel(light, 2, 10 - lift, 2, 2);
    pixel(outline, 14, 7 - lift, 4, 8);
    pixel(coat, 15, 8 - lift, 2, 6);
    pixel(outline, 15, 5 - lift, 6, 5);
    pixel(coat, 16, 6 - lift, 4, 3);
    pixel(light, 18, 8 - lift, 3, 1);
    pixel(outline, 18, 6 - lift, 1, 1);
    pixel(outline, 21, 7 - lift, 2, 2);
    pixel(coat, 13, 4 - lift, 3, 2);
    pixel(light, 16, 1, 1, 4 - lift);
    pixel(light, 14, 1, 2, 1);
    pixel(light, 18, 2, 1, 3 - lift);
    pixel(light, 19, 1, 1, 2);
  }
  return sheet;
}
