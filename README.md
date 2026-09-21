# Golden Barbershop

Application Streamlit pour regrouper les paiements Clover et les paiements CASH, puis calculer les commissions par période de paie.

## Déploiement

Dans Streamlit Community Cloud :

- Repository : `aymanboisvert-pixel/golden-barbershop`
- Branch : `main`
- Main file path : `streamlit_app.py`

## Règles appliquées

- Vente normale d'un barbier : 70 % au barbier, 30 % à l'entreprise.
- Pourboires : 100 % au barbier.
- Vente nette de 29,99 $ : 100 % à l'entreprise, pourboire au barbier.
- Vente nette de 14,99 $ ou moins : 100 % à l'entreprise, pourboire au barbier.
- Ayman : ventes et pourboires à l'entreprise; aucun montant à verser.
- Périodes de paie de 14 jours à partir du 3 septembre 2026.

## Utilisation

1. Exporter les paiements de Clover en CSV et les déposer dans l'onglet **Import**.
2. Dans Google Sheets, ouvrir l'onglet CASH puis choisir **Fichier → Télécharger → Valeurs séparées par des virgules (.csv)**.
3. Déposer ce deuxième fichier dans la section **Paiements CASH**.
4. Consulter les onglets **Transactions** et **Commissions**.

Les fichiers importés restent seulement dans la session active de l'application.
