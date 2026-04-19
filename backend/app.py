"""
=============================================================
  PARIS IA — Backend Flask (Render.com)
  API REST + Scheduler + Push Notifications
=============================================================
"""

import os
import json
import sqlite3
import csv
import io
import time
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

load_dotenv()

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
ODDS_API_KEY     = os.getenv("ODDS_API_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL      = os.getenv("VAPID_EMAIL", "mailto:parisIA@example.com")

DB_PATH          = os.getenv("DB_PATH", "paris_sportifs.db")
JOURNAL_PATH     = os.getenv("JOURNAL_PATH", "paris_virtuels.csv")
BANKROLL_DEPART  = 1000
MISE_MIN         = 10
MISE_MAX         = 100
SEUIL_VALEUR     = 0.05

SAISON = 2024

LIGUES_FOOTBALL = {
    "Premier League": 39,
    "Liga":           140,
    "Bundesliga":     78,
    "Ligue 1":        61,
}

LIGUES_ODDS = {
    "Premier League": "soccer_epl",
    "Liga":           "soccer_spain_la_liga",
    "Bundesliga":     "soccer_germany_bundesliga",
    "Ligue 1":        "soccer_france_ligue_one",
}

# Store push subscriptions in memory (persisted to file)
SUBSCRIPTIONS_FILE = "push_subscriptions.json"
push_subscriptions = []


def load_subscriptions():
    global push_subscriptions
    if os.path.exists(SUBSCRIPTIONS_FILE):
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            push_subscriptions = json.load(f)


def save_subscriptions():
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(push_subscriptions, f)


def send_push_notification(title, body, url="/"):
    """Send push notification to all subscribers."""
    if not VAPID_PRIVATE_KEY or not push_subscriptions:
        return
    payload = json.dumps({"title": title, "body": body, "url": url})
    dead = []
    for i, sub in enumerate(push_subscriptions):
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_EMAIL},
            )
        except WebPushException as e:
            if e.response and e.response.status_code in (404, 410):
                dead.append(i)
        except Exception:
            pass
    for i in sorted(dead, reverse=True):
        push_subscriptions.pop(i)
    if dead:
        save_subscriptions()


# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS matchs_football (
        id INTEGER PRIMARY KEY, ligue TEXT, date_match TEXT,
        equipe_domicile TEXT, equipe_exterieur TEXT, statut TEXT,
        score_dom INTEGER, score_ext INTEGER, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS stats_equipes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, equipe TEXT, ligue TEXT,
        saison INTEGER, matchs_joues INTEGER, victoires INTEGER,
        nuls INTEGER, defaites INTEGER, buts_marques INTEGER,
        buts_encaisses INTEGER, forme_recente TEXT, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, sport TEXT, ligue TEXT,
        equipe_dom TEXT, equipe_ext TEXT, date_match TEXT,
        bookmaker TEXT, cote_dom REAL, cote_nul REAL, cote_ext REAL,
        collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS matchs_tennis (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tournoi TEXT, surface TEXT,
        date_match TEXT, joueur_1 TEXT, joueur_2 TEXT, statut TEXT,
        gagnant TEXT, score TEXT, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS classement_atp (
        id INTEGER PRIMARY KEY AUTOINCREMENT, rang INTEGER,
        joueur TEXT, pays TEXT, points INTEGER, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS historique_matchs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, ligue TEXT, date_match TEXT,
        equipe_domicile TEXT, equipe_exterieur TEXT, buts_dom INTEGER,
        buts_ext INTEGER, resultat TEXT, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS historique_tennis (
        id INTEGER PRIMARY KEY AUTOINCREMENT, tournoi TEXT, surface TEXT,
        saison TEXT, date_match TEXT, joueur_1 TEXT, joueur_2 TEXT,
        gagnant TEXT, rang_j1 INTEGER, rang_j2 INTEGER,
        cote_j1 REAL, cote_j2 REAL, collecte_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS journal_paris (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sport TEXT, ligue TEXT, match_nom TEXT, date_match TEXT,
        type_pari TEXT, probabilite TEXT, cote REAL, valeur_ev TEXT,
        mise REAL, gain_potentiel REAL, bookmaker TEXT,
        resultat TEXT DEFAULT 'EN ATTENTE', gain_net REAL DEFAULT 0,
        enregistre_le TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT, message TEXT, timestamp TEXT
    )""")

    conn.commit()
    conn.close()
    log_activity("system", "Base de données initialisée")


def log_activity(type_, message):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO activity_log (type, message, timestamp) VALUES (?,?,?)",
            (type_, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# Exécuté à l'import du module (gunicorn, etc.)
init_db()
load_subscriptions()


# ─────────────────────────────────────────────
#  DATA COLLECTION
# ─────────────────────────────────────────────

def collecter_matchs_football():
    log_activity("collecte", "Collecte matchs football...")
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0

    for nom, lid in LIGUES_FOOTBALL.items():
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=headers,
                params={
                    "league": lid, "season": SAISON,
                    "from": datetime.now().strftime("%Y-%m-%d"),
                    "to": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"),
                },
                timeout=10,
            )
            data = resp.json()
            for m in data.get("response", []):
                fix = m["fixture"]
                teams = m["teams"]
                goals = m["goals"]
                c.execute("""INSERT OR REPLACE INTO matchs_football
                    (id,ligue,date_match,equipe_domicile,equipe_exterieur,statut,score_dom,score_ext,collecte_le)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (fix["id"], nom, fix["date"], teams["home"]["name"],
                     teams["away"]["name"], fix["status"]["long"],
                     goals.get("home"), goals.get("away"), now))
                total += 1
        except Exception as e:
            log_activity("erreur", f"Matchs {nom}: {e}")

    conn.commit()
    conn.close()
    log_activity("collecte", f"✅ {total} matchs football collectés")


def collecter_stats_equipes():
    log_activity("collecte", "Collecte stats équipes...")
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for nom, lid in LIGUES_FOOTBALL.items():
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/standings",
                headers=headers,
                params={"league": lid, "season": SAISON},
                timeout=10,
            )
            data = resp.json()
            standings = data.get("response", [])
            if not standings:
                continue
            equipes = standings[0]["league"]["standings"][0]
            for eq in equipes:
                a = eq["all"]
                g = a["goals"]
                c.execute("""INSERT INTO stats_equipes
                    (equipe,ligue,saison,matchs_joues,victoires,nuls,defaites,
                     buts_marques,buts_encaisses,forme_recente,collecte_le)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (eq["team"]["name"], nom, SAISON, a["played"], a["win"],
                     a["draw"], a["lose"], g["for"], g["against"],
                     eq.get("form", ""), now))
        except Exception as e:
            log_activity("erreur", f"Stats {nom}: {e}")

    conn.commit()
    conn.close()
    log_activity("collecte", "✅ Stats équipes collectées")


def collecter_cotes():
    log_activity("collecte", "Collecte cotes...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0

    for nom, key in LIGUES_ODDS.items():
        try:
            resp = requests.get(
                f"https://api.the-odds-api.com/v4/sports/{key}/odds/",
                params={
                    "apiKey": ODDS_API_KEY, "regions": "eu",
                    "markets": "h2h", "oddsFormat": "decimal",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                continue
            for match in resp.json():
                dom = match.get("home_team", "?")
                ext = match.get("away_team", "?")
                date = match.get("commence_time", "?")
                for bk in match.get("bookmakers", []):
                    for mkt in bk.get("markets", []):
                        if mkt["key"] != "h2h":
                            continue
                        oc = {o["name"]: o["price"] for o in mkt["outcomes"]}
                        c.execute("""INSERT INTO cotes
                            (sport,ligue,equipe_dom,equipe_ext,date_match,
                             bookmaker,cote_dom,cote_nul,cote_ext,collecte_le)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            ("football", nom, dom, ext, date, bk["title"],
                             oc.get(dom), oc.get("Draw"), oc.get(ext), now))
                        total += 1
        except Exception as e:
            log_activity("erreur", f"Cotes {nom}: {e}")

    conn.commit()
    conn.close()
    log_activity("collecte", f"✅ {total} cotes collectées")


# ─────────────────────────────────────────────
#  ANALYSIS ENGINE
# ─────────────────────────────────────────────

def valeur_attendue(prob, cote):
    return round((prob * cote) - 1, 4)


def kelly_mise(prob, cote, bankroll):
    if cote <= 1 or prob <= 0:
        return 0
    f = (prob * cote - 1) / (cote - 1)
    f = max(0, f)
    mise = bankroll * (f / 2)
    return round(max(MISE_MIN, min(MISE_MAX, mise)), 2)


def get_bankroll():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT resultat, gain_net, mise FROM journal_paris")
    rows = c.fetchall()
    conn.close()
    bankroll = BANKROLL_DEPART
    for r in rows:
        if r["resultat"] == "GAGNÉ":
            bankroll += r["gain_net"]
        elif r["resultat"] == "PERDU":
            bankroll -= r["mise"]
    return bankroll


def calculer_stats_equipe(conn, equipe, ligue, nb=20):
    c = conn.cursor()
    c.execute("""SELECT buts_dom, buts_ext, resultat FROM historique_matchs
        WHERE equipe_domicile=? AND ligue=? ORDER BY date_match DESC LIMIT ?""",
        (equipe, ligue, nb // 2))
    dom = c.fetchall()
    c.execute("""SELECT buts_ext, buts_dom, resultat FROM historique_matchs
        WHERE equipe_exterieur=? AND ligue=? ORDER BY date_match DESC LIMIT ?""",
        (equipe, ligue, nb // 2))
    ext = c.fetchall()

    v = n = d = bm = be = 0
    for row in dom:
        bm += row[0] or 0; be += row[1] or 0
        if row[2] == "H": v += 1
        elif row[2] == "D": n += 1
        elif row[2] == "A": d += 1
    for row in ext:
        bm += row[0] or 0; be += row[1] or 0
        if row[2] == "A": v += 1
        elif row[2] == "D": n += 1
        elif row[2] == "H": d += 1

    total = v + n + d
    if total == 0:
        return None
    return {"taux_vic": v/total, "taux_nul": n/total, "taux_def": d/total, "total": total}


def calculer_h2h(conn, dom, ext, ligue):
    c = conn.cursor()
    c.execute("""SELECT resultat FROM historique_matchs
        WHERE equipe_domicile=? AND equipe_exterieur=? AND ligue=?
        ORDER BY date_match DESC LIMIT 10""", (dom, ext, ligue))
    rows = c.fetchall()
    if not rows:
        return None
    t = len(rows)
    return {
        "vic_dom": sum(1 for r in rows if r[0] == "H") / t,
        "nuls": sum(1 for r in rows if r[0] == "D") / t,
        "vic_ext": sum(1 for r in rows if r[0] == "A") / t,
        "total": t,
    }


def analyser_et_parier():
    log_activity("analyse", "Analyse des matchs en cours...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""SELECT DISTINCT equipe_dom, equipe_ext, ligue,
        date_match, cote_dom, cote_nul, cote_ext, bookmaker
        FROM cotes WHERE date_match >= datetime('now')
        AND cote_dom IS NOT NULL AND cote_nul IS NOT NULL AND cote_ext IS NOT NULL
        AND sport='football' ORDER BY date_match LIMIT 50""")
    matchs = c.fetchall()

    paris_trouves = 0
    bankroll = get_bankroll()

    for m in matchs:
        dom, ext, ligue = m["equipe_dom"], m["equipe_ext"], m["ligue"]
        sd = calculer_stats_equipe(conn, dom, ligue)
        se = calculer_stats_equipe(conn, ext, ligue)
        if not sd or not se:
            continue

        h2h = calculer_h2h(conn, dom, ext, ligue)

        # Probabilities
        pd = sd["taux_vic"] * 0.5 + (1 - se["taux_vic"]) * 0.3
        pe = se["taux_vic"] * 0.5 + (1 - sd["taux_vic"]) * 0.3
        pn = sd["taux_nul"] * 0.5 + se["taux_nul"] * 0.5
        pd *= 1.15; pe *= 0.90

        if h2h and h2h["total"] >= 3:
            pd = pd * 0.7 + h2h["vic_dom"] * 0.3
            pn = pn * 0.7 + h2h["nuls"] * 0.3
            pe = pe * 0.7 + h2h["vic_ext"] * 0.3

        total = pd + pn + pe
        if total == 0:
            continue
        pd /= total; pn /= total; pe /= total

        ev_d = valeur_attendue(pd, m["cote_dom"])
        ev_n = valeur_attendue(pn, m["cote_nul"])
        ev_e = valeur_attendue(pe, m["cote_ext"])

        best_ev = max(ev_d, ev_n, ev_e)
        if best_ev < SEUIL_VALEUR:
            continue

        if best_ev == ev_d:
            tp, cote, prob = "1 (victoire domicile)", m["cote_dom"], pd
        elif best_ev == ev_n:
            tp, cote, prob = "X (match nul)", m["cote_nul"], pn
        else:
            tp, cote, prob = "2 (victoire extérieur)", m["cote_ext"], pe

        mise = kelly_mise(prob, cote, bankroll)
        gain = round(mise * cote - mise, 2)

        # Check duplicate
        c.execute("""SELECT id FROM journal_paris
            WHERE match_nom=? AND date_match=? AND type_pari=?""",
            (f"{dom} vs {ext}", str(m["date_match"])[:10], tp))
        if c.fetchone():
            continue

        c.execute("""INSERT INTO journal_paris
            (sport,ligue,match_nom,date_match,type_pari,probabilite,cote,
             valeur_ev,mise,gain_potentiel,bookmaker,resultat,gain_net,enregistre_le)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("Football", ligue, f"{dom} vs {ext}", str(m["date_match"])[:10],
             tp, f"{prob*100:.1f}%", cote, f"{best_ev*100:.1f}%",
             mise, gain, m["bookmaker"], "EN ATTENTE", 0,
             datetime.now().strftime("%Y-%m-%d %H:%M")))
        paris_trouves += 1

    conn.commit()
    conn.close()

    if paris_trouves > 0:
        log_activity("analyse", f"✅ {paris_trouves} pari(s) à valeur détecté(s)")
        send_push_notification(
            "🎯 Paris IA",
            f"{paris_trouves} nouveau(x) pari(s) à valeur détecté(s) !",
            "/",
        )
    else:
        log_activity("analyse", "Aucun pari à valeur trouvé")


def maj_resultats():
    log_activity("maj", "Mise à jour résultats...")
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    resultats = {}

    for nom, lid in LIGUES_FOOTBALL.items():
        try:
            resp = requests.get(
                "https://v3.football.api-sports.io/fixtures",
                headers=headers,
                params={
                    "league": lid, "season": SAISON,
                    "from": (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                    "to": datetime.now().strftime("%Y-%m-%d"),
                    "status": "FT",
                },
                timeout=10,
            )
            for m in resp.json().get("response", []):
                d = m["teams"]["home"]["name"]
                e = m["teams"]["away"]["name"]
                bd = m["goals"]["home"]
                be = m["goals"]["away"]
                if bd is None or be is None:
                    continue
                res = "H" if bd > be else ("A" if bd < be else "D")
                resultats[f"{d} vs {e}".lower()] = res
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, match_nom, type_pari, cote, mise FROM journal_paris WHERE resultat='EN ATTENTE'")
    rows = c.fetchall()

    nb_maj = 0
    for row in rows:
        pid, match_nom, tp, cote, mise = row
        key = match_nom.lower()
        if key not in resultats:
            continue
        res = resultats[key]
        if "domicile" in tp or tp == "1":
            gagne = res == "H"
        elif "nul" in tp or tp == "X":
            gagne = res == "D"
        elif "extérieur" in tp or tp == "2":
            gagne = res == "A"
        else:
            continue

        if gagne:
            gain_net = round(mise * cote - mise, 2)
            c.execute("UPDATE journal_paris SET resultat='GAGNÉ', gain_net=? WHERE id=?", (gain_net, pid))
        else:
            c.execute("UPDATE journal_paris SET resultat='PERDU', gain_net=0 WHERE id=?", (pid,))
        nb_maj += 1

    conn.commit()
    conn.close()
    if nb_maj > 0:
        log_activity("maj", f"✅ {nb_maj} paris mis à jour")
        send_push_notification("📊 Paris IA", f"{nb_maj} résultat(s) mis à jour !")


# ─────────────────────────────────────────────
#  SCHEDULED TASKS
# ─────────────────────────────────────────────

def tache_collecte():
    try:
        collecter_cotes()
    except Exception as e:
        log_activity("erreur", f"Collecte cotes: {e}")


def tache_complete():
    try:
        collecter_matchs_football()
        collecter_stats_equipes()
        collecter_cotes()
    except Exception as e:
        log_activity("erreur", f"Collecte complète: {e}")


def tache_analyse():
    try:
        analyser_et_parier()
    except Exception as e:
        log_activity("erreur", f"Analyse: {e}")


def tache_maj():
    try:
        maj_resultats()
    except Exception as e:
        log_activity("erreur", f"MAJ résultats: {e}")


# ─────────────────────────────────────────────
#  API ROUTES
# ─────────────────────────────────────────────

@app.route("/api/dashboard")
def api_dashboard():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM journal_paris ORDER BY enregistre_le DESC")
    paris = [dict(r) for r in c.fetchall()]

    total = len(paris)
    gagnes = [p for p in paris if p["resultat"] == "GAGNÉ"]
    perdus = [p for p in paris if p["resultat"] == "PERDU"]
    attente = [p for p in paris if p["resultat"] == "EN ATTENTE"]

    profit = sum(p["gain_net"] for p in gagnes)
    pertes = sum(p["mise"] for p in perdus)
    net = profit - pertes
    bankroll = BANKROLL_DEPART + net
    termines = len(gagnes) + len(perdus)

    # Bankroll history
    historique = [BANKROLL_DEPART]
    running = BANKROLL_DEPART
    for p in sorted(paris, key=lambda x: x["enregistre_le"]):
        if p["resultat"] == "GAGNÉ":
            running += p["gain_net"]
            historique.append(round(running, 2))
        elif p["resultat"] == "PERDU":
            running -= p["mise"]
            historique.append(round(running, 2))

    conn.close()
    return jsonify({
        "bankroll": round(bankroll, 2),
        "net": round(net, 2),
        "roi": round((net / BANKROLL_DEPART) * 100, 2) if BANKROLL_DEPART else 0,
        "taux_vic": round(len(gagnes) / termines * 100, 1) if termines > 0 else 0,
        "total": total,
        "gagnes": len(gagnes),
        "perdus": len(perdus),
        "en_attente": len(attente),
        "historique": historique,
        "paris": paris,
    })


@app.route("/api/activity")
def api_activity():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM activity_log ORDER BY timestamp DESC LIMIT 50")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/forcer-collecte", methods=["POST"])
def api_forcer_collecte():
    tache_complete()
    return jsonify({"status": "ok", "message": "Collecte lancée"})


@app.route("/api/forcer-analyse", methods=["POST"])
def api_forcer_analyse():
    tache_analyse()
    return jsonify({"status": "ok", "message": "Analyse lancée"})


@app.route("/api/forcer-maj", methods=["POST"])
def api_forcer_maj():
    tache_maj()
    return jsonify({"status": "ok", "message": "MAJ résultats lancée"})


@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    sub = request.json
    if sub and sub not in push_subscriptions:
        push_subscriptions.append(sub)
        save_subscriptions()
    return jsonify({"status": "ok"})


@app.route("/api/push/vapid-key")
def vapid_key():
    return jsonify({"publicKey": VAPID_PUBLIC_KEY})


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
    })


# Migrate CSV to DB on first run
@app.route("/api/migrate-csv", methods=["POST"])
def migrate_csv():
    if not os.path.exists(JOURNAL_PATH):
        return jsonify({"status": "no csv"})
    with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        nb = 0
        for row in reader:
            c.execute("""INSERT INTO journal_paris
                (sport,ligue,match_nom,date_match,type_pari,probabilite,cote,
                 valeur_ev,mise,gain_potentiel,bookmaker,resultat,gain_net,enregistre_le)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row.get("sport"), row.get("ligue"), row.get("match"),
                 row.get("date"), row.get("type_pari"), row.get("probabilite"),
                 float(row.get("cote", 0)), row.get("valeur_ev"),
                 float(row.get("mise", 0)), float(row.get("gain_potentiel", 0)),
                 row.get("bookmaker"), row.get("resultat"),
                 float(row.get("gain_net", 0)), row.get("enregistre_le")))
            nb += 1
        conn.commit()
        conn.close()
    return jsonify({"status": "ok", "migrated": nb})


# ─────────────────────────────────────────────
#  PWA FRONTEND (inline HTML — no static files)
# ─────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover">
<title>Paris IA</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0a0f">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Paris IA">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0a0a0f;--surf:#12121a;--surf2:#1a1a24;
  --green:#00e68a;--red:#ff4d6a;--amber:#ffb832;--blue:#7b8fff;
  --text:#f0f0f5;--muted:#7070a0;--border:#252535;
  --nav:64px;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text)}

/* ── LAYOUT ── */
.panel{display:none;height:calc(100dvh - var(--nav));overflow-y:auto;
  padding:12px 14px calc(env(safe-area-inset-bottom,0px) + 14px)}
.panel.active{display:block}

/* ── BOTTOM NAV ── */
.bnav{
  position:fixed;bottom:0;left:0;right:0;
  height:calc(var(--nav) + env(safe-area-inset-bottom,0px));
  background:var(--surf);border-top:1px solid var(--border);
  display:flex;z-index:100;padding-bottom:env(safe-area-inset-bottom,0px)
}
.nbtn{
  flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:3px;background:none;border:none;
  color:var(--muted);cursor:pointer;font-family:'DM Sans',sans-serif;
  font-size:11px;font-weight:500;transition:color .2s
}
.nbtn.active{color:var(--green)}
.nbtn svg{width:22px;height:22px;stroke-width:1.8}

/* ── CARDS ── */
.card{background:var(--surf);border:1px solid var(--border);border-radius:16px;padding:16px;margin-bottom:10px}

/* ── BANKROLL ── */
.br-card{
  background:linear-gradient(135deg,#12121a 0%,#0e1a2a 100%);
  border:1px solid #1e2a3a;border-radius:20px;padding:20px;margin-bottom:10px
}
.br-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:1.2px;margin-bottom:2px}
.br-value{font-size:38px;font-weight:700;font-family:'JetBrains Mono',monospace;line-height:1.1}
.br-net{font-size:13px;font-family:'JetBrains Mono',monospace;margin-top:4px}
.pos{color:var(--green)}.neg{color:var(--red)}

/* ── SPARKLINE ── */
.spark{margin-top:14px;height:56px}
.spark svg{width:100%;height:100%}

/* ── STATS ── */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px}
.scard{background:var(--surf2);border:1px solid var(--border);border-radius:14px;padding:14px 8px;text-align:center}
.sval{font-size:24px;font-weight:700;font-family:'JetBrains Mono',monospace}
.slbl{font-size:11px;color:var(--muted);margin-top:2px}

/* ── SECTION TITLE ── */
.stitle{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:1.2px;margin-bottom:8px;margin-top:6px}

/* ── PAGE HEADER ── */
.phdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-top:6px}
.ptitle{font-size:20px;font-weight:700}
.rbtn{background:none;border:1px solid var(--border);border-radius:10px;
  padding:7px 10px;cursor:pointer;color:var(--muted);font-size:16px;
  transition:color .2s;line-height:1}
.rbtn:hover{color:var(--text)}

/* ── PARIS LIST ── */
.pitem{background:var(--surf);border:1px solid var(--border);border-radius:14px;
  padding:14px;margin-bottom:8px}
.phd{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px;gap:8px}
.pmatch{font-weight:600;font-size:14px;line-height:1.3;flex:1}
.badge{font-size:10px;font-weight:700;padding:3px 8px;border-radius:20px;
  font-family:'JetBrains Mono',monospace;white-space:nowrap;flex-shrink:0}
.bw{background:rgba(0,230,138,.14);color:var(--green)}
.bl{background:rgba(255,77,106,.14);color:var(--red)}
.ba{background:rgba(255,255,255,.07);color:var(--muted)}
.pmeta{font-size:11px;color:var(--muted)}
.pdet{display:flex;gap:10px;margin-top:8px;flex-wrap:wrap}
.pd{font-size:11px;color:var(--muted)}
.pd b{font-family:'JetBrains Mono',monospace;color:var(--text);font-size:12px;font-weight:500}

/* ── FILTER ── */
.frow{display:flex;gap:6px;margin-bottom:10px;overflow-x:auto;padding-bottom:4px}
.frow::-webkit-scrollbar{display:none}
.fbtn{flex-shrink:0;padding:6px 14px;border-radius:20px;border:1px solid var(--border);
  background:none;color:var(--muted);font-family:'DM Sans',sans-serif;
  font-size:12px;font-weight:500;cursor:pointer;transition:all .2s}
.fbtn.active{background:var(--green);color:#000;border-color:var(--green)}

/* ── ACTION BUTTONS ── */
.abtn{
  width:100%;padding:16px 14px;border-radius:14px;border:none;
  font-family:'DM Sans',sans-serif;font-size:15px;font-weight:600;
  cursor:pointer;display:flex;align-items:center;gap:12px;
  transition:opacity .2s,transform .1s;margin-bottom:10px;text-align:left
}
.abtn:active{transform:scale(.97);opacity:.8}
.abtn:disabled{opacity:.5;cursor:not-allowed}
.a-g{background:rgba(0,230,138,.1);color:var(--green);border:1px solid rgba(0,230,138,.2)}
.a-b{background:rgba(123,143,255,.1);color:var(--blue);border:1px solid rgba(123,143,255,.2)}
.a-a{background:rgba(255,184,50,.1);color:var(--amber);border:1px solid rgba(255,184,50,.2)}
.aico{font-size:20px;width:28px;text-align:center}
.albl{flex:1}.asub{font-size:12px;font-weight:400;opacity:.7;display:block;margin-top:1px}
.achev{font-size:18px;opacity:.5}

/* ── ACTIVITY ── */
.logitem{padding:9px 0;border-bottom:1px solid var(--border)}
.logitem:last-child{border-bottom:none}
.logmsg{font-size:13px;line-height:1.4}
.logtime{font-size:10px;color:var(--muted);font-family:'JetBrains Mono',monospace;margin-top:2px}

/* ── EXTRA STATS ROW ── */
.xrow{display:flex;justify-content:space-between;padding:2px 0}
.xitem{text-align:center}
.xval{font-size:20px;font-weight:700;font-family:'JetBrains Mono',monospace}
.xlbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px}

/* ── SKELETON ── */
.sk{background:linear-gradient(90deg,var(--surf) 25%,var(--surf2) 50%,var(--surf) 75%);
  background-size:200% 100%;animation:sh 1.5s infinite;border-radius:8px}
@keyframes sh{0%{background-position:-200% 0}100%{background-position:200% 0}}

/* ── TOAST ── */
.toast{
  position:fixed;bottom:calc(var(--nav) + 12px);left:50%;
  transform:translateX(-50%) translateY(12px);
  background:var(--surf2);border:1px solid var(--border);border-radius:10px;
  padding:10px 18px;font-size:13px;font-weight:500;
  opacity:0;transition:all .3s;z-index:200;white-space:nowrap;pointer-events:none
}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}

/* ── SPIN ── */
@keyframes spin{to{transform:rotate(360deg)}}
.spinning{display:inline-block;animation:spin .8s linear infinite}
</style>
</head>
<body>

<!-- ═══════════ DASHBOARD ═══════════ -->
<div id="tab-dashboard" class="panel active">
  <div class="phdr">
    <span class="ptitle">Dashboard</span>
    <button class="rbtn" onclick="loadAll(this)" title="Rafraichir">&#8635;</button>
  </div>

  <div class="br-card">
    <div class="br-label">Bankroll</div>
    <div class="br-value pos" id="br-val">— €</div>
    <div class="br-net" id="br-net">—</div>
    <div class="spark"><svg id="sparkline" viewBox="0 0 300 56" preserveAspectRatio="none"></svg></div>
  </div>

  <div class="stats">
    <div class="scard">
      <div class="sval pos" id="s-taux">—</div>
      <div class="slbl">Réussite</div>
    </div>
    <div class="scard">
      <div class="sval pos" id="s-gagnes">—</div>
      <div class="slbl">Gagnés</div>
    </div>
    <div class="scard">
      <div class="sval neg" id="s-perdus">—</div>
      <div class="slbl">Perdus</div>
    </div>
  </div>

  <div class="card">
    <div class="xrow">
      <div class="xitem">
        <div class="xval" id="s-roi">—</div>
        <div class="xlbl">ROI</div>
      </div>
      <div class="xitem">
        <div class="xval" style="color:var(--amber)" id="s-attente">—</div>
        <div class="xlbl">En attente</div>
      </div>
      <div class="xitem">
        <div class="xval" id="s-total">—</div>
        <div class="xlbl">Total paris</div>
      </div>
    </div>
  </div>

  <div class="stitle">Activité récente</div>
  <div class="card" id="act-recent">
    <div class="sk" style="height:13px;margin-bottom:8px;width:68%"></div>
    <div class="sk" style="height:13px;margin-bottom:8px;width:45%"></div>
    <div class="sk" style="height:13px;width:75%"></div>
  </div>
</div>

<!-- ═══════════ PARIS ═══════════ -->
<div id="tab-paris" class="panel">
  <div class="phdr">
    <span class="ptitle">Paris</span>
    <button class="rbtn" onclick="loadAll(this)">&#8635;</button>
  </div>
  <div class="frow">
    <button class="fbtn active" onclick="filterParis('all',this)">Tous</button>
    <button class="fbtn" onclick="filterParis('EN ATTENTE',this)">En attente</button>
    <button class="fbtn" onclick="filterParis('GAGN\\u00c9',this)">Gagnés</button>
    <button class="fbtn" onclick="filterParis('PERDU',this)">Perdus</button>
  </div>
  <div id="paris-list">
    <div class="sk" style="height:90px;margin-bottom:8px;border-radius:14px"></div>
    <div class="sk" style="height:90px;margin-bottom:8px;border-radius:14px"></div>
    <div class="sk" style="height:90px;border-radius:14px"></div>
  </div>
</div>

<!-- ═══════════ ACTIONS ═══════════ -->
<div id="tab-actions" class="panel">
  <div class="phdr"><span class="ptitle">Actions</span></div>

  <button class="abtn a-g" onclick="doAction('collecte',this)">
    <span class="aico">&#128225;</span>
    <span class="albl">Forcer collecte<span class="asub">Matchs, stats &amp; cotes</span></span>
    <span class="achev">&#8250;</span>
  </button>

  <button class="abtn a-b" onclick="doAction('analyse',this)">
    <span class="aico">&#129504;</span>
    <span class="albl">Lancer analyse<span class="asub">Détection paris à valeur</span></span>
    <span class="achev">&#8250;</span>
  </button>

  <button class="abtn a-a" onclick="doAction('maj',this)">
    <span class="aico">&#128260;</span>
    <span class="albl">Maj résultats<span class="asub">Mise à jour gains / pertes</span></span>
    <span class="achev">&#8250;</span>
  </button>

  <div class="stitle" style="margin-top:6px">Journal d'activité</div>
  <div class="card" id="act-full">
    <div class="sk" style="height:13px;margin-bottom:8px;width:68%"></div>
    <div class="sk" style="height:13px;margin-bottom:8px;width:45%"></div>
    <div class="sk" style="height:13px;width:75%"></div>
  </div>
</div>

<!-- ═══════════ BOTTOM NAV ═══════════ -->
<nav class="bnav">
  <button class="nbtn active" id="nav-dashboard" onclick="goTab('dashboard')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
      <rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>
    </svg>
    Dashboard
  </button>
  <button class="nbtn" id="nav-paris" onclick="goTab('paris')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
    </svg>
    Paris
  </button>
  <button class="nbtn" id="nav-actions" onclick="goTab('actions')">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.07 4.93A10 10 0 0 0 4.93 19.07M4.93 4.93A10 10 0 0 1 19.07 19.07"/>
    </svg>
    Actions
  </button>
</nav>

<div class="toast" id="toast"></div>

<script>
'use strict';
let allParis = [], curFilter = 'all';

/* ── TAB SWITCH ── */
function goTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nbtn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('nav-' + name).classList.add('active');
}

/* ── TOAST ── */
function toast(msg, color) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.color = color || 'var(--text)';
  t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.classList.remove('show'), 2800);
}

/* ── FORMAT ── */
function eur(v) {
  return v.toLocaleString('fr-FR', {style:'currency',currency:'EUR',maximumFractionDigits:2});
}

/* ── SPARKLINE ── */
function sparkline(data) {
  if (!data || data.length < 2) return;
  const W = 300, H = 56, pad = 4;
  const mn = Math.min(...data), mx = Math.max(...data), rng = mx - mn || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * W,
    H - pad - ((v - mn) / rng) * (H - pad * 2)
  ]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('');
  const area = line + ' L' + pts[pts.length-1][0] + ',' + H + ' L0,' + H + ' Z';
  const up = data[data.length-1] >= data[0];
  const col = up ? '#00e68a' : '#ff4d6a';
  const last = pts[pts.length-1];
  document.getElementById('sparkline').innerHTML =
    '<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">' +
    '<stop offset="0%" stop-color="' + col + '" stop-opacity=".25"/>' +
    '<stop offset="100%" stop-color="' + col + '" stop-opacity="0"/></linearGradient></defs>' +
    '<path d="' + area + '" fill="url(#sg)"/>' +
    '<path d="' + line + '" fill="none" stroke="' + col + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<circle cx="' + last[0] + '" cy="' + last[1] + '" r="3.5" fill="' + col + '"/>';
}

/* ── LOAD DASHBOARD ── */
async function loadDashboard() {
  const r = await fetch('/api/dashboard');
  const d = await r.json();
  allParis = d.paris || [];

  const br = d.bankroll;
  const brEl = document.getElementById('br-val');
  brEl.textContent = eur(br);
  brEl.className = 'br-value ' + (br >= 1000 ? 'pos' : 'neg');

  const net = d.net;
  const netEl = document.getElementById('br-net');
  netEl.textContent = (net >= 0 ? '+' : '') + eur(net) + ' net  ·  ROI ' + (d.roi >= 0 ? '+' : '') + d.roi + '%';
  netEl.className = 'br-net ' + (net >= 0 ? 'pos' : 'neg');

  document.getElementById('s-taux').textContent = d.taux_vic + '%';
  document.getElementById('s-gagnes').textContent = d.gagnes;
  document.getElementById('s-perdus').textContent = d.perdus;

  const roi = d.roi;
  const roiEl = document.getElementById('s-roi');
  roiEl.textContent = (roi >= 0 ? '+' : '') + roi + '%';
  roiEl.style.color = roi >= 0 ? 'var(--green)' : 'var(--red)';

  document.getElementById('s-attente').textContent = d.en_attente;
  document.getElementById('s-total').textContent = d.total;

  sparkline(d.historique);
  renderParis(allParis, curFilter);
}

/* ── LOAD ACTIVITY ── */
async function loadActivity() {
  const r = await fetch('/api/activity');
  const data = await r.json();

  const row = items => items.map(a =>
    '<div class="logitem"><div class="logmsg">' + esc(a.message) + '</div>' +
    '<div class="logtime">' + a.timestamp + '</div></div>'
  ).join('') || '<div style="color:var(--muted);font-size:13px">Aucune activité</div>';

  document.getElementById('act-recent').innerHTML = row(data.slice(0, 5));
  document.getElementById('act-full').innerHTML = row(data);
}

/* ── RENDER PARIS ── */
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function filterParis(filter, btn) {
  curFilter = filter;
  document.querySelectorAll('.fbtn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderParis(allParis, filter);
}

function renderParis(paris, filter) {
  const list = filter === 'all' ? paris : paris.filter(p => p.resultat === filter);
  const el = document.getElementById('paris-list');
  if (!list.length) {
    el.innerHTML = '<div class="card" style="text-align:center;color:var(--muted);padding:28px 16px;font-size:14px">Aucun pari</div>';
    return;
  }
  el.innerHTML = list.map(p => {
    const isW = p.resultat === 'GAGN\\u00c9', isL = p.resultat === 'PERDU';
    const bc = isW ? 'bw' : isL ? 'bl' : 'ba';
    const bt = isW ? '&#10003; GAGN\\u00c9' : isL ? '&#10007; PERDU' : '&#9203; ATTENTE';
    const gain = isW
      ? '<span style="color:var(--green);font-weight:600">+' + (p.gain_net||0).toFixed(2) + ' &#8364;</span>'
      : isL
      ? '<span style="color:var(--red);font-weight:600">-' + (p.mise||0).toFixed(2) + ' &#8364;</span>'
      : '<span style="color:var(--muted)">' + (p.gain_potentiel||0).toFixed(2) + ' &#8364; pot.</span>';
    return '<div class="pitem">' +
      '<div class="phd"><div class="pmatch">' + esc(p.match_nom) + '</div>' +
      '<span class="badge ' + bc + '">' + bt + '</span></div>' +
      '<div class="pmeta">' + esc(p.ligue||'') + ' &middot; ' + esc(p.date_match||'') + '</div>' +
      '<div class="pdet">' +
      '<div class="pd">Type <b>' + esc(p.type_pari||'') + '</b></div>' +
      '<div class="pd">Cote <b>' + (p.cote||0) + '</b></div>' +
      '<div class="pd">Mise <b>' + (p.mise||0) + ' &#8364;</b></div>' +
      '<div class="pd">' + gain + '</div>' +
      '</div></div>';
  }).join('');
}

/* ── ACTIONS ── */
async function doAction(action, btn) {
  const urls = {collecte:'/api/forcer-collecte',analyse:'/api/forcer-analyse',maj:'/api/forcer-maj'};
  const labels = {collecte:'Collecte',analyse:'Analyse',maj:'Mise \\u00e0 jour'};
  btn.disabled = true;
  const chev = btn.querySelector('.achev');
  if (chev) chev.innerHTML = '<span class="spinning">&#8635;</span>';
  toast(labels[action] + ' en cours\\u2026');
  try {
    const r = await fetch(urls[action], {method:'POST'});
    const d = await r.json();
    toast('\\u2713 ' + (d.message || labels[action] + ' termin\\u00e9e'), 'var(--green)');
    await loadAll();
  } catch(e) {
    toast('Erreur', 'var(--red)');
  } finally {
    btn.disabled = false;
    if (chev) chev.textContent = '\\u203a';
  }
}

/* ── REFRESH BTN ── */
async function loadAll(btn) {
  if (btn) { btn.classList.add('spinning'); }
  try { await Promise.all([loadDashboard(), loadActivity()]); }
  catch(e) { toast('Erreur de chargement', 'var(--red)'); }
  finally { if (btn) btn.classList.remove('spinning'); }
}

/* ── SERVICE WORKER ── */
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js').catch(() => {});
}

/* ── INIT ── */
loadAll();
</script>
</body>
</html>"""


@app.route("/")
def serve_frontend():
    return _HTML


@app.route("/manifest.json")
def pwa_manifest():
    return jsonify({
        "name": "Paris IA",
        "short_name": "Paris IA",
        "description": "Intelligence artificielle pour paris sportifs",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#0a0a0f",
        "orientation": "portrait-primary",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


@app.route("/icon-192.png")
def icon192():
    return send_from_directory("../frontend/public", "icon-192.png")


@app.route("/icon-512.png")
def icon512():
    return send_from_directory("../frontend/public", "icon-512.png")


@app.route("/sw.js")
def service_worker():
    sw = """
const CACHE = 'paris-ia-v1';

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.add('/')));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith(
    caches.match(e.request).then(cached => {
      const fresh = fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      });
      return cached || fresh;
    })
  );
});

self.addEventListener('push', e => {
  if (!e.data) return;
  const d = e.data.json();
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body,
    icon: '/icon-192.png',
    data: { url: d.url || '/' }
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url));
});
"""
    return Response(sw, mimetype="application/javascript")


# ─────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    load_subscriptions()

    scheduler = BackgroundScheduler()
    scheduler.add_job(tache_collecte, "interval", hours=1)
    scheduler.add_job(tache_complete, "cron", hour=7)
    scheduler.add_job(tache_analyse, "cron", hour=8)
    scheduler.add_job(tache_analyse, "cron", hour=20)
    scheduler.add_job(tache_maj, "cron", hour=23)
    scheduler.start()

    print("🚀 Paris IA — Serveur démarré")
    print(f"⏰ Scheduler actif (collecte/analyse/maj)")

    # Initial run
    tache_complete()
    tache_analyse()

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
