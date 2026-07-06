import { marked } from "marked";

export function Markdown({ children, className = "" }: { children: string; className?: string }) {
  const html = marked.parse(children, { async: false }) as string;
  return (
    <div
      className={`md-content ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
