/**
 * State the twin keeps about its own world, in the shape the ECS wants.
 *
 * Nothing here is computed locally: `day`, `dueDay`, `fog` and `accuracyPct` are copied
 * from the backend's scene payload, and `hold` is copied from an input event. A prop that
 * could work out its own number would be a second opinion nobody asked for.
 */

import { Types, createComponent } from '@iwsdk/core';

export const Moods = {
  idle: 'idle',
  thinking: 'thinking',
  speaking: 'speaking',
  waiting: 'waiting',
  asking: 'asking',
  checking: 'checking',
  offline: 'offline',
} as const;

export const TwinState = createComponent('TwinState', {
  day: { type: Types.Int32, default: 0, label: 'Day' },
  horizonDays: { type: Types.Int32, default: 90, label: 'Horizon' },
  pinchDay: { type: Types.Int32, default: -1, label: 'Pinch day' },
});

export const RiverFlow = createComponent('RiverFlow', {
  dryAt: { type: Types.Int32, default: -1, label: 'First dry day' },
  flow: { type: Types.Float32, default: 1, label: 'Flow' },
});

export const BillStone = createComponent('BillStone', {
  eventKey: { type: Types.String, default: '' },
  label: { type: Types.String, default: '' },
  amountDollars: { type: Types.Float64, default: 0 },
  dueDay: { type: Types.Int32, default: 0 },
  belowSurface: { type: Types.Boolean, default: false },
});

export const LateBoat = createComponent('LateBoat', {
  eventKey: { type: Types.String, default: '' },
  label: { type: Types.String, default: '' },
  fog: { type: Types.Float32, default: 0 },
  worstLagDays: { type: Types.Int32, default: 0 },
  stuck: { type: Types.Boolean, default: false },
});

export const SubscriptionPipe = createComponent('SubscriptionPipe', {
  eventKey: { type: Types.String, default: '' },
  label: { type: Types.String, default: '' },
  amountDollars: { type: Types.Float64, default: 0 },
  cancelled: { type: Types.Boolean, default: false },
});

export const CashBranch = createComponent('CashBranch', {
  branchId: { type: Types.String, default: '' },
  label: { type: Types.String, default: '' },
  deltaDollars: { type: Types.Float64, default: 0 },
});

export const ForkRibbon = createComponent('ForkRibbon', {
  branchId: { type: Types.String, default: '' },
  pull: { type: Types.Float32, default: 0 },
});

export const TimeWheel = createComponent('TimeWheel', {
  day: { type: Types.Int32, default: 0 },
  turnDeg: { type: Types.Float32, default: 0 },
});

export const TwinOrb = createComponent('TwinOrb', {
  mood: { type: Types.Enum, default: Moods.idle, enum: Moods },
  accuracyPct: { type: Types.Float32, default: 0 },
  /** How many claims the twin has had answered. A percentage out of nothing is not a score. */
  resolved: { type: Types.Int32, default: 0 },
});

/**
 * The state the panels show, in one place.
 *
 * The voice system decides it once per change and writes it here; every other system
 * reads it instead of working out what the table is doing again. `holdPct` is copied from
 * the token a hand is gripping, so the gauge on the approval card and the coin are the same
 * measurement of the same gesture.
 */
export const TableVoice = createComponent('TableVoice', {
  mood: { type: Types.Enum, default: Moods.idle, enum: Moods, label: 'Mood' },
  holdPct: { type: Types.Float32, default: 0, label: 'Hold' },
  /** Requests the client is still waiting an answer on, so a slow twin is a state, not a freeze. */
  waitingOn: { type: Types.Int32, default: 0, label: 'Waiting on' },
});

export const ApprovalPrompt = createComponent('ApprovalPrompt', {
  hold: { type: Types.Float32, default: 0 },
  armed: { type: Types.Boolean, default: false },
});

/**
 * The audit firm's figures, on the card that shows them.
 *
 * Every one is a count the backend already made — roles it hired, numbers it derived
 * from the corpus, agreements a contract accepted or refused — copied here rather
 * than worked out again. A panel that added up its own findings would be a second
 * opinion about somebody else's arithmetic.
 */
export const FirmPanel = createComponent('FirmPanel', {
  /** Whether a contract was reached at all. Nothing on this card means more without it. */
  onChain: { type: Types.Boolean, default: false, label: 'On contract' },
  hired: { type: Types.Int32, default: 0, label: 'Roles hired' },
  refusedRoles: { type: Types.Int32, default: 0, label: 'Roles refused' },
  derived: { type: Types.Int32, default: 0, label: 'Derived figures' },
  figures: { type: Types.Int32, default: 0, label: 'Figures quoted' },
  /** Which engagement was last put to the firm, and how many there are to ask about. */
  engagement: { type: Types.Int32, default: -1, label: 'Engagement' },
  engagements: { type: Types.Int32, default: 0, label: 'Engagements' },
  opened: { type: Types.Int32, default: 0, label: 'Agreements opened' },
  refusedWrites: { type: Types.Int32, default: 0, label: 'Refused by contract' },
  waiting: { type: Types.Int32, default: 0, label: 'Waiting on a human' },
});
