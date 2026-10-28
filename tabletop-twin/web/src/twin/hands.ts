/**
 * Hands are the only controller this app has.
 *
 * Each gesture maps to one documented IWSDK interaction and one backend call:
 * twist the wheel (proximity grab, rotate only), pull the ribbon or a pipe (ray
 * grab with spring-back), and hold the approval token for a full second.
 * A gesture never executes anything — it only ever asks.
 */

import { Grabbed, Object3D, createSystem, type Entity } from '@iwsdk/core';
import { twin } from './controller.js';
import { ApprovalPrompt, ForkRibbon, SubscriptionPipe, TimeWheel } from './components.js';

/** A pinch shorter than this is not an approval. It is an accident. */
export const APPROVAL_HOLD_SEC = 1;
/** How far a pipe or ribbon must travel before the twin treats it as a pull. */
export const PULL_METRES = 0.05;

export class TwinHandsSystem extends createSystem({
  wheels: { required: [TimeWheel] },
  heldWheels: { required: [TimeWheel, Grabbed] },
  ribbons: { required: [ForkRibbon] },
  heldRibbons: { required: [ForkRibbon, Grabbed] },
  pipes: { required: [SubscriptionPipe] },
  heldPipes: { required: [SubscriptionPipe, Grabbed] },
  tokens: { required: [ApprovalPrompt] },
  heldTokens: { required: [ApprovalPrompt, Grabbed] },
}) {
  private origins = new Map<Entity, number>();
  private travelled = new Map<Entity, number>();
  private wheel?: Object3D;
  private debounce = 0;
  private pendingDay = -1;
  private stopping: Array<() => void> = [];

  init(): void {
    for (const entity of this.queries.wheels.entities) {
      this.wheel = entity.object3D as Object3D;
      break;
    }
    this.stopping.push(
      this.queries.heldTokens.subscribe('disqualify', (entity: Entity) => {
        entity.setValue(ApprovalPrompt, 'hold', 0);
        entity.setValue(ApprovalPrompt, 'armed', false);
      }),
    );
    this.stopping.push(
      this.queries.heldPipes.subscribe('disqualify', (entity: Entity) => this.releasePipe(entity)),
    );
    this.stopping.push(
      this.queries.heldRibbons.subscribe('disqualify', (entity: Entity) => this.releaseRibbon(entity)),
    );
    this.stopping.push(
      this.queries.heldWheels.subscribe('disqualify', () => {
        this.debouncing();
      }),
    );
    twin.subscribe(() => this.followPayloadDay());
  }

  dispose(): void {
    for (const stop of this.stopping) stop();
  }

  update(delta: number): void {
    for (const entity of this.queries.heldPipes.entities) this.measure(entity, 'z');
    for (const entity of this.queries.heldRibbons.entities) this.measure(entity, 'z');
    this.holdTokens(delta);
    this.scrubFromWheel(delta);
  }

  private measure(entity: Entity, axis: 'x' | 'z'): void {
    const object = entity.object3D as Object3D;
    const coordinate = object.position[axis];
    if (!this.origins.has(entity)) {
      this.origins.set(entity, coordinate);
      this.travelled.set(entity, 0);
    }
    const origin = this.origins.get(entity) ?? coordinate;
    this.travelled.set(entity, Math.max(this.travelled.get(entity) ?? 0, Math.abs(coordinate - origin)));
  }

  private forget(entity: Entity): number {
    const amount = this.travelled.get(entity) ?? 0;
    this.travelled.delete(entity);
    this.origins.delete(entity);
    return amount;
  }

  private releasePipe(entity: Entity): void {
    const pulled = this.forget(entity);
    if (pulled < PULL_METRES) return;
    const eventKey = entity.getValue(SubscriptionPipe, 'eventKey') ?? '';
    const label = entity.getValue(SubscriptionPipe, 'label') ?? eventKey;
    if (eventKey) void twin.propose('cancel_subscription', eventKey, `pulled the ${label} pipe`);
  }

  private releaseRibbon(entity: Entity): void {
    const pulled = this.forget(entity);
    if (pulled < PULL_METRES) return;
    const payload = twin.payload;
    if (!payload) return;
    const target = nearestStone(payload.river.pinch_day);
    void twin.fork(`shift ${target.label} by a week`, [], { [target.event_id]: 7 });
  }

  /** One second of held pinch is the whole gesture; anything less changes nothing. */
  private holdTokens(delta: number): void {
    for (const entity of this.queries.heldTokens.entities) {
      const hold = (entity.getValue(ApprovalPrompt, 'hold') ?? 0) + delta;
      entity.setValue(ApprovalPrompt, 'hold', hold);
      const armed = entity.getValue(ApprovalPrompt, 'armed') ?? false;
      if (armed || hold < APPROVAL_HOLD_SEC) continue;
      entity.setValue(ApprovalPrompt, 'armed', true);
      const action = twin.pending;
      if (action) void twin.approve(action.action_id, 'hold-pinch');
    }
  }

  private scrubFromWheel(delta: number): void {
    if (this.queries.heldWheels.entities.size === 0 || !this.wheel) return;
    const payload = twin.payload;
    if (!payload) return;
    const horizon = payload.meta.horizon_days;
    const turn = ((-this.wheel.rotation.y * 180) / Math.PI) % 360;
    const day = Math.floor((((turn % 360) + 360) % 360) / 360 * horizon);
    if (day !== this.pendingDay) {
      this.pendingDay = day;
      this.debounce = 0.2;
      return;
    }
    this.debounce -= delta;
    if (this.debounce > 0) return;
    this.debounce = 0.5;
    void twin.scrub(day);
  }

  private debouncing(): void {
    this.pendingDay = -1;
    if (this.debounce > 0) this.debounce = 0.001;
  }

  /** When the day arrives from elsewhere, the wheel is told where to stand. */
  private followPayloadDay(): void {
    const payload = twin.payload;
    if (!this.wheel || !payload) return;
    if (this.queries.heldWheels.entities.size > 0) return;
    const turn = (payload.meta.day / Math.max(1, payload.meta.horizon_days)) * Math.PI * 2;
    this.wheel.rotation.y = -turn;
    for (const entity of this.queries.wheels.entities) {
      if (!entity.hasComponent(TimeWheel)) continue;
      entity.setValue(TimeWheel, 'day', payload.meta.day);
      entity.setValue(TimeWheel, 'turnDeg', (-turn * 180) / Math.PI);
    }
  }
}

function nearestStone(day: number): { event_id: string; label: string; day: number } {
  const payload = twin.payload;
  const wanted = (payload?.stones ?? []).filter((s) => !s.cancellable);
  const pool = wanted.length > 0 ? wanted : (payload?.stones ?? []);
  let best = pool[0];
  for (const stone of pool) {
    if (Math.abs(stone.day - day) < Math.abs(best.day - day)) best = stone;
  }
  return { event_id: best?.event_id ?? '', label: best?.label ?? 'the next bill', day: best?.day ?? day };
}
