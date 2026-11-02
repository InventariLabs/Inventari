/**
 * Barcode modules for the fake camera. Both encoders return plain module
 * data — the fake camera draws it — so a spec renders the code it names
 * instead of shipping an image of it.
 */

const L_CODES = [
  "0001101",
  "0011001",
  "0010011",
  "0111101",
  "0100011",
  "0110001",
  "0101111",
  "0111011",
  "0110111",
  "0001011",
];
const G_CODES = [
  "0100111",
  "0110011",
  "0011011",
  "0100001",
  "0011101",
  "0111001",
  "0000101",
  "0010001",
  "0001001",
  "0010111",
];
const R_CODES = [
  "1110010",
  "1100110",
  "1101100",
  "1000010",
  "1011100",
  "1001110",
  "1010000",
  "1000100",
  "1001000",
  "1110100",
];
const PARITY = [
  "LLLLLL",
  "LLGLGG",
  "LLGGLG",
  "LLGGGL",
  "LGLLGG",
  "LGGLLG",
  "LGGGLL",
  "LGLGLG",
  "LGLGGL",
  "LGGLGL",
];

function ean13CheckDigit(first12: string): number {
  let sum = 0;
  for (let i = 0; i < 12; i++)
    sum += Number(first12[i]) * (i % 2 === 0 ? 1 : 3);
  return (10 - (sum % 10)) % 10;
}

/** The bars of an EAN-13 as a string of 0/1 modules (95 of them). */
export function ean13Modules(code: string): string {
  if (!/^\d{13}$/.test(code))
    throw new Error(`EAN-13 needs 13 digits: ${code}`);
  if (ean13CheckDigit(code.slice(0, 12)) !== Number(code[12])) {
    throw new Error(`EAN-13 check digit is wrong: ${code}`);
  }
  const parity = PARITY[Number(code[0])];
  let bars = "101";
  for (let i = 0; i < 6; i++) {
    const digit = Number(code[i + 1]);
    bars += parity[i] === "L" ? L_CODES[digit] : G_CODES[digit];
  }
  bars += "01010";
  for (let i = 7; i < 13; i++) bars += R_CODES[Number(code[i])];
  return bars + "101";
}

// --- QR: version 2, error correction L, byte mode (up to 32 bytes).
// The mask is chosen by the standard's penalty score, as a real encoder does.
// Mask 0 alone used to be drawn for every payload, and for some (LOC-Y9MJ, a
// storage code a stack happened to generate) it left patterns the scanner's
// detector could not lock onto, so a spec passed or failed with the data.

const GF_EXP: number[] = [];
const GF_LOG: number[] = new Array(256).fill(0);
for (let i = 0, x = 1; i < 255; i++) {
  GF_EXP[i] = x;
  GF_LOG[x] = i;
  x <<= 1;
  if (x & 0x100) x ^= 0x11d;
}
const gfMul = (a: number, b: number) =>
  a === 0 || b === 0 ? 0 : GF_EXP[(GF_LOG[a] + GF_LOG[b]) % 255];

function reedSolomon(data: number[], ecLength: number): number[] {
  let gen = [1];
  for (let i = 0; i < ecLength; i++) {
    const next = new Array(gen.length + 1).fill(0);
    gen.forEach((c, j) => {
      next[j] ^= c;
      next[j + 1] ^= gfMul(c, GF_EXP[i]);
    });
    gen = next;
  }
  const rem = new Array(ecLength).fill(0);
  for (const byte of data) {
    const factor = byte ^ rem.shift();
    rem.push(0);
    gen.slice(1).forEach((c, j) => {
      rem[j] ^= gfMul(c, factor);
    });
  }
  return rem;
}

const QR_SIZE = 25;
const QR_DATA_CODEWORDS = 34;
const QR_EC_CODEWORDS = 10;

/** The 15 format bits for level L and `mask`: BCH-coded, then XOR-masked. */
function formatBitsL(mask: number): number {
  const data = (0b01 << 3) | mask; // level L is 01
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  return ((data << 10) | (rem & 0x3ff)) ^ 0x5412;
}

