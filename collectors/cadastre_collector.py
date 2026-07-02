"""Collecte des géométries de parcelles cadastrales (cadastre.data.gouv.fr)."""

import gzip
import io
import json
import logging

import requests

from database import get_connection, insert_parcelle
from geo_utils import resoudre_codes_postaux, codes_postaux_vers_communes

logger = logging.getLogger(__name__)

CADASTRE_URL_TEMPLATE = (
    "https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/"
    "{code_dep}/{code_insee}/cadastre-{code_insee}-parcelles.json.gz"
)


def telecharger_parcelles(code_dep: str, code_insee: str) -> dict:
    url = CADASTRE_URL_TEMPLATE.format(code_dep=code_dep, code_insee=code_insee)
    logger.info("Téléchargement cadastre : %s", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as f:
        return json.load(f)


def collecter(config: dict):
    codes_postaux = resoudre_codes_postaux(config["zone"])
    communes = codes_postaux_vers_communes(tuple(codes_postaux))

    total_inserees = 0
    with get_connection() as conn:
        for commune in communes:
            try:
                geojson = telecharger_parcelles(commune["code_dep"], commune["code_insee"])
            except requests.HTTPError as exc:
                logger.warning(
                    "Cadastre indisponible pour %s : %s", commune["code_insee"], exc
                )
                continue

            for feature in geojson.get("features", []):
                props = feature.get("properties", {})
                insert_parcelle(
                    conn,
                    {
                        "code_postal": commune["code_postal"],
                        "id_parcelle": props.get("id"),
                        "contenance": props.get("contenance"),
                        "commune": commune["nom"],
                        "geometry": json.dumps(feature.get("geometry")),
                    },
                )
                total_inserees += 1

    logger.info("Collecte cadastre terminée : %s parcelles traitées", total_inserees)
    return total_inserees


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    collecter(cfg)
