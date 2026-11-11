/**
 * The single owner of everything the client knows.
 *
 * Systems never fetch on their own and never invent a number: they call one of
 * these methods, the controller asks the twin, and every listener redraws from
 * the payload that came back. One source, so two props cannot drift apart.
 */

import { session, twinApi } from './client.js';
import type { Caption, FirmBrief, FirmHealth, FirmReview, Fork, Held, ScenePayload, Verdict } from './client.js';

type Listener = () => void;

/** The states the payment machine leaves open for a hand to settle. */
const AWAITING_A_PINCH = new Set(['draft', 'proposed']);

class TwinController {
  payload: ScenePayload | null = null;
  /** The action being held for a hand gesture, by this browser or by the twin itself. */
  pending: Held | null = null;
  /** Set between the pinch and the twin's answer, so the table can say "asking". */
  settling: string | null = null;
  captions: Caption[] = [];
  offline = false;
  /** Requests the twin has been asked and has not answered. A slow table is a state. */
  inFlight = 0;
  /** The payment whose provider is being asked right now, or nothing is. */
  chasing: string | null = null;
  route = '';
  /** False while the route is only what the environment says it would be. */
  routeMeasured = true;
  account = '';
  /** What the firm says it is: every role, the figures they quote, and what they stand on. */
  firm: FirmBrief | null = null;
  /** How the boot probe found the contract, if it reached one. */
  firmHealth: FirmHealth | null = null;
  /** The last engagement put to the firm, and the answers it gave. */
  firmReview: FirmReview | null = null;
  firmIndex = 0;
  /** Which engagement the answer above is about, once there is one. */
  firmAsked = -1;
  firmBusy = false;
  private chased = new Set<string>();
  private joining: Promise<boolean> | null = null;
  private listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private adopt(scene: ScenePayload | undefined): void {
    if (scene) {
      this.payload = scene;
      this.chaseUnknown(scene);
      this.holdForPinch(scene);
    }
    this.offline = false;
    this.emit();
  }

  /**
   * A payment the machine never finished is a decision waiting for a hand, whether
   * this browser asked for it or the twin did. Nothing is invented here: the rule
   * line says which state the record is in, because that is all the record says.
   */
  private holdForPinch(scene: ScenePayload): void {
    if (this.pending || this.settling) return;
    const held = scene.payments.find((payment) => AWAITING_A_PINCH.has(payment.state));
    if (!held) return;
    this.pending = {
      action_id: held.action_id,
      verb: '',
      recipient: held.recipient,
      country: held.country,
      currency: held.currency,
      amount_dollars: held.amount_dollars,
      rail: held.rail,
      fee_dollars: held.fee_dollars,
      rule: `payment state: ${held.state}`,
      reason: '',
    };
  }

  /**
   * An unknown payment is money whose fate nobody has confirmed. The table asks
   * the provider once per attempt rather than leaving that boat in the fog.
   */
  private chaseUnknown(scene: ScenePayload): void {
    for (const payment of scene.payments) {
      if (payment.state !== 'unknown') continue;
      const marker = `${payment.action_id}:${payment.attempt}`;
      if (this.chased.has(marker)) continue;
      this.chased.add(marker);
      void this.reconcile(payment.action_id);
    }
  }

  /**
   * Every request goes through here, so the count of unanswered ones is a fact about
   * this class rather than something each caller remembers to set. The `finally` is the
   * point: a request that throws still stops being in flight.
   */
  private async call<T>(run: () => Promise<T>, fallback: T): Promise<T> {
    this.inFlight += 1;
    this.emit();
    try {
      return await run();
    } catch {
      this.offline = true;
      return fallback;
    } finally {
      this.inFlight -= 1;
      this.emit();
    }
  }

  /**
   * Land on the world this browser was pointed at, if it was pointed at one.
   *
   * Nothing here signs anybody up. The device key rides on every request and the
   * twin opens the world behind it, so the table is there before any account is.
   * `?email=&password=` is the only text a headset can be handed, and it is the one
   * way to join a world that already belongs to somebody.
   */
  private async joinWorld(): Promise<void> {
    if (!this.account) this.account = session.name;
    const wanted = signedInFromUrl();
    if (!wanted) return;
    // Two systems boot at once, so joining is one shared promise, not two logins.
    this.joining ??= this.authenticate(wanted.email, wanted.password).finally(() => {
      this.joining = null;
    });
    await this.joining;
  }