const MASKS: Array<(r: number, c: number) => boolean> = [
  (r, c) => (r + c) % 2 === 0,
  (r) => r % 2 === 0,
  (_, c) => c % 3 === 0,
  (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
  (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
  (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
];

/** The standard's penalty (ISO/IEC 18004, 7.8.3): lower reads more easily. */
function penalty(m: boolean[][]): number {
  const n = m.length;
  let score = 0;
  const lines = [...m, ...m.map((_, c) => m.map((row) => row[c]))];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= n; i++) {
      if (i < n && line[i] === line[i - 1]) run++;
      else {
        if (run >= 5) score += 3 + (run - 5);
        run = 1;
      }
    }
    const s = line.map((v) => (v ? "1" : "0")).join("");
    for (
      let i = s.indexOf("1011101");
      i !== -1;
      i = s.indexOf("1011101", i + 1)
    ) {
      const before = s.slice(Math.max(0, i - 4), i);
      const after = s.slice(i + 7, i + 11);
      if (before === "0000" || after === "0000") score += 40;
    }
  }
  for (let r = 0; r < n - 1; r++) {
    for (let c = 0; c < n - 1; c++) {
      const v = m[r][c];
      if (m[r][c + 1] === v && m[r + 1][c] === v && m[r + 1][c + 1] === v)
        score += 3;
    }
  }
  const dark = m.flat().filter(Boolean).length;
  score += 10 * Math.floor(Math.abs((dark * 100) / (n * n) - 50) / 5);
  return score;
}

/** A QR code (version 2-L) as rows of booleans; true is a dark module. */
export function qrModules(text: string): boolean[][] {
  const bytes = Array.from(new TextEncoder().encode(text));
  if (bytes.length > 32) throw new Error("QR payload is limited to 32 bytes");

  let bits = "0100" + bytes.length.toString(2).padStart(8, "0");
  for (const b of bytes) bits += b.toString(2).padStart(8, "0");
  bits += "0".repeat(Math.min(4, QR_DATA_CODEWORDS * 8 - bits.length));
  bits += "0".repeat((8 - (bits.length % 8)) % 8);
  const data: number[] = [];
  for (let i = 0; i < bits.length; i += 8)
    data.push(parseInt(bits.slice(i, i + 8), 2));
  for (let pad = 0; data.length < QR_DATA_CODEWORDS; pad++)
    data.push(pad % 2 === 0 ? 0xec : 0x11);
  const all = [...data, ...reedSolomon(data, QR_EC_CODEWORDS)];
  const stream =
    all.map((b) => b.toString(2).padStart(8, "0")).join("") + "0000000"; // 7 remainder bits

  const dark: boolean[][] = Array.from({ length: QR_SIZE }, () =>
    new Array(QR_SIZE).fill(false),
  );
  const reserved: boolean[][] = Array.from({ length: QR_SIZE }, () =>
    new Array(QR_SIZE).fill(false),
  );
  const set = (r: number, c: number, v: boolean) => {
    if (r < 0 || c < 0 || r >= QR_SIZE || c >= QR_SIZE) return;
    dark[r][c] = v;
    reserved[r][c] = true;
  };

  const finder = (r0: number, c0: number) => {
    for (let r = -1; r <= 7; r++) {
      for (let c = -1; c <= 7; c++) {
        const ring = Math.max(Math.abs(r - 3), Math.abs(c - 3));
        set(r0 + r, c0 + c, r >= 0 && r <= 6 && c >= 0 && c <= 6 && ring !== 2);
      }
    }
  };
  finder(0, 0);
  finder(0, QR_SIZE - 7);
  finder(QR_SIZE - 7, 0);
  for (let r = -2; r <= 2; r++) {
    for (let c = -2; c <= 2; c++) {
      set(18 + r, 18 + c, Math.max(Math.abs(r), Math.abs(c)) !== 1);
    }
  }
  for (let i = 8; i < QR_SIZE - 8; i++) {
    set(6, i, i % 2 === 0);
    set(i, 6, i % 2 === 0);
  }
  set(QR_SIZE - 8, 8, true); // the always-dark module

  // Reserve the format areas before the data goes in; each mask writes its own
  // format bits there below.
  const formatCells: Array<[number, number, number]> = [];
  for (let i = 0; i < 15; i++) {
    // first copy: around the top-left finder
    if (i < 6) formatCells.push([i, 8, i]);
    else if (i < 8) formatCells.push([i + 1, 8, i]);
    else if (i === 8) formatCells.push([8, 7, i]);
    else formatCells.push([8, 14 - i, i]);
    // second copy: split between the other two finders
    if (i < 8) formatCells.push([8, QR_SIZE - 1 - i, i]);
    else formatCells.push([QR_SIZE - 15 + i, 8, i]);
  }
  for (const [r, c] of formatCells) set(r, c, false);

  let k = 0;
  let upward = true;
  for (let col = QR_SIZE - 1; col > 0; col -= 2) {
    if (col === 6) col--;
    for (let n = 0; n < QR_SIZE; n++) {
      const r = upward ? QR_SIZE - 1 - n : n;
      for (const c of [col, col - 1]) {
        if (reserved[r][c]) continue;
        dark[r][c] = stream[k++] === "1";
      }
    }
    upward = !upward;
  }

  let best: boolean[][] = dark;
  let bestScore = Infinity;
  MASKS.forEach((mask, index) => {
    const candidate = dark.map((row, r) =>
      row.map((v, c) => (!reserved[r][c] && mask(r, c) ? !v : v)),
    );
    const format = formatBitsL(index);
    for (const [r, c, i] of formatCells)
      candidate[r][c] = ((format >> i) & 1) === 1;
    const score = penalty(candidate);
    if (score < bestScore) {
      best = candidate;
      bestScore = score;
    }
  });
  return best;
}
