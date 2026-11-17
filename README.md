# DriveShare – Peer-to-Peer Car Rental Platform

DriveShare is a web application (Python 3 + Flask + SQLite) that connects car owners with people who need a car for a short time, in the spirit of Turo. Owners list their cars and manage price and availability. Renters search, watch, book and pay. Both sides message each other, get notifications, see their rental history and review each other.

> Term project – Software design patterns. **Author:** Dheyaa Alrabeei (individual project, all optional features included).
>
> **Repository:** https://github.com/dheyaa-create/Term-Project-Cis-476-001  
> **Video presentation:** [ADD VIDEO LINK]

## Features

| Area | What's implemented |
|---|---|
| Registration & auth | Email + password sign-up with **three security questions**. Passwords and answers are stored as salted hashes. Sessions are managed by the **Singleton** `SessionManager`. |
| Car listing (owner) | Model, year, mileage, pick-up location, daily price, availability calendar, plus optional type/seats/transmission/fuel/features/description. Listings are created with the **Builder**. Owners can update price, add or remove availability windows, edit details, unlist and relist. |
| No double booking | Overlap check inside a `BEGIN IMMEDIATE` transaction, plus a SQLite trigger as a second safety net. |
| Search & booking (renter) | Filter by location, pick-up/drop-off date-time, max price, car type, seats and keyword. Sort by price, year or owner rating. Results update live through the **Mediator**. Bookings go pending → confirmed → paid (or declined/cancelled). |
| Watch list | Renters watch a car with a target price and/or dates. The **Observer** pattern notifies them when the car matches. |
| Messaging & notifications | Owner ↔ renter chat. In-app notifications (bell badge + toast) mirrored to a simulated email outbox (`instance/email_outbox.log`). |
| Payment | A "Pay $X" button goes through the **Proxy** `PaymentProxy`. It changes both balances and notifies owner and renter. |
| Password recovery | **Chain of Responsibility**: lockout → question 1 → question 2 → question 3 → reset. |
| Rental history & reviews | Renter and owner tabs. Each side can rate the other (1–5 stars) after payment. |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py          # optional: loads demo users and cars (resets the DB)
python run.py           # open http://127.0.0.1:5000
```

Demo accounts created by `seed.py` all use the password `Password123`:

| Email | Role |
|---|---|
| alice@driveshare.test | Owner of all 5 demo cars |
| bob@driveshare.test | Renter |
| carol@driveshare.test | Renter |

Alice has a sample pending request from Bob; log in as Alice to confirm or decline it from the home page.
Security answers for the demo users are `blue`, `ann arbor` and `smith`. Every user starts with a simulated balance of $1,000.

Run the test suite (22 tests covering every pattern, the security helpers and the full rental flow):

```bash
python -m pytest -q
```

## Project layout

```
driveshare/
  __init__.py              app factory
  database.py              SQLite schema + connection handling
  security.py              password / answer hashing
  routes.py                Flask blueprints (thin controllers)
  patterns/
    session_manager.py     Singleton
    car_builder.py         Builder (+ Director)
    observer.py            Observer
    payment_proxy.py       Proxy
    password_recovery.py   Chain of Responsibility
  services/                business logic (auth, cars, bookings, community, notifications)
  static/js/mediator.js    Mediator (UI components)
  static/css/style.css
  templates/               Jinja2 pages
tests/                     pytest suite
docs/
  REPORT.md                design report: class diagrams, DB schema, screenshots
  diagrams/                Mermaid sources (.mmd) + rendered PNGs
  screenshots/             UI screenshots
  DriveShare_Presentation.pptx
  Canvas_Report.docx       one-page submission report
seed.py, run.py, requirements.txt
```

See **[docs/REPORT.md](docs/REPORT.md)** for the full design documentation.
See **[docs/CAR_IMAGE_CREDITS.md](docs/CAR_IMAGE_CREDITS.md)** for credits and licenses for the bundled model photos.

# Termproject-DriveShare-476-001
