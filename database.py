"""Initialisation et opérations CRUD sur la base SQLite locale."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "veille.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ventes_dvf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    id_mutation TEXT UNIQUE,
    date_mutation TEXT,
    code_postal TEXT,
    commune TEXT,
    adresse TEXT,
    type_local TEXT,
    surface_reelle_bati REAL,
    nb_pieces INTEGER,
    valeur_fonciere REAL,
    prix_m2 REAL,
    longitude REAL,
    latitude REAL
);

CREATE TABLE IF NOT EXISTS cadastre_parcelles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_postal TEXT,
    id_parcelle TEXT UNIQUE,
    contenance REAL,
    commune TEXT,
    geometry TEXT
);

-- Loyers de référence officiels (Carte des Loyers, ANIL/data.gouv.fr) : estimation
-- statistique du loyer moyen/m² par commune et type de bien.
CREATE TABLE IF NOT EXISTS loyers_reference (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    annee INTEGER,
    code_insee TEXT,
    commune TEXT,
    code_postal TEXT,
    type_bien TEXT,
    loyer_m2 REAL,
    loyer_m2_min REAL,
    loyer_m2_max REAL,
    type_prediction TEXT,
    nb_observations INTEGER,
    UNIQUE(annee, code_insee, type_bien)
);

CREATE INDEX IF NOT EXISTS idx_dvf_code_postal ON ventes_dvf(code_postal);
CREATE INDEX IF NOT EXISTS idx_loyers_code_postal ON loyers_reference(code_postal);
"""


@contextmanager
def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def insert_vente_dvf(conn, vente: dict):
    conn.execute(
        """
        INSERT OR IGNORE INTO ventes_dvf
        (id_mutation, date_mutation, code_postal, commune, adresse, type_local,
         surface_reelle_bati, nb_pieces, valeur_fonciere, prix_m2, longitude, latitude)
        VALUES (:id_mutation, :date_mutation, :code_postal, :commune, :adresse, :type_local,
                :surface_reelle_bati, :nb_pieces, :valeur_fonciere, :prix_m2, :longitude, :latitude)
        """,
        vente,
    )


def insert_parcelle(conn, parcelle: dict):
    conn.execute(
        """
        INSERT OR IGNORE INTO cadastre_parcelles
        (code_postal, id_parcelle, contenance, commune, geometry)
        VALUES (:code_postal, :id_parcelle, :contenance, :commune, :geometry)
        """,
        parcelle,
    )


def insert_loyer_reference(conn, loyer: dict):
    """Remplace la valeur existante (REPLACE) : contrairement aux ventes,
    ce n'est pas un historique à accumuler mais la dernière estimation officielle connue."""
    conn.execute(
        """
        INSERT OR REPLACE INTO loyers_reference
        (annee, code_insee, commune, code_postal, type_bien, loyer_m2, loyer_m2_min,
         loyer_m2_max, type_prediction, nb_observations)
        VALUES (:annee, :code_insee, :commune, :code_postal, :type_bien, :loyer_m2, :loyer_m2_min,
                :loyer_m2_max, :type_prediction, :nb_observations)
        """,
        loyer,
    )


if __name__ == "__main__":
    init_db()
    print(f"Base initialisée : {DB_PATH}")
