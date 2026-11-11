/**
 * The twin's mouth, and the three panels that carry everything it says.
 *
 * Captions are not an extra here: the sentence the orb speaks is written to a
 * panel too, so the app works with the sound off. Every state the twin is in is
 * spelled in words as well as painted, because no colour in this palette is
 * allowed to be the only signal that something changed.
 */

import { Mesh, MeshStandardMaterial, Object3D, UIKit, Vector3, createSystem, type Entity, type UIKitMLAsset } from '@iwsdk/core';
import { twin } from './controller.js';
import { APPROVAL_HOLD_SEC, type Payment, type ScenePayload } from './client.js';
import { ApprovalPrompt, Moods, TableVoice, TwinOrb } from './components.js';

/** Seconds between heartbeat ticks. Each tick advances the world one day. */
export const HEARTBEAT_SEC = 45;

const QUESTIONS: Record<string, string> = {
  'Btn-why': 'why is the middle path so thin',
  'Btn-driest': 'which day worries you most',
  'Btn-cancel': 'what if I cancel the plates subscription',
  'Btn-best': 'what is the best thing I could do',
};

/** How many payments the rails panel has room for; the rest are counted, not hidden. */
const PAY_SLOTS = 3;

type PanelState = 'idle' | 'thinking' | 'speaking' | 'waiting' | 'asking' | 'checking' | 'offline';

/** How many marks the hold gauge is broken into: one per fifth of the approval second. */
const SEGMENTS = 5;

/**
 * Blue, teal, amber, slate and orange-red: the backend's colourblind-safe set, and
 * every pair differs in lightness as well as hue. The chip always carries the word.
 */
const SURFACE: Record<PanelState, { band: string; chip: string; edge: string }> = {
  idle: { band: '#1a222c', chip: '#9aa5b1', edge: '#33414f' },
  thinking: { band: '#16202b', chip: '#7fb3d5', edge: '#4a5f74' },
  speaking: { band: '#12222f', chip: '#2e7dd1', edge: '#2e7dd1' },
  waiting: { band: '#2b2412', chip: '#ffd166', edge: '#ffd166' },
  asking: { band: '#122b28', chip: '#5bc8af', edge: '#5bc8af' },
  checking: { band: '#0f2a2f', chip: '#00b3a4', edge: '#00b3a4' },
  offline: { band: '#2a1813', chip: '#e4572e', edge: '#e4572e' },
};

const STATE_WORD: Record<PanelState, string> = {
  idle: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
  waiting: 'your hold',
  asking: 'pinch sent',
  checking: 'asking the rail',
  offline: 'offline',
};

/**
 * The orb's half of the same state. Colour never carries a claim on its own here —
 * the caption chip spells the word — but a hand mid-reach should see that the twin
 * is waiting without having to read a panel first.
 */
const ORB_GLOW: Record<PanelState, { tint: string; intensity: number }> = {
  idle: { tint: '#8fb8d8', intensity: 1 },
  thinking: { tint: '#7fb3d5', intensity: 1.7 },
  speaking: { tint: '#2e7dd1', intensity: 2.6 },
  waiting: { tint: '#ffd166', intensity: 3.2 },
  asking: { tint: '#5bc8af', intensity: 2.4 },
  checking: { tint: '#00b3a4', intensity: 2 },
  offline: { tint: '#e4572e', intensity: 0.35 },
};

/** A provider that has not answered is not a payment that landed. */
const UNASKED = new Set(['unknown', 'reconciling']);

interface Paint {
  text?: string;
  color?: string;
  backgroundColor?: string;
  borderColor?: string;
  display?: 'none' | 'flex' | 'contents';
}

/** One way to write a field, so a missing element is a no-op rather than a thrown frame. */
function put(panel: UIKitMLAsset | undefined, id: string, props: Paint): void {
  panel?.getElementById<UIKit.Text>(id)?.setProperties(props);
}

function money(currency: string, dollars: number): string {
  return `${currency} ${dollars.toFixed(2)}`;
}

/**
 * One separator for every line the panels join. A middle dot is what this wording
 * wants and the bundled font atlas does not draw it, so the joiner is plain ASCII:
 * a box in the middle of a figure is worse than a hyphen.
 */
function joined(parts: Array<string | undefined>): string {
  return parts.filter((part) => part !== undefined && part !== '').join('  -  ');
}