  private async authenticate(email: string, password: string): Promise<boolean> {
    const account = await this.call(() => twinApi.login(email, password), null);
    if (!account) return false;
    session.set(account);
    this.account = account.name;
    return true;
  }

  async signIn(email: string, password: string): Promise<boolean> {
    if (!(await this.authenticate(email, password))) return false;
    await this.boot();
    return true;
  }

  /** Leaving revokes the token. The device still opens this table; only the name goes. */
  async signOut(): Promise<void> {
    if (session.token) await this.call(() => twinApi.logout(), null);
    session.set(null);
    this.account = '';
    this.payload = null;
    this.pending = null;
    this.settling = null;
    this.captions = [];
    this.emit();
  }

  async boot(): Promise<void> {
    await this.joinWorld();
    const [world, health, me, firm] = await Promise.all([
      this.call(() => twinApi.world(), null as ScenePayload | null),
      this.call(() => twinApi.health(), null),
      this.call(() => twinApi.me(), null),
      this.call(() => twinApi.firm(), null),
    ]);
    if (world) this.payload = world;
    // A world nobody has named yet is still somebody's table, and the twin is the
    // one that knows what to call it.
    if (me && !this.account) this.account = me.name;
    if (health) {
      this.route = health.route;
      this.routeMeasured = health.route_is_measured;
      this.firmHealth = health.audit;
    }
    if (firm) this.firm = firm;
    this.offline = !world;
    this.emit();
  }

  async scrub(day: number): Promise<void> {
    const result = await this.call(() => twinApi.scrub(day), null);
    if (result) this.adopt(result.scene);
  }

  /** Yanking a pipe out of the table grows a second miniature without it. */
  async pull(eventId: string, label: string): Promise<Fork | null> {
    const result = await this.call(() => twinApi.pull(eventId), null);
    if (!result) return null;
    this.adopt(result.scene);
    const fork = result.fork;
    this.say(
      'fork',
      `${label} is out. ${fork.delta.verdict}: ${dollars(fork.delta.cost_change_dollars)} in cost over the horizon.`,
      `branch-${fork.branch}`,
    );
    return fork;
  }

  async fork(label: string, cancelEventIds: string[] = [], shift: Record<string, number> = {}): Promise<void> {
    const args: Record<string, unknown> = { label, cancel_event_ids: cancelEventIds };
    if (Object.keys(shift).length > 0) args.shift = shift;
    const result = await this.call(() => twinApi.propose([{ tool: 'fork', args }]), null);
    if (result) this.adopt(result.scene);
  }

  async propose(verb: string, eventId: string, justification: string): Promise<Verdict | null> {
    const result = await this.call(
      () =>
        twinApi.propose([
          { tool: 'propose_action', args: { verb, event_id: eventId, justification } },
        ]),
      null,
    );
    if (!result) return null;
    const first = result.results[0] as unknown as Verdict | undefined;
    if (first?.verdict === 'require_approval') this.pending = heldFrom(first);
    this.adopt(result.scene);
    if (first) this.say('policy', first.reason, first.action_id);
    return first ?? null;
  }

  async approve(actionId: string, gesture: string): Promise<string | null> {
    this.settling = actionId;
    this.emit();
    const result = await this.call(() => twinApi.approve(actionId, gesture), null);
    this.pending = null;
    await this.refresh();
    this.settling = null;
    if (!result) return null;
    this.say('approval', `Settled as ${result.state}.`, actionId);
    return result.state;
  }

  /** A no said from the panel is a decision the twin writes down, not a panel closing. */
  async reject(actionId: string): Promise<string | null> {
    const result = await this.call(() => twinApi.reject(actionId), null);
    this.pending = null;
    if (!result) return null;
    await this.refresh();
    this.say('reject', `Refused. That record now reads ${result.state}.`, actionId);
    return result.state;
  }

