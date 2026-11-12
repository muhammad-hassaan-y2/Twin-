import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Bot,
  Activity,
  Play,
  CheckCircle2,
  Send,
  Sparkles,
  ArrowRight,
  RefreshCw,
  Lock,
  FileText,
  DollarSign,
} from './icons';

interface Metrics {
  total_spend_cents: number;
  total_spend_usd: string;
  active_mandates: Record<string, number>;
  caught_attack_attempts: number;
  blocked_attempts: any[];
  session_state: string;
  total_transactions: number;
}

interface Invoice {
  invoice_id: string;
  external_id: string;
  client_name: string;
  amount_cents: number;
  amount_usd: string;
  state: string;
  paypal_order_id: string | null;
}

export default function App() {
  const [metrics, setMetrics] = useState<Metrics>({
    total_spend_cents: 0,
    total_spend_usd: "0.00",
    active_mandates: {},
    caught_attack_attempts: 0,
    blocked_attempts: [],
    session_state: "ONLINE",
    total_transactions: 0,
  });

  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [logs, setLogs] = useState<Array<{ id: string; time: string; text: string; type: 'success' | 'danger' | 'info' | 'warn' }>>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string; tool?: string }>>([
    {
      role: 'assistant',
      content: "Hello! I am your AI CFO. I manage client invoicing and vendor payouts through PayPal rails with strict anti-structuring oversight guards. How can I assist your business today?",
    }
  ]);
  const [isRunningSim, setIsRunningSim] = useState(false);

  // Poll metrics
  const fetchMetrics = async () => {
    try {
      const res = await fetch('/api/v1/swarm/metrics');
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
      const invRes = await fetch('/api/v1/invoices');
      if (invRes.ok) {
        const invData = await invRes.json();
        setInvoices(invData);
      }
    } catch (e) {
      console.warn("Backend not reached yet, using initial state:", e);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 3000);
    return () => clearInterval(interval);
  }, []);

  const addLog = (text: string, type: 'success' | 'danger' | 'info' | 'warn') => {
    const time = new Date().toLocaleTimeString();
    setLogs(prev => [{ id: Math.random().toString(), time, text, type }, ...prev.slice(0, 19)]);
  };

  // Run Scenarios
  const runScenario = async (scenario: string) => {
    setIsRunningSim(true);
    try {
      if (scenario === 'compliant') {
        addLog("Initiating autonomous agent procurement spend ($25.00) under mandate cap...", "info");
        const res = await fetch('/api/v1/agents/charge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: 'procure-01',
            payee_id: 'cloud-compute-inc',
            amount_cents: 2500,
            mandate_cap_cents: 50000,
          })
        });
        const data = await res.json();
        if (res.ok) {
          addLog(`✓ PayPal Order ${data.paypal_order_id} COMPLETED for $${data.amount_usd}. Transaction settled cleanly.`, "success");
        }
      } else if (scenario === 'over_cap') {
        addLog("Agent attempting $1,500.00 charge against a $500.00 mandate cap...", "warn");
        const res = await fetch('/api/v1/agents/charge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_id: 'procure-02',
            payee_id: 'server-farm-llc',
            amount_cents: 150000,
            mandate_cap_cents: 50000,
          })
        });
        const data = await res.json();
        if (res.status === 402) {
          addLog(`🛡️ GUARD TRIGGERED (HTTP 402): ${data.detail} (${data.reason}). ZERO dollars moved on PayPal.`, "danger");
        }
      } else if (scenario === 'split_attack') {
        addLog("Simulating collusive multi-agent split attack: 3 agents attempting to bypass $100 cap...", "warn");
        const res = await fetch('/api/v1/assistant/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: 'simulate split attack' })
        });
        const data = await res.json();
        addLog(`🚨 SWARM INTERCEPTION: ${data.reply}`, "danger");
      } else if (scenario === 'invoice') {
        addLog("Reviewing completed CRM engagement facts and generating server-priced invoice...", "info");
        const res = await fetch('/api/v1/assistant/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: 'price invoice' })
        });
        const data = await res.json();
        addLog(`🧾 SERVER PRICED & BILLED: ${data.reply}`, "success");
      }
      fetchMetrics();
    } catch (e: any) {
      addLog(`Error executing scenario: ${e.message}`, "danger");
    } finally {
      setIsRunningSim(false);
    }
  };

  // Chat Submission
  const handleChat = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!chatInput.trim()) return;

    const userMsg = chatInput;
    setChatInput('');
    setChatMessages(prev => [...prev, { role: 'user', content: userMsg }]);

    try {
      const res = await fetch('/api/v1/assistant/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: userMsg, operator_name: 'H. Shaukat' })
      });
      const data = await res.json();
      setChatMessages(prev => [...prev, {
        role: 'assistant',
        content: data.reply,
        tool: data.tool_called,
      }]);
      fetchMetrics();
    } catch (e: any) {
      setChatMessages(prev => [...prev, {
        role: 'assistant',
        content: `Error communicating with AI CFO: ${e.message}`,
      }]);
    }
  };

  // Capture Invoice
  const handleCapture = async (invoiceId: string) => {
    try {
      addLog(`Capturing PayPal order for invoice ${invoiceId} under operator H. Shaukat...`, "info");
      const res = await fetch(`/api/v1/invoices/${invoiceId}/capture`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_by: 'H. Shaukat' })
      });
      const data = await res.json();
      if (res.ok) {
        addLog(`✓ Invoice ${invoiceId} captured successfully on PayPal!`, "success");
      } else {
        addLog(`Capture failed: ${data.detail}`, "danger");
      }
      fetchMetrics();
    } catch (e: any) {
      addLog(`Capture error: ${e.message}`, "danger");
    }
  };

  return (
    <div className="min-h-screen bg-[#080c14] text-gray-100 p-4 md:p-8">
      {/* Top Banner */}
      <header className="max-w-7xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between pb-6 border-b border-gray-800 gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center font-bold text-white shadow-lg glow-blue text-xl">
            P
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl md:text-2xl font-bold tracking-tight text-white">
                Oversight Twin
              </h1>
              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
                PayPal AI Settlement Hub
              </span>
            </div>
            <p className="text-xs text-gray-400 mt-0.5">
              Financial settlement rails & multi-agent anti-structuring defense for autonomous enterprise AI
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-800/80 text-emerald-400 text-xs font-medium">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            PayPal Sandbox v2 Active
          </div>
          <button
            onClick={fetchMetrics}
            className="p-2 rounded-lg bg-gray-900 border border-gray-800 hover:bg-gray-800 text-gray-400 hover:text-white transition"
            title="Refresh Ledger"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="max-w-7xl mx-auto mt-6 space-y-6">
        {/* KPI Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur shadow-sm">
            <div className="flex items-center justify-between text-gray-400">
              <span className="text-xs font-medium uppercase tracking-wider">PayPal Settled Volume</span>
              <DollarSign className="w-4 h-4 text-blue-400" />
            </div>
            <div className="text-3xl font-extrabold text-blue-400 mt-3">
              ${metrics.total_spend_usd}
            </div>
            <p className="text-xs text-gray-500 mt-1 flex items-center gap-1">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> 100% Idempotent Captures
            </p>
          </div>

          <div className="p-5 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur shadow-sm">
            <div className="flex items-center justify-between text-gray-400">
              <span className="text-xs font-medium uppercase tracking-wider">Attacks Intercepted</span>
              <ShieldAlert className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-3xl font-extrabold text-amber-400 mt-3">
              {metrics.caught_attack_attempts}
            </div>
            <p className="text-xs text-emerald-400 mt-1 flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5" /> $0.00 Capital Lost to Swarms
            </p>
          </div>

          <div className="p-5 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur shadow-sm">
            <div className="flex items-center justify-between text-gray-400">
              <span className="text-xs font-medium uppercase tracking-wider">Active Agent Mandates</span>
              <Bot className="w-4 h-4 text-purple-400" />
            </div>
            <div className="text-3xl font-extrabold text-purple-400 mt-3">
              {Object.keys(metrics.active_mandates || {}).length || 4}
            </div>
            <p className="text-xs text-gray-500 mt-1">Autonomous roles monitored</p>
          </div>

          <div className="p-5 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur shadow-sm">
            <div className="flex items-center justify-between text-gray-400">
              <span className="text-xs font-medium uppercase tracking-wider">Settlement Guard</span>
              <Lock className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-3xl font-extrabold text-emerald-400 mt-3">
              FAIL-CLOSED
            </div>
            <p className="text-xs text-gray-500 mt-1">Human clearance over $300</p>
          </div>
        </section>

        {/* Swarm & PayPal Visualizer */}
        <section className="p-6 rounded-2xl bg-gray-900/40 border border-gray-800/80 backdrop-blur">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold text-white flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" /> Autonomous Multi-Agent Settlement Topology
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Every agent spend or invoice request must pass through the Oversight Twin guard before reaching PayPal rails
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-5 gap-3 mt-4">
            <div className="p-4 rounded-xl bg-gray-950/80 border border-gray-800 flex flex-col justify-between">
              <div>
                <span className="text-[10px] uppercase font-bold text-blue-400">Agent Fleet</span>
                <h3 className="text-sm font-semibold text-white mt-1">Procurement AI</h3>
                <p className="text-xs text-gray-400 mt-1">SaaS & vendor purchasing</p>
              </div>
              <div className="mt-3 text-[11px] text-gray-500 font-mono">Cap: $500/day</div>
            </div>

            <div className="p-4 rounded-xl bg-gray-950/80 border border-gray-800 flex flex-col justify-between">
              <div>
                <span className="text-[10px] uppercase font-bold text-purple-400">Agent Fleet</span>
                <h3 className="text-sm font-semibold text-white mt-1">Billing & Invoicing</h3>
                <p className="text-xs text-gray-400 mt-1">Pricing verified CRM cases</p>
              </div>
              <div className="mt-3 text-[11px] text-emerald-400 font-mono">Server-Priced Only</div>
            </div>

            <div className="p-4 rounded-xl bg-gray-950/80 border border-gray-800 flex flex-col justify-between">
              <div>
                <span className="text-[10px] uppercase font-bold text-amber-400">Agent Fleet</span>
                <h3 className="text-sm font-semibold text-white mt-1">26-Desk Compliance</h3>
                <p className="text-xs text-gray-400 mt-1">Regulatory & sanctions review</p>
              </div>
              <div className="mt-3 text-[11px] text-gray-500 font-mono">EU Article Audit</div>
            </div>

            <div className="p-4 rounded-xl bg-blue-950/30 border border-blue-500/40 flex flex-col justify-between shadow-sm glow-blue">
              <div>
                <span className="text-[10px] uppercase font-bold text-emerald-400">Security Guard</span>
                <h3 className="text-sm font-semibold text-white mt-1">Oversight Twin</h3>
                <p className="text-xs text-gray-300 mt-1">Sliding-window monitor</p>
              </div>
              <div className="mt-3 text-[11px] text-blue-300 font-mono">Anti-Structuring Active</div>
            </div>

            <div className="p-4 rounded-xl bg-blue-600/20 border border-blue-500 flex flex-col justify-between shadow-lg">
              <div>
                <span className="text-[10px] uppercase font-bold text-blue-300">Financial Hub</span>
                <h3 className="text-sm font-semibold text-white mt-1">PayPal Orders v2</h3>
                <p className="text-xs text-gray-300 mt-1">Deterministic Settlement</p>
              </div>
              <div className="mt-3 text-[11px] text-blue-200 font-mono">Idempotency-Keyed</div>
            </div>
          </div>
        </section>

        {/* Demo Lab & Interactive Scenarios */}
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-7 space-y-6">
            {/* 1-Click Hackathon Scenarios */}
            <div className="p-6 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-base font-semibold text-white flex items-center gap-2">
                    <Play className="w-4 h-4 text-emerald-400" /> Live Hackathon Demo Simulator
                  </h2>
                  <p className="text-xs text-gray-400">
                    Trigger live agent transactions to prove the PayPal settlement & safety mechanisms
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  disabled={isRunningSim}
                  onClick={() => runScenario('compliant')}
                  className="p-4 rounded-xl bg-gray-950/90 border border-emerald-500/40 hover:border-emerald-500 text-left transition group hover:glow-emerald"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-emerald-400 uppercase tracking-wide">Scenario 1</span>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-emerald-400 transition" />
                  </div>
                  <h4 className="text-sm font-semibold text-white mt-1">Compliant Vendor Spend</h4>
                  <p className="text-xs text-gray-400 mt-1">
                    Agent spends $25.00 within mandate → Passes guard → PayPal Order COMPLETED.
                  </p>
                </button>

                <button
                  disabled={isRunningSim}
                  onClick={() => runScenario('over_cap')}
                  className="p-4 rounded-xl bg-gray-950/90 border border-red-500/40 hover:border-red-500 text-left transition group hover:glow-red"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-red-400 uppercase tracking-wide">Scenario 2</span>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-red-400 transition" />
                  </div>
                  <h4 className="text-sm font-semibold text-white mt-1">Single-Agent Cap Breach</h4>
                  <p className="text-xs text-gray-400 mt-1">
                    Agent attempts $1,500 vs $500 cap → Guard halts with HTTP 402 ($0 to PayPal).
                  </p>
                </button>

                <button
                  disabled={isRunningSim}
                  onClick={() => runScenario('split_attack')}
                  className="p-4 rounded-xl bg-gray-950/90 border border-amber-500/40 hover:border-amber-500 text-left transition group"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-amber-400 uppercase tracking-wide">Scenario 3</span>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-amber-400 transition" />
                  </div>
                  <h4 className="text-sm font-semibold text-white mt-1">Collusive Split Attack</h4>
                  <p className="text-xs text-gray-400 mt-1">
                    Agents A ($40) + B ($40) pass. Agent C ($30) attempts split → Caught instantly!
                  </p>
                </button>

                <button
                  disabled={isRunningSim}
                  onClick={() => runScenario('invoice')}
                  className="p-4 rounded-xl bg-gray-950/90 border border-blue-500/40 hover:border-blue-500 text-left transition group hover:glow-blue"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-blue-400 uppercase tracking-wide">Scenario 4</span>
                    <ArrowRight className="w-3.5 h-3.5 text-gray-500 group-hover:text-blue-400 transition" />
                  </div>
                  <h4 className="text-sm font-semibold text-white mt-1">Server-Priced Invoicing</h4>
                  <p className="text-xs text-gray-400 mt-1">
                    Audits CRM engagement → Server sets verified price → Opens PayPal checkout order.
                  </p>
                </button>
              </div>

              {/* Console log */}
              <div className="mt-5 p-4 rounded-xl bg-black/80 border border-gray-800 font-mono text-xs max-h-48 overflow-y-auto space-y-1.5">
                <div className="text-gray-500 pb-1 border-b border-gray-900 flex justify-between items-center">
                  <span>// Live Settlement Console & Oversight Telemetry</span>
                  <span className="text-[10px] text-gray-600">Auto-scrolling</span>
                </div>
                {logs.length === 0 ? (
                  <div className="text-gray-600 italic py-2">Click any scenario above to observe live transaction execution...</div>
                ) : (
                  logs.map(log => (
                    <div key={log.id} className="leading-relaxed">
                      <span className="text-gray-600">[{log.time}] </span>
                      <span className={
                        log.type === 'success' ? 'text-emerald-400' :
                        log.type === 'danger' ? 'text-red-400 font-semibold' :
                        log.type === 'warn' ? 'text-amber-400' : 'text-blue-400'
                      }>{log.text}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Invoices List */}
            <div className="p-6 rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur">
              <h2 className="text-base font-semibold text-white flex items-center gap-2 mb-3">
                <FileText className="w-4 h-4 text-blue-400" /> Client Invoicing & PayPal Orders
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-gray-400 border-b border-gray-800">
                    <tr>
                      <th className="pb-2">Invoice ID</th>
                      <th className="pb-2">Client</th>
                      <th className="pb-2">Amount</th>
                      <th className="pb-2">PayPal Status</th>
                      <th className="pb-2 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/50">
                    {invoices.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="py-4 text-center text-gray-500">
                          No client invoices generated yet. Click "Scenario 4" or prompt the AI CFO!
                        </td>
                      </tr>
                    ) : (
                      invoices.map(inv => (
                        <tr key={inv.invoice_id}>
                          <td className="py-2.5 font-mono text-gray-300">{inv.invoice_id}</td>
                          <td className="py-2.5 text-white font-medium">{inv.client_name}</td>
                          <td className="py-2.5 text-emerald-400 font-semibold">${inv.amount_usd}</td>
                          <td className="py-2.5">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                              inv.state === 'captured' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                              inv.state === 'awaiting_capture' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                              'bg-gray-800 text-gray-300'
                            }`}>
                              {inv.state}
                            </span>
                          </td>
                          <td className="py-2.5 text-right">
                            {inv.state === 'awaiting_capture' && (
                              <button
                                onClick={() => handleCapture(inv.invoice_id)}
                                className="px-2.5 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded font-medium text-[10px] transition"
                              >
                                Human Capture
                              </button>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* AI CFO Assistant Panel */}
          <div className="lg:col-span-5 flex flex-col h-full rounded-2xl bg-gray-900/60 border border-gray-800/80 backdrop-blur p-6">
            <div className="flex items-center gap-2 pb-4 border-b border-gray-800">
              <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">AI CFO Assistant</h3>
                <p className="text-[11px] text-gray-400">Natural Language Tool Dispatcher</p>
              </div>
            </div>

            {/* Chat Messages */}
            <div className="flex-1 overflow-y-auto space-y-3 py-4 text-xs min-h-[360px] max-h-[500px]">
              {chatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`p-3 rounded-xl max-w-[85%] leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-950 border border-gray-800 text-gray-200'
                  }`}>
                    {msg.content}
                    {msg.tool && (
                      <div className="mt-2 pt-1 border-t border-gray-800/80 text-[10px] text-blue-400 font-mono flex items-center gap-1">
                        <CheckCircle2 className="w-3 h-3 text-blue-400" /> Tool Executed: {msg.tool}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Quick Prompts */}
            <div className="py-2 border-t border-gray-800/50 flex flex-wrap gap-1.5">
              <button
                onClick={() => setChatInput("What is our current PayPal treasury spend and attack metrics?")}
                className="px-2 py-1 bg-gray-950 hover:bg-gray-800 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white transition"
              >
                📊 Treasury Metrics
              </button>
              <button
                onClick={() => setChatInput("Price and bill client Acme GmbH on PayPal")}
                className="px-2 py-1 bg-gray-950 hover:bg-gray-800 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white transition"
              >
                🧾 Bill Client Acme
              </button>
              <button
                onClick={() => setChatInput("Simulate a split attack to test our guards")}
                className="px-2 py-1 bg-gray-950 hover:bg-gray-800 border border-gray-800 rounded text-[10px] text-gray-400 hover:text-white transition"
              >
                🛡️ Test Split Attack
              </button>
            </div>

            {/* Input Form */}
            <form onSubmit={handleChat} className="mt-2 flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                placeholder="Ask the AI CFO or execute tools..."
                className="flex-1 bg-gray-950 border border-gray-800 px-3 py-2 rounded-xl text-xs focus:outline-none focus:border-blue-500"
              />
              <button
                type="submit"
                className="p-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-white transition flex items-center justify-center"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </section>
      </main>
    </div>
  );
}
