# Factory Maintenance AI System

AI-powered factory maintenance coordination system with 11 AI agents for end-to-end maintenance workflow management.

## Features

- **11 AI Agents** coordinating fault investigation, parts sourcing, technician scheduling, production coordination, and repair verification
- **Human-in-the-loop approval** - No execution before explicit human approval
- **Full workflow**: Incident → Investigation → Plan → Approval → Work Order → Verification → Closure
- **Image upload** for failed component and repair completion photos
- **SQLite database** with SQLAlchemy ORM
- **REST API** with FastAPI and Swagger documentation
- **React + TypeScript frontend** with Tailwind CSS
- **Comprehensive test suite**

## Architecture

```
factory-maintenance-ai/
├── frontend/                 # React + Vite + TypeScript
│   ├── src/
│   │   ├── components/       # Reusable UI components
│   │   ├── pages/            # Page components
│   │   ├── services/         # API services and utilities
│   │   └── types/            # TypeScript type definitions
│   └── package.json
└── backend/                  # Python + FastAPI
    ├── app/
    │   ├── agents/           # 11 AI Agent implementations
    │   ├── api/              # REST API routes
    │   ├── models/           # SQLAlchemy models
    │   ├── schemas/          # Pydantic schemas
    │   ├── services/         # Business logic services
    │   ├── database.py       # Database configuration
    │   ├── config.py         # Application configuration
    │   └── main.py           # FastAPI application entry
    ├── uploads/              # Local file storage
    ├── tests/                # Pytest test suite
    └── requirements.txt
```

## The 11 AI Agents

1. **Incident Intake Agent** - Validates incident data and stores details
2. **Visual Inspection Agent** - Analyzes component photo for visual clues (simulated)
3. **Fault Diagnosis Agent** - Identifies likely fault and root cause (simulated)
4. **Parts Sourcing Agent** - Searches inventory for replacement parts
5. **Procurement Agent** - Creates purchase requests for unavailable parts
6. **Technician Scheduling Agent** - Matches repair to available technicians
7. **Production Coordination Agent** - Proposes optimal downtime window
8. **Maintenance Planning Agent** - Combines findings into repair plan with risk assessment
9. **Human Approval Agent** - Pauses workflow for human approval
10. **Work Order Execution Agent** - Creates and advances work orders
11. **Repair Verification Agent** - Verifies repair with completion photo (simulated)

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm or yarn

### Backend Setup

```bash
cd factory-maintenance-ai/backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Run backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at:
- **API**: http://localhost:8000
- **Swagger Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Frontend Setup

```bash
cd factory-maintenance-ai/frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The frontend will be available at http://localhost:5173

### Running Tests

```bash
cd factory-maintenance-ai/backend

# Run all tests
pytest -v

# Run with coverage
pytest --cov=app --cov-report=html
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLite database path | `sqlite:///./factory_maintenance.db` |
| `UPLOAD_DIR` | File upload directory | `./uploads` |
| `MAX_FILE_SIZE` | Max upload size (bytes) | `10485760` (10MB) |
| `ALLOWED_EXTENSIONS` | Allowed file extensions | `jpg,jpeg,png` |
| `LLM_API_KEY` | Optional LLM API key | - |
| `LLM_API_URL` | Optional LLM API endpoint | - |
| `LLM_MODEL` | Optional LLM model name | - |
| `APP_ENV` | Environment | `development` |
| `DEBUG` | Debug mode | `true` |
| `SECRET_KEY` | Secret key for sessions | `your-secret-key-change-in-production` |

## API Endpoints

### Health & Dashboard
- `GET /api/health` - Health check
- `GET /api/dashboard` - Dashboard metrics

### Incidents
- `POST /api/incidents` - Create incident with photo
- `GET /api/incidents` - List incidents
- `GET /api/incidents/{id}` - Get incident details
- `POST /api/incidents/{id}/investigate` - Start AI investigation
- `GET /api/incidents/{id}/agents` - Get agent execution status
- `GET /api/incidents/{id}/plan` - Get maintenance plan
- `POST /api/incidents/{id}/approve` - Approve/reject plan

### Work Orders
- `GET /api/work-orders` - List work orders
- `GET /api/work-orders/{id}` - Get work order details
- `POST /api/work-orders/{id}/execute` - Execute work order action
- `POST /api/work-orders/{id}/verification` - Upload repair photo
- `POST /api/work-orders/{id}/close` - Close verified work order

### Reference Data
- `GET /api/technicians` - List technicians
- `POST /api/technicians` - Create technician
- `GET /api/parts` - List inventory parts
- `POST /api/parts` - Create inventory part

### Activity
- `GET /api/activity` - Recent workflow activity

### Admin
- `POST /api/admin/seed` - Seed database
- `POST /api/admin/reset` - Reset and seed database

## Workflow

```
1. Operator creates incident + uploads failed component photo
         │
         ▼
2. 11 AI agents run in sequence:
   ├── Incident Intake → Validates data
   ├── Visual Inspection → Analyzes photo (simulated)
   ├── Fault Diagnosis → Identifies failure (simulated)
   ├── Parts Sourcing → Finds replacement part
   ├── Procurement → Creates PO if needed
   ├── Technician Scheduling → Assigns technician
   ├── Production Coordination → Proposes downtime
   ├── Maintenance Planning → Creates plan + risk assessment
   └── Human Approval → PAUSES for human decision
         │
         ▼ (if approved)
3. Work Order Execution Agent creates work order
         │
         ▼
4. Technician executes repair (start → complete)
         │
         ▼
5. Operator uploads repair completion photo
         │
         ▼
6. Repair Verification Agent compares photos (simulated)
         │
         ├── Verified → Work order can be closed
         ├── Failed/Inconclusive → Human override or re-upload
         │
         ▼
7. Work order closed
```

## Safety Rules (Enforced in Backend)

- ❌ No execution before human approval
- ❌ Rejected plans cannot execute
- ❌ Missing parts treated as unavailable
- ❌ Failed verification blocks closure
- ❌ Only verified repairs can be closed
- ✅ All transitions logged in audit trail
- ✅ Status transitions validated

## Simulated AI Components

The following agents use simulated logic for the MVP (clearly labeled in responses):

- **Visual Inspection Agent** - Simulates photo analysis based on severity
- **Fault Diagnosis Agent** - Rule-based diagnosis from visual clues
- **Repair Verification Agent** - Randomized verification with confidence scores

These are designed to be replaceable with real vision/LLM models by implementing the same interfaces.

## Database Models

- **Incident** - Maintenance incidents with photos
- **AgentRun** - Execution log for each agent
- **MaintenancePlan** - Proposed repair plans
- **Technician** - Available technicians with skills
- **InventoryPart** - Spare parts inventory
- **WorkOrder** - Work orders with scheduling
- **RepairVerification** - Photo verification results
- **ActivityLog** - Audit trail

## Development

### Backend Structure
```python
# Adding a new agent:
# 1. Create app/agents/new_agent.py extending BaseAgent
# 2. Register in app/agents/__init__.py
# 3. Add to AGENT_REGISTRY
```

### Frontend Structure
```typescript
// Adding a new page:
// 1. Create component in src/pages/
// 2. Add route in App.tsx
// 3. Add navigation in Sidebar.tsx
```

## License

MIT License - See LICENSE file for details