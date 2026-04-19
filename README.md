# 🚀 Paris IA — Guide de déploiement

## Architecture

```
paris-ia-app/
├── backend/
│   ├── app.py              ← Serveur Flask + API + Scheduler
│   ├── requirements.txt
│   ├── gunicorn.conf.py
│   └── .env.example
├── frontend/
│   ├── public/
│   │   ├── index.html
│   │   ├── manifest.json   ← Config PWA (installable)
│   │   ├── sw.js           ← Service Worker (push + offline)
│   │   └── icon-*.png
│   ├── src/
│   │   ├── index.js
│   │   └── App.js          ← Dashboard React mobile-first
│   └── package.json
├── render.yaml             ← Config Render.com
└── README.md
```

## Étape 1 : Générer les clés VAPID (notifications push)

```bash
npx web-push generate-vapid-keys
```

Ça te donne deux clés. Note-les, tu en auras besoin.

## Étape 2 : Créer le repo GitHub

```bash
cd paris-ia-app
git init
git add .
git commit -m "Paris IA v1"
git remote add origin https://github.com/TON-USER/paris-ia.git
git push -u origin main
```

## Étape 3 : Déployer sur Render.com (gratuit)

1. Va sur https://render.com et connecte-toi avec GitHub
2. Clique **New > Web Service**
3. Sélectionne ton repo `paris-ia`
4. Render détecte automatiquement le `render.yaml`
5. Ajoute les **variables d'environnement** :

| Variable | Valeur |
|----------|--------|
| `API_FOOTBALL_KEY` | Ta clé API-Football |
| `ODDS_API_KEY` | Ta clé The Odds API |
| `VAPID_PUBLIC_KEY` | Clé publique (étape 1) |
| `VAPID_PRIVATE_KEY` | Clé privée (étape 1) |
| `VAPID_EMAIL` | `mailto:ton-email@example.com` |

6. Clique **Deploy** → attends ~3 minutes

## Étape 4 : Installer sur ton téléphone

### iPhone (Safari)
1. Ouvre `https://ton-app.onrender.com` dans Safari
2. Appuie sur l'icône **Partage** (carré avec flèche)
3. Choisis **"Sur l'écran d'accueil"**
4. L'app apparaît comme une vraie app !

### Android (Chrome)
1. Ouvre l'URL dans Chrome
2. Chrome proposera automatiquement **"Installer l'application"**
3. Sinon : menu ⋮ > **"Installer l'application"**

## Étape 5 : Activer les notifications

1. Ouvre l'app sur ton téléphone
2. Va dans l'onglet **Actions** (⚙️)
3. Active le toggle **Notifications push**
4. Accepte la permission du navigateur
5. Tu recevras une alerte à chaque nouveau pari détecté !

---

## Fonctionnement

Le serveur tourne 24/7 sur Render et fait tout automatiquement :

| Tâche | Fréquence |
|-------|-----------|
| Collecte cotes | Toutes les heures |
| Collecte complète (matchs + stats) | Tous les jours à 7h |
| Analyse + détection paris | Tous les jours à 8h et 20h |
| Mise à jour résultats | Tous les jours à 23h |

Tu peux aussi forcer une tâche manuellement depuis l'onglet **Actions**.

## ⚠️ Limites du plan gratuit Render

- Le service **s'endort après 15 min d'inactivité** (se réveille au prochain accès, ~30s)
- Pour garder le scheduler actif 24/7, tu peux :
  - Utiliser un service comme **UptimeRobot** (gratuit) qui ping ton URL toutes les 14 min
  - Ou passer au plan Starter à $7/mois

## Développement local

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # Remplis tes clés
python app.py

# Frontend (dans un autre terminal)
cd frontend
npm install
npm start
```

Le frontend local se connecte à `http://localhost:5000`.

---

**C'est tout !** Tu as maintenant une app mobile dédiée accessible depuis ton téléphone, avec des notifications push quand un pari à valeur est détecté. 🎯
