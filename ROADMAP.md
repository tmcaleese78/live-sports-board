
1. Tech Stack & Hosting

• Backend: Python / Flask (web_live.py) running on Gunicorn.
• Frontend: Single-file HTML/CSS/JS (templates/index.html) with live polling and inline editing.
• Hosting & Auto-Deploy: GitHub repository connected to Railway (every commit pushed to main automatically triggers a live deploy).
• Database & Auth: Supabase (User Sign In, Sign Up, Password Reset, cross-device bet card sync, and Admin-managed Daily Sample Cards for logged-out visitors).
• AI Vision OCR: Gemini Vision (gemini-3.5-flash-lite primary with automatic failover to gemini-3.6-flash / gemini-3.8-flash and model cooldown cache) via /api/parse-slip in web_live.py using Railway environment variable GEMINI_API_KEY (with automatic fallback to local Tesseract + modular parsers).

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
	• Full NFL stat coverage: PASS YDS, PASS TD, PASS ATT, COMP (Pass Comp), RUSH YDS, RUSH ATT (CAR), RUSH TD, REC YDS, REC, REC TGTS (Rec Targets), REC TD, SCRIM YDS (RUSH YDS + REC YDS), and combined TD (Anytime TD).
	• Full NBA stat coverage: PTS, REB, AST, 3PM, STL, BLK, PRA, PR, PA, RA.
	• Full 32-team NFL & 30-team NBA cached roster coverage (including bye-week/off-slate teams) + gzip response compression, 7-day static asset caching, and persistent ESPN HTTP session.
• Bet Card Builder, Active Cards & Settled History UX (templates/index.html):
	• Home-screen Upload Bet Slip shortcut + Builder Upload Screenshot button with dark-mode Sportsbook Picker modal (FanDuel, DraftKings, PrizePicks, Underdog, Kalshi).
	• Inline target editing, 1-tap O / U toggle, leg reordering, shareable live links (?sweat=...), audio hit chimes, and full stat parity across Builder & Live Stats.
	• Permanent Settled History: finished cards lock in final status + frozen leg snapshots across NFL week resets, grouped by date (newest first) with today's cards expanded by default and older days collapsed into pick dropdowns.
	• Live Command Center Differentiators:
		• Cross-Book Rooting Guide: aggregates all active slips by Game (sorted by dollars riding on each game) and by Player/Pick (showing every target across FanDuel, DraftKings, PrizePicks, Underdog, and Kalshi on one card).
		• Live Pace Projections & "1 Leg Away" Sweat Alerts: projects final stats from live ESPN game clocks (Pace badges) and highlights multi-leg cards that are 1 leg away from cashing.
		• Personal Performance Analytics: cumulative P&L SVG curve, ROI by platform, individual leg hit rates by stat type, Over/Under splits, and slip-size breakdowns.
		• Installable PWA: manifest.json + network-first service worker (sw.js) + 1-tap Install App prompt for native iOS/Android home-screen launch.
	• Mobile Portrait UX & Performance: 4-column single-row mobile nav bar (Cards, + Build, Scores, Stats), 57 KB Retina logo, O(1) player index, visibility-aware smart polling, and compact mobile Live Stats cards with category pills & Sort By dropdown (showing only players with accrued stats in the active column).
• Hybrid Screenshot Slip Importer (web_live.py + templates/index.html):
	• Primary parser: /api/parse-slip (gemini-3.5-flash-lite Vision AI with compact JPEG uploads, book-specific prompts, and model failover) extracting cost, payout, and structured legs (prop, spread, ml, total).
	• Deterministic PrizePicks pixel-geometry arrow detector (detectPrizePicksArrows) classifying white/colored ↑ (Over) and ↓ (Under) arrows with 100% precision.
	• Supported California platforms (Verified Live): FanDuel, DraftKings, PrizePicks, Underdog, and Kalshi.
	• Offline/fallback parser (Section 7 in templates/index.html): Modularized into 7A (Router & Roster Helpers), 7B (parseFanDuelSlip), 7C (parseDraftKingsSlip), 7D (parsePrizePicksSlip), 7E (parseUnderdogSlip), and 7F (parseKalshiSlip).

4. Immediate Next Milestones (In Priority Order)

1. Post-Dec 13 — North Carolina Online Sportsbooks Expansion:
	• Once in North Carolina (after Dec 13), add slip upload support, badges, Vision AI rules, and fallback parsers for legal NC online sportsbooks (e.g., BetMGM, Caesars, ESPN BET, bet365, Fanatics Sportsbook).
2. Phase 4 — Freemium Limits, Stripe Pro Tier & Legal Monetization Checklist:
	• Product & Billing:
		• Enforce free-tier limits (e.g., max 3 active cards + monthly scan cap) in Supabase user profiles.
		• Add Stripe Checkout, Billing Customer Portal (easy online cancel), and Webhook endpoint in web_live.py to unlock unlimited active cards, unlimited Vision AI scans, and priority live refresh.
	• Business & Payments Setup:
		• Form LLC (in North Carolina after establishing residency to avoid CA's $800/yr franchise tax), obtain free IRS EIN, and open a dedicated business bank account.
		• Onboard Stripe under the LLC as "sports statistics & personal bet-tracking SaaS (no wagering, no holding of user funds)" and configure Stripe Tax / bookkeeping.
	• Licensed Data & IP Compliance:
		• Replace undocumented ESPN endpoints in web_live.py with a commercial-licensed live sports stats API (e.g., BallDontLie, API-Sports, MySportsFeeds, or SportsDataIO).
		• Replace ESPN-hotlinked trademarked league/team logos & headshots with custom team-colored monogram badges (unless official media rights are licensed).
		• Ensure GEMINI_API_KEY is on a paid Google AI billing tier for commercial SaaS terms & data privacy.
	• Legal Policies, Disclaimers & Security:
		• Publish Terms of Service (informational/entertainment only, no liability for stat delays/wagers, renewal/refund terms) and Privacy Policy (Supabase, Gemini Vision OCR image handling, Stripe, data deletion / CCPA).
		• Add non-affiliation disclaimer (NFL/NBA/NCAA & sportsbooks), 18+/21+ signup age confirmation, and Responsible Gaming footer notice (1-800-GAMBLER); stay strictly tracking-only (no affiliate links without state vendor registration).
		• Lock down Supabase RLS so only the server-side Stripe webhook (service-role key) can modify is_pro, and add server-side rate limiting on /api/parse-slip.
