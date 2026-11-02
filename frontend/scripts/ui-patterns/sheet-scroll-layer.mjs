export default {
  name: "sheet-scroll-layer",
  says:
    "A `Sheet` panel is `overflow-hidden`, so a body longer than the panel " +
    "is clipped and unreachable — the page scroll is locked while a sheet " +
    "is open, and nothing else can scroll it.",
  advice:
    "Wrap the sheet body in <SheetBody>, or give the scrolling region\n" +
    "overflow-y-auto of its own.",

  run(files) {
    const considered = files.filter((f) => /<Sheet([\s>]|$)/.test(f.text));
    const findings = [];

    for (const file of considered) {
      if (/\bSheetBody\b/.test(file.text)) continue;
      if (/overflow-(y-)?auto/.test(file.text)) continue;
      findings.push(file.path);
    }

    return { considered: considered.length, findings };
  },
};
