/**
 * State the twin keeps about its own world, in the shape the ECS wants.
 *
 * Nothing here is computed locally: `day`, `p10/p50/p90` and the approval
 * verdicts are all copied from the backend's scene payload.
 */

import { Types, createComponent } from '@iwsdk/core';

export const Moods = { idle: 'idle', speaking: 'speaking', pointing: 'pointing', waiting: 'waiting' } as const;

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
});

export const ApprovalPrompt = createComponent('ApprovalPrompt', {
  hold: { type: Types.Float32, default: 0 },
  armed: { type: Types.Boolean, default: false },
});
