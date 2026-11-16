<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OmniStatPro — Every Game. Every Stat. Every Wager.</title>
<link rel="icon" type="image/png" href="/static/favicon.png">
<link rel="apple-touch-icon" href="/static/favicon.png">
<style>
  :root {
    --bg: #04070d; --surface: #0d1526; --surface2: #131f38; --border: #1e3154;
    --text: #f1f5f9; --muted: #94a3b8; --accent: #1d8cf8; --accent-glow: rgba(29,140,248,0.35);
    --shadow: 0 10px 28px rgba(0,0,0,0.55);
    --hit-bg: rgba(22,163,74,0.18); --hit-txt: #4ade80; --hit-bdr: #16a34a;
    --miss-bg: rgba(220,38,38,0.18); --miss-txt: #f87171; --miss-bdr: #dc2626;
  }
  body.light {
    --bg: #eef2f7; --surface: #ffffff; --surface2: #f8fafc; --border: #cbd5e1;
    --text: #0f172a; --muted: #475569; --accent: #0066ff; --accent-glow: rgba(0,102,255,0.2);
    --shadow: 0 4px 16px rgba(15,23,42,0.08);
    --hit-bg: #ecfdf5; --hit-txt: #15803d; --hit-bdr: #16a34a;
    --miss-bg: #fef2f2; --miss-txt: #b91c1c; --miss-bdr: #dc2626;
  }
  * { box-sizing: border-box; }
  body { font-family: Calibri, -apple-system, BlinkMacSystemFont, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0 0 48px; }
  .hero-header { background: #000000; border-bottom: 2px solid var(--accent); box-shadow: 0 4px 24px var(--accent-glow); padding: 12px 20px; }
  body.light .hero-header { background: #ffffff; }
  .hero-inner { max-width: 1440px; margin: 0 auto; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; }
  .logo-box { flex: 1 1 560px; max-width: 780px; }
  .brand-logo { height: 98px; width: 100%; max-width: 780px; object-fit: contain; object-position: left center; display: block; }
  @media (max-width: 640px) { .brand-logo { height: 68px; } }
  .logo-light { display: none; }
  body.light .logo-dark { display: none; }
  body.light .logo-light { display: block; }
  .nav-bar { max-width: 1440px; margin: 16px auto 0; padding: 0 20px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
  .nav { display: flex; flex-wrap: wrap; gap: 8px; }
  .tab-btn, .pill { background: var(--surface); color: var(--muted); border: 1px solid var(--border); border-radius: 999px; padding: 8px 16px; font-weight: 700; font-size: 13px; cursor: pointer; transition: all .15s; }
  .tab-btn:hover, .pill:hover { border-color: var(--accent); color: var(--text); }
  .tab-btn.active, .pill.active { background: linear-gradient(135deg, #0066ff, #1d8cf8); color: #ffffff; border-color: #38bdf8; box-shadow: 0 0 14px var(--accent-glow); }
  .live-pill { display: flex; align-items: center; gap: 7px; background: var(--surface); border: 1px solid var(--border); padding: 6px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; color: var(--muted); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 8px #22c55e; animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
  .main-wrap { max-width: 1440px; margin: 0 auto; padding: 6px 20px 0; }
  h2 { color: var(--accent); font-size: 15px; letter-spacing: 1px; margin: 22px 0 10px; text-transform: uppercase; font-weight: 800; border-left: 3px solid var(--accent); padding-left: 10px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(365px, 1fr)); gap: 16px; }
  .card { background: var(--surface); border-radius: 14px; border: 2px solid var(--border); box-shadow: var(--shadow); overflow: hidden; }
  .card.hit { border-color: var(--hit-bdr); } .card.miss { border-color: var(--miss-bdr); }
  .card-banner { display: grid; grid-template-columns: 1fr 1fr 38px; background: linear-gradient(90deg, #0f172a, #1e3a8a); color: #fff; font-weight: 800; font-size: 15px; text-align: center; align-items: center; padding: 9px 0; }
  .card-banner.hit { background: #16a34a; } .card-banner.miss { background: #b91c1c; }
  .card-banner div:first-child { border-right: 1px solid rgba(255,255,255,0.25); }
  .del-btn { background: none; border: none; color: rgba(255,255,255,0.85); font-weight: 800; cursor: pointer; font-size: 15px; }
  .hdr-row, .p-main { display: grid; grid-template-columns: 46px 1.6fr 1fr 0.65fr 0.65fr; align-items: center; text-align: center; }
  .hdr-row { background: var(--surface2); color: var(--muted); font-weight: 700; font-size: 12px; text-transform: uppercase; padding: 7px 0; border-top: 1px solid var(--border); }
  .p-wrap { border-top: 1px solid var(--border); }
  .p-wrap.hit { background: var(--hit-bg); color: var(--hit-txt); } .p-wrap.miss { background: var(--miss-bg); color: var(--miss-txt); }
  .p-main { font-weight: 700; font-size: 14px; min-height: 44px; padding: 2px 4px; }
  .logo-cell { height: 100%; display: flex; align-items: center; justify-content: center; padding: 4px; }
  .logo-cell img { width: 26px; height: 26px; object-fit: contain; }
  .prog-track { height: 4px; width: 100%; background: rgba(148,163,184,0.18); }
  .prog-fill { height: 100%; transition: width 0.4s ease; }
  .sum-row { display: grid; grid-template-columns: 1.35fr 1fr; padding: 11px 16px; font-weight: 800; font-size: 16px; border-top: 1px solid var(--border); }
  .sum-row:first-child { border-top: none; background: var(--surface2); }
  .sum-row.paid { background: var(--hit-bg); color: var(--hit-txt); }

  /* Broadcast Scoreboard Cards */
  .sb-card { background: var(--surface); border-radius: 14px; border: 2px solid var(--border); box-shadow: var(--shadow); overflow: hidden; display: flex; flex-direction: column; }
  .sb-card.is-live { border-color: #22c55e; }
  .sb-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 12px; background: var(--surface2); border-bottom: 1px solid var(--border); font-size: 12px; font-weight: 800; color: var(--muted); }
  .sb-badge { display: inline-flex; align-items: center; gap: 5px; }
  .sb-live-tag { color: #4ade80; }
  .sb-team { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px; font-weight: 800; font-size: 15px; }
  .sb-team + .sb-team { border-top: 1px solid rgba(255,255,255,0.18); }
  .sb-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .sb-left img { width: 28px; height: 28px; object-fit: contain; flex-shrink: 0; }
  .sb-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .sb-rec { font-size: 12px; font-weight: 600; opacity: 0.82; margin-left: 4px; }
  .sb-poss { width: 8px; height: 8px; border-radius: 50%; background: #facc15; box-shadow: 0 0 8px #facc15; flex-shrink: 0; }
  .sb-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  .sb-score { font-size: 19px; font-weight: 900; min-width: 28px; text-align: right; }
  .pick-btn { background: rgba(0,0,0,0.32); color: #fff; border: 1px solid rgba(255,255,255,0.38); border-radius: 999px; padding: 3px 10px; font-size: 11px; font-weight: 800; cursor: pointer; transition: all .15s; }
  .pick-btn:hover { background: #1d8cf8; border-color: #fff; }
  .sb-foot { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; background: var(--surface2); border-top: 1px solid var(--border); font-size: 12px; font-weight: 700; color: var(--muted); }

  .filter-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; }
  .filter-grp { display: flex; flex-wrap: wrap; gap: 8px; }
  .search-box, select, input { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 9px 12px; font-size: 14px; font-family: inherit; }
  .tbl-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { background: var(--surface2); color: var(--muted); text-align: left; padding: 10px 12px; font-size: 12px; text-transform: uppercase; }
  td { padding: 9px 12px; border-top: 1px solid var(--border); font-weight: 600; }
  .builder { max-width: 680px; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; }
  .row-flex { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
  .btn-primary { background: linear-gradient(135deg, #0066ff, #1d8cf8); color: #ffffff; border: 1px solid #38bdf8; border-radius: 10px; padding: 10px 18px; font-weight: 800; font-size: 14px; cursor: pointer; box-shadow: 0 0 14px var(--accent-glow); }
  .leg-chip { display: flex; justify-content: space-between; align-items: center; background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; margin-bottom: 8px; font-weight: 700; font-size: 14px; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: linear-gradient(135deg, #0066ff, #1d8cf8); color: #fff; font-weight: 800; font-size: 13px; padding: 10px 16px; border-radius: 999px; box-shadow: 0 8px 24px rgba(0,0,0,0.45); display: none; z-index: 99; }
</style>
</head>
<body>
<header class="hero-header">
  <div class="hero-inner">
    <div class="logo-box">
      <img class="brand-logo logo-dark" src="/static/logo-dark.png" alt="OmniStatPro">
      <img class="brand-logo logo-light" src="/static/logo-light.png" alt="OmniStatPro">
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <div class="live-pill"><span class="dot"></span><span id="sync-time">LIVE</span></div>
      <button class="pill" id="theme-btn" onclick="toggleTheme()">Light</button>
    </div>
  </div>
</header>

<div class="nav-bar">
  <div class="nav">
    <button class="tab-btn active" data-t="scoreboard" onclick="setTab('scoreboard')">Live Scoreboard</button>
    <button class="tab-btn" data-t="stats" onclick="setTab('stats')">Live Stats</button>
