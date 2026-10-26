/** Motion constants for framer-motion (mirrors tokens.css; seconds). */
export const motion = {
  fast: 0.12,
  base: 0.2,
  slow: 0.36,
  ease: [0.2, 0.7, 0.2, 1] as [number, number, number, number],
  stagger: 0.03,
  spring: { type: "spring" as const, stiffness: 520, damping: 28, mass: 0.9 },
};

/** Where an item stands, in the order the runway bar shows it. */
export const STATES = ["auto", "done", "client", "review", "parked"] as const;
export type ItemState = (typeof STATES)[number];

export const STATE_LABEL: Record<ItemState, string> = {
  auto: "Automatisch gebucht",
  done: "Geprüft gebucht",
  client: "Beim Mandanten",
  review: "Zu prüfen",
  parked: "Klärungskonto",
};
