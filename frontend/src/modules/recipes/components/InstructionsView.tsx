import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { Lightbulb } from "lucide-react";
import { STEP_RE, TIP_RE } from "../constants/instructionPrefixes";

interface InstructionsViewProps {
  text: string;
}

export interface ParsedBlock {
  type: "step" | "tip" | "text";
  stepNumber?: number;
  title?: string;
  body: string;
}

/** Detects whether the text uses markdown formatting */
const MD_HINT_RE =
  /(?:^#{1,6}\s|[*_]{1,2}\S|\n-\s|\n\d+\.\s|\[.+?\]\(.+?\)|^>\s)/m;

export function hasMarkdown(text: string): boolean {
  return MD_HINT_RE.test(text);
}

export function parseInstructions(text: string): ParsedBlock[] {
  const lines = text.split("\n");
  const blocks: ParsedBlock[] = [];
  let current: ParsedBlock | null = null;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (current) current.body += "\n";
      continue;
    }

    const stepMatch = trimmed.match(STEP_RE);
    if (stepMatch) {
      if (current) blocks.push(current);
      current = {
        type: "step",
        stepNumber: parseInt(stepMatch[1], 10),
        title: stepMatch[2].trim(),
        body: "",
      };
      continue;
    }

    const tipMatch = trimmed.match(TIP_RE);
    if (tipMatch) {
      if (current) blocks.push(current);
      current = { type: "tip", body: tipMatch[1].trim() };
      continue;
    }

    if (current) {
      current.body += (current.body ? "\n" : "") + trimmed;
    } else {
      current = { type: "text", body: trimmed };
    }
  }
  if (current) blocks.push(current);

  return blocks;
}

export function InstructionsView({ text }: InstructionsViewProps) {
  const isMarkdown = useMemo(() => hasMarkdown(text), [text]);
  const blocks = useMemo(
    () => (isMarkdown ? [] : parseInstructions(text)),
    [text, isMarkdown],
  );

  if (!text.trim()) return null;

  // Markdown path
  if (isMarkdown) {
    return (
      <div className="max-w-none text-sm text-on-secondary leading-relaxed [&_h1]:text-base [&_h1]:font-medium [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-sm [&_h2]:font-medium [&_h2]:mt-3 [&_h2]:mb-1.5 [&_h3]:text-sm [&_h3]:font-medium [&_h3]:mt-2 [&_h3]:mb-1 [&_p]:mb-2 [&_ul]:pl-5 [&_ul]:list-disc [&_ul]:mb-2 [&_ol]:pl-5 [&_ol]:list-decimal [&_ol]:mb-2 [&_li]:mb-0.5 [&_strong]:font-medium [&_em]:italic [&_blockquote]:border-l-2 [&_blockquote]:border-amber-300 [&_blockquote]:bg-amber-50 [&_blockquote]:italic [&_blockquote]:text-on-warning [&_blockquote]:text-xs [&_blockquote]:pl-3 [&_blockquote]:py-2 [&_blockquote]:my-2 [&_blockquote]:rounded-r-lg [&_a]:text-on-primary [&_a]:underline">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{text}</ReactMarkdown>
      </div>
    );
  }

  // If no step patterns detected, fall back to plain pre-wrap text
  const hasSteps = blocks.some((b) => b.type === "step");
  if (!hasSteps) {
    return (
      <p className="text-sm text-on-secondary whitespace-pre-wrap leading-relaxed">
        {text}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {blocks.map((block, i) => {
        if (block.type === "step") {
          return (
            <div key={i} className="flex gap-3">
              <div className="flex-shrink-0 w-7 h-7 rounded-full bg-accent-50 border border-accent-200 flex items-center justify-center mt-0.5">
                <span className="text-xs font-medium text-accent-700">
                  {block.stepNumber}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                {block.title && (
                  <h3 className="text-sm font-semibold text-on mb-1">
                    {block.title}
                  </h3>
                )}
                {block.body.trim() && (
                  <p className="text-sm text-on-secondary leading-relaxed whitespace-pre-wrap">
                    {block.body.trim()}
                  </p>
                )}
              </div>
            </div>
          );
        }

        if (block.type === "tip") {
          return (
            <div
              key={i}
              className="ml-10 pl-3 border-l-2 border-amber-300 bg-amber-50 rounded-r-lg py-2 pr-3"
            >
              <p className="text-xs text-on-warning leading-relaxed">
                <Lightbulb
                  size={12}
                  className="inline-block mr-1 text-on-warning align-[-1px]"
                />
                {block.body.trim()}
              </p>
            </div>
          );
        }

        return (
          <p
            key={i}
            className="text-sm text-on-secondary leading-relaxed whitespace-pre-wrap"
          >
            {block.body.trim()}
          </p>
        );
      })}
    </div>
  );
}
