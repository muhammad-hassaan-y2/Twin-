/**
 * The single owner of everything the client knows.
 *
 * Systems never fetch on their own and never invent a number: they call one of
 * these methods, the controller asks the twin, and every listener redraws from
 * the payload that came back. One source, so two props cannot drift apart.
 */

import { session, twinApi } from './client.js';
import type { Caption, Fork, ScenePayload, Verdict } from './client.js';

type Listener = () => void;

class TwinController {
  payload: ScenePayload | null = null;
  /** The action the policy engine put on hold for a hand gesture. */
  pending: Verdict | null = null;
  captions: Caption[] = [];
  offline = false;
  route = '';
  account = '';
  private chased = new Set<string>();
  private provisioning: Promise<void> | null = null;
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
    }
    this.offline = false;
    this.emit();
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

  private async call<T>(run: () => Promise<T>, fallback: T): Promise<T> {
    try {
      return await run();
    } catch {
      this.offline = true;
      this.emit();
      return fallback;
    }
  }

  /**
   * A table is nobody's world until the twin hands back a token, so this happens
   * before anything is fetched. `?email=&password=` joins an existing account;
   * otherwise this browser keeps the one it made for itself.
   */
  private async ensureToken(): Promise<void> {
    if (session.token) {
      this.account = session.name;
      return;
    }
    // Two systems boot at once, so provisioning is one shared promise, not two signups.
    this.provisioning ??= this.provision().finally(() => {
      this.provisioning = null;
    });
    await this.provisioning;
  }

  private async provision(): Promise<void> {
    const wanted = signedInFromUrl() ?? session.device();
    const account = await this.call(
      async () => {
        try {
          return await twinApi.login(wanted.email, wanted.password);
        } catch {
          return await twinApi.signup(wanted.email, wanted.password);
        }
      },
      null,
    );
    if (!account) return;
    session.set(account);
    this.account = account.name;
  }

  async signIn(email: string, password: string): Promise<boolean> {
    const account = await this.call(() => twinApi.login(email, password), null);
    if (!account) return false;
    session.set(account);
    this.account = account.name;
    await this.boot();
    return true;
  }

  /** Leaving revokes the token server-side; the next boot opens a fresh world. */
  async signOut(): Promise<void> {
    if (session.token) await this.call(() => twinApi.logout(), null);
    session.set(null);
    this.account = '';
    this.payload = null;
    this.captions = [];
    this.emit();
  }

  async boot(): Promise<void> {
    await this.ensureToken();
    const [world, health] = await Promise.all([
      this.call(() => twinApi.world(), null as ScenePayload | null),
      this.call(() => twinApi.health(), null),
    ]);
    if (world) this.payload = world;
    if (health) this.route = health.route;
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
    this.adopt(result.scene);
    const first = result.results[0] as unknown as Verdict | undefined;
    this.pending = first && first.verdict === 'require_approval' ? first : null;
    if (first) this.say('policy', first.reason, first.action_id);
    return first ?? null;
  }

  async approve(actionId: string, gesture: string): Promise<string | null> {
    const result = await this.call(() => twinApi.approve(actionId, gesture), null);
    this.pending = null;
    if (!result) return null;
    this.say('approval', `Settled as ${result.state}.`, actionId);
    await this.refresh();
    return result.state;
  }

  async reconcile(actionId: string): Promise<void> {
    const result = await this.call(() => twinApi.reconcile(actionId), null);
    if (!result) return;
    this.say('reconcile', `Asked the provider about that one again. It is ${result.state}.`, actionId);
    await this.refresh();
  }

  /** A line the twin said in this app, in the same shape the heartbeat returns. */
  say(step: string, text: string, target = ''): void {
    if (!text) return;
    this.captions = [...this.captions.slice(-5), { step, text, target }];
    this.emit();
  }

  async tick(days: number, finalOfDay: boolean): Promise<Caption[]> {
    await this.ensureToken();
    const result = await this.call(() => twinApi.tick(days, finalOfDay), null);
    if (!result) return [];
    this.captions = result.captions;
    this.adopt(result.scene);
    return result.captions;
  }

  async ask(intent: string): Promise<string> {
    const result = await this.call(() => twinApi.ask(intent), null);
    if (!result) return '';
    this.adopt(result.scene);
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

export const twin = new TwinController();
