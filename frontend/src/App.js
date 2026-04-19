import React, { useState, useEffect, useCallback } from "react";

// ─── API HELPER ───
const API = "";  // Same origin in production; set to http://localhost:5000 for dev

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  return res.json();
}

// ─── PUSH NOTIFICATIONS ───
async function subscribePush() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    const reg = await navigator.serviceWorker.ready;
    const { publicKey } = await api("/api/push/vapid-key");
    if (!publicKey) return;

    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
    await api("/api/push/subscribe", {
      method: "POST",
      body: JSON.stringify(sub.toJSON()),
    });
  } catch (e) {
    console.log("Push subscription failed:", e);
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

// ─── STYLES ───
const css = `
  :root {
    --bg: #0a0a0f;
    --bg2: #12121a;
    --bg3: #1a1a26;
    --surface: #16161f;
    --surface2: #1e1e2a;
    --border: rgba(255,255,255,0.06);
    --border2: rgba(255,255,255,0.1);
    --text: #e8e8ed;
    --text2: #8b8b99;
    --text3: #5a5a6e;
    --green: #00e68a;
    --green-bg: rgba(0,230,138,0.08);
    --green-bg2: rgba(0,230,138,0.15);
    --red: #ff4d6a;
    --red-bg: rgba(255,77,106,0.08);
    --red-bg2: rgba(255,77,106,0.15);
    --blue: #4d9fff;
    --blue-bg: rgba(77,159,255,0.08);
    --amber: #ffb84d;
    --amber-bg: rgba(255,184,77,0.08);
    --font: 'DM Sans', -apple-system, sans-serif;
    --mono: 'JetBrains Mono', monospace;
    --radius: 16px;
    --radius-sm: 10px;
  }

  * { margin:0; padding:0; box-sizing:border-box; }

  html, body, #root {
    height: 100%;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
  }

  .app {
    max-width: 480px;
    margin: 0 auto;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    padding-bottom: 80px;
  }

  /* ─── HEADER ─── */
  .header {
    padding: 20px 20px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header-left { display: flex; align-items: center; gap: 10px; }
  .header-logo {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, var(--green), #00b368);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; font-weight: 700;
  }
  .header-title { font-size: 18px; font-weight: 600; letter-spacing: -0.3px; }
  .header-sub { font-size: 11px; color: var(--text3); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* ─── BANKROLL HERO ─── */
  .hero {
    padding: 24px 20px;
    text-align: center;
  }
  .hero-label { font-size: 12px; color: var(--text3); text-transform: uppercase; letter-spacing: 1px; font-weight: 600; margin-bottom: 6px; }
  .hero-amount { font-size: 42px; font-weight: 700; letter-spacing: -1.5px; font-family: var(--mono); }
  .hero-change {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 14px; font-weight: 600; margin-top: 6px;
    padding: 4px 12px; border-radius: 20px;
  }
  .hero-change.up { color: var(--green); background: var(--green-bg); }
  .hero-change.down { color: var(--red); background: var(--red-bg); }

  /* ─── MINI CHART ─── */
  .chart-wrap {
    padding: 0 20px;
    margin-bottom: 20px;
  }
  .chart-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    height: 140px;
    position: relative;
    overflow: hidden;
  }
  .chart-container svg { width: 100%; height: 100%; }

  /* ─── STATS GRID ─── */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 10px;
    padding: 0 20px;
    margin-bottom: 20px;
  }
  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
  }
  .stat-label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 4px; }
  .stat-value { font-size: 22px; font-weight: 700; font-family: var(--mono); letter-spacing: -0.5px; }
  .stat-value.green { color: var(--green); }
  .stat-value.red { color: var(--red); }
  .stat-value.blue { color: var(--blue); }

  /* ─── SECTION TITLE ─── */
  .section-head {
    padding: 20px 20px 12px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .section-title { font-size: 15px; font-weight: 600; }
  .section-count {
    font-size: 11px; color: var(--text3); background: var(--surface);
    padding: 3px 10px; border-radius: 20px;
    border: 1px solid var(--border);
  }

  /* ─── PARIS CARDS ─── */
  .paris-list { padding: 0 20px; display: flex; flex-direction: column; gap: 10px; }
  .pari-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
    transition: all 0.2s;
  }
  .pari-card:active { transform: scale(0.98); background: var(--surface2); }
  .pari-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
  .pari-sport { font-size: 11px; color: var(--text3); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .pari-badge {
    font-size: 10px; font-weight: 700; padding: 3px 10px; border-radius: 20px;
    text-transform: uppercase; letter-spacing: 0.5px;
  }
  .pari-badge.attente { color: var(--blue); background: var(--blue-bg); }
  .pari-badge.gagne { color: var(--green); background: var(--green-bg2); }
  .pari-badge.perdu { color: var(--red); background: var(--red-bg2); }
  .pari-match { font-size: 15px; font-weight: 600; margin-bottom: 4px; letter-spacing: -0.2px; }
  .pari-type { font-size: 12px; color: var(--text2); margin-bottom: 10px; }
  .pari-meta {
    display: flex; gap: 6px; flex-wrap: wrap;
  }
  .pari-tag {
    font-size: 11px; font-family: var(--mono); padding: 4px 10px;
    background: var(--bg); border-radius: 6px; color: var(--text2);
    border: 1px solid var(--border);
  }
  .pari-tag .label { color: var(--text3); margin-right: 3px; }
  .pari-tag.ev { color: var(--green); border-color: rgba(0,230,138,0.15); background: var(--green-bg); }

  /* ─── ACTIONS ─── */
  .actions {
    padding: 0 20px 20px;
    display: flex; gap: 8px; flex-wrap: wrap;
  }
  .action-btn {
    flex: 1; min-width: 90px;
    background: var(--surface);
    border: 1px solid var(--border2);
    color: var(--text);
    font-family: var(--font);
    font-size: 12px; font-weight: 600;
    padding: 12px 8px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: all 0.15s;
    display: flex; flex-direction: column; align-items: center; gap: 6px;
  }
  .action-btn:active { transform: scale(0.95); background: var(--surface2); }
  .action-btn .icon { font-size: 20px; }
  .action-btn.loading { opacity: 0.5; pointer-events: none; }

  /* ─── NOTIF TOGGLE ─── */
  .notif-bar {
    margin: 0 20px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 14px 16px;
    display: flex; align-items: center; justify-content: space-between;
    cursor: pointer;
  }
  .notif-bar:active { background: var(--surface2); }
  .notif-left { display: flex; align-items: center; gap: 10px; }
  .notif-text { font-size: 13px; font-weight: 500; }
  .notif-sub { font-size: 11px; color: var(--text3); }
  .notif-toggle {
    width: 44px; height: 26px; border-radius: 13px;
    background: var(--bg3); position: relative; transition: 0.2s;
    border: 1px solid var(--border2);
  }
  .notif-toggle.on { background: var(--green); border-color: var(--green); }
  .notif-toggle::after {
    content: ''; position: absolute;
    width: 20px; height: 20px; border-radius: 50%;
    background: white; top: 2px; left: 2px;
    transition: 0.2s;
  }
  .notif-toggle.on::after { left: 20px; }

  /* ─── ACTIVITY LOG ─── */
  .log-list { padding: 0 20px 20px; display: flex; flex-direction: column; gap: 6px; }
  .log-item {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 8px 0;
    border-bottom: 1px solid var(--border);
    font-size: 12px;
  }
  .log-time { color: var(--text3); font-family: var(--mono); min-width: 45px; font-size: 11px; }
  .log-msg { color: var(--text2); flex: 1; }
  .log-type {
    font-size: 9px; font-weight: 700; text-transform: uppercase;
    padding: 2px 6px; border-radius: 4px; letter-spacing: 0.5px;
  }
  .log-type.collecte { color: var(--blue); background: var(--blue-bg); }
  .log-type.analyse { color: var(--amber); background: var(--amber-bg); }
  .log-type.maj { color: var(--green); background: var(--green-bg); }
  .log-type.erreur { color: var(--red); background: var(--red-bg); }
  .log-type.system { color: var(--text3); background: var(--bg3); }

  /* ─── BOTTOM NAV ─── */
  .bottom-nav {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: var(--bg2);
    border-top: 1px solid var(--border);
    display: flex; justify-content: center;
    padding: 8px 0 calc(8px + env(safe-area-inset-bottom));
    backdrop-filter: blur(20px);
    z-index: 100;
  }
  .bottom-nav-inner {
    max-width: 480px; width: 100%;
    display: flex; justify-content: space-around;
  }
  .nav-item {
    display: flex; flex-direction: column; align-items: center; gap: 3px;
    font-size: 10px; color: var(--text3); font-weight: 600;
    cursor: pointer; padding: 6px 16px;
    border-radius: 10px; transition: 0.15s;
    border: none; background: none;
    text-transform: uppercase; letter-spacing: 0.3px;
  }
  .nav-item.active { color: var(--green); }
  .nav-item .nav-icon { font-size: 22px; }

  /* ─── LOADING ─── */
  .loading-screen {
    display: flex; align-items: center; justify-content: center;
    height: 100vh; flex-direction: column; gap: 16px;
  }
  .spinner {
    width: 32px; height: 32px; border-radius: 50%;
    border: 3px solid var(--border);
    border-top-color: var(--green);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading-text { font-size: 13px; color: var(--text3); }

  /* ─── EMPTY STATE ─── */
  .empty {
    text-align: center; padding: 40px 20px;
    color: var(--text3); font-size: 13px;
  }
  .empty .icon { font-size: 36px; margin-bottom: 12px; opacity: 0.5; }

  /* ─── PULL REFRESH ─── */
  .pull-indicator {
    text-align: center; padding: 12px; font-size: 12px; color: var(--text3);
    transition: 0.2s;
  }

  @media (min-width: 481px) {
    .app { border-left: 1px solid var(--border); border-right: 1px solid var(--border); }
  }
`;

// ─── MINI SPARKLINE ───
function Sparkline({ data, color = "#00e68a" }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 100;
  const h = 100;
  const pad = 5;

  const points = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / range) * (h - 2 * pad);
    return `${x},${y}`;
  });

  const line = points.join(" ");
  const area = `${pad},${h - pad} ${line} ${w - pad},${h - pad}`;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#sparkGrad)" />
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// ─── TAB: DASHBOARD ───
function TabDashboard({ data, loading, onRefresh }) {
  if (loading) return <LoadingScreen />;
  if (!data) return <div className="empty"><div className="icon">📊</div>Chargement...</div>;

  const isUp = data.net >= 0;
  return (
    <>
      <div className="hero">
        <div className="hero-label">Bankroll virtuelle</div>
        <div className="hero-amount">{data.bankroll.toLocaleString("fr-FR")}€</div>
        <div className={`hero-change ${isUp ? "up" : "down"}`}>
          {isUp ? "▲" : "▼"} {isUp ? "+" : ""}{data.net}€ ({isUp ? "+" : ""}{data.roi}%)
        </div>
      </div>

      <div className="chart-wrap">
        <div className="chart-container">
          <Sparkline
            data={data.historique}
            color={isUp ? "#00e68a" : "#ff4d6a"}
          />
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Taux réussite</div>
          <div className={`stat-value ${data.taux_vic >= 50 ? "green" : "red"}`}>
            {data.taux_vic}%
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total paris</div>
          <div className="stat-value">{data.total}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Gagnés</div>
          <div className="stat-value green">{data.gagnes}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Perdus</div>
          <div className="stat-value red">{data.perdus}</div>
        </div>
      </div>

      {data.en_attente > 0 && (
        <div className="stats-grid" style={{ gridTemplateColumns: "1fr" }}>
          <div className="stat-card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <div className="stat-label">En attente</div>
              <div className="stat-value blue">{data.en_attente}</div>
            </div>
            <div style={{ fontSize: 32, opacity: 0.3 }}>⏳</div>
          </div>
        </div>
      )}
    </>
  );
}

