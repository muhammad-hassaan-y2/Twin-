/**
 * The single owner of everything the client knows.
 *
 * Systems never fetch on their own and never invent a number: they call one of
 * these methods, the controller asks the twin, and every listener redraws from
 * the payload that came back. One source, so two props cannot drift apart.
 */

import { twinApi } from './client.js';
import type { Caption, ScenePayload, Verdict } from './client.js';

type Listener = () => void;

class TwinController {
  payload: ScenePayload | null = null;
  /** The action the policy engine put on hold for a hand gesture. */
  pending: Verdict | null = null;
  captions: Caption[] = [];
  offline = false;
  route = '';
  private listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }

  private adopt(scene: ScenePayload | undefined): void {
    if (scene) this.payload = scene;
    this.offline = false;
    this.emit();
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

  async boot(): Promise<void> {
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

  async pull(eventId: string): Promise<boolean> {
    const result = await this.call(() => twinApi.pull(eventId), null);
    if (result) this.adopt(result.scene);
    return result !== null;
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
    await this.call(() => twinApi.reconcile(actionId), {});
    await this.refresh();
  }

  /** A line the twin said in this app, in the same shape the heartbeat returns. */
  say(step: string, text: string, target = ''): void {
    if (!text) return;
    this.captions = [...this.captions.slice(-5), { step, text, target }];
    this.emit();
  }

  async tick(days: number, finalOfDay: boolean): Promise<Caption[]> {
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
    if (result) {
      this.payload = result;
      this.offline = false;
      this.emit();
    }
  }
}

export const twin = new TwinController();
