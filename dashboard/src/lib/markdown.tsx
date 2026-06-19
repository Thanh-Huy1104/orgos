"use client";

import { useMemo } from "react";
import { marked } from "marked";

// configure marked for GitHub-ish output
marked.setOptions({
  gfm: true,
  breaks: false,
});

export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => marked.parse(text) as string, [text]);
  return (
    <div
      className="md-content"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
