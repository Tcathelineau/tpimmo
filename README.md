# Analyse Immobilière

Application locale d'analyse immobilière fondée exclusivement sur les **données publiques**
(data.gouv.fr) : historique des ventes réelles (DVF), loyers de référence (Carte des Loyers,
ANIL) et cadastre, sur une zone définie par communes ou codes postaux.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configurez `config.yaml` :
- `zone.villes` : liste de noms de villes/communes à étudier (ex. `["Barfleur", "Réville"]`),
  résolue automatiquement en codes postaux via l'API `geo.api.gouv.fr` (`geo_utils.py`). Les
  villes à arrondissements (Paris, Lyon, Marseille) renvoient tous leurs codes postaux en un
  seul nom.
- `zone.codes_postaux` : codes postaux additionnels, en complément de `zone.villes`
- `criteres.types_bien` : types de bien pour les loyers de référence (Appartement, Maison)
- `dvf.annees` : années de transactions à collecter

## Utilisation

```bash
python main.py start        # rafraîchit toutes les données puis lance le dashboard
```

Ou commande par commande :

```bash
python main.py init-db      # crée data/veille.db
python main.py dvf          # collecte ponctuelle DVF (ventes réelles)
python main.py cadastre     # collecte ponctuelle cadastre (parcelles)
python main.py loyers       # collecte des loyers de référence (Carte des Loyers ANIL)
python main.py scheduler    # rafraîchissement automatique hebdomadaire (APScheduler)
streamlit run dashboard/app.py   # dashboard seul, sans rafraîchir
```

## Dashboard

- **📊 Ventes DVF** : distribution et évolution du prix au m², tableau détaillé avec lien
  Google Maps par vente
- **🗺️ Carte** : ventes géolocalisées, colorées par prix au m²
- **💡 Analyse investissement** :
  - rendement locatif brut par commune et type de bien (prix DVF × loyers ANIL)
  - calculateur de financement : apport, montant emprunté, taux, mensualité → surface
    achetable, loyer estimé, cash-flow, rendements, durée et coût total du crédit

Les filtres (codes postaux, **communes**, prix, surface, pièces, type de bien) s'appliquent
à tous les onglets. Le filtre communes permet d'isoler précisément les communes étudiées
quand un code postal rural en couvre plusieurs.

## Déploiement (Streamlit Community Cloud, gratuit)

Le dépôt GitHub associé (`Tcathelineau/tpimmo`) est **privé**. Streamlit Community Cloud
ne propose plus d'app privée gratuite (ça passe désormais par un essai Snowflake payant) :
le déploiement gratuit se fait via **"Deploy a public app from GitHub"**, ce qui rend l'URL
accessible sans authentification native. Un verrou par mot de passe est donc intégré dans
l'app elle-même :

1. Sur [share.streamlit.io](https://share.streamlit.io), connectez-vous avec GitHub puis
   **"New app" → "Deploy a public app from GitHub"**, dépôt `Tcathelineau/tpimmo`, branche
   `master`, fichier `dashboard/app.py`.
2. Dans les réglages de l'app déployée → **Secrets**, collez le contenu de
   `.streamlit/secrets.toml.example` en remplaçant la valeur par un vrai mot de passe.
3. Partagez l'URL et le mot de passe aux personnes concernées.

Sans mot de passe configuré (cas par défaut en local), le dashboard reste en accès libre —
pratique pour `streamlit run dashboard/app.py` sur votre machine.

Le workflow `.github/workflows/refresh-data.yml` relance `dvf`/`cadastre`/`loyers` chaque
lundi et repousse `data/veille.db` si elle change, ce qui redéploie automatiquement l'app.
Il peut aussi être déclenché manuellement depuis l'onglet **Actions** du dépôt. À noter :
GitHub désactive les workflows planifiés après 60 jours sans activité sur le dépôt (un push
ou un déclenchement manuel suffit à le réactiver).

## Structure

```
TPImmo/
├── data/veille.db                 # SQLite (créée automatiquement)
├── collectors/
│   ├── dvf_collector.py           # ventes réelles (DVF, data.gouv.fr)
│   ├── cadastre_collector.py      # parcelles (cadastre.data.gouv.fr)
│   └── loyers_collector.py        # loyers de référence (Carte des Loyers, ANIL)
├── dashboard/app.py               # dashboard Streamlit
├── scheduler.py                   # orchestration planifiée (APScheduler)
├── database.py                    # init + CRUD SQLite
├── geo_utils.py                   # résolution villes -> codes postaux / communes INSEE
├── main.py                        # point d'entrée CLI
├── config.yaml
├── requirements.txt
└── README.md
```

## Sources de données

| Donnée | Source | Fréquence de mise à jour |
|---|---|---|
| Ventes réelles | [DVF géolocalisées](https://files.data.gouv.fr/geo-dvf/) | semestrielle (avril/octobre) |
| Loyers de référence | [Carte des Loyers](https://www.data.gouv.fr/datasets/carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025) (ANIL/SDES) | annuelle |
| Parcelles | [Cadastre Etalab](https://cadastre.data.gouv.fr/) | trimestrielle |
| Communes | [geo.api.gouv.fr](https://geo.api.gouv.fr/) | temps réel |

## Notes

- Les loyers de la Carte des Loyers sont des **estimations statistiques** communales
  (modèle du ministère) ; en zone rurale ils reposent souvent sur une maille régionale
  (voir la colonne Fiabilité dans le dashboard). Les rendements calculés sont bruts :
  hors charges, taxe foncière, vacance locative, assurance emprunteur et fiscalité.
- La géolocalisation DVF dépend de la qualité du dataset `geo-dvf` (certaines lignes
  n'ont pas de coordonnées).
- Historique : une partie scraping d'annonces (LeBonCoin, PAP) et notifications
  (email/Telegram) a existé puis a été retirée le 2026-07-02 au profit d'une approche
  100 % données publiques, plus fiable (voir l'historique git le cas échéant).
