/* Serialize validated visual-note data as SVG primitives, never model markup. */
(function (root) {
  "use strict";
  const esc = s => Array.from(String(s ?? ""), c => {
    const n = c.codePointAt(0);
    return n >= 0xd800 && n <= 0xdfff ? "\ufffd" : c;
  }).join("").replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]/g, "")
    .replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"})[c]);
  const valid = n => typeof n === "number" && Number.isFinite(n) && n >= 0 && n <= 1;
  function describe(items, strokes) {
    const parts = (Array.isArray(items) ? items : []).slice(0, 3).map((item, index) => {
      if (!item || typeof item !== "object") return `${index + 1}. visual item`;
      let detail = typeof item.label === "string" ? item.label : typeof item.text === "string" ? item.text : typeof item.expression === "string" ? item.expression : "";
      detail = detail.replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 120);
      if (item.kind === "geometry" && Array.isArray(item.objects)) {
        const shapes = item.objects.slice(0, 12).filter(o => o && ["point", "segment", "circle", "polygon"].includes(o.kind))
          .map(o => `${o.kind}${typeof o.label === "string" && o.label ? ` ${o.label.replace(/[\x00-\x1f\x7f]/g, " ").slice(0, 32)}` : ""}`);
        detail = shapes.join(", ");
      }
      const kind = ["pin", "callout", "rect", "arrow", "underline", "equation", "graph", "geometry"].includes(item.kind) ? item.kind : "visual item";
      return `${index + 1}. ${kind}${detail ? `: ${detail}` : ""}`;
    });
    const count = Math.min(Array.isArray(strokes) ? strokes.length : 0, 200);
    return `${parts.length ? `Visual answer: ${parts.join("; ")}. ` : ""}Drawing strokes: ${count}.`;
  }
  function build(items, strokes, width, height) {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0 || width > 10000 || height > 10000) throw new Error("Invalid dimensions");
    const out = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-labelledby="note-title note-description">`, '<title id="note-title">Helpie visual note</title>', `<desc id="note-description">${Math.min(Array.isArray(items) ? items.length : 0, 3)} visual items and ${Math.min(Array.isArray(strokes) ? strokes.length : 0, 200)} drawing strokes.</desc>`, '<rect width="100%" height="100%" fill="#080d14"/>'];
    const label = (text, x, y, size = 14) => { if (text) out.push(`<text x="${x}" y="${y}" fill="#fff" font-family="Segoe UI, sans-serif" font-size="${size}" font-weight="600">${esc(String(text).slice(0, 120))}</text>`); };
    const line = (x1,y1,x2,y2) => out.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#55d6ff" stroke-width="3"/>`);
    for (const item of (Array.isArray(items) ? items : []).slice(0,3)) {
      if (!item || typeof item !== "object") continue;
      const x = item.x * width, y = item.y * height, w = item.width * width, h = item.height * height;
      if ((item.kind === "pin" || item.kind === "callout") && valid(item.x) && valid(item.y)) {
        out.push(`<circle cx="${x}" cy="${y}" r="10" fill="#ffca52"/>`);
        if (item.kind === "callout" && Number.isInteger(item.number) && item.number >= 1 && item.number <= 3) out.push(`<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" font-weight="700" fill="#07111f">${item.number}</text>`);
        label(item.label,x+15,y-10);
      } else if (item.kind === "rect" && [item.x,item.y,item.width,item.height].every(valid)) {
        out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#ffca52" fill-opacity="0.12" stroke="#55d6ff" stroke-width="3"/>`); label(item.label,x,y-7);
      } else if ((item.kind === "arrow" || item.kind === "underline") && [item.x1,item.y1,item.x2,item.y2].every(valid)) {
        const x1=item.x1*width,y1=item.y1*height,x2=item.x2*width,y2=item.y2*height,a=Math.atan2(y2-y1,x2-x1); line(x1,y1,x2,y2);
        if (item.kind === "arrow") out.push(`<polygon points="${x2},${y2} ${x2-11*Math.cos(a-.45)},${y2-11*Math.sin(a-.45)} ${x2-11*Math.cos(a+.45)},${y2-11*Math.sin(a+.45)}" fill="#55d6ff"/>`); label(item.label,(x1+x2)/2,(y1+y2)/2-8);
      } else if (item.kind === "equation" && valid(item.x) && valid(item.y)) label(item.text,x,y,20);
      else if (item.kind === "graph" && [item.x,item.y,item.width,item.height].every(valid) && Array.isArray(item.segments)) {
        out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="#08111d" stroke="#83a4c8"/>`);
        for (let n=1;n<4;n++) {
          out.push(`<line x1="${x+w*n/4}" y1="${y}" x2="${x+w*n/4}" y2="${y+h}" stroke="#b0cdeb" stroke-opacity="0.3" stroke-width="1"/>`);
          out.push(`<line x1="${x}" y1="${y+h*n/4}" x2="${x+w}" y2="${y+h*n/4}" stroke="#b0cdeb" stroke-opacity="0.3" stroke-width="1"/>`);
        }
        for (const segment of item.segments.slice(0,65)) if (Array.isArray(segment) && segment.length <= 65 && segment.length >= 2 && segment.every(p => Array.isArray(p) && p.length===2 && p.every(valid))) out.push(`<polyline fill="none" stroke="#55d6ff" stroke-width="2" points="${segment.map(p=>`${x+p[0]*w},${y+p[1]*h}`).join(" ")}"/>`);
        label(`f(x) = ${item.expression || ""}`,x,y-5);
      } else if (item.kind === "geometry" && [item.x,item.y,item.width,item.height].every(valid) && Array.isArray(item.objects)) {
        const objects=item.objects.slice(0,12), pos=(a,b)=>[x+a*w,y+b*h];
        objects.forEach(o=>{ if(!o || typeof o!=="object") return;
          if(o.kind==="point" && [o.x,o.y].every(valid)){const [a,b]=pos(o.x,o.y);out.push(`<circle cx="${a}" cy="${b}" r="4" fill="#ffca52"/>`);label(o.label,a+7,b-6,12);}
          else if(o.kind==="segment" && [o.x1,o.y1,o.x2,o.y2].every(valid)){const [a,b]=pos(o.x1,o.y1),[c,d]=pos(o.x2,o.y2);line(a,b,c,d);label(o.label,(a+c)/2+5,(b+d)/2-5,12);}
          else if(o.kind==="circle" && [o.cx,o.cy,o.radius].every(valid)){const [a,b]=pos(o.cx,o.cy);out.push(`<ellipse cx="${a}" cy="${b}" rx="${o.radius*w}" ry="${o.radius*h}" fill="none" stroke="#8be9ff" stroke-width="2"/>`);label(o.label,a+o.radius*w+4,b,12);}
          else if(o.kind==="polygon" && Array.isArray(o.points) && o.points.length>=3 && o.points.length<=8 && o.points.every(p=>Array.isArray(p)&&p.length===2&&p.every(valid))){out.push(`<polygon points="${o.points.map(p=>pos(p[0],p[1]).join(",")).join(" ")}" fill="none" stroke="#8be9ff" stroke-width="2"/>`);const a=o.points.reduce((s,p)=>s+p[0],0)/o.points.length,b=o.points.reduce((s,p)=>s+p[1],0)/o.points.length;label(o.label,x+a*w+5,y+b*h-5,12);}
        });
        const marks={horizontal:"↔",vertical:"↕",equal:"=",perpendicular:"⊥",parallel:"∥"};
        for(const c of (Array.isArray(item.constraints)?item.constraints:[]).slice(0,8)){if(!Object.hasOwn(marks,c?.kind)||!Array.isArray(c.objects)||c.objects.length!==(["horizontal","vertical"].includes(c.kind)?1:2)||!c.objects.every(i=>Number.isInteger(i)&&objects[i]?.kind==="segment"&&[objects[i].x1,objects[i].y1,objects[i].x2,objects[i].y2].every(valid)))continue;const pts=c.objects.map(i=>pos((objects[i].x1+objects[i].x2)/2,(objects[i].y1+objects[i].y2)/2));label(marks[c.kind],pts.reduce((s,p)=>s+p[0],0)/pts.length,pts.reduce((s,p)=>s+p[1],0)/pts.length,16);}
      }
    }
    const colors = new Set(["#55d6ff", "#f59e0b", "#f472b6", "#f8fafc"]);
    for (const stroke of (Array.isArray(strokes)?strokes:[]).slice(0,200)) {
      if (!stroke || !colors.has(stroke.color) || !Number.isFinite(stroke.size) || stroke.size<1 || stroke.size>20 || !Array.isArray(stroke.points) || stroke.points.length<1 || stroke.points.length>500 || !stroke.points.every(p=>p&&valid(p.x)&&valid(p.y))) continue;
      const points=stroke.points.map(p=>`${p.x*width},${p.y*height}`).join(" ");
      if(stroke.points.length===1) out.push(`<circle cx="${stroke.points[0].x*width}" cy="${stroke.points[0].y*height}" r="${stroke.size/2}" fill="${stroke.color}"/>`);
      else out.push(`<polyline points="${points}" fill="none" stroke="${stroke.color}" stroke-width="${stroke.size}" stroke-linecap="round" stroke-linejoin="round"/>`);
    }
    out.push("</svg>"); return out.join("\n");
  }
  const api={build,describe}; if(typeof module!=="undefined"&&module.exports) module.exports=api; else root.HelpieNoteSvg=api;
})(globalThis);
