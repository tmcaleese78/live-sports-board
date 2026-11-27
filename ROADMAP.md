
1. Tech Stack & Hosting

• Backend: Python / Flask (web_live.py) running on Gunicorn.
• Frontend: Single-file HTML/CSS/JS (templates/index.html) with live polling and inline editing.
• Hosting & Auto-Deploy: GitHub repository connected to Railway (every commit pushed to main automatically triggers a live deploy).
• Database & Auth: Supabase (User Sign In, Sign Up, Password Reset, cross-device bet card sync, and Admin-managed Daily Sample Cards for logged-out visitors).
• AI Vision OCR: Gemini Vision (gemini-2.5-flash) via /api/parse-slip in web_live.py using Railway environment variable GEMINI_API_KEY (with automatic fallback to local Tesseract + modular parsers).

2. Strict UI & Naming Conventions (Do Not Override)

• Dark Mode Only: All screens, modals, dropdowns, and cards must remain exclusively in dark mode (#0f172a / #1e293b backgrounds).
• Naming Labels:
	• Use DraftKings (never DraftKings Predictions—saves card header space).
	• Name the active betting view Active Cards (never Sweats).
	• List athlete James Cook as James Cook III to match live roster feeds.
• 4-Column Prop Tracking Cards: Keep the 4-column prop card grid layout (Player / Stat, Target, Live, Need / Status) that turns green when a target metric hits, with readable portrait-mode sizing.
• Spreadsheet / Team Filtering: Exclude South Alabama when querying or matching Alabama.
• Code Block Formatting: Keep code modifications modular and concise to prevent truncation.

3. Completed Features (Live in Production)

• Live ESPN Scoreboard & Box Scores (web_live.py):
	• Fast cached startup (get_live_payload) + /ping 24/7 keep-alive endpoint.
	• Live NFL, NBA, and CFB game clocks, scores, possession indicators, clickable Game Box Score modals (/api/boxscore/<lg>/<eid>), and clickable Player Game Log modals (/api/player/<lg>/<pid>).
	• Full NFL stat coverage: PASS YDS, PASS TD, RUSH YDS, RUSH ATT (CAR), RUSH TD, REC YDS, REC, REC TGTS (TGTS), REC TD, SCRIM YDS (RUSH YDS + REC YDS), and combined TD (RUSH TD + REC TD).
	• Full NBA stat coverage: PTS, REB, AST, 3PM, STL, BLK, PRA, PR, PA, RA.
• Bet Card Builder & Active Cards UX (templates/index.html):
	• Home-screen Upload Bet Slip shortcut + Builder Upload Screenshot button with dark-mode Sportsbook Picker modal (FanDuel, DraftKings, PrizePicks).
	• Inline target editing, 1-tap O / U toggle, leg reordering, shareable live links (?sweat=...), and audio hit chimes.
• Hybrid Screenshot Slip Importer (web_live.py + templates/index.html):
	• Primary parser: /api/parse-slip (gemini-2.5-flash Vision AI) extracting cost, payout, and structured legs (prop, spread, ml, total).
	• Offline/fallback parser (Section 7 in templates/index.html): Modularized into 7A (Router & Roster Helpers), 7B (parseFanDuelSlip), 7C (parseDraftKingsSlip), and 7D (parsePrizePicksSlip).

4. Immediate Next Milestones (In Priority Order)

1. Finish PrizePicks White Down-Arrow (↓) Vision Accuracy:
	• In web_live.py (/api/parse-slip), add "media_resolution": "MEDIA_RESOLUTION_HIGH" to generationConfig (or send a high-res crop of the right-hand prop number/arrow column) so small white ↓ arrows on PrizePicks (e.g., ↓ 6 Rec Targets) always return "ou": "Under" instead of defaulting to "Over".
2. Site Speed & Mobile UX Optimization:
	• Audit templates/index.html and web_live.py to streamline redundant DOM renders, optimize portrait-mode card spacing, and verify smooth performance across iOS Safari and Android Chrome.
3. Phase 4 — Freemium Limits & Stripe Pro Tier:
	• Enforce a free-tier limit (e.g., max 3 active cards for free users) stored in Supabase user profiles.
	• Add Stripe Checkout + Webhook endpoint in web_live.py to unlock unlimited active cards, unlimited Vision AI slip scans, and priority live refresh for Pro subscribers.