// ─── TAB: PARIS ───
function TabParis({ data }) {
  if (!data || !data.paris) return <div className="empty"><div className="icon">🎯</div>Aucun pari détecté</div>;

  const paris = data.paris;
  if (paris.length === 0) return <div className="empty"><div className="icon">🎯</div>Aucun pari enregistré</div>;

  return (
    <>
      <div className="section-head">
        <div className="section-title">Tous les paris</div>
        <div className="section-count">{paris.length}</div>
      </div>
      <div className="paris-list">
        {paris.map((p, i) => {
          const res = p.resultat;
          const badgeCls = res === "GAGNÉ" ? "gagne" : res === "PERDU" ? "perdu" : "attente";
          const icon = p.sport === "Football" ? "⚽" : "🎾";
          return (
            <div className="pari-card" key={p.id || i}>
              <div className="pari-top">
                <span className="pari-sport">{icon} {p.ligue}</span>
                <span className={`pari-badge ${badgeCls}`}>{res}</span>
              </div>
              <div className="pari-match">{p.match_nom || p.match}</div>
              <div className="pari-type">{p.type_pari} — {p.date_match || p.date}</div>
              <div className="pari-meta">
                <span className="pari-tag"><span className="label">Cote</span>{p.cote}</span>
                <span className="pari-tag ev"><span className="label">EV</span>{p.valeur_ev}</span>
                <span className="pari-tag"><span className="label">Mise</span>{p.mise}€</span>
                <span className="pari-tag"><span className="label">Gain</span>{p.gain_potentiel}€</span>
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ─── TAB: ACTIONS ───
function TabActions({ onAction, actionLoading, notifEnabled, onToggleNotif, activity }) {
  return (
    <>
      <div className="section-head">
        <div className="section-title">Actions manuelles</div>
      </div>
      <div className="actions">
        <button
          className={`action-btn ${actionLoading === "collecte" ? "loading" : ""}`}
          onClick={() => onAction("collecte")}
        >
          <span className="icon">📡</span>
          Collecte
        </button>
        <button
          className={`action-btn ${actionLoading === "analyse" ? "loading" : ""}`}
          onClick={() => onAction("analyse")}
        >
          <span className="icon">🧠</span>
          Analyse
        </button>
        <button
          className={`action-btn ${actionLoading === "maj" ? "loading" : ""}`}
          onClick={() => onAction("maj")}
        >
          <span className="icon">🔄</span>
          MAJ Résultats
        </button>
      </div>

      <div className="notif-bar" onClick={onToggleNotif}>
        <div className="notif-left">
          <span style={{ fontSize: 20 }}>🔔</span>
          <div>
            <div className="notif-text">Notifications push</div>
            <div className="notif-sub">Alerte quand un pari est détecté</div>
          </div>
        </div>
        <div className={`notif-toggle ${notifEnabled ? "on" : ""}`} />
      </div>

      <div className="section-head">
        <div className="section-title">Activité récente</div>
      </div>
      <div className="log-list">
        {activity.length === 0 && (
          <div className="empty"><div className="icon">📋</div>Aucune activité</div>
        )}
        {activity.slice(0, 20).map((log, i) => (
          <div className="log-item" key={i}>
            <span className="log-time">{log.timestamp?.slice(11, 16)}</span>
            <span className={`log-type ${log.type}`}>{log.type}</span>
            <span className="log-msg">{log.message}</span>
          </div>
        ))}
      </div>
    </>
  );
}

// ─── LOADING ───
function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="spinner" />
      <div className="loading-text">Chargement des données...</div>
    </div>
  );
}

// ─── MAIN APP ───
export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [data, setData] = useState(null);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  const [notifEnabled, setNotifEnabled] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [dash, act] = await Promise.all([
        api("/api/dashboard"),
        api("/api/activity"),
      ]);
      setData(dash);
      setActivity(act);
    } catch (e) {
      console.error("Fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    // Check if push already subscribed
    if ("serviceWorker" in navigator && "PushManager" in window) {
      navigator.serviceWorker.ready.then((reg) => {
        reg.pushManager.getSubscription().then((sub) => {
          if (sub) setNotifEnabled(true);
        });
      });
    }
  }, []);

  const handleAction = async (type) => {
    setActionLoading(type);
    try {
      const endpoint = type === "collecte"
        ? "/api/forcer-collecte"
        : type === "analyse"
        ? "/api/forcer-analyse"
        : "/api/forcer-maj";
      await api(endpoint, { method: "POST" });
      await fetchData();
    } catch (e) {
      console.error(e);
    } finally {
      setActionLoading(null);
    }
  };

  const handleToggleNotif = async () => {
    if (!notifEnabled) {
      const perm = await Notification.requestPermission();
      if (perm === "granted") {
        await subscribePush();
        setNotifEnabled(true);
      }
    } else {
      setNotifEnabled(false);
    }
  };

  return (
    <>
      <style>{css}</style>
      <div className="app">
        <div className="header">
          <div className="header-left">
            <div className="header-logo">⚡</div>
            <div>
              <div className="header-title">Paris IA</div>
              <div className="header-sub">Paper Trading</div>
            </div>
          </div>
          <div className="status-dot" title="Système actif" />
        </div>

        {tab === "dashboard" && <TabDashboard data={data} loading={loading} onRefresh={fetchData} />}
        {tab === "paris" && <TabParis data={data} />}
        {tab === "actions" && (
          <TabActions
            onAction={handleAction}
            actionLoading={actionLoading}
            notifEnabled={notifEnabled}
            onToggleNotif={handleToggleNotif}
            activity={activity}
          />
        )}

        <div className="bottom-nav">
          <div className="bottom-nav-inner">
            <button className={`nav-item ${tab === "dashboard" ? "active" : ""}`} onClick={() => setTab("dashboard")}>
              <span className="nav-icon">📊</span>
              Dashboard
            </button>
            <button className={`nav-item ${tab === "paris" ? "active" : ""}`} onClick={() => setTab("paris")}>
              <span className="nav-icon">🎯</span>
              Paris
            </button>
            <button className={`nav-item ${tab === "actions" ? "active" : ""}`} onClick={() => setTab("actions")}>
              <span className="nav-icon">⚙️</span>
              Actions
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
