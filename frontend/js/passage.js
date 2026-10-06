// Passage = fixed Grade 1 Braille text, one Cell per character (mirrors passage.py).
// When the backend has GET /passages/{id}, fetch it instead of using DEFAULT_PASSAGE.

const ASCII_TO_BRAILLE = {
  a: "⠁", b: "⠃", c: "⠉", d: "⠙", e: "⠑", f: "⠋", g: "⠛", h: "⠓",
  i: "⠊", j: "⠚", k: "⠅", l: "⠇", m: "⠍", n: "⠝", o: "⠕", p: "⠏",
  q: "⠟", r: "⠗", s: "⠎", t: "⠞", u: "⠥", v: "⠧", w: "⠺", x: "⠭",
  y: "⠽", z: "⠵", " ": "⠀",
};

export function textToBraille(text) {
  return [...text].map((ch) => ASCII_TO_BRAILLE[ch] ?? "⠀").join("");
}

export function makePassage(lines) {
  const widths = new Set(lines.map((l) => l.length));
  if (widths.size > 1) throw new Error("Passage lines must all have the same length");

  return {
    lines,
    numRows: lines.length,
    numColumns: lines[0]?.length ?? 0,
    charCount: lines.reduce((n, l) => n + l.replaceAll(" ", "").length, 0),
    wordCount: lines.reduce((n, l) => n + l.split(" ").filter(Boolean).length, 0),
  };
}

// Same text as build_default_passage() in passage.py.
export const DEFAULT_PASSAGE = makePassage([
  "read the texts",
  "with your eyes",
  "and count them",
]);

export async function loadPassage(httpUrl, passageId) {
  const res = await fetch(`${httpUrl}/passages/${encodeURIComponent(passageId)}`);
  if (!res.ok) throw new Error(`Could not load passage (${res.status})`);
  const data = await res.json();
  return makePassage(data.lines);
}
