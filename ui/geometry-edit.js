/* Bounded, data-only editing helpers for visual note geometry. */
(function (root) {
  "use strict";
  function handles(items) {
    const choices = [];
    (Array.isArray(items) ? items : []).forEach((item, i) => {
      if (item?.kind !== "geometry" || !Array.isArray(item.objects)) return;
      item.objects.forEach((object, j) => {
        const add = (part, name) => choices.push({ key: `${i}:${j}:${part}`,
          label: `Geometry ${i + 1}, ${name}${object.label ? `: ${object.label}` : ""}` });
        if (object.kind === "point") add("point", `point ${j + 1}`);
        if (object.kind === "segment") { add("start", `segment ${j + 1} start`); add("end", `segment ${j + 1} end`); }
        if (object.kind === "circle") { add("center", `circle ${j + 1} center`); add("radius", `circle ${j + 1} radius`); }
        if (object.kind === "polygon" && Array.isArray(object.points)) {
          object.points.forEach((_point, k) => add(`vertex${k}`, `polygon ${j + 1} vertex ${k + 1}`));
        }
      });
    });
    return choices;
  }
  function resolve(items, key) {
    const match = /^(\d+):(\d+):(point|start|end|center|radius|vertex[0-7])$/.exec(key || "");
    if (!match) return null;
    const i = Number(match[1]), j = Number(match[2]), part = match[3];
    const item = items?.[i], object = item?.kind === "geometry" ? item.objects?.[j] : null;
    if (!object) return null;
    let x, y;
    if (part === "point" && object.kind === "point") [x, y] = [object.x, object.y];
    else if (part === "start" && object.kind === "segment") [x, y] = [object.x1, object.y1];
    else if (part === "end" && object.kind === "segment") [x, y] = [object.x2, object.y2];
    else if (part === "center" && object.kind === "circle") [x, y] = [object.cx, object.cy];
    else if (part === "radius" && object.kind === "circle") [x, y] = [object.cx + object.radius, object.cy];
    else if (part.startsWith("vertex") && object.kind === "polygon") [x, y] = object.points?.[Number(part.slice(6))] || [];
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return { i, j, part, object, x, y };
  }
  function propose(items, key, x, y, label, radius = undefined) {
    const target = resolve(items, key);
    if (!target || !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1 || typeof label !== "string") return null;
    const object = JSON.parse(JSON.stringify(target.object));
    object.label = label.replace(/[\x00-\x1f\x7f]/g, "").trim().slice(0, 32);
    if (target.part === "point") { object.x = x; object.y = y; }
    if (target.part === "start") { object.x1 = x; object.y1 = y; }
    if (target.part === "end") { object.x2 = x; object.y2 = y; }
    if (target.part === "center") { object.cx = x; object.cy = y; }
    if (target.part === "radius") object.radius = Math.hypot(x - object.cx, y - object.cy);
    if (object.kind === "circle" && radius !== undefined) object.radius = radius;
    if (target.part.startsWith("vertex")) object.points[Number(target.part.slice(6))] = [x, y];
    if (object.kind === "segment" && object.x1 === object.x2 && object.y1 === object.y2) return null;
    if (object.kind === "circle" && (!Number.isFinite(object.radius) || object.radius <= 0
      || object.cx - object.radius < 0 || object.cx + object.radius > 1
      || object.cy - object.radius < 0 || object.cy + object.radius > 1)) return null;
    return { i: target.i, j: target.j, object };
  }
  function canvasPosition(items, key, width, height) {
    const target = resolve(items, key);
    if (!target || !Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
    const item = items[target.i];
    if (![item.x, item.y, item.width, item.height].every(Number.isFinite) || item.width <= 0 || item.height <= 0) return null;
    return { x: (item.x + target.x * item.width) * width,
      y: (item.y + target.y * item.height) * height };
  }
  function localPosition(items, key, width, height, x, y) {
    const target = resolve(items, key);
    if (!target || !Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(width)
        || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
    const item = items[target.i];
    if (![item.x, item.y, item.width, item.height].every(Number.isFinite) || item.width <= 0 || item.height <= 0) return null;
    return { x: (x / width - item.x) / item.width, y: (y / height - item.y) / item.height };
  }
  function hitTest(items, width, height, x, y, tolerance = 14) {
    if (![x, y, tolerance].every(Number.isFinite) || tolerance < 0) return null;
    let winner = null, nearest = tolerance * tolerance;
    for (const choice of handles(items)) {
      const point = canvasPosition(items, choice.key, width, height);
      if (!point) continue;
      const distance = (x - point.x) ** 2 + (y - point.y) ** 2;
      if (distance <= nearest) { nearest = distance; winner = choice.key; }
    }
    return winner;
  }
  const api = { handles, resolve, propose, canvasPosition, localPosition, hitTest };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HelpieGeometry = api;
})(globalThis);
