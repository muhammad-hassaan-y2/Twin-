/**
 * The table this twin stands on is looked for, not assumed.
 *
 * In an immersive AR session the first steady, upward-facing hit that sits at table
 * height and within arm's reach becomes the world's origin, and the miniature turns
 * to face whoever found it. Everything else keeps the authored pose: a browser with
 * no session, a room whose table has not been detected yet, a headset that did not
 * grant hit-test. A placement is taken once per session and never revised, because a
 * table that slides across the room when the estimate improves is worse than one
 * that stays where the app put it.
 */

import { Object3D, Quaternion, Vector3, createSystem } from '@iwsdk/core';
import { TwinState } from './components.js';

/** Above the tracked floor and below a shelf, a surface is a table top. */
const TABLE_LOW = 0.35;
const TABLE_HIGH = 1.05;
/** And only within arm's reach of the head, so it lands in front of the person. */
const REACH_MIN = 0.35;
const REACH_MAX = 1.3;
/** The surface has to face the sky this squarely; a wall facing the viewer is not a table. */
const LEVEL = 0.9;
/** Consecutive frames a hit must hold still, and how still counts as still. */
const SETTLE_FRAMES = 5;
const SETTLE_DRIFT = 0.02;

interface Pose {
  transform: {
    position: { x: number; y: number; z: number };
    orientation: { x: number; y: number; z: number; w: number };
  };
}

export class TwinPlacementSystem extends createSystem({
  tables: { required: [TwinState] },
}) {
  private root?: Object3D;
  private readonly authored = new Vector3();
  private authoredYaw = 0;
  private readonly head = new Vector3();
  private readonly normal = new Vector3();
  private readonly spin = new Quaternion();
  private readonly candidate = new Vector3();
  private readonly previous = new Vector3(Infinity, Infinity, Infinity);
  private stopping: Array<() => void> = [];
  private searching = false;
  private placed = false;
  private wasInXR = false;
  private settle = 0;

  init(): void {
    for (const entity of this.queries.tables.entities) {
      this.root = entity.object3D as Object3D;
      this.authored.copy(this.root.position);
      this.authoredYaw = this.root.rotation.y;
      break;
    }
  }

  dispose(): void {
    this.release();
  }

  update(): void {
    if (!this.root) return;
    const session = this.world.xrSession;
    if (!session) {
      if (this.wasInXR) this.leave();
      return;
    }
    this.wasInXR = true;
    if (this.placed || this.searching) return;
    this.searching = true;
    void this.search();
  }

  private async search(): Promise<void> {
    const session = this.world.xrSession;
    const space = this.world.xrReferenceSpace;
    if (!session || !space) {
      this.searching = false;
      return;
    }
    const viewer = await session.requestReferenceSpace('viewer').catch(() => null);
    // The session can be gone by the time either promise lands, and a source asked
    // for on a dead session never answers.
    if (!viewer || !this.world.xrSession) {
      this.searching = false;
      return;
    }
    const source = await this.world.requestHitTestSource({ space: viewer });
    if (!source || !this.world.xrSession) {
      this.searching = false;
      return;
    }
    this.stopping.push(() => source.cancel?.());
    this.stopping.push(
      this.world.onXRFrame(() => {
        if (this.placed) return;
        const hit = this.world.getHitTestResults(source)[0];
        const pose: Pose | undefined = hit?.getPose(space);
        if (pose) this.consider(pose);
        else this.settle = 0;
      }),
    );
  }

  private consider(pose: Pose): void {
    const point = pose.transform.position;
    const turn = pose.transform.orientation;
    if (point.y < TABLE_LOW || point.y > TABLE_HIGH) {
      this.settle = 0;
      return;
    }
    this.spin.set(turn.x, turn.y, turn.z, turn.w);
    this.normal.set(0, 0, -1).applyQuaternion(this.spin);
    const head = this.world.playerHeadEntity.object3D as Object3D | undefined;
    if (!head) {
      this.settle = 0;
      return;
    }
    head.getWorldPosition(this.head);
    const reach = this.candidate.set(point.x, point.y, point.z).distanceTo(this.head);
    if (this.normal.y < LEVEL || reach < REACH_MIN || reach > REACH_MAX) {
      this.settle = 0;
      return;
    }
    const still =
      Math.abs(point.x - this.previous.x) <= SETTLE_DRIFT &&
      Math.abs(point.y - this.previous.y) <= SETTLE_DRIFT &&
      Math.abs(point.z - this.previous.z) <= SETTLE_DRIFT;
    this.previous.copy(this.candidate);
    this.settle = still ? this.settle + 1 : 0;
    if (this.settle >= SETTLE_FRAMES) this.place();
  }

  private place(): void {
    const root = this.root;
    if (!root) return;
    root.position.copy(this.candidate);
    root.rotation.y = Math.atan2(this.head.x - this.candidate.x, this.head.z - this.candidate.z);
    this.placed = true;
    this.searching = false;
    this.release();
  }

  /** Leaving XR puts the world back on the table the composition was drawn for. */
  private leave(): void {
    this.wasInXR = false;
    this.searching = false;
    this.settle = 0;
    this.previous.set(Infinity, Infinity, Infinity);
    this.release();
    if (this.placed && this.root) {
      this.root.position.copy(this.authored);
      this.root.rotation.y = this.authoredYaw;
    }
    this.placed = false;
  }

  private release(): void {
    for (const stop of this.stopping) stop();
    this.stopping = [];
  }
}
