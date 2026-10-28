/**
 * Draws the twin's numbers on the table.
 *
 * The payload is the only truth; this system turns it into positions, heights
 * and opacities and owns nothing else. Props are pooled by their ledger key so
 * a stone that is still due tomorrow is the same stone, not a new one.
 */

import { DistanceGrabbable, Mesh, MeshPhysicalMaterial, Object3D, RayInteractable, createSystem, type Entity } from '@iwsdk/core';
import { twin } from './controller.js';
import type { ScenePayload } from './client.js';
import {
  BANK_REST_HEIGHT,
  BANK_SEGMENTS,
  MAX_BANK_HEIGHT,
  STONE_UNIT_HEIGHT,
  UPSTREAM_Z,
  UTILITY_Z,
  dayToX,
  dollarScale,
  heightFor,
  segmentDay,
} from './layout.js';
import { BillStone, CashBranch, LateBoat, RiverFlow, SubscriptionPipe, TwinState } from './components.js';

interface Handle {
  entity: Entity;
  object: Object3D;
}

const CONTAINERS = ['banks', 'stones', 'boats', 'pipes', 'garden', 'branches'] as const;

export class TwinWorldSystem extends createSystem({
  worlds: { required: [TwinState] },
}) {
  private root!: Object3D;
  private rootEntity!: Entity;
  private containers = new Map<string, Entity>();
  private props = new Map<string, Handle>();
  private river!: Object3D;
  private riverEntity!: Entity;
  private water!: Object3D;
  private lake!: Object3D;
  private ribbon!: Object3D;
  private drawing = Promise.resolve();
  private clock = 0;
  private unsubscribe = (): void => {};

  init(): void {
    for (const entity of this.queries.worlds.entities) {
      this.rootEntity = entity;
      this.root = entity.object3D as Object3D;
      break;
    }
    for (const id of CONTAINERS) {
      const entity = this.world.getSceneEntity(id);
      if (entity) this.containers.set(id, entity);
    }
    this.river = this.world.requireSceneObject('river');
    this.riverEntity = this.world.requireSceneEntity('river');
    this.water = this.river.getObjectByName('River/Water') ?? this.river;
    this.lake = this.world.requireSceneObject('lake');
    this.ribbon = this.world.requireSceneObject('fork-ribbon');
    this.unsubscribe = twin.subscribe(() => {
      this.drawing = this.drawing.then(() => this.sync());
    });
    void twin.boot();
  }

  dispose(): void {
    this.unsubscribe();
  }

  private async spawn(container: string, assetId: string, key: string): Promise<Handle> {
    const existing = this.props.get(key);
    if (existing) return existing;
    const object = await this.world.assets.instantiate<Object3D>(assetId);
    object.name = key;
    const parent = this.containers.get(container) ?? this.rootEntity;
    const entity = this.world.createTransformEntity(object, parent);
    const handle = { entity, object };
    this.props.set(key, handle);
    return handle;
  }

  private write(handle: Handle, component: any, values: Record<string, unknown>): void {
    if (!handle.entity.hasComponent(component)) handle.entity.addComponent(component, {});
    for (const [field, value] of Object.entries(values)) {
      handle.entity.setValue(component, field as never, value as never);
    }
  }

  private async sync(): Promise<void> {
    const payload = twin.payload;
    if (!payload) return;
    this.rootEntity.setValue(TwinState, 'day', payload.meta.day);
    this.rootEntity.setValue(TwinState, 'horizonDays', payload.meta.horizon_days);
    this.rootEntity.setValue(TwinState, 'pinchDay', payload.river.pinch_day);
    const scale = dollarScale(payload);
    await this.drawBanks(payload, scale);
    await this.drawStones(payload);
    await this.drawBoats(payload);
    await this.drawPipes(payload);
    await this.drawGarden(payload);
    await this.drawBranches(payload);
    this.drawWater(payload, scale);
  }

  /**
   * Two walls, one per quantile, standing on either side of the channel. Height
   * is dollars; a negative P10 hangs below the table instead of lying about it.
   */
  private async drawBanks(payload: ScenePayload, scale: number): Promise<void> {
    const horizon = payload.meta.horizon_days;
    const width = 0.9 / BANK_SEGMENTS + 0.004;
    for (let i = 0; i < BANK_SEGMENTS; i += 1) {
      const day = segmentDay(i, horizon);
      const x = dayToX(day, horizon);
      const tiers: Array<['high' | 'low', number, number]> = [
        ['high', payload.river.p90_dollars[day] ?? 0, -0.066],
        ['low', payload.river.p10_dollars[day] ?? 0, 0.066],
      ];
      for (const [tier, dollars, z] of tiers) {
        const handle = await this.spawn('banks', 'twin-bank', `bank-${tier}-${i}`);
        const height = heightFor(dollars, scale);
        const stretch = Math.max(0.02, Math.abs(height)) / BANK_REST_HEIGHT;
        handle.object.position.set(x, Math.min(0, height), z);
        handle.object.scale.set(width, stretch, 1);
        const rail = handle.object.getObjectByName('Bank/Rail');
        if (rail) rail.scale.y = 1 / stretch;
      }
    }
  }

  /** Bills are stones at their dates, in three lanes so the channel stays readable. */
  private async drawStones(payload: ScenePayload): Promise<void> {
    const horizon = payload.meta.horizon_days;
    for (const stone of payload.stones) {
      const handle = await this.spawn('stones', 'twin-stone', `stone-${stone.id}`);
      const x = dayToX(stone.day, horizon);
      const lane = ((payload.stones.indexOf(stone) % 3) - 1) * 0.034;
      const rise = Math.max(0.55, Math.min(2.1, stone.height / STONE_UNIT_HEIGHT));
      handle.object.position.set(x, stone.below_surface ? -0.02 : 0.014, lane);
      handle.object.scale.set(0.62, rise * 0.62, 0.62);
      this.write(handle, BillStone, {
        eventKey: stone.event_id,
        label: stone.label,
        amountDollars: stone.amount_dollars,
        dueDay: stone.day,
        belowSurface: stone.below_surface,
      });
    }
  }

  /** A late invoice is a boat upstream; fog carries the probability and the mast carries the lag. */
  private async drawBoats(payload: ScenePayload): Promise<void> {
    const horizon = payload.meta.horizon_days;
    for (const boat of payload.boats) {
      const handle = await this.spawn('boats', 'twin-boat', `boat-${boat.id}`);
      handle.object.position.set(dayToX(boat.day, horizon), 0.012, UPSTREAM_Z);
      handle.object.rotation.y = boat.stuck ? 0.35 : 0;
      const veil = await this.spawn('boats', 'twin-fog', `fog-${boat.id}`);
      veil.object.position.set(dayToX(boat.day, horizon), 0.012, UPSTREAM_Z);
      veil.object.scale.setScalar(0.7 + boat.fog * 0.8);
      this.opacity(veil, 0.1 + boat.fog * 0.55);
      this.write(handle, LateBoat, {
        eventKey: boat.id,
        label: boat.label,
        fog: boat.fog,
        worstLagDays: boat.worst_lag_days,
        stuck: boat.stuck,
      });
    }
  }

  private opacity(handle: Handle, value: number): void {
    handle.object.traverse((node) => {
      if (!(node instanceof Mesh)) return;
      if (!node.userData.perInstance) {
        const source = node.material as MeshPhysicalMaterial;
        node.material = source.clone();
        node.userData.perInstance = true;
      }
      const material = node.material as MeshPhysicalMaterial;
      material.transparent = true;
      material.opacity = Math.max(0.05, Math.min(0.85, value));
    });
  }

  /**
   * One pipe per cancellable event, not one per due date: cancelling Adobe is
   * one decision that reaches every month it would have billed.
   */
  private async drawPipes(payload: ScenePayload): Promise<void> {
    const horizon = payload.meta.horizon_days;
    const first = new Map<string, { id: string; day: number; dollars: number; label: string }>();
    for (const stone of payload.stones) {
      if (!stone.cancellable || first.has(stone.event_id)) continue;
      first.set(stone.event_id, { id: stone.event_id, day: stone.day, dollars: stone.amount_dollars, label: stone.label });
    }
    for (const [eventId, pipe] of first) {
      const handle = await this.spawn('pipes', 'twin-pipe', `pipe-${eventId}`);
      handle.object.position.set(dayToX(pipe.day, horizon), 0, UTILITY_Z);
      this.write(handle, SubscriptionPipe, {
        eventKey: eventId,
        label: pipe.label,
        amountDollars: pipe.dollars,
        cancelled: false,
      });
      if (!handle.entity.hasComponent(DistanceGrabbable)) {
        handle.entity.addComponent(DistanceGrabbable, { movementMode: 'MoveFromTarget', returnToOrigin: true });
        handle.entity.addComponent(RayInteractable, {});
      }
    }
  }

  /** Accuracy grows a garden instead of drawing a dial: five sprouts along the lake rim. */
  private async drawGarden(payload: ScenePayload): Promise<void> {
    for (let i = 0; i < 5; i += 1) {
      const handle = await this.spawn('garden', 'twin-sprout', `sprout-${i}`);
      const angle = Math.PI * (0.15 + (i / 5) * 0.75);
      handle.object.position.set(0.4 + Math.cos(angle) * 0.14, 0.012, -0.16 + Math.sin(angle) * 0.14);
      handle.object.visible = i < payload.garden.stage;
      const bud = handle.object.getObjectByName('Sprout/Bud');
      if (bud) bud.visible = i === payload.garden.stage - 1 && payload.garden.stage >= 3;
    }
  }

  /** A forked world appears as a second, smaller miniature beside the first. */
  private async drawBranches(payload: ScenePayload): Promise<void> {
    for (let index = 0; index < payload.branches.length; index += 1) {
      const branch = payload.branches[index];
      await this.spawnBranch(branch.key, branch.label, branch.min_balance_change_dollars, index);
    }
  }

  private async spawnBranch(key: string, label: string, delta: number, index: number): Promise<void> {
    const handle = await this.spawn('branches', 'twin-river', `branch-${key}`);
    handle.object.position.set(-0.28 + index * 0.28, 0.004, -0.3);
    handle.object.scale.set(0.32, 1, 0.32);
    const water = handle.object.getObjectByName('River/Water');
    if (water) water.scale.y = delta >= 0 ? 1.6 : 0.45;
    this.write(handle, CashBranch, { branchId: key, label, deltaDollars: delta });
  }

  /** The river itself: stretched over the horizon, rising and falling with P50. */
  private drawWater(payload: ScenePayload, scale: number): void {
    const horizon = payload.meta.horizon_days;
    const day = Math.min(horizon - 1, payload.meta.day);
    this.river.scale.x = 0.9;
    const p50 = payload.river.p50_dollars[day] ?? 0;
    this.water.scale.y = Math.max(0.35, Math.min(3, 0.5 + heightFor(p50, scale) / 0.06));
    const depth = payload.lake.depth_dollars;
    const peak = Math.max(1, ...payload.river.p50_dollars);
    this.lake.scale.y = 0.5 + 2.5 * Math.min(1, depth / peak);
    this.ribbon.position.x = dayToX(Math.max(0, payload.river.pinch_day), horizon);
    this.riverEntity.setValue(RiverFlow, 'dryAt', payload.river.pinch_day);
    this.riverEntity.setValue(RiverFlow, 'flow', 1 - (payload.river.dry_probability[day] ?? 0));
  }

  update(delta: number): void {
    this.clock += delta;
    this.water.position.y = 0.012 + Math.sin(this.clock * 0.8) * 0.0012;
  }
}
