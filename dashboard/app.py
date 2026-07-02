"""Dashboard Streamlit d'analyse immobilière (données publiques : DVF, cadastre, loyers).

Lancement : streamlit run dashboard/app.py
"""

import math
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import streamlit as st
import yaml

ROOT_DIR = Path(__file__).parent.parent
DB_PATH = ROOT_DIR / "data" / "veille.db"
CONFIG_PATH = ROOT_DIR / "config.yaml"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from geo_utils import resoudre_codes_postaux  # noqa: E402

st.set_page_config(
    page_title="Analyse Immobilière",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

DVF_COLUMNS = [
    "id_mutation", "date_mutation", "code_postal", "commune", "adresse", "type_local",
    "surface_reelle_bati", "nb_pieces", "valeur_fonciere", "prix_m2", "longitude", "latitude",
]
LOYERS_COLUMNS = [
    "annee", "code_insee", "commune", "code_postal", "type_bien", "loyer_m2",
    "loyer_m2_min", "loyer_m2_max", "type_prediction", "nb_observations",
]


# ----------------------------------------------------------------------------
# Chargement des données (mis en cache 5 minutes)
# ----------------------------------------------------------------------------

@st.cache_data(ttl=300)
def charger_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@st.cache_data(ttl=3600)
def resoudre_zone(zone_config: dict) -> list[str]:
    """Résout `zone.villes` en codes postaux (mis en cache 1h : la géographie ne bouge pas)."""
    return resoudre_codes_postaux(zone_config)


def _lire_table(nom_table: str, colonnes: list[str]) -> pd.DataFrame:
    if not DB_PATH.exists():
        return pd.DataFrame(columns=colonnes)
    try:
        with sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True) as conn:
            df = pd.read_sql_query(f"SELECT * FROM {nom_table}", conn)
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return pd.DataFrame(columns=colonnes)
    return df


