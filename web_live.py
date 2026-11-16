import os
import json
import re
from flask import Flask, jsonify, render_template
import gspread
import doc_brand
import doc_data

SHEET_ID = "1zQ0jUfO_Siik-bwBx7ok6UIILZgc5X0JINp-KbEZXTQ"
creds_env = os.environ.get("GOOGLE_CREDS_JSON", "").strip()
gc = gspread.service_account_from_dict(json.loads(creds_env)) if creds_env else gspread.service_account(filename="credentials.json")
ss = gc.open_by_key(SHEET_ID)
app = Flask(__name__)

def get_rows(tab):
    try: return ss.worksheet(tab).get_all_values()
    except Exception: return list()

def rgb_css(c):
    return f"rgb({int(c['red']*255)},{int(c['green']*255)},{int(c['blue']*255)})"

def parse_cp(raw):
    parts = [p.strip() for p in re.split(r"[|/,-]", str(raw)) if p.strip()]
    c, p = next(iter(parts), "—"), next(iter(parts[1:]), "—")
    if c != "—" and not c.startswith("$"): c = "$" + c
    if p != "—" and not p.startswith("$"): p = "$" + p
    return c, p

def money_val(s):
    m = re.search(r"(\d+(?:\.\d+)?)", str(s))
    return float(m.group(1)) if m else 0.0

def build_blocks(rows, watch_rows, val_fn, is_nfl, lg):
    cards = doc_data.build_player_cards(rows, [(n, t) for n, t, _ in watch_rows], val_fn, is_nfl)
    out = list()
    for i in range(0, len(cards), 8):
        grp = cards[i:i + 8]
        _, _, cp_raw = next(iter(watch_rows[i:i+1]), ("", "", ""))
        c_str, p_str = parse_cp(cp_raw)
        p_items = list()
        for tl, tm, rt, bl, bm, _ in grp:
            is_hit = bm.startswith("+") or bm == "0" or "HIT" in bm
            is_miss = (not is_hit) and ("final" in str(rt).lower())
            abbr = next(iter(tl.split("•")[-1].split()), "") if "•" in tl else ""
            bg, _, logo = doc_brand.team_style(abbr, league=lg)
            p_items.append({"name": next(iter(tl.split("•")), tl).strip(), "stat": tm, "gained": bl, "needed": bm,
                            "hit": is_hit, "miss": is_miss, "bg": rgb_css(bg), "logo": logo})
        all_hit = len(p_items) > 0 and all(x["hit"] for x in p_items)
        any_miss = any(x["miss"] for x in p_items)
        out.append({"cost": c_str, "payout": p_str, "c_val": money_val(c_str), "p_val": money_val(p_str),
                    "all_hit": all_hit, "any_miss": any_miss, "players": p_items})
    return out

@app.route("/api/data")
def api_data():
    wl = get_rows("Watchlist")[1:]
    cfb_w = [(doc_data.col(r,0).strip().lower(), doc_data.col(r,1).strip()) for r in wl if doc_data.col(r,0).strip()]
    nfl_w = [(doc_data.col(r,2).strip().lower(), doc_data.col(r,3).strip(), doc_data.col(r,6).strip()) for r in wl if doc_data.col(r,2).strip()]
    nba_w = [(doc_data.col(r,4).strip().lower(), doc_data.col(r,5).strip(), doc_data.col(r,7).strip()) for r in wl if doc_data.col(r,4).strip()]
    nfl_g = build_blocks(get_rows("NFL Live Stats")[1:], nfl_w, doc_data.nfl_val, True, "nfl")
    nba_g = build_blocks(get_rows("NBA Live Stats")[1:], nba_w, doc_data.nba_val, False, "nba")
    all_b = nfl_g + nba_g
    tot_c = sum(b["c_val"] for b in all_b)
    live_p = sum(b["p_val"] for b in all_b if not b["any_miss"])
    paid_p = sum(b["p_val"] for b in all_b if b["all_hit"])
    cfb_list = list()
    for r in get_rows("CFB Live Scores")[1:]:
        ac, hc = doc_data.clean_team(doc_data.col(r,2)), doc_data.clean_team(doc_data.col(r,4))
        for k, note in cfb_w:
            if k == ac or k == hc:
                bg0, fg0, lg0 = doc_brand.team_style(doc_data.col(r,2), league="cfb")
                bg1, fg1, lg1 = doc_brand.team_style(doc_data.col(r,4), league="cfb")
                cfb_list.append((doc_data.col(r,8,"9999"), {"away": doc_data.col(r,2), "ascore": doc_data.col(r,3), "home": doc_data.col(r,4), "hscore": doc_data.col(r,5),
                                 "status": doc_data.col(r,1), "note": note, "bg0": rgb_css(bg0), "fg0": rgb_css(fg0), "lg0": lg0, "bg1": rgb_css(bg1), "fg1": rgb_css(fg1), "lg1": lg1}))
                break
    cfb_list.sort(key=lambda x: next(iter(x)))
    return jsonify({"summary": {"cost": tot_c, "live": live_p, "paid": paid_p}, "nfl": nfl_g, "nba": nba_g, "cfb": [x[-1] for x in cfb_list]})

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
