# B2B Email Campaign Tool

Application locale avec interface web (Streamlit) pour automatiser une campagne email B2B de A a Z.

## Fonctionnalites

- **Import** de fichiers prospects et messages (CSV / XLSX) avec auto-detection des colonnes
- **Recherche de domaines** et **inference de patterns email** pour chaque entreprise
- **Construction d'un outbox** (file d'envoi) avec validation et deduplication
- **Envoi SMTP** via Gmail/Google Workspace avec quotas et delais aleatoires
- **Tracking des bounces** via IMAP (detection DSN, mailer-daemon)
- **Export CSV** a chaque etape

## Prerequis

- Python 3.10+
- Un compte Gmail ou Google Workspace
- Un **App Password** Gmail (voir ci-dessous)

## Installation

```bash
# 1. Cloner ou copier le projet
cd b2b-email-campaign

# 2. Creer un environnement virtuel
python3 -m venv venv
source venv/bin/activate  # macOS / Linux
# venv\Scripts\activate   # Windows

# 3. Installer les dependances
pip install -r requirements.txt

# 4. Configurer les credentials
cp config.example.env .env
# Editer .env avec vos identifiants
```

## Configuration Gmail

### Activer IMAP

1. Ouvrir Gmail > Parametres > Voir tous les parametres
2. Onglet "Transfert et POP/IMAP"
3. Activer "Acces IMAP"

### Creer un App Password

1. Aller sur https://myaccount.google.com/apppasswords
2. Verifier que la validation en 2 etapes est activee
3. Creer un mot de passe d'application (categorie "Autre", nom "B2B Campaign")
4. Copier le mot de passe genere (16 caracteres) dans `.env` :

```
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_PASSWORD=xxxx xxxx xxxx xxxx
```

## Lancement

```bash
streamlit run app.py
```

L'application s'ouvre automatiquement dans le navigateur (par defaut http://localhost:8501).

## Workflow utilisateur

### Etape 1 : Import Data

- Uploader un fichier **prospects** (colonnes : firstname, lastname, company)
- Uploader un fichier **messages** (colonnes : company, subject, body_text)
- Les colonnes sont auto-detectees via synonymes (prenom/firstname, nom/lastname, etc.)
- Cliquer "Importer dans la DB"

### Etape 2 : Find Emails

- Cliquer "Lancer la recherche d'emails"
- Pour chaque entreprise, l'app :
  1. Cherche le domaine officiel (DuckDuckGo + verification MX)
  2. Decouvre des emails publics sur le site
  3. Infere le pattern email dominant (prenom.nom, p.nom, etc.)
  4. Genere une adresse email suggeree pour le prospect
- Un score de confiance est attribue a chaque suggestion

### Etape 3 : Prepare Outbox

- Cliquer "Construire l'outbox"
- Fusionne les suggestions d'emails avec les messages via la cle entreprise
- Statut READY si tout est valide, ERROR sinon (raison affichee)
- Export CSV possible

### Etape 4 : Send Emails

- Cliquer "Envoyer les emails READY"
- Envoie via SMTP avec delais aleatoires entre chaque email
- Progression en temps reel
- Statuts mis a jour : SENT ou ERROR

### Etape 5 : Track Bounces

- Cliquer "Verifier les bounces"
- Lit la boite IMAP et detecte les DSN (Delivery Status Notification)
- Met a jour les statuts : BOUNCED ou INVALID (si code 5.1.1)
- Les bounces deja traites sont memorises

### Etape 6 : Outbox Table

- Vue complete de l'outbox avec filtres par statut et recherche texte
- Export CSV

### Etape 7 : Settings

- Configuration SMTP/IMAP directement dans l'interface
- Test de connexion SMTP et IMAP
- Parametres d'envoi (delais, quota)

## Structure du projet

```
b2b-email-campaign/
  app.py                      # Point d'entree Streamlit
  requirements.txt            # Dependances Python
  config.example.env          # Template de configuration
  .env                        # Configuration locale (non versionne)
  pages/
    1_Import_Data.py           # Import prospects + messages
    2_Find_Emails.py           # Recherche domaines + patterns
    3_Prepare_Outbox.py        # Construction de l'outbox
    4_Send_Emails.py           # Envoi SMTP
    5_Track_Bounces.py         # Tracking bounces IMAP
    6_Outbox_Table.py          # Vue outbox + export
    7_Settings.py              # Configuration
  engine/
    __init__.py
    db.py                      # Couche SQLite
    normalize.py               # Normalisation noms / entreprises
    domain_finder.py           # Recherche de domaines
    web_discovery.py           # Decouverte d'emails sur le web
    email_pattern.py           # Inference de pattern + generation
    outbox.py                  # Construction de l'outbox
    mailer.py                  # Envoi SMTP
    bounce_tracker.py          # Tracking bounces IMAP
    io_utils.py                # Import/export CSV/XLSX
  data/
    app.db                     # Base SQLite (creee automatiquement)
    cache/
      domain_cache.json        # Cache des domaines trouves
      pattern_cache.json       # Cache des patterns inferes
      seen_bounces.json        # UIDs des bounces deja traites
  logs/
    app.log                    # Logs applicatifs
```

## Schema de la base de donnees (SQLite)

| Table | Colonnes principales |
|-------|---------------------|
| prospects | id, firstname, lastname, company, company_key, created_at |
| messages | id, company, company_key, subject, body_text, created_at |
| email_suggestions | id, prospect_id, domain, pattern, suggested_email, confidence_score, status, debug_notes |
| outbox | id, company, company_key, email, firstname, lastname, subject, body_text, status, sent_at, error_message |

## Limites connues

- **Recherche web** : utilise le scraping DuckDuckGo HTML qui peut etre bloque en cas d'usage intensif. En cas de blocage, l'app se rabat sur la devinette de domaine (slug + TLD + verification MX).
- **Inference de pattern** : basee sur les emails publics trouves sur les pages du site. Si aucune page ne contient d'email, le pattern par defaut `prenom.nom` est utilise avec un score de confiance faible.
- **Pas de verification d'email** : l'app ne verifie pas si l'adresse email existe reellement avant l'envoi (pas de SMTP VRFY).

## Licence

Usage personnel / interne uniquement.
