# ORLE

ORLE is a men's formalwear recommendation platform. This repo is the Flask web backend —
customer and vendor authentication, a style-profile onboarding flow, a product catalogue with
vendor-managed listings, sales analytics, and a rule-based recommendation engine that matches
products to a customer's body type, skin tone, and occasion.

A Flutter mobile app is being built alongside this as a separate client.

## Features

### Customers
- **Email/password authentication** — hashed passwords, session-based login via Flask-Login
- **Google Sign-In** — OAuth login/signup via Authlib, auto-links to an existing account by email
- **Email verification** — signed, expiring email links (Google sign-ins are verified automatically)
- **Forgot / reset password** — signed, expiring reset links; deliberately non-committal about
  whether an email is registered, to avoid leaking account existence
- **Style profile onboarding** — age group, height range, body type, skin tone, undertone, and
  occasion preference
- **Profile management** — view account + style profile, edit name/phone (email locked), delete
  account
- **Personalised recommendations** — a rule-based scoring engine ranks the catalogue against a
  customer's body type, color/undertone match, occasion, and height, with a visible match score
- **Product catalogue** — browsable, filterable by category, with a detail page per product

### Vendors
- **Separate vendor authentication** — its own registration/login, coexisting with customer
  auth via a shared Flask-Login session (differentiated by an `is_vendor` flag and a prefixed
  session identity so one `user_loader` can resolve either account type)
- **Product listing management** — add, edit, delete products, including image upload
  (JPG/PNG/WEBP, stored under `static/uploads/products/`)
- **Sales dashboard** — a date-range-filterable chart (Chart.js) and mutable sale log per
  vendor, with revenue and units-sold totals

### Site-wide
- **Floating flash notifications** — toast-style, auto-dismissing based on message length
- **Responsive nav** — collapses into an animated hamburger menu on mobile
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
| Charts | Chart.js |
| Database (local) | SQLite |
| Database (production) | PostgreSQL |

## Project structure

```
Orle-web/
├── main.py                    # App entry point — all routes
├── config.py                   # Reads secrets/config from environment
├── models.py                   # User, UserProfile, Product, Offer, Vendor, Sale
├── recommendations.py           # Rule-based scoring engine
├── seed_data.py                 # Populates sample men's formalwear + offers
├── requirements.txt
├── .env                          # Local secrets — never committed
├── .env.example                   # Template of required env vars — safe to commit
├── .gitignore
├── static/
│   ├── styles.css
│   └── uploads/
│       └── products/             # Vendor-uploaded product images
└── templates/
    ├── base.html                  # Shared layout — nav, flash messages, footer
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
    ├── verify_result.html
    ├── dashboard.html
    ├── catalogue.html
    ├── product_detail.html
    ├── recommendations.html
    ├── vendor_login.html
    ├── vendor_register.html
    ├── vendor_dashboard.html
    ├── vendor_product_form.html
    └── vendor_profile.html
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

- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` need an OAuth client in Google Cloud Console —
  authorized redirect URI must be `http://127.0.0.1:5000/login/google/callback` locally.
- `MAIL_PASSWORD` must be a Gmail **App Password** (requires 2-Step Verification), not your
  regular Gmail password.

### 4. Set up the database

```bash
flask --app main db init        # only once, if migrations/ doesn't exist yet
flask --app main db migrate -m "initial tables"
flask --app main db upgrade
```

### 5. (Optional) Seed sample products and offers

```bash
python seed_data.py
```

### 6. Run the app

```bash
python main.py
```

Visit `http://127.0.0.1:5000`.

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Landing page |
| `/register` | GET, POST | Create a customer account |
| `/login` | GET, POST | Customer sign in |
| `/login/google` / `/login/google/callback` | GET | Google OAuth flow |
| `/verify/<token>` | GET | Confirm email via link |
| `/forgot-password` / `/reset-password/<token>` | GET, POST | Password reset flow |
| `/onboarding` | GET, POST | Style profile (requires login) |
| `/profile` / `/profile/edit` / `/profile/delete` | — | Account management (requires login) |
| `/dashboard` | GET | Public dashboard — offers, new arrivals, full catalogue |
| `/catalogue` / `/catalogue/<int:product_id>` | GET | Browse / view a product |
| `/recommendations` | GET | Ranked products matched to the customer's style profile |
| `/logout` | GET | End session |
| `/vendor/register` / `/vendor/login` | GET, POST | Vendor auth |
| `/vendor/dashboard` | GET | Vendor's own product listings |
| `/vendor/products/add` / `/vendor/products/<id>/edit` / `/vendor/products/<id>/delete` | — | Product management (requires vendor login) |
| `/vendor/profile` | GET | Sales chart + filterable sale log |
| `/vendor/sales/add` / `/vendor/sales/<id>/delete` | POST | Log / remove a sale entry |

## How the recommendation engine works

`recommendations.py` is a transparent, rule-based scoring system — not a trained ML model. It
scores every product against a customer's saved `UserProfile` across four weighted factors:

- **Color match (35%)** — skin tone + undertone against a color-harmony table
- **Body type (30%)** — whether the product is tagged as suited to the customer's body type
- **Occasion (25%)** — whether the product matches the customer's stated occasion
- **Height (10%)** — a light adjustment based on silhouette (structured vs. relaxed)

This was a deliberate choice over ML for the current stage: there's no user interaction data
yet (clicks, saves, purchases) to train a model on, and a transparent rule-based system is
easier to debug and tune. Once real usage data exists, the natural next step is training a
lightweight model (e.g. logistic regression or gradient boosting) to re-rank these results,
rather than replacing the rules outright.

## Deployment notes

- Never run with `debug=True` in production.
- Use a production WSGI server (`gunicorn main:app`), not Flask's built-in dev server.
- Set every value from `.env.example` as an environment variable on the host.
- Run `flask --app main db upgrade` once against the production database after first deploy.
- Update the Google OAuth client's authorized redirect URI to the production domain.
- Vendor-uploaded product images are stored on local disk (`static/uploads/products/`) — this
  won't persist on hosts with an ephemeral filesystem (see the SQLite-in-production note below,
  the same issue applies to uploaded files). Move to object storage (S3, Cloudinary, etc.)
  before a real production launch.
- **Never commit `.env`.** If a secret is ever accidentally committed, rotate it immediately.

## Roadmap

- [ ] Move product image storage to cloud object storage before production
- [ ] JWT-based API endpoints for the Flutter app
- [ ] Learned re-ranking model once real user interaction data exists
- [ ] Vendor email verification and password reset (currently simpler than customer auth)
- [ ] Two-factor authentication (deferred until there's a concrete need for it)