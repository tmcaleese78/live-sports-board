import os
import re
import gzip
import json
import time
import hashlib
import smtplib
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse
from email.message import EmailMessage
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 604800
_ESPN_SESSION = requests.Session()
_ESPN_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})
HOST = "site." + "api." + "espn." + "com"
_CACHE = {"ts": 0.0, "data": None}
_ROSTER_CACHE = {}
_TEAMS_CACHE = {}
_PLAYER_CACHE = {}
_SEASON_CACHE = {}
_PROJ_CACHE = {}
WEB_HOST = "site.web." + "api." + "espn." + "com"
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://decjgnolcxnndpicztun.supabase.co").strip().rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_3c6v1nK9dALLIork-YqBWg_hK7Vi_jh").strip()

_ANALYTICS_LOCK = threading.Lock()
_ANALYTICS = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "days": {},
    "referrers": {},
    "devices": {"mobile": 0, "desktop": 0},
    "scans_total": 0,
    "scans_vision_ok": 0,
    "scans_by_book": {},
    "recent_feedback": []
}


def _today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _record_page_visit():
    ua = str(request.headers.get("User-Agent") or "")
    if re.search(r"bot|crawler|spider|uptimerobot|pingdom|curl|python-requests|health", ua, re.I):
        return
    day = _today_utc()
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",")[0].strip()
    vid = hashlib.sha256(f"{day}|{ip}|{ua}".encode("utf-8", "ignore")).hexdigest()[:12]
    is_mobile = bool(re.search(r"mobile|iphone|ipad|android", ua, re.I))
    ref_raw = str(request.headers.get("Referer") or "").strip()
    ref_host = "Direct"
    if ref_raw:
        try:
            h = (urlparse(ref_raw).hostname or "").lower().lstrip("www.")
            if h and "omnistatpro" not in h:
                ref_host = h
        except Exception:
            pass
    with _ANALYTICS_LOCK:
        d = _ANALYTICS["days"].setdefault(day, {"views": 0, "visitors": set()})
        d["views"] += 1
        d["visitors"].add(vid)
        if len(_ANALYTICS["days"]) > 35:
            for old_k in sorted(_ANALYTICS["days"].keys())[:-35]:
                _ANALYTICS["days"].pop(old_k, None)
        _ANALYTICS["devices"]["mobile" if is_mobile else "desktop"] += 1
        _ANALYTICS["referrers"][ref_host] = _ANALYTICS["referrers"].get(ref_host, 0) + 1


def _record_slip_scan(book, vision_ok):
    bk = str(book or "Other").strip() or "Other"
    with _ANALYTICS_LOCK:
        _ANALYTICS["scans_total"] += 1
        if vision_ok:
            _ANALYTICS["scans_vision_ok"] += 1
        _ANALYTICS["scans_by_book"][bk] = _ANALYTICS["scans_by_book"].get(bk, 0) + 1

def _to_num(val):
    first_part = next(iter(str(val).split("/")), "")
    s = first_part.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0

def _walk_pa(node, pa_by_tm, gp_by_tm):
    if not isinstance(node, dict):
        return
    for entry in node.get("standings", {}).get("entries", []):
        tm = entry.get("team", {})
        ab = tm.get("abbreviation", "")
        st_map = {s.get("name"): s.get("value", 0) for s in entry.get("stats", [])}
        gp = float(st_map.get("gamesPlayed") or (float(st_map.get("wins", 0)) + float(st_map.get("losses", 0))) or 1)
        pa = float(st_map.get("pointsAgainst") or 0)
        if ab:
            gp_by_tm[ab] = max(gp, 1.0)
            if pa > 0:
                pa_by_tm[ab] = pa / max(gp, 1.0)
    for ch in node.get("children", []):
        _walk_pa(ch, pa_by_tm, gp_by_tm)