@st.cache_data(ttl=300)
def charger_dvf() -> pd.DataFrame:
    df = _lire_table("ventes_dvf", DVF_COLUMNS)
    if df.empty:
        return df
    df["date_mutation"] = pd.to_datetime(df["date_mutation"], errors="coerce")
    for col in ["surface_reelle_bati", "valeur_fonciere", "prix_m2", "longitude", "latitude"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["nb_pieces"] = pd.to_numeric(df["nb_pieces"], errors="coerce")
    df["code_postal"] = df["code_postal"].astype(str)
    return df


@st.cache_data(ttl=300)
def charger_loyers() -> pd.DataFrame:
    df = _lire_table("loyers_reference", LOYERS_COLUMNS)
    if df.empty:
        return df
    for col in ["loyer_m2", "loyer_m2_min", "loyer_m2_max"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["nb_observations"] = pd.to_numeric(df["nb_observations"], errors="coerce")
    df["code_postal"] = df["code_postal"].astype(str)
    return df


# ----------------------------------------------------------------------------
# Filtres
# ----------------------------------------------------------------------------

def construire_filtres(df_dvf: pd.DataFrame, config: dict) -> dict:
    st.sidebar.header("🔎 Filtres")

    codes_disponibles = sorted(
        df_dvf.get("code_postal", pd.Series(dtype=str)).dropna().unique()
    )
    defaut_cp = resoudre_zone(config.get("zone", {}))
    defaut_cp = [cp for cp in defaut_cp if cp in codes_disponibles] or codes_disponibles

    codes_postaux = st.sidebar.multiselect(
        "Codes postaux", options=codes_disponibles, default=defaut_cp
    )

    # Un code postal rural couvre souvent plusieurs communes : ce filtre permet
    # d'isoler précisément celles qu'on étudie. Par défaut : les communes de
    # `zone.villes` (config.yaml) si elles sont présentes dans les données.
    communes_disponibles = sorted(
        df_dvf.get("commune", pd.Series(dtype=str)).dropna().unique()
    )
    defaut_communes = [
        v for v in (config.get("zone", {}).get("villes") or []) if v in communes_disponibles
    ] or communes_disponibles
    communes = st.sidebar.multiselect(
        "Communes", options=communes_disponibles, default=defaut_communes
    )

    prix_valeurs = df_dvf.get("valeur_fonciere", pd.Series(dtype=float)).dropna()
    prix_min_data = int(prix_valeurs.min()) if not prix_valeurs.empty else 0
    prix_max_data = int(prix_valeurs.max()) if not prix_valeurs.empty else 1_000_000
    prix_range = st.sidebar.slider(
        "Prix (€)", min_value=prix_min_data, max_value=max(prix_max_data, prix_min_data + 1),
        value=(prix_min_data, prix_max_data),
    )

    surface_valeurs = df_dvf.get("surface_reelle_bati", pd.Series(dtype=float)).dropna()
    surface_min_data = int(surface_valeurs.min()) if not surface_valeurs.empty else 0
    surface_max_data = int(surface_valeurs.max()) if not surface_valeurs.empty else 300
    surface_range = st.sidebar.slider(
        "Surface (m²)", min_value=surface_min_data,
        max_value=max(surface_max_data, surface_min_data + 1),
        value=(surface_min_data, surface_max_data),
    )

    nb_pieces_min = st.sidebar.number_input("Nombre de pièces minimum", min_value=0, value=0, step=1)

    types_disponibles = sorted(
        df_dvf.get("type_local", pd.Series(dtype=str)).dropna().unique()
    )
    types_bien = st.sidebar.multiselect(
        "Type de bien", options=types_disponibles, default=types_disponibles
    )

    return {
        "codes_postaux": codes_postaux,
        "communes": communes,
        "prix_range": prix_range,
        "surface_range": surface_range,
        "nb_pieces_min": nb_pieces_min,
        "types_bien": types_bien,
    }


def filtrer_dvf(df: pd.DataFrame, filtres: dict) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if filtres["codes_postaux"]:
        out = out[out["code_postal"].isin(filtres["codes_postaux"])]
    if filtres["communes"]:
        out = out[out["commune"].isin(filtres["communes"])]
    out = out[out["valeur_fonciere"].between(*filtres["prix_range"]) | out["valeur_fonciere"].isna()]
    out = out[out["surface_reelle_bati"].between(*filtres["surface_range"]) | out["surface_reelle_bati"].isna()]
    out = out[(out["nb_pieces"].fillna(0) >= filtres["nb_pieces_min"])]
    if filtres["types_bien"]:
        out = out[out["type_local"].isin(filtres["types_bien"]) | out["type_local"].isna()]
    return out


def filtrer_loyers(df: pd.DataFrame, filtres: dict) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if filtres["codes_postaux"]:
        out = out[out["code_postal"].isin(filtres["codes_postaux"])]
    if filtres["communes"]:
        out = out[out["commune"].isin(filtres["communes"])]
    if filtres["types_bien"]:
        out = out[out["type_bien"].isin(filtres["types_bien"])]
    return out


# ----------------------------------------------------------------------------
# KPIs
# ----------------------------------------------------------------------------

def afficher_kpis(df_dvf: pd.DataFrame, df_loyers: pd.DataFrame):
    col1, col2, col3, col4 = st.columns(4)

    col1.metric("🏛️ Ventes DVF", f"{len(df_dvf):,}".replace(",", " "))

    prix_m2_moyen = df_dvf["prix_m2"].mean() if not df_dvf.empty else None
    col2.metric("💶 Prix moyen/m² (DVF)", f"{prix_m2_moyen:,.0f} €".replace(",", " ") if prix_m2_moyen else "—")

    loyer_m2_moyen = df_loyers["loyer_m2"].mean() if not df_loyers.empty else None
    col3.metric("🏘️ Loyer réf. moyen/m²", f"{loyer_m2_moyen:.2f} €" if loyer_m2_moyen else "—")

    if prix_m2_moyen and loyer_m2_moyen:
        rendement_moyen = loyer_m2_moyen * 12 / prix_m2_moyen * 100
        col4.metric("📈 Rendement brut moyen", f"{rendement_moyen:.2f} %")
    else:
        col4.metric("📈 Rendement brut moyen", "—")


# ----------------------------------------------------------------------------
# Onglet Ventes DVF
# ----------------------------------------------------------------------------

def onglet_ventes_dvf(df: pd.DataFrame):
    if df.empty:
        st.info("Aucune donnée DVF disponible pour ces filtres. Lancez une collecte via `python main.py dvf`.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 Distribution du prix au m²")
        fig = px.histogram(
            df.dropna(subset=["prix_m2"]), x="prix_m2", nbins=30,
            labels={"prix_m2": "Prix au m² (€)"}, color_discrete_sequence=["#2E7D32"],
        )
        fig.update_layout(yaxis_title="Nombre de ventes")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("📈 Évolution du prix moyen au m²")
        df_mensuel = df.dropna(subset=["date_mutation", "prix_m2"]).copy()
        if df_mensuel.empty:
            st.info("Pas assez de données datées pour tracer une évolution.")
        else:
            df_mensuel["mois"] = df_mensuel["date_mutation"].dt.to_period("M").dt.to_timestamp()
            evolution = df_mensuel.groupby("mois")["prix_m2"].mean().reset_index()
            fig = px.line(
                evolution, x="mois", y="prix_m2", markers=True,
                labels={"mois": "Mois", "prix_m2": "Prix moyen au m² (€)"},
                color_discrete_sequence=["#1565C0"],
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("📋 Détail des ventes")
    df_affichage = df.sort_values("date_mutation", ascending=False).copy()
    df_affichage["lien_carte"] = df_affichage.apply(
        lambda r: f"https://www.google.com/maps?q={r['latitude']},{r['longitude']}"
        if pd.notna(r["latitude"]) and pd.notna(r["longitude"]) else None,
        axis=1,
    )
    st.dataframe(
        df_affichage,
        use_container_width=True,
        hide_index=True,
        column_config={
            "date_mutation": st.column_config.DateColumn("Date"),
            "valeur_fonciere": st.column_config.NumberColumn("Prix (€)", format="%.0f €"),
            "prix_m2": st.column_config.NumberColumn("Prix/m²", format="%.0f €"),
            "surface_reelle_bati": st.column_config.NumberColumn("Surface (m²)"),
            "lien_carte": st.column_config.LinkColumn("Carte", display_text="🗺️ Voir"),
            "latitude": None,
            "longitude": None,
        },
    )


# ----------------------------------------------------------------------------
# Onglet Carte
# ----------------------------------------------------------------------------

def onglet_carte(df_dvf: pd.DataFrame):
    dvf_geo = df_dvf.dropna(subset=["latitude", "longitude"]) if not df_dvf.empty else df_dvf

    if dvf_geo.empty:
        st.info("Aucune vente DVF géolocalisée pour ces filtres.")
        return

    fig = go.Figure(
        go.Scattermap(
            lat=dvf_geo["latitude"], lon=dvf_geo["longitude"], mode="markers",
            marker=dict(
                size=9, color=dvf_geo["prix_m2"], colorscale="RdYlGn_r", showscale=True,
                colorbar=dict(title="Prix/m² (€)"),
            ),
            text=dvf_geo.apply(
                lambda r: f"{r['adresse'] or ''}<br>{r['prix_m2']:.0f} €/m²"
                if pd.notna(r["prix_m2"]) else "", axis=1,
            ),
            hoverinfo="text", name="Ventes DVF",
        )
    )
    fig.update_layout(
        map=dict(
            style="open-street-map",
            center=dict(lat=dvf_geo["latitude"].mean(), lon=dvf_geo["longitude"].mean()),
            zoom=11,
        ),
        margin=dict(l=0, r=0, t=0, b=0), height=600,
    )
    st.plotly_chart(fig, use_container_width=True)


# ----------------------------------------------------------------------------
# Onglet Analyse investissement
# ----------------------------------------------------------------------------

def calculer_duree_credit(montant: float, taux_annuel_pct: float, mensualite: float):
    """Durée (en mois) d'un crédit amortissable classique, ou None si la mensualité
    ne couvre pas les intérêts (le capital ne serait jamais remboursé)."""
    if montant <= 0:
        return 0
    if mensualite <= 0:
        return None
    taux_mensuel = taux_annuel_pct / 100 / 12
    if taux_mensuel == 0:
        return math.ceil(montant / mensualite)
    if mensualite <= montant * taux_mensuel:
        return None
    n = -math.log(1 - montant * taux_mensuel / mensualite) / math.log(1 + taux_mensuel)
    return math.ceil(n)


def calculateur_financement(rendement: pd.DataFrame):
    st.subheader("💰 Calculateur de financement")
    st.caption(
        "Simulez un projet locatif : choisissez un secteur (prix d'achat et loyer au m² "
        "issus des données publiques ci-dessus), puis votre plan de financement."
    )

    col_secteur, col_type = st.columns(2)
    rendement = rendement.sort_values(["commune", "type_bien"])
    with col_secteur:
        commune = st.selectbox("Commune", sorted(rendement["commune"].unique()))
    types_dispo = sorted(rendement.loc[rendement["commune"] == commune, "type_bien"].unique())
    with col_type:
        type_bien = st.selectbox("Type de bien", types_dispo)

    ligne = rendement[(rendement["commune"] == commune) & (rendement["type_bien"] == type_bien)].iloc[0]
    prix_m2_dvf = float(ligne["prix_m2_achat"])
    loyer_m2 = float(ligne["loyer_m2"])

    st.caption(
        f"Prix DVF observé pour ce secteur : {prix_m2_dvf:,.0f} €/m² · "
        f"loyer de référence ANIL : {loyer_m2:.2f} €/m².".replace(",", " ")
    )
    prix_m2_achat = st.number_input(
        "Prix d'achat au m² (€) — modifiable", min_value=1, value=round(prix_m2_dvf), step=50,
        help="Pré-rempli avec le prix moyen DVF du secteur. Ajustez-le pour tester différents "
        "scénarios de négociation et voir l'effet sur le cash-flow.",
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        apport = st.number_input("Apport (€)", min_value=0, value=30_000, step=5_000)
    with col2:
        montant_emprunte = st.number_input("Montant emprunté (€)", min_value=0, value=150_000, step=10_000)
    with col3:
        taux = st.number_input("Taux annuel (%)", min_value=0.0, value=3.5, step=0.1, format="%.2f")
    with col4:
        mensualite = st.number_input("Mensualité (€)", min_value=0, value=900, step=50)

    frais_pct = st.slider(
        "Frais d'acquisition (notaire, garantie...) en % du prix d'achat", 0.0, 15.0, 8.0, 0.5,
        help="Environ 8 % dans l'ancien, 2 à 3 % dans le neuf.",
    )

    budget_total = apport + montant_emprunte
    if budget_total <= 0:
        st.warning("Renseignez un apport et/ou un montant emprunté.")
        return

    prix_achat = budget_total / (1 + frais_pct / 100)
    surface = prix_achat / prix_m2_achat
    loyer_mensuel = surface * loyer_m2
    rendement_brut = loyer_mensuel * 12 / prix_achat * 100
    rendement_cout_total = loyer_mensuel * 12 / budget_total * 100
    cash_flow = loyer_mensuel - mensualite

    duree_mois = calculer_duree_credit(montant_emprunte, taux, mensualite)

    st.divider()
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Budget total", f"{budget_total:,.0f} €".replace(",", " "),
              help="Apport + montant emprunté, frais d'acquisition inclus.")
    r2.metric("Surface achetable", f"{surface:,.0f} m²".replace(",", " "),
              help=f"Prix d'achat net de frais ({prix_achat:,.0f} €) / prix au m² saisi ci-dessus.".replace(",", " "))
    r3.metric("Loyer mensuel estimé", f"{loyer_mensuel:,.0f} €".replace(",", " "))
    r4.metric("Cash-flow mensuel", f"{cash_flow:+,.0f} €".replace(",", " "),
              delta=f"{cash_flow:+,.0f} €".replace(",", " "),
              help="Loyer estimé − mensualité de crédit. Hors charges, taxe foncière, vacance et fiscalité.")

    if mensualite > 0 and loyer_m2 > 0:
        prix_m2_seuil = prix_achat * loyer_m2 / mensualite
        if cash_flow >= 0:
            st.success(
                f"✅ Cash-flow positif jusqu'à **{prix_m2_seuil:,.0f} €/m²** à l'achat "
                f"(actuellement {prix_m2_achat:,.0f} €/m²), à budget et mensualité constants."
                .replace(",", " ")
            )
        else:
            st.warning(
                f"📉 Cash-flow négatif au prix actuel ({prix_m2_achat:,.0f} €/m²). "
                f"Il faudrait négocier à **{prix_m2_seuil:,.0f} €/m²** ou moins pour repasser "
                f"positif, à budget et mensualité constants.".replace(",", " ")
            )

    r5, r6, r7, r8 = st.columns(4)
    r5.metric("Rendement brut", f"{rendement_brut:.2f} %",
              help="Loyer annuel / prix d'achat (hors frais).")
    r6.metric("Rendement sur coût total", f"{rendement_cout_total:.2f} %",
              help="Loyer annuel / (apport + emprunt), frais d'acquisition inclus.")

    if duree_mois is None:
        r7.metric("Durée du crédit", "∞")
        st.error(
            "⚠️ La mensualité ne couvre pas les intérêts du prêt : le capital ne serait "
            "jamais remboursé. Augmentez la mensualité ou réduisez le montant emprunté."
        )
    elif duree_mois == 0:
        r7.metric("Durée du crédit", "—")
        r8.metric("Coût total du crédit", "0 €")
    else:
        annees, mois = divmod(duree_mois, 12)
        cout_credit = mensualite * duree_mois - montant_emprunte
        r7.metric("Durée du crédit", f"{annees} ans {mois} mois" if mois else f"{annees} ans")
        r8.metric("Coût total du crédit", f"{cout_credit:,.0f} €".replace(",", " "),
                  help="Total des mensualités − capital emprunté (hors assurance emprunteur).")
        if duree_mois > 300:
            st.warning(
                "⚠️ Durée supérieure à 25 ans : la plupart des banques ne financent pas "
                "au-delà (norme HCSF). Augmentez la mensualité ou l'apport."
            )

    st.caption(
        "Simulation indicative : rendements bruts hors charges de copropriété, taxe foncière, "
        "entretien, vacance locative, assurance emprunteur et fiscalité. Le loyer de référence "
        "est une estimation statistique communale (voir fiabilité dans le tableau ci-dessus)."
    )


def onglet_analyse_investissement(df_dvf: pd.DataFrame, df_loyers: pd.DataFrame):
    if df_dvf.empty:
        st.info("Il faut des ventes DVF pour lancer une analyse d'investissement.")
        return

    st.subheader("🏘️ Rendement locatif brut estimé")
    st.caption(
        "Rendement brut = (loyer de référence annuel / prix d'achat au m²) × 100, par commune "
        "et type de bien. Le loyer de référence provient de la Carte des Loyers "
        "(ANIL / data.gouv.fr) : une **estimation statistique** par commune, pas des annonces "
        "individuelles — voir la fiabilité ci-dessous. Ne tient pas compte des charges, de la "
        "taxe foncière, de la vacance locative ni de la fiscalité."
    )

    if df_loyers.empty:
        st.info("Aucune donnée de loyer de référence. Lancez `python main.py loyers`.")
        return

    # Agrégation par commune (et non par code postal) : en zone rurale un code postal
    # couvre plusieurs communes, chacune doit avoir son propre prix d'achat de référence.
    marche_dvf_type = (
        df_dvf.dropna(subset=["prix_m2"])
        .groupby(["commune", "type_local"])
        .agg(prix_m2_achat=("prix_m2", "mean"), nb_ventes_dvf=("prix_m2", "size"))
        .reset_index()
        .rename(columns={"type_local": "type_bien"})
    )

    rendement = df_loyers.merge(marche_dvf_type, on=["commune", "type_bien"], how="inner")
    if rendement.empty:
        st.info(
            "Aucune commune commune entre les loyers de référence et les ventes DVF "
            "pour calculer un rendement (vérifiez les filtres commune/type de bien)."
        )
        return

    rendement["rendement_brut_pct"] = (rendement["loyer_m2"] * 12) / rendement["prix_m2_achat"] * 100

    def fiabilite(row):
        if row["type_prediction"] == "commune" and (row["nb_observations"] or 0) >= 30:
            return "🟢 Fiable"
        if row["type_prediction"] == "commune":
            return "🟡 Peu d'observations"
        return "🟠 Estimation régionale (repli)"

    rendement["fiabilite"] = rendement.apply(fiabilite, axis=1)

    st.dataframe(
        rendement[
            ["code_postal", "commune", "type_bien", "prix_m2_achat", "nb_ventes_dvf",
             "loyer_m2", "rendement_brut_pct", "fiabilite", "nb_observations"]
        ].sort_values("rendement_brut_pct", ascending=False),
        use_container_width=True,
        hide_index=True,
        column_config={
            "code_postal": "CP",
            "commune": "Commune",
            "type_bien": "Type",
            "prix_m2_achat": st.column_config.NumberColumn("Prix achat/m² (DVF)", format="%.0f €"),
            "nb_ventes_dvf": "Nb ventes DVF",
            "loyer_m2": st.column_config.NumberColumn("Loyer réf./m²", format="%.2f €"),
            "rendement_brut_pct": st.column_config.NumberColumn("Rendement brut", format="%.2f %%"),
            "fiabilite": "Fiabilité",
            "nb_observations": "Nb obs. loyer",
        },
    )

    st.divider()
    calculateur_financement(rendement)


# ----------------------------------------------------------------------------
# Page principale
# ----------------------------------------------------------------------------

def main():
    st.title("🏠 Analyse Immobilière")
    st.caption(
        "Ventes réelles (DVF), loyers de référence (ANIL) et cadastre : "
        "données publiques data.gouv.fr"
    )

    if not DB_PATH.exists():
        st.warning(
            "⚠️ Base de données introuvable (`data/veille.db`). Lancez d'abord "
            "`python main.py init-db` puis une collecte (`python main.py dvf`, "
            "`python main.py loyers`)."
        )

    config = charger_config()
    df_dvf = charger_dvf()
    df_loyers = charger_loyers()

    filtres = construire_filtres(df_dvf, config)
    df_dvf_filtre = filtrer_dvf(df_dvf, filtres)
    df_loyers_filtre = filtrer_loyers(df_loyers, filtres)

    afficher_kpis(df_dvf_filtre, df_loyers_filtre)
    st.divider()

    onglet1, onglet2, onglet3 = st.tabs(
        ["📊 Ventes DVF", "🗺️ Carte", "💡 Analyse investissement"]
    )
    with onglet1:
        onglet_ventes_dvf(df_dvf_filtre)
    with onglet2:
        onglet_carte(df_dvf_filtre)
    with onglet3:
        onglet_analyse_investissement(df_dvf_filtre, df_loyers_filtre)


if __name__ == "__main__":
    main()
