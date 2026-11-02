export default {
  name: "border-weight",
  says:
    "`border-2` is off the scale — one border weight, 1px, in every context " +
    "(UI_GUIDELINES §2.10). Two pixels change a control's outer box, so it " +
    "stops aligning with the inputs and buttons it sits next to.",
  advice:
    "Emphasis is colour plus fill (border-primary-500 with a tint), never\n" +
    "thickness. The one exception is a transparent border used as geometry\n" +
    "rather than as a frame — a switch track's knob inset.",

  run(files) {
    const considered = files.filter((f) => /border-2/.test(f.text));
    const findings = [];

    for (const file of considered) {
      file.text.split("\n").forEach((line, i) => {
        if (!/\bborder-2\b/.test(line)) return;
        if (/border-2 border-transparent/.test(line)) return;
        findings.push(`${file.path}:${i + 1}`);
      });
    }

    return { considered: considered.length, findings };
  },
};
