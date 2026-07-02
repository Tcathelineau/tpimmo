"""Point d'entrée CLI de l'application de veille immobilière."""

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import yaml

from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent


def charger_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def refresh_toutes_donnees(config: dict):
    from collectors import dvf_collector, cadastre_collector, loyers_collector

    logger.info("Rafraîchissement DVF...")
    dvf_collector.collecter(config)

    logger.info("Rafraîchissement cadastre...")
    cadastre_collector.collecter(config)

    logger.info("Rafraîchissement loyers de référence...")
    loyers_collector.collecter(config)


def lancer_dashboard():
    dashboard_path = ROOT_DIR / "dashboard" / "app.py"
    logger.info("Lancement du dashboard Streamlit...")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


def main():
    parser = argparse.ArgumentParser(description="Veille immobilière locale")
    sous_commandes = parser.add_subparsers(dest="commande", required=True)

    sous_commandes.add_parser("init-db", help="Initialise la base SQLite")
    sous_commandes.add_parser("dvf", help="Lance une collecte DVF ponctuelle")
    sous_commandes.add_parser("cadastre", help="Lance une collecte cadastre ponctuelle")
    sous_commandes.add_parser("loyers", help="Lance une collecte des loyers de référence (Carte des Loyers)")
    sous_commandes.add_parser("scheduler", help="Démarre l'orchestration planifiée en continu")
    sous_commandes.add_parser("dashboard", help="Affiche la commande pour lancer le dashboard Streamlit")
    sous_commandes.add_parser(
        "start",
        help="Rafraîchit toutes les données (DVF, cadastre, loyers) puis lance le dashboard Streamlit",
    )

    args = parser.parse_args()
    init_db()
    config = charger_config()

    if args.commande == "init-db":
        logger.info("Base SQLite initialisée (data/veille.db)")

    elif args.commande == "dvf":
        from collectors import dvf_collector
        dvf_collector.collecter(config)

    elif args.commande == "cadastre":
        from collectors import cadastre_collector
        cadastre_collector.collecter(config)

    elif args.commande == "loyers":
        from collectors import loyers_collector
        loyers_collector.collecter(config)

    elif args.commande == "scheduler":
        import scheduler
        scheduler.main()

    elif args.commande == "dashboard":
        print("Lancez : streamlit run dashboard/app.py")

    elif args.commande == "start":
        refresh_toutes_donnees(config)
        lancer_dashboard()


if __name__ == "__main__":
    main()
