/**
 * App.jsx — FD Rate Comparison Frontend
 * Premium fintech dashboard with modern UI/UX
 *
 * Features:
 *  - Compare all banks for a given tenure → table + bar chart
 *  - Best rate finder → ranked cards with medals
 *  - Bank tenure list → full rate table for one bank
 *
 * Stack: React + Recharts (charts) + premium CSS
 */

import { useState, useEffect, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, LineChart, Line
} from "recharts";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

// ── API helpers ───────────────────────────────────────────────────────────────
const post = (url, body) =>
  fetch(`${API}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(r => r.json());

const get = (url) => fetch(`${API}${url}`).then(r => r.json());

// ── Tenure helpers ────────────────────────────────────────────────────────────
const TENURES = [
  { label: "7 Days", days: 7 },
  { label: "1 Month", days: 30 },
  { label: "3 Months", days: 90 },
  { label: "6 Months", days: 180 },
  { label: "1 Year", days: 365 },
  { label: "2 Years", days: 730 },
  { label: "3 Years", days: 1095 },
  { label: "5 Years", days: 1825 },
];

const COLORS = { SBI: "#2563eb", ICICI: "#f59e0b", Kotak: "#10b981" };

// ── Components ────────────────────────────────────────────────────────────────

// Skeleton Loaders
function SkeletonTable() {
  return (
    <div className="skeleton-table">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="skeleton skeleton-row" />
      ))}
    </div>
  );
}

function SkeletonChart() {
  return <div className="skeleton skeleton-chart" />;
}

function SkeletonCards() {
  return (
    <div className="skeleton-cards">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="skeleton skeleton-card" />
      ))}
    </div>
  );
}

// Error Message
function ErrorMsg({ msg }) {
  return (
    <div className="error-alert">
      <div className="error-icon">⚠️</div>
      <div className="error-content">
        <div className="error-title">Error</div>
        <div className="error-message">{msg}</div>
      </div>
    </div>
  );
}

// Empty State
function EmptyState({ icon, text, hint }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <div className="empty-state-text">{text}</div>
      {hint && <div className="empty-state-hint">{hint}</div>}
    </div>
  );
}

// Pill Selector Component
function PillSelector({ options, value, onChange, labelKey = "label", valueKey = "days" }) {
  return (
    <div className="pill-selector">
      {options.map(opt => (
        <button
          key={opt[valueKey]}
          className={`pill ${value === opt[valueKey] ? "active" : ""}`}
          onClick={() => onChange(opt[valueKey])}
        >
          {opt[labelKey]}
        </button>
      ))}
    </div>
  );
}

// Chat View — Natural Language Interface
function ChatView({ log }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    const query = input.trim();
    if (!query || loading) return;

    const userMsg = { role: "user", text: query };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    log("query", `Chat: ${query}`);

    try {
      const res = await post("/chat", { query });
      setMessages(prev => [...prev, { role: "assistant", text: res.answer }]);
      log("result", "Chat answered");
    } catch (e) {
      setMessages(prev => [...prev, {
        role: "error",
        text: `Error: ${e.message || "Failed to get response"}`
      }]);
      log("error", e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const setExample = (text) => {
    setInput(text);
  };

  return (
    <section className="card chat-view">
      <h2>💬 Ask Anything</h2>
      <p className="chat-subtitle">Natural language questions about FD rates</p>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-welcome">
            <p>👋 Hi! Ask me anything about FD rates.</p>
            <div className="chat-examples">
              <button onClick={() => setExample("What is SBI's rate for 1 year?")}>
                What is SBI's rate for 1 year?
              </button>
              <button onClick={() => setExample("Compare all banks for 2 years")}>
                Compare all banks for 2 years
              </button>
              <button onClick={() => setExample("Best rate for senior citizens")}>
                Best rate for senior citizens
              </button>
              <button onClick={() => setExample("Show me ICICI's rates for all tenures")}>
                Show me ICICI's rates for all tenures
              </button>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`chat-bubble chat-${msg.role}`}>
            <div className="bubble-content">
              {msg.role === "assistant" ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {msg.text}
                </ReactMarkdown>
              ) : (
                msg.text
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="chat-bubble chat-assistant">
            <div className="bubble-content typing">Thinking...</div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input-row">
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Ask about FD rates..."
          rows={2}
          disabled={loading}
        />
        <button onClick={sendMessage} disabled={!input.trim() || loading}>
          {loading ? "..." : "Send"}
        </button>
      </div>
    </section>
  );
}

// Comparison Table + Bar Chart
function CompareView({ log }) {
  const [days, setDays] = useState(365);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetch = async () => {
    setLoading(true); setError(null); setData(null);
    const label = TENURES.find(t => t.days === days)?.label || `${days}d`;
    log("query", `Compare all banks — ${label}`);
    try {
      const res = await post("/compare", { days });
      if (res.status === "error") throw new Error(res.error);
      setData(res);
      log("result", `Best general: ${res.best_general} | Best senior: ${res.best_senior}`);
    } catch (e) { setError(e.message); log("error", e.message); }
    finally { setLoading(false); }
  };

  // Calculate best rates for highlighting
  const bestGeneralRate = data?.comparison?.reduce((max, r) =>
    r.general_rate > max ? r.general_rate : max, 0) || 0;
  const bestSeniorRate = data?.comparison?.reduce((max, r) =>
    r.senior_rate > max ? r.senior_rate : max, 0) || 0;

  const chartData = data?.comparison?.map(r => ({
    bank: r.bank,
    General: r.general_rate,
    Senior: r.senior_rate,
  })) || [];

  return (
    <section className="card">
      <h2>Compare Banks</h2>

      <PillSelector
        options={TENURES}
        value={days}
        onChange={setDays}
      />

      <button onClick={fetch}>Compare Rates</button>

      {loading && (
        <>
          <SkeletonTable />
          <SkeletonChart />
        </>
      )}
      {error && <ErrorMsg msg={error} />}

      {data && <>
        {/* Table */}
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Bank</th>
                <th>Tenure</th>
                <th>General Rate</th>
                <th>Senior Rate</th>
                <th>Difference</th>
              </tr>
            </thead>
            <tbody>
              {data.comparison.map(r => {
                const generalDiff = r.general_rate - bestGeneralRate;
                const seniorDiff = r.senior_rate - bestSeniorRate;

                return (
                  <tr key={r.bank}>
                    <td>
                      <span className="bank-tag" style={{ background: COLORS[r.bank] }}>
                        {r.bank}
                      </span>
                    </td>
                    <td>{r.tenure_label}</td>
                    <td className={r.general_rate === bestGeneralRate ? "best-cell" : ""}>
                      {r.general_rate != null ? `${r.general_rate}%` : "—"}
                    </td>
                    <td className={r.senior_rate === bestSeniorRate ? "best-cell" : ""}>
                      {r.senior_rate != null ? `${r.senior_rate}%` : "—"}
                    </td>
                    <td>
                      <span className={
                        generalDiff === 0 ? "diff-zero" :
                          generalDiff < 0 ? "diff-negative" : "diff-positive"
                      }>
                        {generalDiff === 0 ? "Best" :
                          generalDiff > 0 ? `+${generalDiff.toFixed(2)}%` :
                            `${generalDiff.toFixed(2)}%`}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Bar Chart */}
        <h3>Rate Comparison Chart</h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 5 }}>
            <defs>
              <linearGradient id="colorGeneral" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.8} />
                <stop offset="100%" stopColor="#2563eb" stopOpacity={0.9} />
              </linearGradient>
              <linearGradient id="colorSenior" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity={0.8} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0.9} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
            <XAxis dataKey="bank" stroke="#94a3b8" />
            <YAxis domain={[0, 10]} tickFormatter={v => `${v}%`} stroke="#94a3b8" />
            <Tooltip
              formatter={v => `${v}%`}
              contentStyle={{
                background: 'rgba(30, 41, 59, 0.95)',
                border: '1px solid rgba(255,255,255,0.2)',
                borderRadius: '0.5rem',
                color: '#f1f5f9'
              }}
            />
            <Legend />
            <Bar dataKey="General" fill="url(#colorGeneral)" radius={[8, 8, 0, 0]} />
            <Bar dataKey="Senior" fill="url(#colorSenior)" radius={[8, 8, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </>}
    </section>
  );
}

// Best Rate Finder
function BestRateView({ log }) {
  const [days, setDays] = useState(365);
  const [category, setCategory] = useState("general");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetch = async () => {
    setLoading(true); setError(null); setData(null);
    const label = TENURES.find(t => t.days === days)?.label || `${days}d`;
    log("query", `Best ${category} rate — ${label}`);
    try {
      const res = await post("/best", { days, category });
      if (res.status === "error") throw new Error(res.error);
      setData(res);
      if (res.top_banks?.[0]) log("result", `#1 ${res.top_banks[0].bank} at ${res.top_banks[0].rate}%`);
    } catch (e) { setError(e.message); log("error", e.message); }
    finally { setLoading(false); }
  };

  const getMedal = (rank) => {
    if (rank === 1) return "🥇";
    if (rank === 2) return "🥈";
    if (rank === 3) return "🥉";
    return `#${rank}`;
  };

  return (
    <section className="card">
      <h2>Best Rate Finder</h2>

      <PillSelector
        options={TENURES}
        value={days}
        onChange={setDays}
      />

      <div className="row">
        <select value={category} onChange={e => setCategory(e.target.value)}>
          <option value="general">General Citizen</option>
          <option value="senior">Senior Citizen</option>
        </select>
        <button onClick={fetch}>Find Best Rate</button>
      </div>

      {loading && <SkeletonCards />}
      {error && <ErrorMsg msg={error} />}

      {data && (
        data.top_banks.length > 0 ? (
          <div className="rank-cards">
            {data.top_banks.map(b => (
              <div key={b.bank} className={`rank-card rank-${b.rank}`}>
                <span className="rank-medal">{getMedal(b.rank)}</span>
                <div className="rank-num">Rank #{b.rank}</div>
                <div className="rank-bank" style={{ color: COLORS[b.bank] }}>{b.bank}</div>
                <div className="rank-rate">{b.rate}%</div>
                <div className="rank-label">{b.tenure_label} • p.a.</div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState
            icon="🔍"
            text="No rates found"
            hint="Try a different tenure or category"
          />
        )
      )}
    </section>
  );
}

// Tenure List (line chart — rate across all tenures for one bank)
function TenureView({ log, banks }) {
  const [bank, setBank] = useState(banks[0] || "SBI");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true); setError(null); setData(null);
    log("query", `Load all tenures — ${bank}`);
    try {
      const res = await post("/tenures", { bank_name: bank });
      if (res.status === "error") throw new Error(res.error);
      setData(res);
      log("result", `${res.tenure_count} tenure slabs loaded for ${bank}`);
    } catch (e) { setError(e.message); log("error", e.message); }
    finally { setLoading(false); }
  };

  const chartData = data?.tenures?.map(t => ({
    name: t.tenure_label.length > 18 ? t.tenure_label.slice(0, 18) + "…" : t.tenure_label,
    General: t.general_rate,
    Senior: t.senior_rate,
  })) || [];

  return (
    <section className="card">
      <h2>Bank Tenure Rates</h2>

      <div className="pill-selector">
        {banks.map(b => (
          <button
            key={b}
            className={`pill ${bank === b ? "active" : ""}`}
            onClick={() => setBank(b)}
          >
            <span style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: COLORS[b],
              marginRight: '0.5rem'
            }} />
            {b}
          </button>
        ))}
      </div>

      <button onClick={fetchData}>Load Rates</button>

      {loading && (
        <>
          <SkeletonChart />
          <SkeletonTable />
        </>
      )}
      {error && <ErrorMsg msg={error} />}

      {data && <>
        <h3>Rate vs Tenure</h3>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 70 }}>
            <defs>
              <linearGradient id="lineGeneral" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.8} />
                <stop offset="100%" stopColor="#2563eb" stopOpacity={0.4} />
              </linearGradient>
              <linearGradient id="lineSenior" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#34d399" stopOpacity={0.8} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0.4} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
            <XAxis
              dataKey="name"
              angle={-45}
              textAnchor="end"
              interval={0}
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              height={80}
            />
            <YAxis
              domain={[0, 10]}
              tickFormatter={v => `${v}%`}
              stroke="#94a3b8"
            />
            <Tooltip
              formatter={v => `${v}%`}
              contentStyle={{
                background: 'rgba(30, 41, 59, 0.95)',
                border: '1px solid rgba(255,255,255,0.2)',
                borderRadius: '0.5rem',
                color: '#f1f5f9'
              }}
            />
            <Legend />
            <Line
              type="monotone"
              dataKey="General"
              stroke="#3b82f6"
              strokeWidth={3}
              dot={{ fill: '#3b82f6', r: 5 }}
              activeDot={{ r: 7 }}
            />
            <Line
              type="monotone"
              dataKey="Senior"
              stroke="#10b981"
              strokeWidth={3}
              dot={{ fill: '#10b981', r: 5 }}
              activeDot={{ r: 7 }}
            />
          </LineChart>
        </ResponsiveContainer>

        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Tenure</th>
                <th>General Rate</th>
                <th>Senior Rate</th>
                <th>Difference</th>
              </tr>
            </thead>
            <tbody>
              {data.tenures.map((t, i) => {
                const diff = t.senior_rate - t.general_rate;
                return (
                  <tr key={i}>
                    <td>{t.tenure_label}</td>
                    <td>{t.general_rate != null ? `${t.general_rate}%` : "—"}</td>
                    <td>{t.senior_rate != null ? `${t.senior_rate}%` : "—"}</td>
                    <td>
                      <span className={diff > 0 ? "diff-positive" : "diff-zero"}>
                        {diff > 0 ? `+${diff.toFixed(2)}%` : "—"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </>}
    </section>
  );
}

// ── Chat History Panel ────────────────────────────────────────────────────────

function ChatHistory({ history, onClear }) {
  const bottomRef = useRef(null);

  // Auto-scroll to latest entry
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history]);

  return (
    <aside className="chat-panel">
      <div className="chat-header">
        <span>📋 Activity Log</span>
        {history.length > 0 && (
          <button className="clear-btn" onClick={onClear}>Clear</button>
        )}
      </div>

      <div className="chat-body">
        {history.length === 0 && (
          <p className="chat-empty">No activity yet. Use the tools above.</p>
        )}
        {history.map((entry, i) => (
          <div key={i} className={`chat-entry chat-${entry.type}`}>
            <span className="chat-time">{entry.time}</span>
            <span className="chat-icon">
              {entry.type === "query" ? "🔍" :
                entry.type === "result" ? "✅" : "❌"}
            </span>
            <span className="chat-text">{entry.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </aside>
  );
}

// ── App Shell ─────────────────────────────────────────────────────────────────

const TABS = ["Chat", "Compare", "Best Rate", "Tenures"];

// Shared history logger — passed down as a prop so every view can log to it
function useHistory() {
  const [history, setHistory] = useState([]);

  const log = (type, text) => {
    const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setHistory(h => [...h, { type, text, time }]);
  };

  const clear = () => setHistory([]);
  return { history, log, clear };
}

export default function App() {
  const [tab, setTab] = useState("Chat");
  const [banks, setBanks] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const { history, log, clear } = useHistory();

  useEffect(() => {
    fetchBanks();
  }, []);

  const fetchBanks = async () => {
    try {
      const r = await get("/banks");
      setBanks(r.banks || []);
      setLastUpdated(new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit"
      }));
    } catch (e) {
      console.error("Failed to fetch banks:", e);
    }
  };

  return (
    <div className="app">
      <header>
        <div className="header-content">
          <div className="header-left">
            <h1>🏦 FD Rate Tracker</h1>
            <p>Live Fixed Deposit rates — SBI · ICICI · Kotak</p>
          </div>
          <div className="header-right">
            {lastUpdated && (
              <div className="last-updated">
                <span>🕐</span>
                <span>Updated: {lastUpdated}</span>
              </div>
            )}
            <button className="refresh-btn" onClick={fetchBanks}>
              <span>🔄</span>
              <span>Refresh</span>
            </button>
          </div>
        </div>
      </header>

      <nav>
        {TABS.map(t => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </nav>

      <div className="layout">
        <main>
          {tab === "Chat" && <ChatView log={log} />}
          {tab === "Compare" && <CompareView log={log} />}
          {tab === "Best Rate" && <BestRateView log={log} />}
          {tab === "Tenures" && <TenureView log={log} banks={banks} />}
        </main>

        <ChatHistory history={history} onClear={clear} />
      </div>
    </div>
  );
}