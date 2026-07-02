"""Collecte des loyers de référence officiels : "Carte des Loyers" (ANIL / data.gouv.fr).

Utilisé à la place d'un scraping d'agences de location, jugé trop fragile (cf. les
échecs constatés sur PAP/LeBonCoin : 403/404/timeout dès les premières requêtes réelles).
Ce jeu de données est une estimation statistique du loyer moyen au m² par commune et
type de bien, calculée par le ministère à partir des annonces LeBonCoin/SeLoger.

Limite à garder en tête : ce n'est PAS une annonce individuelle mais un modèle de
prédiction (colonnes `type_prediction` et `nb_observations` indiquent sa fiabilité :
"commune" avec beaucoup d'observations = fiable, "maille" avec peu d'observations =
estimation régionale de repli, moins précise, fréquente en zone rurale).
"""

import csv
import io
import logging

import requests

from database import get_connection, insert_loyer_reference
from geo_utils import resoudre_codes_postaux, codes_postaux_vers_communes

logger = logging.getLogger(__name__)

ANNEE_REFERENCE = 2025

# URLs stables des ressources data.gouv.fr (jeu de données "Carte des loyers" 2025).
# Vérifiées manuellement le 2026-07-02 : https://www.data.gouv.fr/datasets/carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025
URLS_PAR_TYPE = {
    "Appartement": "https://www.data.gouv.fr/api/1/datasets/r/55b34088-0964-415f-9df7-d87dd98a09be",
    "Maison": "https://www.data.gouv.fr/api/1/datasets/r/129f764d-b613-44e4-952c-5ff50a8c9b73",
}


def _to_float(valeur: str) -> float | None:
    if not valeur:
        return None
    try:
        return float(valeur.replace(",", "."))
    except ValueError:
        return None


def _to_int(valeur: str) -> int | None:
    try:
        return int(float(valeur.replace(",", ".")))
    except (ValueError, AttributeError):
        return None


def telecharger_loyers(type_bien: str) -> list[dict]:
    url = URLS_PAR_TYPE[type_bien]
    logger.info("Téléchargement loyers de référence (%s) : %s", type_bien, url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    # Fichier encodé en latin-1 (accents), séparateur ';', décimales avec virgule.
    texte = resp.content.decode("latin-1")
    return list(csv.DictReader(io.StringIO(texte), delimiter=";"))


def collecter(config: dict) -> int:
    codes_postaux = resoudre_codes_postaux(config["zone"])
    if not codes_postaux:
        logger.warning("Aucun code postal résolu, collecte des loyers annulée")
        return 0

    communes = codes_postaux_vers_communes(tuple(codes_postaux))
    code_postal_par_insee = {c["code_insee"]: c["code_postal"] for c in communes}
    nom_par_insee = {c["code_insee"]: c["nom"] for c in communes}

    types_bien = [t for t in config["criteres"].get("types_bien", []) if t in URLS_PAR_TYPE]
    if not types_bien:
        types_bien = list(URLS_PAR_TYPE)

    total = 0
    with get_connection() as conn:
        for type_bien in types_bien:
            try:
                lignes = telecharger_loyers(type_bien)
            except requests.RequestException:
                logger.exception("Échec du téléchargement des loyers pour %s", type_bien)
                continue

            for ligne in lignes:
                code_insee = ligne.get("INSEE_C")
                if code_insee not in code_postal_par_insee:
                    continue
                insert_loyer_reference(
                    conn,
                    {
                        "annee": ANNEE_REFERENCE,
                        "code_insee": code_insee,
                        "commune": nom_par_insee.get(code_insee, ligne.get("LIBGEO")),
                        "code_postal": code_postal_par_insee[code_insee],
                        "type_bien": type_bien,
                        "loyer_m2": _to_float(ligne.get("loypredm2")),
                        "loyer_m2_min": _to_float(ligne.get("lwr.IPm2")),
                        "loyer_m2_max": _to_float(ligne.get("upr.IPm2")),
                        "type_prediction": ligne.get("TYPPRED"),
                        "nb_observations": _to_int(ligne.get("nbobs_com")),
                    },
                )
                total += 1

    logger.info("Collecte loyers de référence terminée : %s lignes insérées", total)
    return total


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    collecter(cfg)
