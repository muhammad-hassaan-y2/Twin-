/**
 * The only place the client talks to the twin.
 *
 * Every number that reaches the table comes from here. The client never does
 * cash arithmetic: it asks, it receives a scene description, it draws.
 */

export interface Stone {
  id: string;
  event_id: string;
  label: string;
  kind: string;
  day: number;
  amount_dollars: number;
  height: number;
  below_surface: boolean;
  cancellable: boolean;
}

export interface Boat {
  id: string;
  label: string;
  day: number;
  amount_dollars: number;
  fog: number;
  worst_lag_days: number;
  stuck: boolean;
}

export interface ReliabilityBin {
  bin: string;
  n: number;
  predicted: number;
  observed: number;
  gap: number;
}

export interface Branch {
  key: string;
  label: string;
  min_balance_dollars: number;
  min_balance_change_dollars: number;
  cost_change_dollars: number;
  dry_probability_change: number;
  shortfall_day_change: number | null;
  verdict: string;
}

export interface ScenePayload {
  meta: {
    persona: string;
    day: number;
    horizon_days: number;
    runs: number;
    seed: number;
    currency: string;
    generated_by: string;
  };
  palette: Record<string, string>;
  river: {
    p10_dollars: number[];
    p50_dollars: number[];
    p90_dollars: number[];
    dry_probability: number[];
    pinch_day: number;
  };
  stones: Stone[];
  boats: Boat[];
  lake: { feed_event_ids: string[]; depth_dollars: number };
  garden: {
    stage: number;
    accuracy_pct: number;
    brier: number;
    resolved: number;
    open: number;
    reliability: ReliabilityBin[];
  };
  branches: Branch[];
  focus: string;
  twin: { look_at: string; speak: string };
}

export interface Caption {
  step: string;
  text: string;
  target: string;
}

export interface Verdict {
  action_id: string;
  verb: string;
  amount_cents: number;
  recipient: string;
  verdict: 'allow' | 'require_approval' | 'deny';
  reason: string;
  rule: string;
  state: string;
  idempotency_key?: string;
  error?: string;
}

const BASE = (import.meta.env.VITE_TWIN_API ?? 'http://localhost:8000').replace(/\/+$/u, '');

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return (await response.json()) as T;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return (await response.json()) as T;
}

export const twinApi = {
  world: () => get<ScenePayload>('/v1/world'),
  health: () => get<{ planner: string; route: string; persona: string }>('/v1/health'),
  persona: () => get<{ name: string; voice_prompt?: string; steps: { slug: string; title: string }[] }>('/v1/persona'),
  scrub: (day: number) => post<{ day: number; scene: ScenePayload }>('/v1/scrub', { day }),
  pull: (event_id: string) => post<{ fork: unknown; scene: ScenePayload }>('/v1/pull', { event_id }),
  tick: (days: number, final_of_day: boolean) =>
    post<{ day: number; captions: Caption[]; scene: ScenePayload }>('/v1/tick', { days, final_of_day }),
  ask: (intent: string) =>
    post<{ said: string; focus: string; scene: ScenePayload }>('/v1/ask', { intent }),
  propose: (calls: unknown[]) => post<{ results: Record<string, unknown>[]; scene: ScenePayload }>('/v1/tools', { calls }),
  approve: (action_id: string, gesture: string) =>
    post<{ action_id: string; state: string; error?: string }>('/v1/approve', { action_id, gesture }),
  reconcile: (action_id: string) => post<Record<string, unknown>>('/v1/reconcile', { action_id }),
};
