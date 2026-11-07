
export interface DeepLinkTarget {
  type: string;
  id: string;
}

export function parseDeepLink(url: string): DeepLinkTarget | null {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "vortis:") return null;

    const parts = parsed.pathname.replace(/^\/\//, "").split("/").filter(Boolean);

    if (parsed.hostname && parts.length >= 1) {
      return { type: parsed.hostname, id: parts[0] };
    }

    if (parts.length >= 2) {
      return { type: parts[0], id: parts[1] };
    }

    return null;
  } catch {
    return null;
  }
}
