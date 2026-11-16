import re

def col(r, i, d=""):
    for idx, val in enumerate(r):
        if idx == i: return val
    return d

def clean_team(n):
    return re.sub(r"^#\d+\s+", "", n.strip()).lower()

def flt(v):
    try: return float(str(v).strip())
    except Exception: return 0.0

def parse_tgt(s):
    s = s.strip().upper()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return ((s[:m.start()] + s[m.end():]).strip(), float(m.group(1))) if m else (s, None)

def fmt_num(v):
    return str(int(v)) if v == int(v) else str(round(v, 1))

def nfl_val(r, lbl):
    m = {"COMP": flt(col(r,4)), "PASS YDS": flt(col(r,6)), "PASS TD": flt(col(r,7)), "CAR": flt(col(r,9)),
         "RUSH YDS": flt(col(r,10)), "RUSH TD": flt(col(r,11)), "REC": flt(col(r,12)), "TGTS": flt(col(r,13)),
         "REC YDS": flt(col(r,14)), "REC TD": flt(col(r,15)), "SCRIM YDS": flt(col(r,10)) + flt(col(r,14))}
    return m.get(lbl, 0.0)

def nba_val(r, lbl):
    pts, reb, ast = flt(col(r,4)), flt(col(r,5)), flt(col(r,6))
    m = {"PTS": pts, "REB": reb, "AST": ast, "3PM": flt(col(r,7)), "STL": flt(col(r,9)), "BLK": flt(col(r,10)),
         "PRA": pts + reb + ast, "PR": pts + reb, "PA": pts + ast, "RA": reb + ast}
    return m.get(lbl, 0.0)

def build_player_cards(rows, watch, val_fn, is_nfl):
    out = list()
    for k, raw in watch:
        for r in rows:
            if k in col(r,2).lower():
                status = col(r,0).strip()
                lbl, tgt = parse_tgt(raw)
                if tgt is not None and lbl:
                    cur = val_fn(r, lbl)
                    delta = round(cur - tgt, 1)
                    need_str = f"+{fmt_num(delta)}" if delta > 0 else fmt_num(delta)
                    stat_needed = f"{fmt_num(tgt)} {lbl if lbl in ('3PM','PRA','PR','PA','RA') else lbl.title()}"
                    gained_str = fmt_num(cur)
                else:
                    stat_needed, gained_str, need_str = (raw or "—"), "—", status
                hdr_txt = f"{col(r,2)}  •  {col(r,1)} {col(r,3)}" if is_nfl else f"{col(r,2)}  •  {col(r,1)}"
                out.append((hdr_txt, stat_needed, status, gained_str, need_str, is_nfl))
                break
    return out
