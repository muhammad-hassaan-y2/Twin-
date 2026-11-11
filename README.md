# Twin: Tabletop Twin, Swarm Oversight & PayPal Settlement Hub

This repository holds two core projects, the enterprise integration that joins them, and the **PayPal AI Hackathon Oversight Twin** production service.

- **`swarm-oversight`**: The Apart Swarm Alignment sprint entry (Track 4, multi-agent oversight and control). It measures the aggregate gap in agent payment protocols (such as Google's AP2): a per-mandate spending cap does not bind the principal across separately issued mandates. A swarm-level monitor and a gateway score defences in money, from seeded logs, with confidence intervals and negative controls.
- **`tabletop-twin`**: A miniature of one person's next ninety days of cash, standing on their real table, that they can push around with their hands in XR. A Python service owns the ledger, the forecast, the spending policy, a payment state machine and a real PayPal settlement transport; an Immersive Web SDK client owns the table, the gestures and the captions.
- **`integration`**: The joined enterprise system: a PayPal-centred settlement hub and a client billing desk guarded by swarm-oversight. Twenty-six audit, tax and finance roles review an engagement; binding findings become payment instructions; a named person clears them; the principal-wide monitor holds the aggregate bound; the merchant book bills the client through PayPal and captures once.
- **`app/` (PayPal AI Hackathon Oversight Twin)**: FastAPI REST gateway placing the multi-agent guard inline in the PayPal execution pipeline before `charge()` hits the PayPal Sandbox API.

---

## PayPal AI Hackathon — Oversight Twin API

The **`oversight_twin`** wrapper places the multi-agent guard inline in the
PayPal execution pipeline before `charge()` hits the PayPal Sandbox API.

```mermaid
graph TD
    A[Client] -->|POST /api/v1/agents/charge| B(FastAPI: app/main.py)
    B -->|Session.observe(Action)| C(Oversight Twin: app/oversight_twin.py)
    C -->|Monitor.review()| D[swarm-oversight Monitor]
    D -->|Flags: over_limit / relay / split| C
    C -- MoneyNotMoved -->|HTTP 402 + FAILED| B
    C -- Pass -->|Route to PayPal| E(PayPal Client: app/paypal_client.py)
    E -->|POST /v2/checkout/orders| F[PayPal Sandbox API]
    F -->|Order ID + status| E
    E -->|ORDER details + COMPLETED| B
    B -->|JSON response| A

    G[GET /api/v1/swarm/metrics] -->|Aggregate stats| B
    B -->|JSON metrics| G
```

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/agents/charge` | Run the oversight guard; if clean, create a PayPal order. Returns `200 COMPLETED`, `402 FAILED`, or `500 UNKNOWN`. |
| `GET` | `/api/v1/swarm/metrics` | Return aggregate swarm metrics: total spend, active mandates, caught attack attempts. |

### Endpoint: POST /api/v1/agents/charge

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | `str` | Identifier of the agent initiating the charge. |
| `payee_id` | `str` | Identifier of the payee receiving the funds. |
| `amount_cents` | `int` | Payment amount in **integer cents** (e.g., `1500` → `"15.00"` USD). |
| `mandate_cap_cents` | `int` | Per-agent spending cap in cents. |

**Success response (200):**

```json
{
  "state": "COMPLETED",
  "reason": null,
  "paypal_order_id": "ORDER-123456789",
  "paypal_order_json": { ... },
  "payee_id": "payee-01",
  "amount_cents": 1500,
  "amount_usd": "15.00"
}
```

**Cap‑breach response (402):**

```json
{
  "state": "FAILED",
  "reason": "Spending cap breached"
}
```

**PayPal/network error response (500/UNKNOWN):**

```json
{
  "state": "UNKNOWN",
  "reason": "PayPal request failed — see UNKNOWN state for reconciliation",
  "detail": "..."
}
```

### Swarm Metrics: GET /api/v1/swarm/metrics

```json
{
  "total_spend_cents": 45000,
  "active_mandates": {
    "agent-01": 100000,
    "agent-02": 75000
  },
  "caught_attack_attempts": 3,
  "session_state": "PENDING"
}
```

---

## Project Structure

```
Twin/
├─ app/                  # FastAPI REST gateway with Oversight Twin guard
│  ├─ main.py
│  ├─ oversight_twin.py
│  ├─ paypal_client.py
│  └─ model.py
├─ integration/          # Enterprise settlement pipeline & merchant billing desk
│  ├─ oversight_twin/    # Hub, store, CRM, LLM tools, pipeline
│  └─ tests/
├─ swarm-oversight/      # Multi-agent AI safety monitor & research suite
│  ├─ swarm_oversight/   # Gateway, monitor, adversary models, frontiers
│  ├─ results/           # Empirical evaluation logs and figures
│  └─ tests/
├─ tabletop-twin/        # Immersive XR client & backend forecasting twin
│  ├─ backend/           # Forecasting engine, payment state machine, persona
│  ├─ chain/             # Smart contracts and agent registries
│  └─ web/               # Immersive Web SDK XR frontend
├─ specs/                # Architectural & functional specifications
├─ tests/                # Hackathon test suite
├─ Dockerfile            # Multi-stage container build
├─ docker-compose.yml    # Compose definition for API & dependencies
└─ Tiltfile              # Local development cluster setup
```

---

## Installation & Running

### 1. Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate on Windows
pip install fastapi uvicorn httpx pytest pytest-requests
```

### 2. Environment Variables

Create a `.env` file in the root directory:

```env
# PayPal Sandbox credentials (required for real API calls)
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_SECRET=your-sandbox-secret
```

If `PAYPAL_CLIENT_ID` and `PAYPAL_SECRET` are not set, the app runs in safe mock mode for testing oversight guards.

### 3. Run the Hackathon API

```bash
# Docker Compose:
docker-compose up --build api

# Or directly with Uvicorn:
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run the Tests

```bash
# Hackathon API suite:
pytest tests/test_hackathon_submission.py -v

# Swarm oversight safety harness:
pytest swarm-oversight/tests/ -v

# Enterprise integration suite:
pytest integration/tests/ -v
```

### 5. Full Stack Development (Tilt & Tabletop Twin)

For the XR tabletop client and backend development:
```sh
examples/common/certs/generate_ca.sh
tilt up
```

From `integration`:
```sh
python -m oversight_twin.showcase
```
Tells the whole story in one command, with every figure measured during the run.
