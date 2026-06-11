const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const gamePath = path.join(root, 'frontend', 'js', 'game.js');
const outputPath = path.join(root, 'diagnostic_anchor_positions.svg');
const jsonOutputPath = path.join(root, 'diagnostic_anchor_positions.json');
const code = fs.readFileSync(gamePath, 'utf8');

const sandbox = {
    console,
    Phaser: {
        AUTO: 0,
        Scale: { FIT: 0, CENTER_BOTH: 0 },
        Math: {
            Clamp(value, min, max) {
                return Math.min(Math.max(value, min), max);
            }
        },
        Game: function Game() {}
    }
};

vm.createContext(sandbox);
vm.runInContext(`${code}
globalThis.__anchorData = {
    UNIT,
    WORLD_W,
    WORLD_H,
    homeConfigs,
    navNodes,
    navEdges: navEdges.filter(([fromName, toName]) => {
        function nodeArea(nodeName) {
            const parts = String(nodeName).split('.');
            return parts[0] === 'road' ? parts[1] : parts[0];
        }
        return isAnchorDebugArea(nodeArea(fromName)) && isAnchorDebugArea(nodeArea(toName));
    }),
    entries: getAnchorDebugEntries().map(entry => ({
        locationName: entry.locationName,
        point: entry.point,
        pose: entry.pose,
        label: getAnchorDebugLabel(entry.locationName)
    }))
};
`, sandbox);

const data = sandbox.__anchorData;

function esc(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;');
}

function colorForPose(pose) {
    if (pose === 'lie') return '#e85d9e';
    if (pose === 'sit') return '#2f80ed';
    return '#f2a93b';
}

const roadLines = data.navEdges.map(([fromName, toName]) => {
    const from = data.navNodes[fromName];
    const to = data.navNodes[toName];
    if (!from || !to) return '';

    return `<line x1="${from.x * data.UNIT}" y1="${from.y * data.UNIT}" x2="${to.x * data.UNIT}" y2="${to.y * data.UNIT}" stroke="#f3e08b" stroke-width="18" stroke-linecap="round" opacity="0.34"/>`;
}).join('\n');

const homeBoxes = data.homeConfigs.map(home => {
    const x = (home.x * data.UNIT) - 138;
    const y = (home.y * data.UNIT) - 104;
    return `<rect x="${x}" y="${y}" width="276" height="214" rx="10" fill="#ffffff" opacity="0.18" stroke="#516170" stroke-width="2"/>
<text x="${home.x * data.UNIT}" y="${y + 17}" text-anchor="middle" font-family="Arial" font-size="14" font-weight="700" fill="#1f2933">${esc(home.area.replace('_home', ''))}</text>`;
}).join('\n');

const publicBoxes = [
    { label: 'Park', x: 55, y: 65, w: 310, h: 250, fill: '#89d780' },
    { label: 'Cafe', x: 105, y: 65, w: 310, h: 250, fill: '#e5c07b' },
    { label: 'Market', x: 155, y: 65, w: 330, h: 250, fill: '#93c5fd' },
    { label: 'Pharmacy', x: 205, y: 65, w: 330, h: 250, fill: '#fca5a5' }
].map(box => {
    const x = (box.x * data.UNIT) - (box.w / 2);
    const y = (box.y * data.UNIT) - (box.h / 2);
    return `<rect x="${x}" y="${y}" width="${box.w}" height="${box.h}" rx="10" fill="${box.fill}" opacity="0.18" stroke="#516170" stroke-width="2"/>
<text x="${box.x * data.UNIT}" y="${y + 17}" text-anchor="middle" font-family="Arial" font-size="14" font-weight="700" fill="#1f2933">${box.label}</text>`;
}).join('\n');

const markers = data.entries.map((entry, index) => {
    const x = entry.point.x * data.UNIT;
    const y = entry.point.y * data.UNIT;
    const labelY = y - 10 - ((index % 3) * 11);
    return `<g>
<line x1="${x - 11}" y1="${y}" x2="${x + 11}" y2="${y}" stroke="#111827" stroke-width="1" opacity="0.55"/>
<line x1="${x}" y1="${y - 11}" x2="${x}" y2="${y + 11}" stroke="#111827" stroke-width="1" opacity="0.55"/>
<circle cx="${x}" cy="${y}" r="7" fill="${colorForPose(entry.pose)}" stroke="#ffffff" stroke-width="2"/>
<text x="${x + 9}" y="${labelY}" font-family="Arial" font-size="10" fill="#111827" paint-order="stroke" stroke="#ffffff" stroke-width="3">${esc(entry.label)}</text>
</g>`;
}).join('\n');

const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${data.WORLD_W}" height="${data.WORLD_H}" viewBox="0 0 ${data.WORLD_W} ${data.WORLD_H}">
<rect width="100%" height="100%" fill="#9ddf74"/>
${roadLines}
${homeBoxes}
${publicBoxes}
<rect x="18" y="752" width="420" height="116" rx="10" fill="#ffffff" opacity="0.88" stroke="#334155"/>
<text x="36" y="782" font-family="Arial" font-size="22" font-weight="700" fill="#111827">Interaction Anchor Debug Map</text>
<circle cx="44" cy="808" r="7" fill="#f2a93b" stroke="#ffffff" stroke-width="2"/><text x="60" y="813" font-family="Arial" font-size="14" fill="#111827">stand point</text>
<circle cx="154" cy="808" r="7" fill="#2f80ed" stroke="#ffffff" stroke-width="2"/><text x="170" y="813" font-family="Arial" font-size="14" fill="#111827">sit point</text>
<circle cx="254" cy="808" r="7" fill="#e85d9e" stroke="#ffffff" stroke-width="2"/><text x="270" y="813" font-family="Arial" font-size="14" fill="#111827">lie point</text>
<text x="36" y="842" font-family="Arial" font-size="13" fill="#334155">Generated from current frontend/js/game.js coordinates.</text>
${markers}
</svg>`;

fs.writeFileSync(outputPath, svg, 'utf8');
fs.writeFileSync(jsonOutputPath, JSON.stringify({
    width: data.WORLD_W,
    height: data.WORLD_H,
    unit: data.UNIT,
    homes: data.homeConfigs.map(home => ({
        label: home.area.replace('_home', ''),
        x: home.x * data.UNIT,
        y: home.y * data.UNIT,
        width: 276,
        height: 214
    })),
    publics: [
        { label: 'Park', x: 55 * data.UNIT, y: 65 * data.UNIT, width: 310, height: 250, fill: '#89d780' },
        { label: 'Cafe', x: 105 * data.UNIT, y: 65 * data.UNIT, width: 310, height: 250, fill: '#e5c07b' },
        { label: 'Market', x: 155 * data.UNIT, y: 65 * data.UNIT, width: 330, height: 250, fill: '#93c5fd' },
        { label: 'Pharmacy', x: 205 * data.UNIT, y: 65 * data.UNIT, width: 330, height: 250, fill: '#fca5a5' }
    ],
    roads: data.navEdges
        .map(([fromName, toName]) => ({ from: data.navNodes[fromName], to: data.navNodes[toName] }))
        .filter(road => road.from && road.to)
        .map(road => ({
            x1: road.from.x * data.UNIT,
            y1: road.from.y * data.UNIT,
            x2: road.to.x * data.UNIT,
            y2: road.to.y * data.UNIT
        })),
    markers: data.entries.map(entry => ({
        x: entry.point.x * data.UNIT,
        y: entry.point.y * data.UNIT,
        pose: entry.pose,
        label: entry.label
    }))
}, null, 2), 'utf8');
console.log(outputPath);
