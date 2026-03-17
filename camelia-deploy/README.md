# 🌸 Camélia — Système de Pointage Intelligent

Camélia est une application web professionnelle de pointage et gestion du temps de travail des employés, avec capture photo en temps réel pour vérification d'identité.

## Fonctionnalités

### 👤 Vue Salarié
- **Badgeage en 1 clic** : Arrivée, Début/Fin de pause, Départ
- **Capture photo webcam** : Vérification d'identité à chaque badge (compte à rebours 3-2-1)
- **Statistiques personnelles** : Heures par jour, semaine, mois
- **Graphique des 7 derniers jours**
- **Historique complet** avec photos

### 🏢 Vue Administrateur
- **Dashboard temps réel** : Qui est présent, en pause, absent
- **Gestion complète des employés** : Créer, modifier, désactiver des profils
- **Détail par employé** : Stats, historique, photos de badgeage
- **Attribution de rôles** : Admin ou Employé

### 🔐 Sécurité
- Authentification par code employé + PIN
- Mots de passe hashés (SHA-256)
- Sessions sécurisées
- Photos stockées côté serveur

## Installation

```bash
# Cloner le projet
git clone <repo-url>
cd camelia

# Installer les dépendances
pip install -r requirements.txt

# Lancer l'application
python app.py
```

L'application sera accessible sur `http://localhost:5000`

## Comptes de démonstration

| Rôle | Code | PIN |
|------|------|-----|
| Admin | E001 | 1234 |
| Employé | E002 | 5678 |
| Employé | E003 | 9012 |
| Employé | E004 | 3456 |

## Déploiement

### Render / Railway / Fly.io
```bash
# Avec gunicorn (production)
pip install gunicorn
gunicorn app:app --bind 0.0.0.0:$PORT
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt gunicorn
EXPOSE 5000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]
```

## Stack Technique
- **Backend** : Flask (Python)
- **Base de données** : SQLite
- **Frontend** : HTML/CSS/JS vanilla (SPA)
- **Fonts** : Playfair Display + DM Sans
- **Photos** : WebRTC (capture webcam navigateur)

## Structure
```
camelia/
├── app.py                 # Backend Flask + API REST
├── camelia.db             # Base de données SQLite (auto-générée)
├── requirements.txt
├── templates/
│   └── index.html         # Frontend SPA
└── static/
    └── uploads/           # Photos de badgeage
```

## Licence
Propriétaire — © 2026 Camélia