export class TwinVoiceSystem extends createSystem({
  orbs: { required: [TwinOrb] },
  voices: { required: [TableVoice] },
  tokens: { required: [ApprovalPrompt] },
}) {
  private orb?: Object3D;
  private restY = 0;
  private core?: MeshStandardMaterial;
  private pointer?: Object3D;
  private clock = 0;
  private spoke = -99;
  private timer = HEARTBEAT_SEC;
  private stopping: Array<() => void> = [];
  /** The oldest payment still waiting on its provider, which is what the chase button asks about. */
  private chase = '';
  private lastText = '';
  private captionsPanel?: UIKitMLAsset;
  private approvePanel?: UIKitMLAsset;
  private railsPanel?: UIKitMLAsset;
  /** How many gauge marks were lit last frame, so a still hand does not repaint five boxes. */
  private lit = -1;
  private gaugeWord = '';
  /** The state decided at the last redraw, kept so the gauge can colour itself the same way. */
  private current: PanelState = 'idle';
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
    this.captionsPanel = this.world.getSceneObject<UIKitMLAsset>('captions');
    this.approvePanel = this.world.getSceneObject<UIKitMLAsset>('approve');
    this.railsPanel = this.world.getSceneObject<UIKitMLAsset>('rails');
    for (const [id, intent] of Object.entries(QUESTIONS)) {
      const button = this.captionsPanel?.getElementById<UIKit.Text>(id);
      if (!button) continue;
      const onClick = () => void twin.ask(intent);
      button.addEventListener('click', onClick);
      this.stopping.push(() => button.removeEventListener('click', onClick));
    }
    const reject = this.approvePanel?.getElementById<UIKit.Text>('Btn-reject');
    if (reject) {
      const onClick = () => {
        const held = twin.pending;
        if (held && !twin.settling) void twin.reject(held.action_id);
      };
      reject.addEventListener('click', onClick);
      this.stopping.push(() => reject.removeEventListener('click', onClick));
    }
    const chase = this.railsPanel?.getElementById<UIKit.Text>('Btn-chase');
    if (chase) {
      const onClick = () => {
        if (this.chase && !twin.chasing) void twin.reconcile(this.chase);
      };
      chase.addEventListener('click', onClick);
      this.stopping.push(() => chase.removeEventListener('click', onClick));
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
    // A float is a sign of life, and offline is the one state that must not fake one.
    if (this.orb) {
      this.orb.position.y = this.current === 'offline'
        ? this.restY
        : this.restY + Math.sin(this.clock * 1.3) * 0.008;
    }
    this.trackHold();
    this.timer -= delta;
    if (this.timer > 0) return;
    this.timer = HEARTBEAT_SEC;
    const payload = twin.payload;
    const atEnd = payload ? payload.meta.day >= payload.meta.horizon_days - 1 : false;
    void twin.tick(1, atEnd);
  }

  /** One redraw path: whatever the controller knows, the table shows. */
  private redraw(): void {
    const payload = twin.payload;
    const latest = twin.captions[twin.captions.length - 1];
    const text = twin.offline
      ? 'The twin is not answering. Nothing has been spent, and nothing will be.'
      : (latest?.text ?? (payload ? `${payload.meta.persona} is watching ${payload.meta.horizon_days} days of cash.` : 'Waking the miniature...'));
    if (text !== this.lastText) {
      this.lastText = text;
      this.spoke = this.clock;
    }
    const state: PanelState = twin.offline
      ? 'offline'
      : twin.settling
        ? 'asking'
        : twin.pending
          ? 'waiting'
          : twin.chasing
            ? 'checking'
            : twin.inFlight > 0
              ? 'thinking'
              : this.clock - this.spoke < 6
                ? 'speaking'
                : 'idle';

    this.publish(state);
    this.paintCaptions(state, text, latest?.step ?? 'idle', payload);
    this.paintApprove(state);
    this.paintRails(payload);
    this.pointAt(payload?.twin.look_at ?? '', payload?.focus ?? '');
    this.mood(state);
  }

  /**
   * The one decision this system makes, written to the component before any panel reads
   * it. The orb, the water and the three cards then all show the same state instead of
   * each working out what the table is doing from the payload again.
   */
  private publish(state: PanelState): void {
    if (state !== this.current) {
      this.current = state;
      this.lit = -1;
    }
    for (const entity of this.queries.voices.entities) {
      entity.setValue(TableVoice, 'mood', Moods[state]);
      entity.setValue(TableVoice, 'waitingOn', twin.inFlight);
    }
  }

  /**
   * The gauge measures the hand rather than the frame rate: `ApprovalPrompt.hold` is the
   * only clock, so the marks say how long this contact has actually lasted. Five marks,
   * one per fifth of the approval second, with the same measurement in words underneath.
   */
  private trackHold(): void {
    let hold = 0;
    let armed = false;
    for (const entity of this.queries.tokens.entities) {
      hold = Math.max(hold, entity.getValue(ApprovalPrompt, 'hold') ?? 0);
      armed = armed || (entity.getValue(ApprovalPrompt, 'armed') ?? false);
    }
    const pct = Math.max(0, Math.min(1, hold / APPROVAL_HOLD_SEC));
    for (const entity of this.queries.voices.entities) entity.setValue(TableVoice, 'holdPct', pct);
    const lit = armed ? SEGMENTS : Math.round(pct * SEGMENTS);
    const word = armed
      ? 'Received: that is an approval.'
      : (hold > 0
        ? `Holding ${Math.min(hold, APPROVAL_HOLD_SEC).toFixed(2)}s of ${APPROVAL_HOLD_SEC}s.`
        : 'Hold the coin for a full second. This card says no.');
    if (lit === this.lit && word === this.gaugeWord) return;
    this.lit = lit;
    this.gaugeWord = word;
    const chip = SURFACE[this.current].chip;
    for (let index = 0; index < SEGMENTS; index += 1) {
      put(this.approvePanel, `Gauge${index}`, {
        backgroundColor: index < lit ? chip : '#1a222c',
        borderColor: index < lit ? chip : '#4a5f74',
      });
    }
    put(this.approvePanel, 'ApproveGauge', { text: word });
  }

  /** What the twin's own record is worth, read off the component the world system fills. */
  private score(): string {
    for (const entity of this.queries.orbs.entities) {
      const resolved = entity.getValue(TwinOrb, 'resolved') ?? 0;
      if (resolved > 0) {
        return `keeps ${Math.round(entity.getValue(TwinOrb, 'accuracyPct') ?? 0)}% of ${resolved}`;
      }
      return 'no claim answered yet';
    }
    return 'no claim answered yet';
  }

  private paintCaptions(state: PanelState, text: string, step: string, payload: ScenePayload | null): void {
    const panel = this.captionsPanel;
    const skin = SURFACE[state];
    put(panel, 'CaptionCard', { borderColor: skin.edge });
    put(panel, 'CaptionBand', { backgroundColor: skin.band });
    put(panel, 'CaptionStep', { text: STATE_WORD[state], backgroundColor: skin.chip });
    put(panel, 'CaptionRoute', {
      text: twin.route
        ? (twin.routeMeasured ? twin.route : `${twin.route} (not yet asked)`)
        : 'planner: not reached',
    });
    put(panel, 'CaptionWho', { text: twin.account || (payload?.meta.persona ?? 'this table') });
    put(panel, 'CaptionKind', { text: `step: ${step} | ${this.score()}` });
    put(panel, 'CaptionDay', {
      text: payload ? `day ${payload.meta.day + 1} of ${payload.meta.horizon_days}` : 'no day yet',
    });
    put(panel, 'CaptionText', { text });
  }

  private paintApprove(state: PanelState): void {
    const panel = this.approvePanel;
    const pending = twin.pending;
    if (panel) panel.visible = pending !== null;
    if (!pending || !panel) return;
    const skin = SURFACE[state];
    put(panel, 'ApproveCard', { borderColor: skin.edge });
    put(panel, 'ApproveBand', { backgroundColor: skin.band });
    put(panel, 'ApproveState', { text: STATE_WORD[state], backgroundColor: skin.chip });
    put(panel, 'ApproveHeld', {
      text: state === 'asking' ? 'pinch received' : (pending.verb ? `${pending.verb}: by policy` : 'by policy'),
    });
    put(panel, 'ApproveAmount', { text: money(pending.currency, pending.amount_dollars) });
    put(panel, 'ApproveTo', { text: joined([pending.recipient || 'nobody named', pending.country]) });
    put(panel, 'ApproveWhy', { text: pending.reason, display: pending.reason ? 'flex' : 'none' });
    put(panel, 'ApproveRule', {
      text: joined([`rule: ${pending.rule}`, pending.rail, `fee ${money(pending.currency, pending.fee_dollars)}`]),
    });
  }

  private paintRails(payload: ScenePayload | null): void {
    const panel = this.railsPanel;
    if (!panel) return;
    const meta = payload?.meta;
    put(panel, 'RailName', { text: meta?.rail ?? 'no rail named' });
    put(panel, 'RailFrom', { text: meta ? `${meta.currency}, sent from ${meta.country}` : 'currency unknown' });

    const list = payload?.payments ?? [];
    this.chase = list.find((payment) => UNASKED.has(payment.state))?.action_id ?? '';
    for (let slot = 0; slot < PAY_SLOTS; slot += 1) {
      const payment = list[slot];
      put(panel, `Pay${slot}`, { display: payment ? 'flex' : 'none' });
      if (!payment) continue;
      put(panel, `PayState${slot}`, {
        text: payment.state,
        backgroundColor: UNASKED.has(payment.state) ? '#7fb3d5' : '#ffd166',
      });
      put(panel, `PayHow${slot}`, {
        text: payment.fee_dollars > 0
          ? `${money(payment.currency, payment.amount_dollars)} + ${payment.fee_dollars.toFixed(2)} fee`
          : money(payment.currency, payment.amount_dollars),
      });
      put(panel, `PayWhom${slot}`, {
        text: joined([
          payment.recipient || 'nobody named',
          payment.country,
          payment.attempt > 1 ? `try ${payment.attempt}` : '',
        ]),
      });
    }
    const extra = list.length - PAY_SLOTS;
    put(panel, 'RailMore', {
      text: extra > 0 ? `+ ${extra} more in flight` : '',
      display: extra > 0 ? 'flex' : 'none',
    });
    put(panel, 'RailNote', { text: this.railNote(list) });
    put(panel, 'RailWeek', { text: this.week(payload) });
    put(panel, 'Btn-chase', {
      text: twin.chasing ? 'Asking the provider...' : 'Ask the provider again',
      display: this.chase ? 'flex' : 'none',
    });
  }

  /**
   * The twin's own week, in the words the backend folded from its logged decisions.
   * Nothing is counted here: every figure is one the summary arithmetic already made.
   */
  private week(payload: ScenePayload | null): string {
    const memory = payload?.memory;
    if (!memory || !payload) return 'this week: nothing logged yet';
    return joined([
      `this week: ${memory.asks_this_week} ask(s), ${memory.moves_this_week} move(s)`,
      `${money(payload.meta.currency, memory.settled_cents_this_week / 100)} settled onward`,
      memory.refused_this_week > 0 ? `${memory.refused_this_week} refused (${memory.top_denied_rule})` : '',
      memory.held_gestures_refused_this_week > 0 ? `${memory.held_gestures_refused_this_week} tap(s) refused` : '',
    ]);
  }

  /**
   * What the panel is allowed to claim. A record still open is money whose fate
   * nobody has confirmed, so the sentence says that instead of reassuring.
   */
  private railNote(list: Payment[]): string {
    if (list.length === 0) return 'Nothing is mid-flight.';
    const unasked = list.filter((payment) => UNASKED.has(payment.state)).length;
    if (unasked > 0) {
      return `${unasked} of ${list.length} have no answer from the provider. The twin will not call them landed.`;
    }
    return `${list.length} asked and not yet settled. Nothing has left the table.`;
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
    // Both points are read in the frame the body actually turns in, so a table that
    // was placed by AR and rotated to face the person still points at the right bill.
    const frame = body.parent ?? body;
    frame.worldToLocal(this.target);
    frame.worldToLocal(this.origin);
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

  /** The orb says the same thing the panels say, in light instead of in words. */
  private mood(state: PanelState): void {
    for (const entity of this.queries.orbs.entities) entity.setValue(TwinOrb, 'mood', Moods[state]);
    if (!this.core) return;
    const glow = ORB_GLOW[state];
    this.core.emissive.set(glow.tint);
    this.core.emissiveIntensity = glow.intensity;
  }
}
