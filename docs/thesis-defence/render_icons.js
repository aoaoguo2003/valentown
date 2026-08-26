/* Rasterise the icon candidates so they can be eyeballed before use. */
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const sharp = require("sharp");
const gi = require("react-icons/gi");
const fs = require("fs");

const OUT = __dirname + "/build";

async function render(name, color, px, file) {
  const Icon = gi[name];
  if (!Icon) throw new Error("no icon " + name);
  let svg = renderToStaticMarkup(React.createElement(Icon, { color, size: px }));
  // react-icons omits an explicit width/height when size is passed as a prop in some versions
  if (!/width=/.test(svg)) svg = svg.replace("<svg", `<svg width="${px}" height="${px}"`);
  const buf = await sharp(Buffer.from(svg), { density: 400 })
    .resize(px, px, { fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .png()
    .toBuffer();
  fs.writeFileSync(`${OUT}/${file}`, buf);
  return file;
}

(async () => {
  const cands = ["GiBat", "GiEvilBat", "GiMoonBats", "GiBatWing", "GiSwampBat",
                 "GiCricket", "GiButterfly", "GiFlyingBeetle", "GiSoundWaves", "GiEchoRipples"];
  for (const n of cands) {
    try { console.log(await render(n, "#0E1B33", 256, `cand_${n}.png`)); }
    catch (e) { console.log(n, "FAILED", e.message); }
  }
})();
