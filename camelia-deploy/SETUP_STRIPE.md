# Phase 2 — Stripe Setup Guide

## Étape 1 : Créer un compte Stripe

1. Va sur **https://stripe.com** → crée un compte
2. Tu seras en **mode test** par défaut (parfait pour commencer)

## Étape 2 : Créer les produits et prix

1. Va sur **https://dashboard.stripe.com/products**
2. Clique **+ Add product**

### Produit 1 — Starter
- Name: `Camélia Starter`
- Price: `19.00 EUR` → Recurring → Monthly
- Clique **Save product**
- Copie le **Price ID** (commence par `price_...`)

### Produit 2 — Pro  
- Name: `Camélia Pro`
- Price: `49.00 EUR` → Recurring → Monthly
- Clique **Save product**
- Copie le **Price ID**

## Étape 3 : Configurer le Customer Portal

1. Va sur **https://dashboard.stripe.com/settings/billing/portal**
2. Active **Allow customers to switch plans**
3. Active **Allow customers to cancel subscriptions**
4. Active **Allow customers to update payment methods**
5. Ajoute tes 2 produits dans la section "Products"
6. Sauvegarde

## Étape 4 : Ajouter les fichiers

Dans ton dossier `camelia-deploy/` :

1. Copie `stripe_routes.py` (nouveau fichier)
2. Remplace `app.py` avec la version mise à jour
3. Remplace `requirements.txt`

## Étape 5 : Variables d'environnement sur Render

Va sur Render → ton service camelia → **Environment** → ajoute :

| Key | Value |
|-----|-------|
| `STRIPE_SECRET_KEY` | `sk_test_...` (depuis Stripe Dashboard → Developers → API keys) |
| `STRIPE_STARTER_PRICE_ID` | `price_...` (le Price ID du plan Starter) |
| `STRIPE_PRO_PRICE_ID` | `price_...` (le Price ID du plan Pro) |
| `APP_URL` | `https://camelia-02uo.onrender.com` |

## Étape 6 : Configurer le Webhook

1. Va sur **https://dashboard.stripe.com/webhooks**
2. Clique **+ Add endpoint**
3. URL: `https://camelia-02uo.onrender.com/api/stripe/webhook`
4. Events à sélectionner :
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
5. Clique **Add endpoint**
6. Copie le **Signing secret** (`whsec_...`)
7. Ajoute sur Render : `STRIPE_WEBHOOK_SECRET` = `whsec_...`

## Étape 7 : Modifier index.html

Ouvre `templates/index.html` et fais ces 2 modifications :

### 7a. Remplace la fonction adminNav()
Cherche `function adminNav()` et remplace par le contenu dans `billing_frontend.js`

### 7b. Dans la fonction render(), ajoute la route billing
Cherche cette ligne :
```js
else if (adminPage === "employees") await renderAdminEmployees(el);
```
Et ajoute JUSTE APRÈS :
```js
else if (adminPage === "billing") await renderAdminBilling(el);
```

### 7c. Colle TOUT le reste du contenu de billing_frontend.js
À la fin du `<script>` (avant `</script>`), colle toutes les fonctions :
- renderAdminBilling
- renderPlanCard  
- startCheckout
- openBillingPortal

## Étape 8 : Push et test

1. Commit + Push dans GitHub Desktop
2. Attends le redéploiement Render
3. Connecte-toi en admin → clique "Abonnement"
4. Clique "Passer au Pro" → tu seras redirigé vers Stripe Checkout
5. En mode test, utilise la carte : `4242 4242 4242 4242` (date future, CVC au choix)
6. Après le paiement, ton plan passe automatiquement à Pro

## Test complet

Carte de test Stripe : `4242 4242 4242 4242`
- Date : n'importe quelle date future
- CVC : n'importe quel chiffre
- Le paiement sera simulé, pas de vrai argent débité

## Pour passer en production

Quand tu es prêt à accepter de vrais paiements :
1. Sur Stripe, active le **mode Live** 
2. Recrée les produits/prix en mode Live
3. Mets à jour les variables d'environnement avec les clés Live (`sk_live_...`, nouveaux `price_...`)
4. Mets à jour le webhook avec l'URL Live
