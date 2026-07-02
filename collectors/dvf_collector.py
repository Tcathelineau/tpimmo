"""Collecte des transactions immobilières réelles (DVF - data.gouv.fr)."""

import gzip
import io
import logging

import pandas as pd
import requests

from database import get_connection, insert_vente_dvf
from geo_utils import resoudre_codes_postaux

logger = logging.getLogger(__name__)

DVF_URL_TEMPLATE = (
    "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/departements/{code_dep}.csv.gz"
)

COLONNES_UTILES = [
    "id_mutation",
    "date_mutation",
    "code_postal",
    "nom_commune",
    "adresse_nom_voie",
    "adresse_numero",
    "type_local",
    "surface_reelle_bati",
    "nombre_pieces_principales",
    "valeur_fonciere",
    "longitude",
    "latitude",
]


def code_postal_vers_departement(code_postal: str) -> str:
    """Déduit le code département depuis un code postal (cas simple métropole/Corse)."""
    if code_postal.startswith("97") or code_postal.startswith("98"):
        return code_postal[:3]
    if code_postal.startswith("20"):
        # Corse : 2A / 2B ne sont pas déductibles du seul code postal de façon fiable,
        # on tente 2A par défaut, à ajuster si besoin.
        return "2A"
    return code_postal[:2]


def telecharger_dvf(annee: int, code_dep: str) -> pd.DataFrame:
    url = DVF_URL_TEMPLATE.format(annee=annee, code_dep=code_dep)
    logger.info("Téléchargement DVF : %s", url)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with gzip.open(io.BytesIO(resp.content), "rt", encoding="utf-8") as f:
        df = pd.read_csv(f, usecols=lambda c: c in COLONNES_UTILES, dtype=str, low_memory=False)
    return df


def transformer(df: pd.DataFrame, codes_postaux_filtre: list[str], types_bien_filtre: list[str] | None = None) -> list[dict]:
    df = df[df["code_postal"].isin(codes_postaux_filtre)].copy()
    if types_bien_filtre:
        df = df[df["type_local"].isin(types_bien_filtre)]

    df["surface_reelle_bati"] = pd.to_numeric(df["surface_reelle_bati"], errors="coerce")
    df["valeur_fonciere"] = pd.to_numeric(df["valeur_fonciere"], errors="coerce")
    df["nombre_pieces_principales"] = pd.to_numeric(
        df["nombre_pieces_principales"], errors="coerce"
    )
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")

    df = df[(df["surface_reelle_bati"] > 0) & (df["valeur_fonciere"] > 0)]
    df["prix_m2"] = df["valeur_fonciere"] / df["surface_reelle_bati"]

    df["adresse"] = (
        df.get("adresse_numero", "").fillna("") + " " + df.get("adresse_nom_voie", "").fillna("")
    ).str.strip()

    ventes = []
    for _, row in df.iterrows():
        ventes.append(
            {
                "id_mutation": row["id_mutation"],
                "date_mutation": row["date_mutation"],
                "code_postal": row["code_postal"],
                "commune": row.get("nom_commune"),
                "adresse": row.get("adresse"),
                "type_local": row.get("type_local"),
                "surface_reelle_bati": row["surface_reelle_bati"],
                "nb_pieces": row["nombre_pieces_principales"],
                "valeur_fonciere": row["valeur_fonciere"],
                "prix_m2": row["prix_m2"],
                "longitude": row["longitude"] if pd.notna(row["longitude"]) else None,
                "latitude": row["latitude"] if pd.notna(row["latitude"]) else None,
            }
        )
    return ventes


def collecter(config: dict):
    codes_postaux = resoudre_codes_postaux(config["zone"])
    annees = config["dvf"]["annees"]
    types_bien = config.get("criteres", {}).get("types_bien")
    departements = sorted({code_postal_vers_departement(cp) for cp in codes_postaux})

    total_inserees = 0
    with get_connection() as conn:
        for annee in annees:
            for dep in departements:
                try:
                    df_brut = telecharger_dvf(annee, dep)
                except requests.HTTPError as exc:
                    logger.warning("DVF indisponible pour %s/%s : %s", annee, dep, exc)
                    continue
                ventes = transformer(df_brut, codes_postaux, types_bien)
                for vente in ventes:
                    insert_vente_dvf(conn, vente)
                total_inserees += len(ventes)
                logger.info("%s ventes traitées pour %s/%s", len(ventes), annee, dep)

    logger.info("Collecte DVF terminée : %s lignes traitées", total_inserees)
    return total_inserees


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    with open("config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    collecter(cfg)
