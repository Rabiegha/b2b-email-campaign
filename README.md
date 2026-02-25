# B2B Email Campaign Tool

Application locale avec interface web (Streamlit) pour automatiser une campagne email B2B de A à Z : trouver les adresses email de prospects, préparer et envoyer des campagnes personnalisées.

## Fonctionnalités

### 🔍 Email Finder
- **Import** de prospects (CSV / XLSX) avec auto-détection des colonnes
- **Recherche automatique** de domaines (DuckDuckGo + vérification MX)
- **Découverte d'emails** sur les sites web des entreprises
- **Inférence de patterns** email (prénom.nom, p.nom, etc.) avec score de confiance
- **Vérification** via Hunter.io API + SMTP RCPT TO (optionnel)
- **Saisie manuelle** d'emails pour les cas particuliers
- **Export CSV** des résultats

### 📤 Campagne Email
- **Import côte à côte** : prospects avec emails (gauche) + messages (droite)
- **Construction d'outbox** avec validation et dédoublonnage
- **Sélection individuelle** des emails à envoyer (checkboxes)
- **Contrôle du débit** : délai min/max entre chaque envoi
- **Envoi SMTP** via Gmail / Google Workspace avec progression en temps réel
- **Suivi des bounces** via IMAP (détection DSN, mailer-daemon)

## Prérequis

- Python 3.10+
- Un compte Gmail ou Google Workspace
- Un **App Password** Gmail (voir ci-dessous)
- *(Optionnel)* Clé API Hunter.io pour la vérification d'emails

## Installation

```bash
# 1. Cloner le projet
git clone https://github.com/Rabiegha/b2b-email-campaign.git
cd b2b-email-campaign

# 2. Créer un environnement virtuel
python3 -m venv venv
source venv/bin/activate  # macOS / Linux
# venv\Scripts\activate   # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les credentials
cp config.example.env .env
# Éditer .env avec vos identifiants
```

## Configuration Gmail

### Activer IMAP

1. Ouvrir Gmail → Paramètres → Voir tous les paramètres
2. Onglet « Transfert et POP/IMAP »
3. Activer « Accès IMAP »

### Créer un App Password

1. Aller sur https://myaccount.google.com/apppasswords
2. Vérifier que la validation en 2 étapes est activée
3. Créer un mot de passe d'application (catégorie « Autre », nom « B2B Campaign »)
4. Copier le mot de passe généré (16 caractères) dans `.env` :

```
SMTP_USER=votre.email@gmail.com
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_USER=votre.email@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx
```

## Lancement

```bash
cd b2b-email-campaign
python3 -m streamlit run app.py
```

L'application s'ouvre automatiquement dans le navigateur (par défaut http://localhost:8501).

## Workflow

### 1. 🔍 Email Finder — Trouver les adresses email

1. **Importer** un fichier prospects (colonnes : prénom, nom, entreprise)
2. **Lancer la recherche** — l'app cherche en arrière-plan :
   - Le domaine officiel de chaque entreprise
   - Les emails publics sur le site web
   - Le pattern email dominant
3. **Consulter les résultats** avec score de confiance
4. **Exporter** en CSV ou saisir manuellement des emails

### 2. 📤 Campagne Email — Préparer et envoyer

1. **Importer les prospects** (avec emails) et les **messages** côte à côte
2. **Construire l'outbox** (page Outbox) — fusion automatique prospects + messages
3. **Sélectionner** les emails à envoyer avec les checkboxes
4. **Régler le débit** (délai min/max entre chaque envoi)
5. **Envoyer** avec suivi en temps réel
6. **Tracker les bounces** via IMAP

## Structure du projet

```
b2b-email-campaign/
  app.py                           # Point d'entrée + Dashboard
  requirements.txt                 # Dépendances Python
  config.example.env               # Template de configuration
  .env                             # Configuration locale (non versionné)
  pages/
    1_🔍_Email_Finder.py           # Import prospects + recherche emails
    2_📤_Campagne_Email.py         # Import prospects+emails + messages
    3_📮_Outbox.py                 # Construction et gestion de l'outbox
    4_✉️_Envoi.py                  # Sélection + envoi SMTP
    5_📊_Suivi_Bounces.py          # Tracking bounces IMAP
    6_Reglages.py                  # Configuration SMTP/IMAP/Hunter.io
  engine/
    __init__.py
    db.py                          # Couche SQLite
    normalize.py                   # Normalisation noms / entreprises
    domain_finder.py               # Recherche de domaines
    web_discovery.py               # Découverte d'emails sur le web
    email_pattern.py               # Inférence de pattern + génération
    email_verifier.py              # Vérification Hunter.io + SMTP RCPT TO
    task_runner.py                 # Recherche d'emails en arrière-plan
    outbox.py                      # Construction de l'outbox
    mailer.py                      # Envoi SMTP avec throttling
    bounce_tracker.py              # Tracking bounces IMAP
    io_utils.py                    # Import/export CSV/XLSX
  data/
    app.db                         # Base SQLite (créée automatiquement)
    cache/                         # Caches (domaines, patterns, bounces)
  logs/
    app.log                        # Logs applicatifs
```

## Schéma de la base de données (SQLite)

| Table | Colonnes principales |
|-------|---------------------|
| **prospects** | id, firstname, lastname, company, company_key, created_at |
| **messages** | id, company, company_key, subject, body_text, created_at |
| **email_suggestions** | id, prospect_id, domain, pattern, suggested_email, confidence_score, status, debug_notes |
| **outbox** | id, company, company_key, email, firstname, lastname, subject, body_text, status, sent_at, error_message |

### Statuts outbox
- `READY` — prêt à envoyer
- `SENT` — envoyé avec succès
- `ERROR` — erreur lors de l'envoi
- `BOUNCED` — bounce détecté
- `INVALID` — adresse invalide (code 5.1.1)

## Configuration avancée (`.env`)

```env
# SMTP (Gmail)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=votre.email@gmail.com
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx

# IMAP (pour bounces)
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=votre.email@gmail.com
IMAP_PASSWORD=xxxx xxxx xxxx xxxx

# Envoi
SEND_MIN_DELAY=5
SEND_MAX_DELAY=15
SEND_MAX_PER_RUN=50

# Hunter.io (optionnel)
HUNTER_API_KEY=votre_cle_api
```

## Limites connues

- **Recherche web** : utilise le scraping DuckDuckGo HTML qui peut être bloqué en cas d'usage intensif. En cas de blocage, l'app se rabat sur la devinette de domaine (slug + TLD + vérification MX).
- **Inférence de pattern** : basée sur les emails publics trouvés sur les pages du site. Si aucune page ne contient d'email, le pattern par défaut `prenom.nom` est utilisé avec un score de confiance faible.
- **Hunter.io** : nécessite une clé API (plan gratuit = 25 vérifications/mois).

## Licence

Usage personnel / interne uniquement.