def _load_team_candidates(args):
    sp, lg_u, t_info = args
    ros = get_roster(sp, t_info["id"])
    picks = []
    if lg_u == "NFL":
        for want_pos, limit in (("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1)):
            cnt = 0
            for r in ros:
                if r.get("pos") == want_pos and r.get("id"):
                    picks.append({**r, "team": t_info["abbr"], "bg": t_info["bg"], "logo": t_info["logo"]})
                    cnt += 1
                    if cnt >= limit:
                        break
    else:
        for r in ros[:6]:
            if r.get("id"):
                picks.append({**r, "team": t_info["abbr"], "bg": t_info["bg"], "logo": t_info["logo"]})
    return picks
def _fetch_espn_proj(args):
    p, sp, lg_u, opp_abbr_map, opp_map, pa_by_tm, gp_by_tm, avg_pa = args
    pid = p.get("id", "")
    tm = p.get("team", "")
    pos = p.get("pos", "")
    opp_ab = opp_abbr_map.get(tm, "")
    def_mult = 1.0
    if opp_ab and opp_ab in pa_by_tm and avg_pa > 0:
        raw_m = pa_by_tm[opp_ab] / avg_pa
        def_mult = max(0.88, min(1.14, 1.0 + (raw_m - 1.0) * 0.6))

    ov = fetch_json(f"https://{WEB_HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/overview", 5)
    if not ov:
        return None
    gl = ov.get("gamelog", {})
    base_labels = [str(x).upper() for x in (gl.get("labels") or gl.get("names") or [])]

    if lg_u == "NBA":
        game_rows = []
        for st_type in gl.get("seasonTypes", []):
            for cat in st_type.get("categories", []):
                lbls = [str(x).upper() for x in (cat.get("labels") or cat.get("names") or base_labels)]
                for ev in cat.get("events", []):
                    if ev.get("stats"):
                        game_rows.append((lbls, ev["stats"]))
        recent = game_rows[:6]
        if recent:
            def nba_avg(col):
                nums = [_to_num(r[lbls.index(col)]) for lbls, r in recent if col in lbls and lbls.index(col) < len(r)]
                return (sum(nums) / len(nums)) if nums else 0.0
        else:
            st_blk = ov.get("statistics", {})
            s_lbls = [str(x).upper() for x in (st_blk.get("labels") or st_blk.get("names") or [])]
            splits = st_blk.get("splits", [])
            first_sp = next(iter(splits), {}) if isinstance(splits, list) else {}
            s_vals = first_sp.get("stats", []) if isinstance(first_sp, dict) else []
            def nba_avg(col):
                return _to_num(s_vals[s_lbls.index(col)]) if (col in s_lbls and s_lbls.index(col) < len(s_vals)) else 0.0
        pts = round(nba_avg("PTS") * def_mult, 1)
        reb = round(nba_avg("REB") * def_mult, 1)
        ast = round(nba_avg("AST") * def_mult, 1)
        tpm = round(nba_avg("3PM") * def_mult, 1)
        stl = round(nba_avg("STL") * def_mult, 1)
        blk = round(nba_avg("BLK") * def_mult, 1)
        if (pts + reb + ast) <= 0:
            return None
        stats = {"PTS": pts, "REB": reb, "AST": ast, "3PM": tpm, "STL": stl, "BLK": blk, "PRA": round(pts + reb + ast, 1)}
    else:
        pass_rows, rush_rows, rec_rows = [], [], []
        for st_type in gl.get("seasonTypes", []):
            for cat in st_type.get("categories", []):
                lbls = [str(x).upper() for x in (cat.get("labels") or cat.get("names") or base_labels)]
                cname = str(cat.get("name", "")).lower()
                evs = [ev["stats"] for ev in cat.get("events", []) if ev.get("stats")][:6]
                if not evs or not lbls:
                    continue
                if "pass" in cname or ("CMP" in lbls and "ATT" in lbls):
                    pass_rows.extend((lbls, r) for r in evs)
                elif "rush" in cname or ("CAR" in lbls and "REC" not in lbls):
                    rush_rows.extend((lbls, r) for r in evs)
                elif "receiv" in cname or "REC" in lbls:
                    rec_rows.extend((lbls, r) for r in evs)

        def grp_avg(rows_grp, col_names):
            for cn in col_names:
                nums = [_to_num(r[lbls.index(cn)]) for lbls, r in rows_grp if cn in lbls and lbls.index(cn) < len(r)]
                if nums:
                    return sum(nums) / len(nums)
            return 0.0

        py = round(grp_avg(pass_rows, ["YDS"]) * def_mult, 1) if pos == "QB" else 0.0
        ptd = round(grp_avg(pass_rows, ["TD"]) * def_mult, 1) if pos == "QB" else 0.0
        ry = round(grp_avg(rush_rows, ["RUSH YDS", "YDS"]) * def_mult, 1) if pos in ("QB", "RB") else 0.0
        rtd = round(grp_avg(rush_rows, ["RUSH TD", "TD"]) * def_mult, 1) if pos in ("QB", "RB") else 0.0
        rec = round(grp_avg(rec_rows, ["REC"]) * def_mult, 1) if pos in ("RB", "WR", "TE") else 0.0
        recy = round(grp_avg(rec_rows, ["REC YDS", "YDS"]) * def_mult, 1) if pos in ("RB", "WR", "TE") else 0.0
        rectd = round(grp_avg(rec_rows, ["REC TD", "TD"]) * def_mult, 1) if pos in ("RB", "WR", "TE") else 0.0

        if (py + ry + recy + rec) <= 0:
            st_blk = ov.get("statistics", {})
            s_lbls = [str(x).upper() for x in (st_blk.get("labels") or st_blk.get("names") or [])]
            splits = st_blk.get("splits", [])
            first_sp = next(iter(splits), {}) if isinstance(splits, list) else {}
            s_vals = first_sp.get("stats", []) if isinstance(first_sp, dict) else []
            tm_gp = gp_by_tm.get(tm, 10.0)
            if "GP" in s_lbls and s_lbls.index("GP") < len(s_vals):
                gp_cand = _to_num(s_vals[s_lbls.index("GP")])
                if gp_cand > 0:
                    tm_gp = gp_cand
            def season_pg(col_names):
                for cn in col_names:
                    if cn in s_lbls and s_lbls.index(cn) < len(s_vals):
                        return _to_num(s_vals[s_lbls.index(cn)]) / tm_gp
                return 0.0
            if pos == "QB":
                py = round(season_pg(["YDS"]) * def_mult, 1)
                ptd = round(season_pg(["TD"]) * def_mult, 1)
            elif pos == "RB":
                ry = round(season_pg(["YDS"]) * def_mult, 1)
                rtd = round(season_pg(["TD"]) * def_mult, 1)
            else:
                rec = round(season_pg(["REC"]) * def_mult, 1)
                recy = round(season_pg(["YDS"]) * def_mult, 1)
                rectd = round(season_pg(["TD"]) * def_mult, 1)

        if (py + ry + recy + rec) <= 0:
            return None
        stats = {
            "PASS YDS": py, "PASS TD": ptd, "RUSH YDS": ry, "RUSH TD": rtd,
            "REC": rec, "REC YDS": recy, "REC TD": rectd, "SCRIM YDS": round(ry + recy, 1)
        }

    return {
        "id": pid,
        "name": p.get("name", ""),
        "team": tm,
        "pos": pos,
        "opp": opp_map.get(tm, "Next Game"),
        "bg": p.get("bg", "#1e293b"),
        "logo": p.get("logo", ""),
        "stats": stats
    }
@app.route("/api/projections/<lg>")
def api_projections(lg):
    lg_u = lg.upper()
    if lg_u not in ("NFL", "NBA"):
        return jsonify({"error": "Invalid league"}), 400
    try:
        ck = f"proj_v7:{lg_u}"
        now = time.time()
        if ck in _PROJ_CACHE and (now - _PROJ_CACHE[ck]["ts"]) < 900:
            return jsonify(_PROJ_CACHE[ck]["data"])

        sp = "football/nfl" if lg_u == "NFL" else "basketball/nba"
        payload = get_live_payload(fast=False)
        games = payload.get("games", {}).get(lg_u, [])

        opp_map = {}
        opp_abbr_map = {}
        for g in games:
            aw, hm = g.get("away", ""), g.get("home", "")
            st = g.get("status", "")
            if aw and hm:
                opp_map[aw] = f"@ {hm} ({st})"
                opp_map[hm] = f"vs {aw} ({st})"
                opp_abbr_map[aw] = hm
                opp_abbr_map[hm] = aw

        tms_json = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sp}/teams?limit=40", 6)
        team_objs = []
        for s_item in tms_json.get("sports", []):
            for l_item in s_item.get("leagues", []):
                for t_wrap in l_item.get("teams", []):
                    t = t_wrap.get("team", {})
                    if t.get("id") and t.get("abbreviation"):
                        team_objs.append({
                            "id": str(t["id"]),
                            "abbr": t["abbreviation"],
                            "bg": clean_hex(t.get("color"), "#1e293b"),
                            "logo": next((x.get("href", "") for x in t.get("logos", [])), "")
                        })

        st_data = fetch_json(f"https://{HOST}/apis/v2/sports/{sp}/standings", 6)
        pa_by_tm = {}
        gp_by_tm = {}
        _walk_pa(st_data, pa_by_tm, gp_by_tm)
        avg_pa = (sum(pa_by_tm.values()) / len(pa_by_tm)) if pa_by_tm else 1.0

        with ThreadPoolExecutor(max_workers=16) as pool:
            nested = list(pool.map(_load_team_candidates, [(sp, lg_u, t) for t in team_objs]))
        candidates = [item for sub in nested for item in sub]

        task_args = [(p, sp, lg_u, opp_abbr_map, opp_map, pa_by_tm, gp_by_tm, avg_pa) for p in candidates]
        with ThreadPoolExecutor(max_workers=24) as pool:
            out = [r for r in pool.map(_fetch_espn_proj, task_args) if r is not None]

        res_obj = {"league": lg_u, "players": out}
        _PROJ_CACHE[ck] = {"ts": now, "data": res_obj}
        return jsonify(res_obj)
    except Exception as exc:
        return jsonify({"league": lg_u, "players": [], "err": str(exc)}), 200

def get_roster(sport_path, tid):
    key = f"{sport_path}:{tid}"
    if key in _ROSTER_CACHE:
        return _ROSTER_CACHE[key]
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/teams/{tid}/roster", timeout=5)
    out = list()
    for grp in data.get("athletes", list()):
        if isinstance(grp, dict) and "items" in grp:
            items = grp.get("items", list())
        else:
            items = [grp]
        for a in items:
            if isinstance(a, dict) and a.get("displayName"):
                out.append({
                    "id": str(a.get("id", "")),
                    "name": a["displayName"],
                    "pos": a.get("position", {}).get("abbreviation", "")
                })
    if out:
        _ROSTER_CACHE[key] = out
    return out
    
@app.before_request
def upgrade_to_https():
    if request.headers.get("X-Forwarded-Proto") == "http":
        return redirect(f"https://{request.host}{request.full_path.rstrip('?')}", code=301)

@app.after_request
def optimize_response(resp):
    if request.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=604800, immutable")
        return resp
    if (
        resp.status_code == 200
        and not resp.direct_passthrough
        and "gzip" in request.headers.get("Accept-Encoding", "").lower()
        and "Content-Encoding" not in resp.headers
        and any(ct in (resp.content_type or "") for ct in ("application/json", "text/html", "text/css", "javascript"))
    ):
        raw = resp.get_data()
        if len(raw) >= 1024:
            resp.set_data(gzip.compress(raw, compresslevel=5))
            resp.headers["Content-Encoding"] = "gzip"
            resp.headers["Content-Length"] = str(len(resp.get_data()))
            vary = resp.headers.get("Vary", "")
            if "Accept-Encoding" not in vary:
                resp.headers["Vary"] = (f"{vary}, Accept-Encoding" if vary else "Accept-Encoding")
    return resp

def fetch_json(url, timeout=6):
    try:
        return _ESPN_SESSION.get(url, timeout=timeout).json()
    except Exception:
        return {}

def clean_hex(val, fallback):
    s = str(val or "").strip().lstrip("#")
    return f"#{s}" if len(s) == 6 else fallback

def parse_scoreboard(sport_path, lg_code, fast=False):
    sb = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard", timeout=6)
    events = list(sb.get("events", list()))
    if lg_code == "nfl" and events and all(
        ev.get("status", {}).get("type", {}).get("state") == "post" for ev in events
    ):
        wk = sb.get("week", {}).get("number")
        st_type = sb.get("season", {}).get("type")
        if wk and st_type:
            nxt = fetch_json(
                f"https://{HOST}/apis/site/v2/sports/{sport_path}/scoreboard?week={int(wk) + 1}&seasontype={st_type}",
                timeout=6,
            )
            events.extend(nxt.get("events", list()))
    games, players = list(), list()
    seen_p = set()
    box_tasks, roster_tasks = list(), list()
    for ev in events:
        eid = ev.get("id", "")
        comp = next(iter(ev.get("competitions", list())), {})
        comps = comp.get("competitors", list())
        if len(comps) < 2:
            continue
        first_c = next(iter(comps), {})
        last_c = next(reversed(comps), {})
        home = next((c for c in comps if c.get("homeAway") == "home"), first_c)
        away = next((c for c in comps if c.get("homeAway") != "home"), last_c)
        st_obj = ev.get("status", {}).get("type", {})
        state = st_obj.get("state", "pre")
        status = "Final" if state == "post" else st_obj.get("shortDetail", "Scheduled")
        a_tm, h_tm = away.get("team", {}), home.get("team", {})
        a_name = a_tm.get("abbreviation") or a_tm.get("shortDisplayName", "") if lg_code != "cfb" else a_tm.get("shortDisplayName", a_tm.get("displayName", ""))
        h_name = h_tm.get("abbreviation") or h_tm.get("shortDisplayName", "") if lg_code != "cfb" else h_tm.get("shortDisplayName", h_tm.get("displayName", ""))
        a_full = a_tm.get("displayName", a_name)
        h_full = h_tm.get("displayName", h_name)
        a_rec = next((r.get("summary", "") for r in away.get("records", list()) if r.get("type") == "total"), "")
        h_rec = next((r.get("summary", "") for r in home.get("records", list()) if r.get("type") == "total"), "")
        bcasts = [n for b in comp.get("broadcasts", list()) for n in b.get("names", list()) if n]
        tv = next(iter(bcasts), "")
        odds_obj = next(iter(comp.get("odds", list())), {})
        odds_txt = str(odds_obj.get("details", "") or "")
        ou = odds_obj.get("overUnder", "")
        if ou:
            odds_txt = f"{odds_txt} | O/U {ou}".strip(" |")
        poss_id = str(comp.get("situation", {}).get("possession", ""))
        bg0 = clean_hex(a_tm.get("color"), "#1e293b")
        bg1 = clean_hex(h_tm.get("color"), "#0f172a")
        lg0 = a_tm.get("logo") or next((x.get("href", "") for x in a_tm.get("logos", list())), "")
        lg1 = h_tm.get("logo") or next((x.get("href", "") for x in h_tm.get("logos", list())), "")
        sort_rank = 0 if state == "in" else (1 if state == "pre" else 2)
        games.append({
            "rank": sort_rank, "date": str(ev.get("date", "")),
            "id": eid, "league": lg_code.upper(), "state": state, "status": status,
            "tv": tv, "odds": odds_txt,
            "away": a_name, "away_full": a_full, "arec": a_rec, "ascore": str(away.get("score", "0")), "aposs": (poss_id == str(away.get("id", "")) and state == "in"),
            "home": h_name, "home_full": h_full, "hrec": h_rec, "hscore": str(home.get("score", "0")), "hposs": (poss_id == str(home.get("id", "")) and state == "in"),
            "bg0": bg0, "fg0": "#ffffff", "lg0": lg0,
            "bg1": bg1, "fg1": "#ffffff", "lg1": lg1
        })
        if fast or lg_code not in ("nfl", "nba") or not eid:
            continue
        team_meta = {}
        for c in comps:
            t = c.get("team", {})
            ab = t.get("abbreviation", "")
            meta = {"bg": clean_hex(t.get("color"), "#1e293b"), "logo": t.get("logo") or next((x.get("href", "") for x in t.get("logos", list())), ""), "tid": t.get("id", "")}
            team_meta[ab] = meta
            roster_tasks.append({"ab": ab, "meta": meta, "status": status, "state": state})
        if state != "pre":
            box_tasks.append({"eid": eid, "team_meta": team_meta, "status": status, "state": state})
    if fast:
        games.sort(key=lambda g: (g["rank"], g["date"]))
        return games, []
    if lg_code in ("nfl", "nba"):
        loaded_abs = {r["ab"] for r in roster_tasks}
        all_tms = _TEAMS_CACHE.get(sport_path)
        if not all_tms:
            tms = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/teams?limit=40", timeout=5)
            parsed_tms = []
            for s_item in tms.get("sports", []):
                for l_item in s_item.get("leagues", []):
                    for sp_t in l_item.get("teams", []):
                        t = sp_t.get("team", {})
                        ab = t.get("abbreviation", "")
                        if ab and t.get("id"):
                            parsed_tms.append({
                                "ab": ab,
                                "meta": {
                                    "bg": clean_hex(t.get("color"), "#1e293b"),
                                    "logo": t.get("logo") or next((x.get("href", "") for x in t.get("logos", [])), ""),
                                    "tid": str(t.get("id", ""))
                                }
                            })
            if parsed_tms:
                _TEAMS_CACHE[sport_path] = parsed_tms
                all_tms = parsed_tms
        off_lbl = "Bye Week" if lg_code == "nfl" else "Off Day"
        for tm_item in (all_tms or []):
            if tm_item["ab"] not in loaded_abs:
                roster_tasks.append({"ab": tm_item["ab"], "meta": tm_item["meta"], "status": off_lbl, "state": "pre"})
    with ThreadPoolExecutor(max_workers=12) as pool:
        boxes = list(pool.map(lambda t: {"box": fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/summary?event={t['eid']}", timeout=6), "meta": t["team_meta"], "status": t["status"], "state": t["state"]}, box_tasks))
        rosters = list(pool.map(lambda r: {"ab": r["ab"], "meta": r["meta"], "rlist": get_roster(sport_path, r["meta"]["tid"]), "status": r["status"], "state": r["state"]}, roster_tasks))
    for item in boxes:
        box, team_meta, status, state = item["box"], item["meta"], item["status"], item["state"]
        pmap = {}
        for tg in box.get("boxscore", {}).get("players", list()):
            ab = tg.get("team", {}).get("abbreviation", "")
            for cat in tg.get("statistics", list()):
                cname = cat.get("name", "").lower()
                im = {str(x).upper(): i for i, x in enumerate(cat.get("labels", list()))}
                for ath in cat.get("athletes", list()):
                    a = ath.get("athlete", {})
                    nm = a.get("displayName", "")
                    if not nm:
                        continue
                    rec = pmap.setdefault((ab, nm), {"id": str(a.get("id", "")), "pos": a.get("position", {}).get("abbreviation", ""), "stats": {}})
                    st = ath.get("stats", list())
                    gv = lambda k: float(st[im[k]]) if (k in im and im[k] < len(st) and str(st[im[k]]).replace(".","",1).isdigit()) else 0.0
                    if lg_code == "nfl":
                        if cname == "passing":
                            ca = str(st[im["C/ATT"]]).split("/") if ("C/ATT" in im and im["C/ATT"] < len(st)) else ["0", "0"]
                            comp_v = float(ca[0]) if len(ca) > 0 and ca[0].replace(".", "", 1).isdigit() else 0.0
                            att_v = float(ca[1]) if len(ca) > 1 and ca[1].replace(".", "", 1).isdigit() else 0.0
                            rec["stats"]["COMP"] = comp_v
                            rec["stats"]["PASS COMP"] = comp_v
                            rec["stats"]["PASS ATT"] = att_v
                            rec["stats"]["PASS YDS"] = gv("YDS")
                            rec["stats"]["PASS TD"] = gv("TD")
                        elif cname == "rushing":
                            rec["stats"]["CAR"] = gv("CAR")
                            rec["stats"]["RUSH YDS"] = gv("YDS")
                            rec["stats"]["RUSH TD"] = gv("TD")
                        elif cname == "receiving":
                            rec["stats"]["REC"] = gv("REC")
                            rec["stats"]["TGTS"] = gv("TGTS")
                            rec["stats"]["REC YDS"] = gv("YDS")
                            rec["stats"]["REC TD"] = gv("TD")
                    else:
                        pts, reb, ast = gv("PTS"), gv("REB"), gv("AST")
                        p3 = str(st[im["3PT"]]).split("-") if ("3PT" in im and im["3PT"] < len(st)) else ["0"]
                        rec["stats"].update({"PTS": pts, "REB": reb, "AST": ast, "3PM": float(next(iter(p3), 0)),
                                             "STL": gv("STL"), "BLK": gv("BLK"), "PRA": pts + reb + ast,
                                             "PR": pts + reb, "PA": pts + ast, "RA": reb + ast})
        for (ab, nm), d in pmap.items():
            if (ab, nm) in seen_p:
                continue
            seen_p.add((ab, nm))
            if lg_code == "nfl":
                d["stats"]["SCRIM YDS"] = d["stats"].get("RUSH YDS", 0.0) + d["stats"].get("REC YDS", 0.0)
                d["stats"]["RUSH ATT"] = d["stats"].get("CAR", 0.0)
                d["stats"]["TD"] = d["stats"].get("RUSH TD", 0.0) + d["stats"].get("REC TD", 0.0)
                d["stats"]["REC TGTS"] = d["stats"].get("TGTS", 0.0)
            m = team_meta.get(ab, {"bg": "#1e293b", "logo": ""})
            players.append({"id": d.get("id", ""), "name": nm, "team": ab, "pos": d["pos"], "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": d["stats"]})
    for r in rosters:
        ab, m, status, state = r["ab"], r["meta"], r["status"], r["state"]
        for p in r["rlist"]:
            nm, pos = p["name"], p["pos"]
            if (lg_code == "nfl" and pos not in ("QB", "RB", "WR", "TE")) or (ab, nm) in seen_p:
                continue
            seen_p.add((ab, nm))
            players.append({"id": p.get("id", ""), "name": nm, "team": ab, "pos": pos, "league": lg_code.upper(), "status": status, "state": state, "bg": m["bg"], "logo": m["logo"], "stats": {}})
    games.sort(key=lambda g: (g["rank"], g["date"]))
    return games, players

_INJURY_CACHE = {"ts": 0.0, "data": {"NFL": [], "NBA": []}}

def _injury_abbr_and_rank(status_str):
    s = str(status_str or "").strip().lower()
    if not s:
        return ("INJ", 5)
    if "injured reserve" in s or s == "ir" or "pup" in s or "nfi" in s:
        return ("IR", 0)
    if "out" in s or "inactive" in s or "suspended" in s:
        return ("OUT", 1)
    if "doubtful" in s:
        return ("D", 2)
    if "questionable" in s:
        return ("Q", 3)
    if "day-to-day" in s or "day to day" in s or "dtd" in s:
        return ("DTD", 4)
    if "probable" in s:
        return ("P", 5)
    return (re.sub(r"[^A-Za-z]", "", status_str).upper()[:3] or "INJ", 5)

def fetch_league_injuries(sport_path, lg_code):
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sport_path}/injuries", timeout=6)
    groups = data.get("injuries") or data.get("items") or []
    out = []
    seen = set()
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        tm_obj = grp.get("team") or {}
        t_name = str(grp.get("displayName") or tm_obj.get("displayName") or tm_obj.get("shortDisplayName") or "").strip()
        t_abbr = str(tm_obj.get("abbreviation") or "").strip()
        t_logo = next((x.get("href", "") for x in tm_obj.get("logos", []) if isinstance(x, dict)), tm_obj.get("logo", ""))
        for inj in (grp.get("injuries") or []):
            if not isinstance(inj, dict):
                continue
            ath = inj.get("athlete") or {}
            nm = str(ath.get("displayName") or ath.get("fullName") or "").strip()
            if not nm:
                continue
            pid = str(ath.get("id") or "").strip()
            ath_tm = ath.get("team") or {}
            ab = t_abbr or str(ath_tm.get("abbreviation") or "").strip()
            lg_logo = t_logo or next((x.get("href", "") for x in ath_tm.get("logos", []) if isinstance(x, dict)), ath_tm.get("logo", ""))
            pos = str((ath.get("position") or {}).get("abbreviation") or "").strip()
            status = str(inj.get("status") or (inj.get("type") or {}).get("description") or "").strip()
            if not status or status.lower() == "active":
                continue
            abbr, rank = _injury_abbr_and_rank(status)
            det = inj.get("details") or {}
            inj_type = str(det.get("type") or det.get("location") or det.get("detail") or "").strip()
            short_c = str(inj.get("shortComment") or "").strip()
            long_c = str(inj.get("longComment") or "").strip()
            if short_c and long_c and long_c.startswith(short_c):
                long_c = long_c[len(short_c):].strip()
            comment = short_c or long_c
            advice = long_c if (short_c and long_c and long_c != short_c) else ""
            raw_dt = str(inj.get("date") or "").strip()
            dt = raw_dt[:10]
            ret_dt = str(det.get("returnDate") or "")[:10]
            dedup = pid or f"{ab}:{nm.lower()}"
            if dedup in seen:
                continue
            seen.add(dedup)
            out.append({
                "id": pid,
                "name": nm,
                "team": ab or t_name,
                "team_name": t_name or ab,
                "logo": lg_logo,
                "pos": pos,
                "league": lg_code.upper(),
                "status": status,
                "abbr": abbr,
                "rank": rank,
                "type": inj_type,
                "comment": comment,
                "advice": advice,
                "date": dt,
                "updated_at": raw_dt,
                "return_date": ret_dt
            })
    out.sort(key=lambda x: (x["rank"], x["team"], x["name"]))
    return out

def _compact_injuries(full_data):
    out = {}
    for lg, items in (full_data or {}).items():
        out[lg] = [{k: v for k, v in x.items() if k != "advice"} for x in (items or [])]
    return out

def get_injuries_payload(force=False, compact=False):
    now = time.time()
    if not force and (now - _INJURY_CACHE["ts"]) < 120 and (_INJURY_CACHE["data"].get("NFL") or _INJURY_CACHE["data"].get("NBA")):
        return _compact_injuries(_INJURY_CACHE["data"]) if compact else _INJURY_CACHE["data"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_nfl = pool.submit(fetch_league_injuries, "football/nfl", "nfl")
        f_nba = pool.submit(fetch_league_injuries, "basketball/nba", "nba")
        nfl_inj = f_nfl.result()
        nba_inj = f_nba.result()
    payload = {
        "NFL": nfl_inj if nfl_inj else _INJURY_CACHE["data"].get("NFL", []),
        "NBA": nba_inj if nba_inj else _INJURY_CACHE["data"].get("NBA", [])
    }
    _INJURY_CACHE["ts"] = now
    _INJURY_CACHE["data"] = payload
    return _compact_injuries(payload) if compact else payload

def get_live_payload(fast=False):
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < 20:
        return _CACHE["data"]
    if fast and not _CACHE["data"]:
        threading.Thread(target=get_live_payload, kwargs={"fast": False}, daemon=True).start()
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_nfl = pool.submit(parse_scoreboard, "football/nfl", "nfl", True)
            f_nba = pool.submit(parse_scoreboard, "basketball/nba", "nba", True)
            f_cfb = pool.submit(parse_scoreboard, "football/college-football", "cfb", True)
            nfl_g, _ = f_nfl.result()
            nba_g, _ = f_nba.result()
            cfb_g, _ = f_cfb.result()
        return {"games": {"NFL": nfl_g, "NBA": nba_g, "CFB": cfb_g}, "players": {"NFL": [], "NBA": []}, "injuries": _compact_injuries(_INJURY_CACHE["data"]), "partial": True}
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_nfl = pool.submit(parse_scoreboard, "football/nfl", "nfl", False)
        f_nba = pool.submit(parse_scoreboard, "basketball/nba", "nba", False)
        f_cfb = pool.submit(parse_scoreboard, "football/college-football", "cfb", False)
        f_inj = pool.submit(get_injuries_payload, False, True)
        nfl_g, nfl_p = f_nfl.result()
        nba_g, nba_p = f_nba.result()
        cfb_g, _ = f_cfb.result()
        inj_data = f_inj.result()
    payload = {"games": {"NFL": nfl_g, "NBA": nba_g, "CFB": cfb_g}, "players": {"NFL": nfl_p, "NBA": nba_p}, "injuries": inj_data}
    _CACHE["ts"], _CACHE["data"] = now, payload
    return payload

@app.route("/api/boxscore/<lg>/<eid>")
def api_boxscore(lg, eid):
    paths = {"nfl": "football/nfl", "nba": "basketball/nba", "cfb": "football/college-football"}
    sp = paths.get(lg.lower())
    if not sp:
        return jsonify({"error": "Invalid league"}), 400
    data = fetch_json(f"https://{HOST}/apis/site/v2/sports/{sp}/summary?event={eid}", timeout=8)
    hdr = next(iter(data.get("header", {}).get("competitions", list())), {})
    teams = list()
    for c in hdr.get("competitors", list()):
        t = c.get("team", {})
        ls = [str(x.get("displayValue", "-")) for x in c.get("linescores", list())]
        teams.append({
            "name": t.get("displayName", t.get("shortDisplayName", "")),
            "abbr": t.get("abbreviation", ""),
            "logo": next((x.get("href", "") for x in t.get("logos", list())), t.get("logo", "")),
            "score": str(c.get("score", "0")),
            "lines": ls,
            "homeAway": c.get("homeAway", "")
        })
    teams.sort(key=lambda x: 0 if x["homeAway"] == "away" else 1)
    team_stats = list()
    for tg in data.get("boxscore", {}).get("teams", list()):
        ab = tg.get("team", {}).get("abbreviation", "")
        st = [{"label": s.get("label", ""), "val": s.get("displayValue", "")} for s in tg.get("statistics", list())]
        team_stats.append({"abbr": ab, "stats": st})
    player_groups = list()
    for tg in data.get("boxscore", {}).get("players", list()):
        t_name = tg.get("team", {}).get("displayName", "")
        cats = list()
        for cat in tg.get("statistics", list()):
            labels = list(cat.get("labels", list()))
            rows = list()
            for ath in cat.get("athletes", list()):
                nm = ath.get("athlete", {}).get("displayName", "")
                if nm:
                    rows.append({"name": nm, "stats": list(ath.get("stats", list()))})
            if rows:
                cats.append({"name": cat.get("text") or cat.get("name", ""), "labels": labels, "rows": rows})
        if cats:
            player_groups.append({"team": t_name, "cats": cats})
    st_txt = hdr.get("status", {}).get("type", {}).get("shortDetail", "")
    return jsonify({"status": st_txt, "teams": teams, "team_stats": team_stats, "players": player_groups})
_PLAYER_CACHE = {}

@app.route("/api/player/<lg>/<pid>")
def api_player(lg, pid):
    paths = {"nfl": "football/nfl", "nba": "basketball/nba"}
    sp = paths.get(lg.lower())
    if not sp or not pid:
        return jsonify({"error": "Invalid player"}), 400
    ck = f"v5:{lg.lower()}:{pid}"
    now = time.time()
    if ck in _PLAYER_CACHE and (now - _PLAYER_CACHE[ck]["ts"]) < 900:
        return jsonify(_PLAYER_CACHE[ck]["data"])

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_bio = pool.submit(fetch_json, f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}", 6)
        f_ov = pool.submit(fetch_json, f"https://{WEB_HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/overview", 6)
        f_gl = pool.submit(fetch_json, f"https://{WEB_HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/gamelog", 6)
        bio = f_bio.result()
        ov = f_ov.result()
        gl = f_gl.result()

    if not ov.get("statistics") and not ov.get("gamelog"):
        ov = fetch_json(f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/overview", 6) or ov
    if not gl.get("seasonTypes"):
        gl = fetch_json(f"https://{HOST}/apis/common/v3/sports/{sp}/athletes/{pid}/gamelog", 6) or gl

    ath = bio.get("athlete") or ov.get("athlete") or {}
    tm = ath.get("team", {})
    season_stats = []
    st_blk = ov.get("statistics") or bio.get("statistics") or {}
    labels = st_blk.get("labels") or st_blk.get("names") or []
    splits = st_blk.get("splits", [])
    if labels and isinstance(splits, list) and len(splits) > 0:
        first_split = splits[0] if isinstance(splits[0], dict) else {}
        vals = first_split.get("stats", [])
        season_stats = [{"label": labels[i], "val": vals[i]} for i in range(min(len(labels), len(vals)))]

    gl_src = gl if gl.get("seasonTypes") else ov.get("gamelog", {})
    gl_labels = gl_src.get("labels") or gl_src.get("names") or []
    events_map = gl_src.get("events", {})
    games_by_id = {}
    for st_type in gl_src.get("seasonTypes", []):
        for cat in st_type.get("categories", []):
            if not gl_labels:
                gl_labels = cat.get("labels") or cat.get("names") or []
            for ev in cat.get("events", []):
                eid = str(ev.get("eventId", ""))
                if not eid or eid in games_by_id:
                    continue
                meta = events_map.get(eid, {}) if isinstance(events_map, dict) else {}
                opp = meta.get("opponent", {})
                games_by_id[eid] = {
                    "date": str(meta.get("gameDate", ""))[:10],
                    "opp": opp.get("abbreviation", ""),
                    "atVs": meta.get("atVs", "vs"),
                    "result": meta.get("gameResult", ""),
                    "score": meta.get("score", ""),
                    "stats": ev.get("stats", [])
                }
    games_log = sorted(games_by_id.values(), key=lambda x: x["date"], reverse=True)

    inj_list = get_injuries_payload().get(lg.upper(), [])
    ath_name_l = str(ath.get("displayName", "")).strip().lower()
    p_inj = next((x for x in inj_list if (pid and x.get("id") == str(pid)) or (ath_name_l and x.get("name", "").lower() == ath_name_l)), None)

    payload = {
        "id": pid,
        "name": ath.get("displayName", ""),
        "jersey": ath.get("jersey", ""),
        "pos": ath.get("position", {}).get("abbreviation", ""),
        "headshot": ath.get("headshot", {}).get("href", ""),
        "team": tm.get("displayName", ""),
        "abbr": tm.get("abbreviation", ""),
        "bg": clean_hex(tm.get("color"), "#1e293b"),
        "logo": next((x.get("href", "") for x in tm.get("logos", [])), ""),
        "injury": p_inj,
        "season": season_stats,
        "gamelog": {"labels": gl_labels, "games": games_log[:10]}
    }
    _PLAYER_CACHE[ck] = {"ts": now, "data": payload}
    return jsonify(payload)

@app.route("/api/injuries")
def api_injuries():
    force = request.args.get("refresh") == "1"
    return jsonify(get_injuries_payload(force=force))

@app.route("/api/live")
def api_live():
    is_fast = request.args.get("fast") == "1"
    return jsonify(get_live_payload(fast=is_fast))

threading.Thread(target=get_live_payload, kwargs={"fast": False}, daemon=True).start()

@app.route("/")
def index():
    _record_page_visit()
    return render_template("index.html")

@app.route("/ping")
def ping():
    return "ok", 200

@app.route("/manifest.json")
def pwa_manifest():
    return send_from_directory(os.path.join(app.root_path, "static"), "manifest.json", mimetype="application/manifest+json")

@app.route("/sw.js")
def pwa_sw():
    resp = send_from_directory(os.path.join(app.root_path, "static"), "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp

@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    body = request.get_json(silent=True) or {}
    topic = re.sub(r"[\r\n]+", " ", str(body.get("topic") or "General Feedback").strip())[:80]
    sender = re.sub(r"[\r\n]+", " ", str(body.get("email") or "").strip())[:120]
    message = str(body.get("message") or "").strip()[:4000]
    if not message:
        return jsonify({"ok": False, "error": "Please enter a message before sending."}), 400

    to_email = os.environ.get("FEEDBACK_TO_EMAIL", "info@omnistatpro.com").strip() or "info@omnistatpro.com"
    subject = f"[OmniStatPro] {topic}"
    full_body = f"Topic: {topic}\nFrom: {sender or 'Anonymous Visitor'}\n\nMessage:\n{message}\n"
    print(f"[FEEDBACK] {subject} | from={sender or 'anon'} | {message[:300]}", flush=True)
    with _ANALYTICS_LOCK:
        _ANALYTICS["recent_feedback"].insert(0, {
            "ts": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "email": sender or "Anonymous",
            "message": message[:500]
        })
        _ANALYTICS["recent_feedback"] = _ANALYTICS["recent_feedback"][:25]

    # 1. Resend HTTP API (if RESEND_API_KEY is configured in Railway)
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key:
        try:
            from_addr = os.environ.get("FEEDBACK_FROM_EMAIL", "OmniStatPro <onboarding@resend.dev>").strip()
            r_payload = {"from": from_addr, "to": [to_email], "subject": subject, "text": full_body}
            if sender and "@" in sender:
                r_payload["reply_to"] = sender
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json=r_payload,
                timeout=10,
            )
            if r.ok:
                return jsonify({"ok": True, "sent": True, "to": to_email})
        except Exception as exc:
            print(f"[FEEDBACK] Resend error: {exc}", flush=True)

    # 2. SMTP delivery (if SMTP_HOST, SMTP_USER, SMTP_PASS are configured in Railway)
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()
    if smtp_host and smtp_user and smtp_pass:
        try:
            smtp_port = int(os.environ.get("SMTP_PORT", "587"))
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = os.environ.get("FEEDBACK_FROM_EMAIL", smtp_user).strip()
            msg["To"] = to_email
            if sender and "@" in sender:
                msg["Reply-To"] = sender
            msg.set_content(full_body)
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as srv:
                    srv.login(smtp_user, smtp_pass)
                    srv.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as srv:
                    srv.starttls()
                    srv.login(smtp_user, smtp_pass)
                    srv.send_message(msg)
            return jsonify({"ok": True, "sent": True, "to": to_email})
        except Exception as exc:
            print(f"[FEEDBACK] SMTP error: {exc}", flush=True)

    return jsonify({"ok": True, "sent": False, "mailto_fallback": True, "to": to_email})


@app.route("/api/admin/overview")
def api_admin_overview():
    auth_hdr = str(request.headers.get("Authorization") or "").strip()
    if not auth_hdr.lower().startswith("bearer "):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    token = auth_hdr.split(" ", 1)[1].strip()
    if not token:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    # Verify the caller's Supabase JWT server-side
    try:
        u_resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_ANON_KEY},
            timeout=8,
        )
        if not u_resp.ok:
            return jsonify({"ok": False, "error": "Invalid session"}), 401
        u_data = u_resp.json()
        caller_email = str(u_data.get("email") or "").strip().lower()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Auth verification failed: {exc}"}), 401

    allowed_extra = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
    if not (caller_email.endswith("@omnistatpro.com") or caller_email in allowed_extra):
        return jsonify({"ok": False, "error": "Forbidden"}), 403

    # Build traffic & scan snapshot
    today = _today_utc()
    with _ANALYTICS_LOCK:
        days_list = [
            {"date": k, "views": v["views"], "visitors": len(v["visitors"])}
            for k, v in sorted(_ANALYTICS["days"].items(), reverse=True)
        ]
        today_stats = _ANALYTICS["days"].get(today, {"views": 0, "visitors": set()})
        traffic = {
            "started_at": _ANALYTICS["started_at"],
            "today_views": today_stats["views"],
            "today_visitors": len(today_stats["visitors"]),
            "total_views": sum(d["views"] for d in days_list),
            "days": days_list[:14],
            "devices": dict(_ANALYTICS["devices"]),
            "referrers": sorted(_ANALYTICS["referrers"].items(), key=lambda x: x[1], reverse=True)[:8],
            "scans_total": _ANALYTICS["scans_total"],
            "scans_vision_ok": _ANALYTICS["scans_vision_ok"],
            "scans_by_book": sorted(_ANALYTICS["scans_by_book"].items(), key=lambda x: x[1], reverse=True),
            "recent_feedback": list(_ANALYTICS["recent_feedback"]),
        }

    # Fetch signed-up users & saved card counts using SUPABASE_SERVICE_ROLE_KEY
    svc_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    users_out = []
    users_summary = {"configured": bool(svc_key), "total_users": 0, "new_7d": 0, "total_cards": 0, "active_cards": 0, "settled_cards": 0, "err": ""}
    if svc_key:
        try:
            svc_hdrs = {"Authorization": f"Bearer {svc_key}", "apikey": svc_key}
            ur = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users?page=1&per_page=200", headers=svc_hdrs, timeout=10)
            cr = requests.get(f"{SUPABASE_URL}/rest/v1/user_cards?select=user_id,cards_json,updated_at", headers=svc_hdrs, timeout=10)
            cards_by_uid = {}
            if cr.ok:
                for row in (cr.json() or []):
                    uid = str(row.get("user_id") or "")
                    clist = row.get("cards_json") if isinstance(row.get("cards_json"), list) else []
                    cards_by_uid[uid] = {"cards": clist, "updated_at": row.get("updated_at") or ""}
            if ur.ok:
                raw_users = (ur.json() or {}).get("users") or []
                now_ts = time.time()
                for u in raw_users:
                    uid = str(u.get("id") or "")
                    cinfo = cards_by_uid.get(uid, {"cards": [], "updated_at": ""})
                    clist = cinfo["cards"]
                    settled_cnt = sum(1 for c in clist if isinstance(c, dict) and (c.get("settled") or c.get("archived")))
                    active_cnt = max(0, len(clist) - settled_cnt)
                    books = sorted({str(c.get("book") or "Other").strip() for c in clist if isinstance(c, dict)})
                    created_str = str(u.get("created_at") or "")
                    try:
                        c_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        if (now_ts - c_dt.timestamp()) <= 7 * 86400:
                            users_summary["new_7d"] += 1
                    except Exception:
                        pass
                    users_summary["total_cards"] += len(clist)
                    users_summary["active_cards"] += active_cnt
                    users_summary["settled_cards"] += settled_cnt
                    users_out.append({
                        "email": u.get("email") or "",
                        "created_at": created_str,
                        "last_sign_in_at": u.get("last_sign_in_at") or "",
                        "cards_total": len(clist),
                        "cards_active": active_cnt,
                        "cards_settled": settled_cnt,
                        "books": books,
                    })
                users_out.sort(key=lambda x: x["created_at"], reverse=True)
                users_summary["total_users"] = len(users_out)
            else:
                users_summary["err"] = f"Supabase Admin API HTTP {ur.status_code}"
        except Exception as exc:
            users_summary["err"] = str(exc)

    return jsonify({"ok": True, "admin": caller_email, "traffic": traffic, "users_summary": users_summary, "users": users_out})

_VALID_STATS = {
    "PASS YDS", "PASS TD", "PASS ATT", "COMP", "RUSH YDS", "RUSH ATT", "RUSH TD",
    "REC YDS", "REC", "REC TGTS", "REC TD", "SCRIM YDS", "TD",
    "PTS", "REB", "AST", "3PM", "STL", "BLK", "PRA", "PR", "PA", "RA"
}
_NBA_STATS = {"PTS", "REB", "AST", "3PM", "STL", "BLK", "PRA", "PR", "PA", "RA"}


def _clean_money_str(val):
    s = re.sub(r"[^0-9.]", "", str(val or "").strip())
    if not s or s.count(".") > 1:
        return ""
    try:
        num = float(s)
        return f"{num:.2f}" if num > 0 else ""
    except ValueError:
        return ""


def _parse_float_opt(val):
    if val is None or isinstance(val, bool):
        return None
    s = str(val).strip().replace(",", "").replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"\+$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_stat(raw):
    up = re.sub(r"\s+", " ", str(raw or "").strip().upper())
    if up in _VALID_STATS:
        return up
    s = up.lower()
    if re.search(r"pts\s*\+\s*rebs?\s*\+\s*asts?|points\s*\+\s*rebounds\s*\+\s*assists|\bpra\b", s):
        return "PRA"
    if re.search(r"(?:pts|points)\s*\+\s*(?:rebs?|rebounds)|\bpr\b", s):
        return "PR"
    if re.search(r"(?:pts|points)\s*\+\s*(?:asts?|assists)|\bpa\b", s):
        return "PA"
    if re.search(r"(?:rebs?|rebounds)\s*\+\s*(?:asts?|assists)|\bra\b", s):
        return "RA"
    if re.search(r"rush(?:ing)?\s*\+\s*rec(?:eiving)?|scrimmage", s):
        return "SCRIM YDS"
    if re.search(r"pass(?:ing)?\s*att(?:empts)?", s):
        return "PASS ATT"
    if re.search(r"pass(?:ing)?\s*comp(?:letions)?|\bcomp\b", s):
        return "COMP"
    if re.search(r"pass(?:ing)?\s*(?:td|touchdown)", s):
        return "PASS TD"
    if re.search(r"rush(?:ing)?\s*(?:td|touchdown)", s):
        return "RUSH TD"
    if re.search(r"rec(?:eiving)?\s*(?:td|touchdown)", s):
        return "REC TD"
    if re.search(r"rush(?:ing)?\s*att(?:empts)?|carries|\bcar\b", s):
        return "RUSH ATT"
    if re.search(r"pass(?:ing)?\s*(?:yards?|yds?)", s):
        return "PASS YDS"
    if re.search(r"rush(?:ing)?\s*(?:yards?|yds?)", s):
        return "RUSH YDS"
    if re.search(r"rec(?:eiving)?\s*(?:yards?|yds?)", s):
        return "REC YDS"
    if re.search(r"rec(?:eiving)?\s*targets?|\btgts?\b|\btargets?\b", s):
        return "REC TGTS"
    if re.search(r"receptions?|catches|\brecs?\b", s):
        return "REC"
    if re.search(r"anytime\s*td|touchdowns?|\btd\b", s):
        return "TD"
    if re.search(r"3-?pt|3pm|3-?point|three\s*pointer|threes", s):
        return "3PM"
    if re.search(r"rebounds?|\brebs?\b", s):
        return "REB"
    if re.search(r"assists?|\basts?\b", s):
        return "AST"
    if re.search(r"steals?|\bstl\b", s):
        return "STL"
    if re.search(r"blocks?|\bblk\b", s):
        return "BLK"
    if re.search(r"points?|\bpts\b", s):
        return "PTS"
    return up if up in _VALID_STATS else ""


def _normalize_player_name(name):
    clean = re.sub(r"\s+", " ", str(name or "").strip())
    if clean.lower() == "james cook":
        return "James Cook III"
    return clean


def _normalize_parsed_slip(parsed):
    if not isinstance(parsed, dict):
        return {"cost": "", "payout": "", "legs": []}
    cost = _clean_money_str(parsed.get("cost"))
    payout = _clean_money_str(parsed.get("payout"))
    raw_legs = parsed.get("legs")
    if not isinstance(raw_legs, list):
        raw_legs = []

    legs = []
    seen = set()
    for item in raw_legs:
        if not isinstance(item, dict):
            continue
        ltype = str(item.get("type") or "").strip().lower()
        sport = str(item.get("sport") or "").strip().upper()
        if sport not in ("NFL", "NBA", "CFB"):
            sport = ""

        if ltype == "prop" or (not ltype and item.get("player")):
            player = _normalize_player_name(item.get("player"))
            stat = _normalize_stat(item.get("stat"))
            if not player or not stat:
                continue
            if not sport:
                sport = "NBA" if stat in _NBA_STATS else "NFL"
            ou_raw = str(item.get("ou") or "Over").strip().lower()
            ou = "Under" if re.search(r"under|less|lower|down|^u$", ou_raw) else "Over"
            target = _parse_float_opt(item.get("target"))
            if stat == "TD" and (target is None or target <= 0):
                target = 0.5
            if target is None or target <= 0 or target >= 700:
                continue
            key = ("prop", sport, player.lower(), stat, ou, target)
            if key in seen:
                continue
            seen.add(key)
            legs.append({"type": "prop", "sport": sport, "player": player, "stat": stat, "ou": ou, "target": target})
        elif ltype in ("spread", "ml"):
            team = re.sub(r"\s+", " ", str(item.get("team") or "").strip())
            if not team:
                continue
            if not sport:
                sport = "NFL"
            if ltype == "ml":
                sp_val = 0.0
            else:
                sp_val = _parse_float_opt(item.get("spread"))
                if sp_val is None or abs(sp_val) > 65:
                    continue
            key = (ltype, sport, team.lower(), sp_val)
            if key in seen:
                continue
            seen.add(key)
            legs.append({"type": ltype, "sport": sport, "team": team, "spread": sp_val})
        elif ltype == "total":
            game = re.sub(r"\s+", " ", str(item.get("game") or "").strip())
            total = _parse_float_opt(item.get("total") if item.get("total") is not None else item.get("target"))
            if not game or total is None or total <= 10 or total > 350:
                continue
            if not sport:
                sport = "NBA" if total >= 150 else "NFL"
            ou_raw = str(item.get("ou") or "Over").strip().lower()
            ou = "Under" if re.search(r"under|less|lower|^u$", ou_raw) else "Over"
            key = ("total", sport, game.lower(), ou, total)
            if key in seen:
                continue
            seen.add(key)
            legs.append({"type": "total", "sport": sport, "game": game, "ou": ou, "total": total})

    return {"cost": cost, "payout": payout, "legs": legs}


def _build_slip_prompt(book, has_crop):
    b_low = str(book or "").lower()
    if "prizepicks" in b_low:
        book_rules = (
            "- PrizePicks: \"$10 to win $50\" -> cost \"10.00\", payout \"50.00\".\n"
            "- Arrow left of each prop number: ↓ or \"Less\" -> \"Under\", ↑ or \"More\" -> \"Over\" (white arrows can point ↓).\n"
            "- Crossed-out original line next to discounted promo (e.g. 302.5 -> 0.5): use 0.5.\n"
            "- Ignore jersey numbers (#8), game times, and multipliers (3x, 6x)."
        )
    elif "underdog" in b_low:
        book_rules = (
            "- Underdog: \"$10 to win $50\" / Entry & Payout -> cost, payout.\n"
            "- \"Higher\"/↑ -> \"Over\"; \"Lower\"/↓ -> \"Under\".\n"
            "- Crossed-out original line next to Gimme promo (0.5): use 0.5. Ignore multipliers (1.25x, 3x, 6x)."
        )
    elif "kalshi" in b_low:
        book_rules = (
            "- Kalshi: COST / Total Cost -> cost; MAX PAYOUT / Payout -> payout (often side-by-side above $ amounts).\n"
            "- Ignore cent prices (62¢), percentages (66%), and contract counts.\n"
            "- Read ALL legs even if the last word is clipped before a % badge (e.g. \"40+ rushing yard 66%\" -> RUSH YDS, 40, Over).\n"
            "- Yes/No rules: winner Yes -> ml that team (No -> opponent); \"wins by over X.5\" Yes -> spread -X.5 (No -> opponent +X.5); total Yes -> Over (No -> Under); \"N+ stat\" Yes -> Over N (No -> Under N-0.5)."
        )
    else:
        book_rules = (
            f"- {book}: Total Wager/Wager/Bought -> cost; Total Payout/Est. Payout/To Pay -> payout.\n"
            "- NEVER use American odds (-110, -115, +145, +250) as target, spread, or total.\n"
            "- Keep exact .5 decimals; \"25+\" -> Over 25; Anytime TD -> stat \"TD\", Over 0.5; keep +/- sign on spreads.\n"
            "- Ignore duplicate summary header lines, cashout buttons, and live mini-scoreboards."
        )
    return f"""Extract {book} bet slip JSON ONLY (no markdown):
{{"cost":"20.00","payout":"60.00","legs":[{{"type":"prop","sport":"NFL"|"NBA"|"CFB","player":"Full Name","stat":"CODE","ou":"Over"|"Under","target":24.5}},{{"type":"spread"|"ml","sport":"NFL"|"NBA"|"CFB","team":"Full Team Name","spread":-3.5}},{{"type":"total","sport":"NFL"|"NBA"|"CFB","game":"Away @ Home","ou":"Over"|"Under","total":48.5}}]}}
Rules:
- Plain numeric cost/payout (no $ or commas, or "" if absent).
{book_rules}
- Exact stat codes: NFL: PASS YDS, PASS TD, PASS ATT, COMP, RUSH YDS, RUSH ATT, RUSH TD, REC YDS, REC, REC TGTS, REC TD, SCRIM YDS, TD. NBA: PTS, REB, AST, 3PM, STL, BLK, PRA, PR, PA, RA.
- List James Cook as "James Cook III". Do not duplicate legs."""


_MODEL_COOLDOWN = {}
_GEMINI_SESSION = requests.Session()


@app.route("/api/parse-slip", methods=["POST"])
def api_parse_slip():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({"ok": False, "fallback": True, "error": "No GEMINI_API_KEY configured"}), 200

    body = request.get_json(silent=True) or {}
    img_b64 = str(body.get("image_b64") or "").strip()
    mime_type = str(body.get("mime_type") or "image/jpeg").strip()
    crop_b64 = str(body.get("crop_b64") or "").strip()
    crop_mime = str(body.get("crop_mime_type") or "image/jpeg").strip()
    book = str(body.get("book") or "PrizePicks").strip()
    if not img_b64:
        return jsonify({"ok": False, "error": "Missing image data"}), 400

    if "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]
    if "," in crop_b64:
        crop_b64 = crop_b64.split(",", 1)[1]

    has_crop = bool(crop_b64)
    parts = [
        {"text": _build_slip_prompt(book, has_crop)},
        {"inline_data": {"mime_type": mime_type, "data": img_b64}}
    ]
    if has_crop:
        parts.append({"text": "IMAGE 2 (zoomed right-hand column):"})
        parts.append({"inline_data": {"mime_type": crop_mime, "data": crop_b64}})

    base_gen_cfg = {
        "temperature": 0.0,
        "responseMimeType": "application/json"
    }

    env_model = os.environ.get("GEMINI_MODEL", "").strip()
    all_models = [m for m in (env_model, "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.0-flash") if m]
    now = time.time()
    candidate_models = [m for m in all_models if _MODEL_COOLDOWN.get(m, 0) <= now] or all_models
    last_err = "Gemini API error"

    try:
        raw_res = None
        used_model = ""
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            t_level = "minimal" if "lite" in model_name else "low"
            payload = {
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingLevel": t_level}
                }
            }
            try:
                resp = _GEMINI_SESSION.post(url, json=payload, timeout=12)
                raw_res = resp.json()
            except Exception as req_err:
                last_err = str(req_err)
                _MODEL_COOLDOWN[model_name] = time.time() + 120
                raw_res = None
                continue
            if "error" in raw_res and resp.status_code == 400:
                payload["generationConfig"] = base_gen_cfg
                resp = _GEMINI_SESSION.post(url, json=payload, timeout=12)
                raw_res = resp.json()
            if "error" not in raw_res:
                used_model = model_name
                _MODEL_COOLDOWN.pop(model_name, None)
                break
            last_err = str(raw_res["error"].get("message", "Gemini API error"))
            if resp.status_code == 404:
                _MODEL_COOLDOWN[model_name] = time.time() + 3600
            elif resp.status_code in (429, 500, 503):
                _MODEL_COOLDOWN[model_name] = time.time() + 180
            if resp.status_code in (401, 403):
                break

        if not raw_res or "error" in raw_res:
            _record_slip_scan(book, False)
            return jsonify({"ok": False, "fallback": True, "error": last_err}), 200
        cands = raw_res.get("candidates") or []
        res_parts = (cands[0].get("content") or {}).get("parts") or [] if cands else []
        txt = next((p.get("text", "") for p in reversed(res_parts) if p.get("text") and not p.get("thought")), "")
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip(), flags=re.I)
        parsed = json.loads(txt)
        cleaned = _normalize_parsed_slip(parsed)
        _record_slip_scan(book, True)
        return jsonify({
            "ok": True,
            "source": "vision",
            "model": used_model,
            "cost": cleaned["cost"],
            "payout": cleaned["payout"],
            "legs": cleaned["legs"]
        })
    except Exception as e:
        _record_slip_scan(book, False)
        return jsonify({"ok": False, "fallback": True, "error": str(e)}), 200

