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

/** What a forked world cost or bought, beside the one already on the table. */
export interface Fork {
  branch: string;
  label: string;
  delta: {
    key: string;
    label: string;
    min_balance_change_dollars: number;
    cost_change_dollars: number;
    dry_probability_change: number;
    shortfall_day_change: number | null;
    verdict: string;
  };
}

export interface Payment {
  action_id: string;
  state: string;
  recipient: string;
  amount_dollars: number;
  attempt: number;
  idempotency_key: string;
  verified: boolean;
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
  payments: Payment[];
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

/** The only gesture string the payment state machine will settle with. */
/** A pinch shorter than this is not an approval. It is an accident. */
export const APPROVAL_HOLD_SEC = 1;
export const APPROVAL_GESTURE = `pinch_hold_${APPROVAL_HOLD_SEC}s`;

export interface Account {
  token: string;
  user_id: string;
  name: string;
}

const TOKEN_KEY = 'twin.token';
const NAME_KEY = 'twin.account';
const DEVICE_KEY = 'twin.device';

/**
 * Which world this browser is looking at.
 *
 * The token is the bearer credential the twin issued; without it every endpoint
 * answers 401, so a table that never signed in is a table that draws nothing.
 */
export const session = {
  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },

  get name(): string {
    return localStorage.getItem(NAME_KEY) ?? '';
  },

  set(account: Account | null): void {
    if (account) {
      localStorage.setItem(TOKEN_KEY, account.token);
      localStorage.setItem(NAME_KEY, account.name);
      return;
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(NAME_KEY);
  },

  /** The credentials of the world this browser made for itself, kept so a reload rejoins it. */
  device(): { email: string; password: string } {
    const saved = localStorage.getItem(DEVICE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved) as { email?: string; password?: string };
        if (parsed.email && parsed.password) return { email: parsed.email, password: parsed.password };
      } catch {
        // A half-written entry is just a missing one.
      }
    }
    const bytes = new Uint8Array(9);
    crypto.getRandomValues(bytes);
    const id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    const account = { email: `twin-${id}@table.local`, password: id.repeat(2) };
    localStorage.setItem(DEVICE_KEY, JSON.stringify(account));
    return account;
  },
};

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const token = session.token;
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    if (response.status === 401 && session.token) session.set(null);
    throw new Error(`${path} -> ${response.status}`);
  }
  return (await response.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body ?? {}),
  });
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET', headers: headers() });
}

export const twinApi = {
  signup: (email: string, password: string, name = '') => post<Account>('/v1/signup', { email, name, password }),
  login: (email: string, password: string) => post<Account>('/v1/login', { email, password }),
  logout: () => post<{ signed_out: boolean }>('/v1/logout', {}),
  me: () => get<{ user_id: string; name: string; persona: string; day: number; horizon_days: number; events: number }>('/v1/me'),
  world: () => get<ScenePayload>('/v1/world'),
  health: () => get<{
    ok: boolean;
    persona: string;
    planner: string;
    route: string;
    model_providers: string[];
    heartbeat_steps: string[];
    heartbeat_unwired: string[];
    paypal_configured: boolean;
    accounts: boolean;
  }>('/v1/health'),
  persona: () => get<{
    name: string;
    voice: string;
    prohibitions: string[];
    loop: string[];
    heartbeat: { slug: string; index: number; title: string; body: string }[];
  }>('/v1/persona'),
  scrub: (day: number) => post<{ day: number; scene: ScenePayload }>('/v1/scrub', { day }),
  pull: (event_id: string) => post<{ fork: Fork; scene: ScenePayload }>('/v1/pull', { event_id }),
  tick: (days: number, final_of_day: boolean) =>
    post<{ day: number; captions: Caption[]; scene: ScenePayload }>('/v1/tick', { days, final_of_day }),
  ask: (intent: string) =>
    post<{ said: string; focus: string; scene: ScenePayload }>('/v1/ask', { intent }),
  propose: (calls: unknown[]) => post<{ results: Record<string, unknown>[]; scene: ScenePayload }>('/v1/tools', { calls }),
  approve: (action_id: string, gesture: string) =>
    post<{ action_id: string; state: string; error?: string }>('/v1/approve', { action_id, gesture }),
  reconcile: (action_id: string) => post<{ action_id: string; state: string }>('/v1/reconcile', { action_id }),
};
