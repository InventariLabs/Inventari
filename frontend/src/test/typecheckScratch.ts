import * as path from "node:path";
import ts from "typescript";

/**
 * Type-checks files written to a scratch directory inside the frontend (a file
 * outside it cannot resolve `react` or `@/module-sdk`) with the project's own
 * compiler settings, and returns each problem found in them as
 * `<file>:<line> <message>` — an empty list when they compile.
 *
 * The tests that hold a guide's code blocks to "pastes and compiles" use it.
 */
export function typecheckScratch(
  frontendDir: string,
  scratchDir: string,
  files: string[],
): string[] {
  const config = ts.getParsedCommandLineOfConfigFile(
    path.join(frontendDir, "tsconfig.json"),
    {},
    {
      ...ts.sys,
      onUnRecoverableConfigFileDiagnostic: (d) => {
        throw new Error(ts.flattenDiagnosticMessageText(d.messageText, "\n"));
      },
    },
  );
  if (!config) throw new Error("frontend tsconfig.json could not be read");
  const program = ts.createProgram({
    // The test setup is in the project's program too: a spec's jest-dom
    // matchers (`toBeInTheDocument`) are typed by its import, not by the spec.
    rootNames: [
      ...files.map((name) => path.join(scratchDir, name)),
      path.join(frontendDir, "src", "test", "setup.ts"),
    ],
    options: { ...config.options, noEmit: true },
  });
  return ts
    .getPreEmitDiagnostics(program)
    .filter((d) => d.file && d.file.fileName.startsWith(scratchDir))
    .map((d) => {
      const { line } = d.file!.getLineAndCharacterOfPosition(d.start ?? 0);
      return `${path.relative(scratchDir, d.file!.fileName)}:${line + 1} ${ts.flattenDiagnosticMessageText(d.messageText, "\n")}`;
    });
}