  /** Asking a provider what happened to a payment is a state the table has to show. */
  async reconcile(actionId: string): Promise<void> {
    this.chasing = actionId;
    this.emit();
    try {
      const result = await this.call(() => twinApi.reconcile(actionId), null);
      if (!result) return;
      this.say('reconcile', `Asked the provider about that one again. It is ${result.state}.`, actionId);
      await this.refresh();
    } finally {
      this.chasing = null;
      this.emit();
    }
  }

  /**
   * Put the next engagement to the firm and write down what the agents bind
   * each other to.
   *
   * The rotation moves only when the review answered. An index that advanced past a
   * failed request would skip a case, and the whole point of walking the corpus is
   * that every one of its boundaries gets asked about once.
   */
  async askFirm(): Promise<void> {
    this.firmBusy = true;
    this.emit();
    try {
      const result = await this.call(() => twinApi.firmReview(this.firmIndex), null);
      if (!result) return;
      this.firmReview = result;
      this.firmAsked = this.firmIndex;
      const opened = result.agreements.filter((agreement) => agreement.state === 'Attested').length;
      this.say('firm', `${result.client}: ${opened} of ${result.agreements.length} binding findings became agreements.`);
      const total = this.firm?.engagements ?? 0;
      this.firmIndex = total > 0 ? (this.firmIndex + 1) % total : 0;
    } finally {
      this.firmBusy = false;
      this.emit();
    }
  }

  /** A line the twin said in this app, in the same shape the heartbeat returns. */
  say(step: string, text: string, target = ''): void {
    if (!text) return;
    this.captions = [...this.captions.slice(-5), { step, text, target }];
    this.emit();
  }

  /**
   * The newest line, rewritten rather than stacked. A sentence that arrives in
   * pieces is one caption growing longer, not five captions.
   */
  private caption(step: string, text: string, target = ''): void {
    if (!text) return;
    const last = this.captions[this.captions.length - 1];
    this.captions = last && last.step === step
      ? [...this.captions.slice(0, -1), { step, text, target }]
      : [...this.captions.slice(-5), { step, text, target }];
    this.emit();
  }

  async tick(days: number, finalOfDay: boolean): Promise<Caption[]> {
    const result = await this.call(() => twinApi.tick(days, finalOfDay), null);
    if (!result) return [];
    this.captions = result.captions;
    this.adopt(result.scene);
    return result.captions;
  }

  /**
   * Ask, and let the answer arrive as it is phrased.
   *
   * Each piece the twin sends has already had its numbers checked, so growing the
   * caption sentence by sentence is safe. When the whole answer arrives the caption
   * is set from it rather than left as the sum of the pieces, because a stream that
   * froze mid-sentence ends with a different sentence than the one it started.
   */
  async ask(intent: string): Promise<string> {
    const pieces: string[] = [];
    const result = await this.call(
      () => twinApi.askStream(intent, (piece) => {
        pieces.push(piece);
        this.caption('answer', pieces.join(''));
      }),
      null,
    );
    if (!result) return pieces.join('');
    // Whichever endpoint answered is now known, not merely configured.
    if (result.route) {
      this.route = result.route;
      this.routeMeasured = true;
    }
    this.adopt(result.scene);
    this.caption('answer', result.said ?? '');
    return result.said ?? '';
  }

  async refresh(): Promise<void> {
    const result = await this.call(() => twinApi.world(), null);
    if (result) this.adopt(result);
  }
}

/** `?email=&password=` is the only text entry a headset has; use it to join an account. */
function signedInFromUrl(): { email: string; password: string } | null {
  const params = new URLSearchParams(location.search);
  const email = params.get('email');
  const password = params.get('password');
  return email && password ? { email, password } : null;
}

function dollars(value: number): string {
  const sign = value < 0 ? 'minus' : 'plus';
  return `${sign} $${Math.abs(value).toFixed(2)}`;
}

/** The verdict the twin just gave, in the shape the panel holds. */
function heldFrom(verdict: Verdict): Held {
  const { action_id, verb, recipient, country, currency, amount_dollars, rail, fee_dollars, rule, reason } = verdict;
  return { action_id, verb, recipient, country, currency, amount_dollars, rail, fee_dollars, rule, reason };
}

export const twin = new TwinController();
