# ORLE

ORLE is a luxury clothing recommendation platform. This repo is the Flask web backend —
authentication, a style-profile onboarding flow, and account management, forming the
foundation for personalised recommendations based on body type, occasion, and taste.
A Flutter mobile app is being built alongside this as a separate client.

## Features

- **Email/password authentication** — hashed passwords (Werkzeug), session-based login via
  Flask-Login
- **Google Sign-In** — OAuth login/signup via Authlib, auto-links to an existing account if the
  email already matches one
- **Email verification** — new accounts must verify via a signed, expiring email link before
  they can log in (Google sign-ins are verified automatically)
- **Forgot / reset password** — signed, expiring reset links sent by email; deliberately shows
  the same response whether or not an email is registered, to avoid leaking account existence
- **Style profile onboarding** — captures age group, height range, body type, skin tone, and
  occasion preference
- **Profile management** — view account + style profile, edit name/phone (email is locked and
  can't be changed), delete account (with password re-confirmation for password-based accounts)
- **Floating flash notifications** — toast-style messages for success/error/info states across
  the app, auto-dismissing based on message length
- **JWT scaffolding** — Flask-JWT-Extended is wired in for a future API layer the Flutter app
  will call directly

## Tech stack

| Layer | Tool |
|---|---|
| Backend framework | Flask |
| ORM | Flask-SQLAlchemy |
| Migrations | Flask-Migrate (Alembic) |
| Web session auth | Flask-Login |
| OAuth | Authlib |
| Email | Flask-Mail |
| Signed tokens (verify/reset links) | itsdangerous |
| API auth (planned) | Flask-JWT-Extended |
| Password hashing | Werkzeug security |
| Templating | Jinja2 |
| Database (local) | SQLite |
| Database (production) | PostgreSQL |

## Project structure

```
Orle-web/
├── main.py                  # App entry point — all routes
├── config.py                 # Reads secrets/config from environment
├── models.py                 # User and UserProfile SQLAlchemy models
├── requirements.txt
├── .env                       # Local secrets — never committed
├── .env.example                # Template of required env vars — safe to commit
├── .gitignore
├── static/
│   └── styles.css
└── templates/
    ├── base.html               # Shared layout — nav, flash messages, block scaffolding
    ├── home.html
    ├── login.html
    ├── register.html
    ├── onboarding.html
    ├── profile.html
    ├── edit_profile.html
    ├── delete_account.html
    ├── forgot_password.html
    ├── reset_password.html
    ├── check_email.html
    └── verify_result.html
```

## Getting started

### 1. Clone and set up a virtual environment

```bash
git clone https://github.com/rajan083/OrleWeb.git
cd Orle-web
python -m venv venv
venv\Scripts\Activate.ps1        # Windows PowerShell
# source venv/bin/activate       # macOS/Linux
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in real values:

```
SECRET_KEY=some-random-string
JWT_SECRET_KEY=another-random-string
DATABASE_URL=                          # leave blank locally — falls back to SQLite

GOOGLE_CLIENT_ID=from-google-cloud-console
GOOGLE_CLIENT_SECRET=from-google-cloud-console

MAIL_USERNAME=your-gmail@gmail.com
MAIL_PASSWORD=your-16-character-app-password
```

- `DATABASE_URL` is optional locally — falls back to a SQLite file (`orle.db`). In production,
  set it to a PostgreSQL connection string and nothing else needs to change.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` come from a Google Cloud Console OAuth client —
  authorized redirect URI must be `http://127.0.0.1:5000/login/google/callback` locally.
- `MAIL_PASSWORD` must be a Gmail **App Password** (requires 2-Step Verification enabled), not
  your regular Gmail password.

### 4. Set up the database

```bash
flask db init        # only once, if migrations/ doesn't exist yet
flask db migrate -m "initial tables"
flask db upgrade
```

### 5. Run the app

```bash
python main.py
```

Visit `http://127.0.0.1:5000`.

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Landing page |
| `/register` | GET, POST | Create an account |
| `/login` | GET, POST | Sign in |
| `/login/google` | GET | Start Google OAuth flow |
| `/login/google/callback` | GET | Google OAuth callback |
| `/verify/<token>` | GET | Confirm email via link |
| `/forgot-password` | GET, POST | Request a reset link |
| `/reset-password/<token>` | GET, POST | Set a new password |
| `/onboarding` | GET, POST | Fill or update the style profile (requires login) |
| `/profile` | GET | View account + style profile (requires login) |
| `/profile/edit` | GET, POST | Edit name/phone (requires login) |
| `/profile/delete` | GET, POST | Delete account (requires login) |
| `/logout` | GET | End session (requires login) |

## Deployment notes

- Never run with `debug=True` in production — it exposes a full interactive traceback.
- Use a production WSGI server (`gunicorn main:app`), not Flask's built-in dev server.
- Set every value from `.env.example` as an environment variable on the host rather than
  committing them.
- Run `flask db upgrade` once against the production database after the first deploy to create
  the tables.
- Update the Google OAuth client's authorized redirect URI to the production domain once
  deployed — `http://127.0.0.1:5000/...` will not work in production.
- **Never commit `.env`.** If a secret is ever accidentally committed, rotate it immediately
  (Google Cloud Console → regenerate client secret; Google Account → revoke and regenerate the
  App Password) even if the push was blocked before reaching GitHub.

## Roadmap

- [ ] Recommendation engine matching products against the saved style profile
- [ ] Product catalogue and browsing pages
- [ ] JWT-based API endpoints for the Flutter app
- [ ] Two-factor authentication (deferred until there's a concrete need for it)
