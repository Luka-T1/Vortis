interface AnalyticsInvitation {
  ready: boolean;
  sharingModalSeen: boolean;
  open: () => void;
  markSharingModalSeen: () => void;
}

export function offerAnalyticsChoice(_args: AnalyticsInvitation): (() => void) | undefined {
  return undefined;
}
