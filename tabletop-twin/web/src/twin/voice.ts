/**
 * The twin's mouth, and the two panels that carry everything it says.
 *
 * Captions are not an extra here: the sentence the orb speaks is written to a
 * panel too, so the app works with the sound off and with colour taken away.
 */

import { Mesh, MeshStandardMaterial, Object3D, UIKit, Vector3, createSystem, type UIKitMLAsset } from '@iwsdk/core';
import { twin } from './controller.js';
import { Moods, TwinOrb } from './components.js';
import { dayToX } from './layout.js';

/** Seconds between heartbeat ticks. Each tick advances the world one day. */
export const HEARTBEAT_SEC = 45;

const QUESTIONS: Record<string, string> = {
  'Btn-why': 'why is the middle path so thin',
  'Btn-driest': 'which day worries you most',
  'Btn-cancel': 'what if I cancel the plates subscription',
  'Btn-best': 'what is the best thing I could do',
};

export class TwinVoiceSystem extends createSystem({
  orbs: { required: [TwinOrb] },
}) {
  private orb?: Object3D;
  private restY = 0;
  private core?: MeshStandardMaterial;
  private pointer?: Object3D;
  private clock = 0;
  private spoke = -99;
  private timer = HEARTBEAT_SEC;
  private stopping: Array<() => void> = [];
  private readonly origin = new Vector3();
  private readonly target = new Vector3();

  init(): void {
    for (const entity of this.queries.orbs.entities) {
      this.orb = entity.object3D as Object3D;
      this.restY = this.orb.position.y;
      const body = this.orb.getObjectByName('Orb/Body');
      this.pointer = body?.getObjectByName('Orb/Pointer');
      const core = body?.getObjectByName('Orb/Core') as Mesh | undefined;
      if (core) {
        this.core = (core.material as MeshStandardMaterial).clone();
        core.material = this.core;
      }
      break;
    }
    const captions = this.world.getSceneObject<UIKitMLAsset>('captions');
    const approve = this.world.getSceneObject<UIKitMLAsset>('approve');
    for (const [id, intent] of Object.entries(QUESTIONS)) {
      const button = captions?.getElementById<UIKit.Text>(id);
      if (!button) continue;
      const onClick = () => void twin.ask(intent).then((said) => twin.say('answer', said));
      button.addEventListener('click', onClick);
      this.stopping.push(() => button.removeEventListener('click', onClick));
    }
    const reject = approve?.getElementById<UIKit.Text>('Btn-reject');
    if (reject) {
      const onClick = () => {
        twin.pending = null;
        twin.say('reject', 'Not spent. That money does not move without your pinch.');
      };
      reject.addEventListener('click', onClick);
      this.stopping.push(() => reject.removeEventListener('click', onClick));
    }
    this.stopping.push(twin.subscribe(() => this.redraw()));
    this.redraw();
    void twin.tick(0, false);
  }

  dispose(): void {
    for (const stop of this.stopping) stop();
  }

  update(delta: number): void {
    this.clock += delta;
    if (this.orb) this.orb.position.y = this.restY + Math.sin(this.clock * 1.3) * 0.008;
    this.timer -= delta;
    if (this.timer > 0) return;
    this.timer = HEARTBEAT_SEC;
    const payload = twin.payload;
    const atEnd = payload ? payload.meta.day >= payload.meta.horizon_days - 1 : false;
    void twin.tick(1, atEnd);
  }

  private lastText = '';

  /** One redraw path: whatever the controller knows, the table shows. */
  private redraw(): void {
    const panel = this.world.getSceneObject<UIKitMLAsset>('captions');
    const approve = this.world.getSceneObject<UIKitMLAsset>('approve');
    const payload = twin.payload;
    const latest = twin.captions[twin.captions.length - 1];
    const text = twin.offline
      ? 'The twin is not answering. Nothing has been spent, and nothing will be.'
      : (latest?.text ?? (payload ? `${payload.meta.persona} is watching ${payload.meta.horizon_days} days of cash.` : 'Waking the miniature...'));
    if (text !== this.lastText) {
      this.lastText = text;
      this.spoke = this.clock;
    }
    panel?.getElementById<UIKit.Text>('CaptionText')?.setProperties({ text });
    panel?.getElementById<UIKit.Text>('CaptionStep')?.setProperties({
      text: twin.offline ? 'offline' : (latest?.step ?? 'idle'),
    });
    panel?.getElementById<UIKit.Text>('StatusLine')?.setProperties({
      text: twin.route || 'planner: not reached',
    });

    const pending = twin.pending;
    if (approve) approve.visible = pending !== null;
    if (pending) {
      const dollars = (pending.amount_cents / 100).toFixed(2);
      approve?.getElementById<UIKit.Text>('ApproveText')?.setProperties({
        text: `${pending.verb} $${dollars} to ${pending.recipient || 'them'}, ${pending.rule}`,
      });
    }

    this.pointAt(payload?.twin.look_at ?? '', payload?.focus ?? '');
    this.mood(pending !== null, this.clock - this.spoke < 6);
  }

  /** The orb turns toward whatever she just mentioned and puts a finger on it. */
  private pointAt(lookAt: string, focus: string): void {
    if (!this.orb || !this.pointer) return;
    const key = lookAt || focus;
    const object = key ? this.find(key) : undefined;
    this.pointer.visible = object !== undefined;
    if (!object) return;
    const body = this.orb.getObjectByName('Orb/Body');
    if (!body) return;
    object.getWorldPosition(this.target);
    this.orb.getWorldPosition(this.origin);
    body.rotation.y = Math.atan2(-(this.target.z - this.origin.z), this.target.x - this.origin.x);
  }

  private find(key: string): Object3D | undefined {
    const root = this.world.getSceneObject<Object3D>('tabletop');
    if (!root) return undefined;
    for (const prefix of ['stone-', 'boat-', 'pipe-', 'branch-']) {
      const found = root.getObjectByName(prefix + key);
      if (found) return found;
    }
    return undefined;
  }

  private mood(waiting: boolean, speaking: boolean): void {
    if (!this.core) return;
    const mood = waiting ? Moods.waiting : speaking ? Moods.speaking : Moods.idle;
    for (const entity of this.queries.orbs.entities) entity.setValue(TwinOrb, 'mood', mood);
    this.core.emissiveIntensity = mood === Moods.waiting ? 3.2 : mood === Moods.speaking ? 2.6 : 1;
  }
}
