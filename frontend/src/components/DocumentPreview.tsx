import type { CSSProperties } from "react";
import type { PreviewBlock, RunStyle } from "../api";

function runStyleToCss(style: RunStyle): CSSProperties {
  return {
    fontFamily: style.font ?? undefined,
    fontSize: style.size ? `${style.size}pt` : undefined,
    color: style.color ?? undefined,
    fontWeight: style.bold ? 600 : undefined,
    fontStyle: style.italic ? "italic" : undefined,
    textDecoration: style.underline ? "underline" : undefined,
  };
}

interface Group {
  key: string;
  blocks: PreviewBlock[];
}

function groupByParagraph(blocks: PreviewBlock[]): Group[] {
  const groups: Group[] = [];
  for (const block of blocks) {
    const last = groups[groups.length - 1];
    if (last && last.key === block.group_key) {
      last.blocks.push(block);
    } else {
      groups.push({ key: block.group_key, blocks: [block] });
    }
  }
  return groups;
}

function spanClassName(block: PreviewBlock, side: "original" | "tailored"): string | undefined {
  const classes: string[] = [];
  if (block.editable === false) classes.push("block-fixed");
  if (side === "tailored" && block.changed) classes.push("block-changed");
  return classes.length ? classes.join(" ") : undefined;
}

function spanTitle(block: PreviewBlock, side: "original" | "tailored"): string | undefined {
  if (block.editable === false) return "Not eligible for editing";
  if (side === "tailored" && block.changed) return "Changed";
  return undefined;
}

export function DocumentPreview({ title, blocks }: { title: string; blocks: PreviewBlock[] }) {
  const groups = groupByParagraph(blocks);

  return (
    <div className="document-preview">
      <h3>{title}</h3>
      <div className="preview-columns">
        <div className="preview-column">
          <div className="preview-column-label">Original</div>
          {groups.map((group) => (
            <p key={group.key}>
              {group.blocks.map((block) => (
                <span
                  key={block.id}
                  style={runStyleToCss(block.run_style)}
                  className={spanClassName(block, "original")}
                  title={spanTitle(block, "original")}
                >
                  {block.original_text}
                </span>
              ))}
            </p>
          ))}
        </div>
        <div className="preview-column">
          <div className="preview-column-label">Tailored</div>
          {groups.map((group) => (
            <p key={group.key}>
              {group.blocks.map((block) => (
                <span
                  key={block.id}
                  style={runStyleToCss(block.run_style)}
                  className={spanClassName(block, "tailored")}
                  title={spanTitle(block, "tailored")}
                >
                  {block.tailored_text}
                </span>
              ))}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}
