/* Build a single-page PDF containing a user-selected JPEG note image. */
(function (root) {
  "use strict";
  function build(jpeg, width, height) {
    if (!(jpeg instanceof Uint8Array) || !jpeg.length || !Number.isInteger(width)
        || !Number.isInteger(height) || width < 1 || height < 1 || width > 16384 || height > 16384) {
      throw new Error("Invalid image");
    }
    const enc = new TextEncoder(), pieces = [], offsets = [0];
    let length = 0;
    const add = value => { const bytes = typeof value === "string" ? enc.encode(value) : value; pieces.push(bytes); length += bytes.length; };
    const obj = (id, body) => { offsets[id] = length; add(`${id} 0 obj\n${body}\nendobj\n`); };
    const pageWidth = 792, pageHeight = 612;
    const scale = Math.min(744 / width, 564 / height);
    const w = (width * scale).toFixed(2), h = (height * scale).toFixed(2);
    const x = ((pageWidth - Number(w)) / 2).toFixed(2), y = ((pageHeight - Number(h)) / 2).toFixed(2);
    add("%PDF-1.4\n");
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>");
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
    obj(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`);
    offsets[4] = length;
    add(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${width} /Height ${height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`);
    add(jpeg); add("\nendstream\nendobj\n");
    const content = `q\n${w} 0 0 ${h} ${x} ${y} cm\n/Im0 Do\nQ\n`;
    obj(5, `<< /Length ${enc.encode(content).length} >>\nstream\n${content}endstream`);
    const xref = length;
    add("xref\n0 6\n0000000000 65535 f \n");
    for (let i = 1; i <= 5; i++) add(`${String(offsets[i]).padStart(10, "0")} 00000 n \n`);
    add(`trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
    return new Blob(pieces, { type: "application/pdf" });
  }
  const api = { build };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.HelpieNotePdf = api;
})(globalThis);
