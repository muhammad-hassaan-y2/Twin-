/**
 * Where the world sits on the table, and how dollars become metres.
 *
 * One file owns the mapping so a reviewer can check the metaphor once instead of
 * hunting it through the systems.
 */

import type { ScenePayload } from './client.js';

/** Metres of table the horizon occupies. The whole world fits inside this. */
export const SPAN = 0.9;
export const BANK_SEGMENTS = 15;
/** A bank at the largest balance in the horizon stands this tall. */
export const MAX_BANK_HEIGHT = 0.12;
export const RIVER_WIDTH = 0.12;
export const UPSTREAM_Z = -0.115;
export const UTILITY_Z = 0.155;
export const STONE_UNIT_HEIGHT = 0.022;
export const BANK_REST_HEIGHT = 0.2;

export function dayToX(day: number, horizon: number): number {
  const t = horizon <= 1 ? 0 : day / (horizon - 1);
  return (t - 0.5) * SPAN;
}

export function heightFor(dollars: number, scale: number): number {
  if (!Number.isFinite(dollars) || scale <= 0) return 0;
  return Math.max(-MAX_BANK_HEIGHT, Math.min(MAX_BANK_HEIGHT, (dollars / scale) * MAX_BANK_HEIGHT));
}

/** The largest absolute balance in the fan, which is what one bank-height is worth. */
export function dollarScale(payload: ScenePayload): number {
  const all = [...payload.river.p90_dollars, ...payload.river.p10_dollars.map((v) => -v)];
  return Math.max(1, ...all.map(Math.abs));
}

export function segmentDay(index: number, horizon: number): number {
  const t = (index + 0.5) / BANK_SEGMENTS;
  return Math.min(horizon - 1, Math.round(t * (horizon - 1)));
}
