from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from commission_engine import add_commissions, merge_transactions, parse_cash_csv, parse_clover_csv


st.set_page_config(page_title="Golden Barbershop", page_icon="✂️", layout="wide")

st.markdown(
    """
    <style>
      .stApp { background: #f7f7f5; }
      .block-container { max-width: 1200px; padding-top: 1.6rem; }
      h1, h2, h3 { color: #1c1c1c; }
      [data-testid="stMetric"] { background: white; border: 1px solid #e4e1da; border-radius: 12px; padding: 14px; }
      .gold { color: #c69b43; }
      .small-note { color: #666; font-size: 0.9rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "clover" not in st.session_state:
    st.session_state.clover = pd.DataFrame()
if "cash" not in st.session_state:
    st.session_state.cash = pd.DataFrame()


def money(value: float) -> str:
    return f"{value:,.2f} $".replace(",", " ").replace(".", ",")


def display_transactions(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.info("Aucune transaction pour cette sélection.")
        return
    shown = frame.copy()
    shown["date"] = pd.to_datetime(shown["date"]).dt.strftime("%Y-%m-%d %H:%M")
    shown = shown.rename(
        columns={
            "date": "Date",
            "barbier": "Barbier",
            "client": "Client",
            "vente_nette": "Vente nette",
            "pourboire": "Pourboire",
            "mode_paiement": "Paiement",
            "source": "Source",
            "transaction_id": "ID",
            "regle": "Règle",
            "part_barbier": "Part barbier",
            "revenu_entreprise": "Entreprise/Ayman",
            "a_verser": "À verser",
        }
    )
    preferred = ["Date", "Barbier", "Client", "Vente nette", "Pourboire", "Paiement", "Source", "Règle", "Part barbier", "Entreprise/Ayman", "À verser", "ID"]
    shown = shown[[col for col in preferred if col in shown.columns]]
    st.dataframe(
        shown,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Vente nette": st.column_config.NumberColumn(format="%.2f $"),
            "Pourboire": st.column_config.NumberColumn(format="%.2f $"),
            "Part barbier": st.column_config.NumberColumn(format="%.2f $"),
            "Entreprise/Ayman": st.column_config.NumberColumn(format="%.2f $"),
            "À verser": st.column_config.NumberColumn(format="%.2f $"),
        },
    )


st.title("Golden Barbershop")
st.caption("Ventes, commissions et périodes de paie")

tab_import, tab_transactions, tab_commissions = st.tabs(["Import", "Transactions", "Commissions"])

with tab_import:
    st.subheader("Importer les ventes")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 1. Clover")
        clover_file = st.file_uploader("Dépose l'export Payments de Clover", type=["csv"], key="clover_upload")
        if clover_file is not None:
            try:
                parsed = parse_clover_csv(clover_file)
                st.session_state.clover = merge_transactions([st.session_state.clover, parsed])
                st.success(f"{len(parsed)} paiements Clover reconnus.")
            except Exception as exc:
                st.error(str(exc))

    with col2:
        st.markdown("#### 2. Paiements CASH")
        st.caption("Dans Google Sheets : Fichier → Télécharger → Valeurs séparées par des virgules (.csv).")
        cash_file = st.file_uploader("Dépose l'onglet CASH exporté en CSV", type=["csv"], key="cash_upload")
        if cash_file is not None:
            try:
                parsed = parse_cash_csv(cash_file)
                st.session_state.cash = merge_transactions([st.session_state.cash, parsed])
                st.success(f"{len(parsed)} paiements cash reconnus.")
            except Exception as exc:
                st.error(str(exc))

    all_imported = add_commissions(merge_transactions([st.session_state.clover, st.session_state.cash]))
    st.divider()
    a, b, c = st.columns(3)
    a.metric("Transactions Clover", len(st.session_state.clover))
    b.metric("Transactions cash", len(st.session_state.cash))
    c.metric("Total regroupé", len(all_imported))
    if not all_imported.empty:
        export = all_imported.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Télécharger le registre regroupé", export, "transactions_golden_barbershop.csv", "text/csv")
    if st.button("Effacer les imports de cette session", type="secondary"):
        st.session_state.clover = pd.DataFrame()
        st.session_state.cash = pd.DataFrame()
        st.rerun()

transactions = add_commissions(merge_transactions([st.session_state.clover, st.session_state.cash]))

with tab_transactions:
    st.subheader("Toutes les transactions")
    if transactions.empty:
        st.info("Commence par importer les fichiers dans l'onglet Import.")
    else:
        barbers = sorted(transactions["barbier"].dropna().unique().tolist())
        sources = sorted(transactions["source"].dropna().unique().tolist())
        f1, f2 = st.columns(2)
        selected_barbers = f1.multiselect("Barbiers", barbers, default=barbers)
        selected_sources = f2.multiselect("Sources", sources, default=sources)
        filtered = transactions[
            transactions["barbier"].isin(selected_barbers) & transactions["source"].isin(selected_sources)
        ]
        display_transactions(filtered)

with tab_commissions:
    st.subheader("Commissions par période de paie")
    if transactions.empty:
        st.info("Commence par importer les fichiers dans l'onglet Import.")
    else:
        periods = (
            transactions[["periode_debut", "periode"]]
            .drop_duplicates()
            .sort_values("periode_debut", ascending=False)
        )
        labels = periods["periode"].tolist()
        selected_period = st.selectbox("Période", labels)
        expenses = st.number_input("Dépenses à couvrir pour la période", min_value=0.0, value=1700.0, step=50.0)
        current = transactions[transactions["periode"] == selected_period].copy()

        net_sales = float(current["vente_nette"].sum())
        tips_non_owner = float(current.loc[current["barbier"] != "Ayman", "pourboire"].sum())
        payouts = float(current["a_verser"].sum())
        business = float(current["revenu_entreprise"].sum())
        result_after_expenses = business - expenses

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Ventes nettes", money(net_sales))
        m2.metric("À verser aux barbiers", money(payouts))
        m3.metric("Pourboires aux barbiers", money(tips_non_owner))
        m4.metric("Entreprise/Ayman", money(business))

        st.markdown("#### Couverture des dépenses")
        progress = 1.0 if expenses <= 0 else min(business / expenses, 1.0)
        st.progress(progress)
        if expenses <= 0:
            st.success(f"Aucune dépense configurée. Résultat : {money(business)}")
        elif business >= expenses:
            st.success(f"Dépenses couvertes — profit après dépenses : {money(result_after_expenses)}")
        else:
            st.write(f"{money(business)} / {money(expenses)} — {progress:.0%}")
            st.caption(f"Il manque {money(expenses - business)} pour couvrir les dépenses.")

        st.markdown("#### Sommaire par barbier")
        summary = (
            current.groupby("barbier", as_index=False)
            .agg(
                transactions=("transaction_id", "count"),
                ventes_nettes=("vente_nette", "sum"),
                pourboires=("pourboire", "sum"),
                part_barbier=("part_barbier", "sum"),
                entreprise=("revenu_entreprise", "sum"),
                a_verser=("a_verser", "sum"),
            )
            .sort_values("barbier")
        )
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "barbier": "Barbier",
                "transactions": "Transactions",
                "ventes_nettes": st.column_config.NumberColumn("Ventes nettes", format="%.2f $"),
                "pourboires": st.column_config.NumberColumn("Pourboires", format="%.2f $"),
                "part_barbier": st.column_config.NumberColumn("Part 70 %", format="%.2f $"),
                "entreprise": st.column_config.NumberColumn("Entreprise/Ayman", format="%.2f $"),
                "a_verser": st.column_config.NumberColumn("À verser", format="%.2f $"),
            },
        )

        with st.expander("Voir le détail de la période"):
            display_transactions(current)

        st.caption("Ayman n'est jamais inclus dans “À verser”. Ses ventes et ses pourboires restent dans l'entreprise.")

