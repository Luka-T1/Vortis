import type { ResearchSource } from '../types';

interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

const SKIP_TAGS = new Set(['code', 'pre', 'script', 'style']);

const CITATION_RE =
  /\[(\s*\d+(?:\s*,\s*\d+)*\s*)\](\s+(?=[.,;:!?]))?/g;

const TOOLTIP_DATE = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

function formatTooltipDate(iso: string | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.trim() || null;
  return TOOLTIP_DATE.format(d);
}

function buildTooltip(src: ResearchSource): string {
  const parts: string[] = [];
  if (src.title) parts.push(src.title);
  const meta: string[] = [];
  if (src.sender) meta.push(src.sender);
  const date = formatTooltipDate(src.date);
  if (date) meta.push(date);
  if (meta.length > 0) parts.push(meta.join(' · '));
  return parts.join('\n');
}

function buildPill(n: number, src: ResearchSource): HastNode {
  return {
    type: 'element',
    tagName: 'a',
    properties: {
      href: src.url,
      target: '_blank',
      rel: 'noopener noreferrer',
      className: ['research-citation'],
      'data-ref': String(n),
      title: buildTooltip(src) || `Source ${n}`,
    },
    children: [{ type: 'text', value: String(n) }],
  };
}

function parseRefList(inner: string): number[] {
  return inner
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => !Number.isNaN(n));
}

export function rehypeCitations(options: {
  sources: Map<number, ResearchSource>;
}) {
  const { sources } = options;
  if (sources.size === 0) {
    return () => undefined;
  }

  function transformText(text: string): HastNode[] | null {
    if (!text.includes('[')) return null;

    const pieces: HastNode[] = [];
    let lastIndex = 0;
    let m: RegExpExecArray | null;
    CITATION_RE.lastIndex = 0;
    let changed = false;

    while ((m = CITATION_RE.exec(text)) !== null) {
      const refs = parseRefList(m[1]);
      const resolved = refs.map((n) => ({ n, src: sources.get(n) }));
      const allMatched =
        resolved.length > 0 && resolved.every((r) => r.src && r.src.url);

      if (m.index > lastIndex) {
        pieces.push({ type: 'text', value: text.slice(lastIndex, m.index) });
      }

      if (allMatched) {
        for (const r of resolved) {
          pieces.push(buildPill(r.n, r.src!));
        }
        changed = true;
      } else {
        pieces.push({ type: 'text', value: m[0] });
      }

      lastIndex = m.index + m[0].length;
    }

    if (!changed) return null;

    if (lastIndex < text.length) {
      pieces.push({ type: 'text', value: text.slice(lastIndex) });
    }
    return pieces;
  }

  function tryMarkdownCitationLink(node: HastNode): HastNode | null {
    if (
      node.type !== 'element' ||
      node.tagName !== 'a' ||
      !node.children ||
      node.children.length !== 1
    ) {
      return null;
    }
    const child = node.children[0];
    if (child.type !== 'text' || typeof child.value !== 'string') return null;

    const trimmed = child.value.trim();
    if (!/^\d+$/.test(trimmed)) return null;

    const n = parseInt(trimmed, 10);
    const src = sources.get(n);
    if (!src || !src.url) return null;

    return buildPill(n, src);
  }

  function walk(node: HastNode): void {
    if (!node.children || node.children.length === 0) return;
    if (node.tagName && SKIP_TAGS.has(node.tagName)) return;

    const out: HastNode[] = [];
    let changed = false;

    for (const child of node.children) {
      const promoted = tryMarkdownCitationLink(child);
      if (promoted) {
        out.push(promoted);
        changed = true;
        continue;
      }

      if (child.type === 'element') {
        if (child.tagName !== 'a') walk(child);
        out.push(child);
        continue;
      }

      if (child.type === 'text' && typeof child.value === 'string') {
        const replaced = transformText(child.value);
        if (replaced) {
          out.push(...replaced);
          changed = true;
        } else {
          out.push(child);
        }
        continue;
      }

      out.push(child);
    }

    if (changed) {
      node.children = out;
    }
  }

  return (tree: HastNode) => {
    walk(tree);
  };
}
