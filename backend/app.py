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
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

load_dotenv()

app = Flask(__name__, static_folder="../frontend/build", static_url_path="")
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


# Serve React frontend
@app.route("/")
@app.route("/<path:path>")
def serve_frontend(path=""):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


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
