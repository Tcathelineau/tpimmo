"""Résolution de zones géographiques : noms de villes -> codes postaux.

Permet de renseigner `zone.villes` dans config.yaml (ex. "Paris", "Lyon") plutôt que
de lister manuellement chaque code postal. Utilise l'API officielle geo.api.gouv.fr.
"""

import logging
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

GEO_API_URL = "https://geo.api.gouv.fr/communes"


@lru_cache(maxsize=256)
def ville_vers_codes_postaux(nom_ville: str) -> tuple[str, ...]:
    """Renvoie tous les codes postaux d'une ville (gère les villes à arrondissements
    comme Paris, Lyon, Marseille, qui renvoient plusieurs codes postaux d'un coup)."""
    try:
        resp = requests.get(
            GEO_API_URL,
            params={"nom": nom_ville, "fields": "nom,codesPostaux", "boost": "population", "limit": 5},
            timeout=15,
        )
        resp.raise_for_status()
        resultats = resp.json()
    except requests.RequestException:
        logger.exception("Impossible de résoudre la ville '%s'", nom_ville)
        return ()

    if not resultats:
        logger.warning("Aucune commune trouvée pour '%s'", nom_ville)
        return ()

    correspondance = next(
        (r for r in resultats if r["nom"].lower() == nom_ville.lower()), None
    )
    if correspondance is None:
        correspondance = resultats[0]
        logger.warning(
            "Aucune correspondance exacte pour '%s', utilisation de '%s' à la place",
            nom_ville, correspondance["nom"],
        )

    return tuple(correspondance.get("codesPostaux", []))


def resoudre_codes_postaux(config_zone: dict) -> list[str]:
    """Fusionne les codes postaux explicites (`zone.codes_postaux`) et ceux résolus
    depuis les noms de villes (`zone.villes`)."""
    # str() au cas où YAML interprète un code postal comme un entier (ex. 50840 au lieu
    # de "50840"), ce qui casserait le tri en mélangeant str et int.
    codes = {str(cp) for cp in (config_zone.get("codes_postaux") or [])}
    for ville in config_zone.get("villes") or []:
        codes.update(ville_vers_codes_postaux(ville))

    if not codes:
        logger.warning(
            "Aucun code postal résolu : vérifiez `zone.villes` / `zone.codes_postaux` dans config.yaml"
        )
    return sorted(codes)


@lru_cache(maxsize=256)
def codes_postaux_vers_communes(codes_postaux: tuple[str, ...]) -> tuple[dict, ...]:
    """Résout chaque code postal en liste de communes (code INSEE, département, nom).

    Un code postal peut couvrir plusieurs communes (ex. zones rurales groupées).
    """
    communes = []
    for cp in codes_postaux:
        resp = requests.get(
            GEO_API_URL,
            params={"codePostal": cp, "fields": "nom,code,codeDepartement,codesPostaux"},
            timeout=30,
        )
        resp.raise_for_status()
        for commune in resp.json():
            communes.append(
                {
                    "code_postal": cp,
                    "code_insee": commune["code"],
                    "code_dep": commune["codeDepartement"],
                    "nom": commune["nom"],
                }
            )
    return tuple(communes)
