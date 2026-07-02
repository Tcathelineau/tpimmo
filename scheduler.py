"""Orchestration planifiée des collectes (DVF, cadastre, loyers) via APScheduler.

Processus Python à laisser tourner en continu (pas de cron externe nécessaire).
"""

import logging

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler

from database import init_db
from collectors import dvf_collector, cadastre_collector, loyers_collector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def charger_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def job_dvf(config: dict):
    logger.info("Démarrage du job DVF")
    dvf_collector.collecter(config)


def job_cadastre(config: dict):
    logger.info("Démarrage du job cadastre")
    cadastre_collector.collecter(config)


def job_loyers(config: dict):
    logger.info("Démarrage du job loyers de référence")
    loyers_collector.collecter(config)


def main():
    init_db()
    config = charger_config()

    scheduler = BlockingScheduler(timezone="Europe/Paris")
    sched_cfg = config["scheduler"]

    scheduler.add_job(
        job_dvf, "interval", hours=sched_cfg["dvf_interval_hours"], args=[config],
        id="job_dvf",
    )
    scheduler.add_job(
        job_cadastre, "interval", hours=sched_cfg["cadastre_interval_hours"], args=[config],
        id="job_cadastre",
    )
    scheduler.add_job(
        job_loyers, "interval", hours=sched_cfg.get("loyers_interval_hours", sched_cfg["cadastre_interval_hours"]),
        args=[config], id="job_loyers",
    )

    logger.info("Scheduler démarré. Ctrl+C pour arrêter.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Arrêt du scheduler")


if __name__ == "__main__":
    main()
