# DriveShare – Design Report

**Project:** DriveShare, a peer-to-peer car rental platform
**Team:** Dheyaa Alrabeei (individual)
**Repository:** https://github.com/dheyaa-create/Term-Project-Cis-476-001
**Video:** [ADD VIDEO LINK]

---

## 1. Overview

DriveShare is a Flask web application backed by SQLite. It follows a three-layer architecture so that each concern stays separate and easier to maintain:

1. **Presentation layer**: Jinja2 templates and `static/js/mediator.js` provide the user interface. The JavaScript Mediator centralises communication between interface components and keeps them loosely coupled.
2. **Application layer**: `routes.py` contains thin Flask controllers; they parse request data, call the right service, and render responses. The real business logic lives in `services/`.
3. **Patterns + persistence layer**: `patterns/` contains the six GoF design patterns used in the project, while `database.py` defines the SQLite schema and database initialization.

![Architecture](diagrams/architecture.png)

### Requirement → implementation map

| Requirement | Where |
|---|---|
| Register with email/password and 3 security questions | `services/auth_service.register_user`, `templates/auth/register.html` |
| List car (model, year, mileage, availability calendar, location, price) | `patterns/car_builder.py`, `services/car_service.save_listing` |
| Update availability and price | `car_service.update_price / add_availability / remove_availability` |
| Prevent overlapping rentals | `booking_service.create_booking` (`BEGIN IMMEDIATE`) + DB trigger `prevent_double_booking` |
| Search by location, date and preferences | `car_service.search`, `/api/search` |
| Watch cars (availability / price) | `patterns/observer.py`, `community_service.add_watch` |
| Booking for a specific period | `booking_service` life-cycle |
| Messaging | `community_service.send_message / conversations / thread` |
| Notifications (in-app + email) | `notification_service.notify` (+ `instance/email_outbox.log`) |
| Payment button changing balances and notifying both parties | `patterns/payment_proxy.py`, `community_service.pay_booking` |
| Rental history | `templates/bookings.html` (renter and owner tabs) |
| Reviews | `community_service.add_review`, profile and car pages |

### 1.1 Feature order and implementation status

The project is organised in the same order as the functional requirements, which makes the system easier to understand and test incrementally:

1. **User registration and authentication** — sign-up, login, password validation, and three security questions are handled in `services/auth_service.py` and the auth templates.
2. **Car listing and management** — owners create, update, and manage listings through the Builder in `patterns/car_builder.py` and the service layer in `services/car_service.py`.
3. **Booking safety** — overlapping rentals are blocked both in application code and in the database trigger inside `database.py`, creating a layered defence.
4. **Search and booking** — renters browse, filter, and book cars using the search logic and booking lifecycle in `services/car_service.py` and `services/booking_service.py`.
5. **Watch notifications** — the Observer pattern in `patterns/observer.py` tracks price/date criteria and sends notifications when conditions are met.
6. **Messaging and notifications** — owners and renters communicate through message threads, while notification delivery and simulated emails are produced by `services/notification_service.py`.
7. **Payment** — the Proxy pattern validates transactions before updating balances and marking a booking as paid.
8. **Rental history and reviews** — both sides can inspect completed rentals and leave ratings through the booking history and profile pages.

---

## 2. Class diagrams and descriptions

The diagrams were drawn directly from the implemented code, and their Mermaid sources are stored in `docs/diagrams/*.mmd` so they can be regenerated whenever the application evolves.

Simplified versions of the same diagrams, showing only the key classes and methods, are used on the presentation slides. They are in `docs/diagrams/slides/`. To regenerate any diagram, run `mmdc -i <file>.mmd -o <file>.png -c docs/diagrams/mermaid-config.json -C docs/diagrams/mermaid-style.css -s 3 -w 1600 -b white`.

### 2.1 Singleton – `SessionManager` (`patterns/session_manager.py`)

![Singleton](diagrams/singleton.png)

`SessionManager.__new__` uses double-checked locking, which ensures only one instance exists per process even when Flask is serving multiple requests concurrently. This singleton is the single source of truth for:

- creating secure random session tokens (`secrets.token_urlsafe(32)`);
- storing only the SHA-256 hash of each token, so a memory dump does not expose a usable session cookie;
- enforcing a sliding 30-minute idle timeout;
- revoking sessions on logout and revoking all sessions for a user after a password reset.

The browser stores the raw token only inside Flask's signed, HttpOnly cookie. `auth_service.load_current_user` runs before each request and resolves the token to `g.user`.

### 2.2 Builder – `CarListingBuilder` (`patterns/car_builder.py`)

![Builder](diagrams/builder.png)

A vehicle listing contains six required attributes and several optional ones. The builder exposes a fluent interface where each `set_*` or `add_*` method validates its input and returns `self`, allowing the object to be assembled step by step.

`build()` checks that every required attribute has been provided and then returns an immutable `CarListing` dataclass. This makes invalid listings fail early and keeps construction logic well organised.

`CarListingDirector` provides reusable recipes such as `economy_sedan` and `family_suv`, which are used by `seed.py` to populate demo data. `car_service.builder_from_form` reuses the same builder pattern to turn HTML form submissions into a valid listing object, so create and edit operations share one validation path.

### 2.3 Observer – watch notifications (`patterns/observer.py`)

![Observer](diagrams/observer.png)

- **Subject:** `CarListingSubject` wraps a single car and keeps a list of observers.
- **Concrete observer:** `WatchObserver`, one per active row in the `watches` table. `update()` checks whether the renter's criteria are satisfied (`price_per_day <= max_price` and/or the car is available for the requested dates). It only sends a notification when all conditions are met.
- **Publisher:** `CarEventPublisher` loads active watches for a car, attaches one `WatchObserver` per watch, and triggers the event. The availability checker and notifier are injected, so the pattern code does not depend on Flask or SQL and can be unit-tested with plain dictionaries.
- **Events that trigger it:** `PRICE_CHANGED` (owner edits price), `AVAILABILITY_CHANGED` (owner adds a new window), `BOOKING_RELEASED` (a booking is cancelled or declined and dates are free again), and `WATCH_CREATED` (a new watch is evaluated immediately).

### 2.4 Mediator – UI components (`static/js/mediator.js`)

![Mediator](diagrams/mediator.png)

The UI components never call one another directly. Instead, they emit events, and the mediator decides what the next action should be.

| Mediator | Components | Coordination |
|---|---|---|
| `BookingMediator` (car page) | `DateRangePicker`, `PriceQuote`, `BookButton`, `WatchForm` | On `datesChanged`, it calls `/api/quote`, displays the computed price or reason for unavailability, enables or disables the Book button, and pre-fills the Watch form with the same dates. |
| `SearchMediator` (search page) | `SearchFilters`, `ResultsList`, `ResultCount` | On `filtersChanged` (debounced), it calls `/api/search`, re-renders search results, and updates the result count and URL state. |
| `NavMediator` (every page) | `Poller`, `NotificationBell`, `Toast` | On each tick, it checks unread notification counts, updates the bell badge, and displays a toast when a new notification arrives. |

### 2.5 Proxy – payment (`patterns/payment_proxy.py`)

![Proxy](diagrams/proxy.png)

`PaymentProxy` and `SimulatedPaymentGateway` both implement `PaymentGateway`. The service layer only ever interacts with the proxy, never with the real gateway directly. Before delegating the payment, the proxy performs the following checks:

1. **Authentication:** the payer is logged in.
2. **Authorisation:** the payer is the renter on the booking.
3. **State:** the booking is confirmed and not already paid (idempotency).
4. **Integrity:** the payment amount matches the booking total.
5. **Funds:** the renter has enough balance.
6. **Audit:** the request is logged with the card number masked.

The real gateway is created lazily, only when a payment passes all checks (virtual-proxy behaviour). It debits the renter, credits the owner, writes a `payments` row, and marks the booking as `paid`, all in one transaction. `community_service.pay_booking` then sends notifications to both sides.

### 2.6 Chain of Responsibility – password recovery (`patterns/password_recovery.py`)

![Chain](diagrams/chain.png)

`build_recovery_chain` links the handlers in sequence:

```
AccountLockoutHandler → SecurityQuestionHandler(1) → SecurityQuestionHandler(2) → SecurityQuestionHandler(3) → PasswordResetHandler
```

Each handler either rejects the request and stops the chain, or passes it to the next handler. The three security-question handlers are created from the user's three stored questions.

- A failed answer increments `users.failed_recovery`. After 5 failures, the lockout handler rejects all further attempts.
- Every recovery request submits all three answers at once and every failure returns the same generic message, so an attacker cannot tell which security answer was wrong.
- The final handler validates the new password, stores its hash, resets the recovery counter, and invalidates all active sessions for that user.

---

## 3. Database schema

![ER diagram](diagrams/er.png)

| Table | Purpose / key constraints |
|---|---|
| `users` | Stores account data, hashed passwords, a simulated `balance` starting at $1,000, and a `failed_recovery` counter. `email` is unique. |
| `security_questions` | Stores exactly three rows per user (`position` 1–3) with a unique constraint per user. Answers are hashed after normalization (trimmed, lower-case, whitespace collapsed). |
| `cars` | Represents a listing created by the Builder. Optional values are nullable; `is_active` hides a listing without deleting its history. |
| `car_availability` | Contains windows in which the owner makes the car available for rental. `CHECK end_time > start_time` ensures valid date windows. |
| `bookings` | Stores each reservation with `status` in pending / confirmed / paid / declined / cancelled. The trigger `prevent_double_booking` prevents overlaps. |
| `payments` | Records successful payments, including payer, payee, amount, and a simulated transaction reference. Each booking may have at most one payment row. |
| `watches` | Stores renter watch criteria (target price and optional date window) for a particular car. Each renter/car pair is unique. |
| `notifications` | Stores in-app notifications, each associated with a user and a kind such as booking, payment, watch, review, or message. |
| `messages` | Stores direct owner-renter communication, including optional `car_id` context. |
| `reviews` | Stores owner or renter reviews after a completed rental. Each reviewer can post only one review per booking. |

The schema is intentionally simple but robust: it enforces critical constraints in SQLite itself, and the application code validates user input before inserting data. This reduces the chance of inconsistent states and protects the system against race conditions or malformed requests.

---

## 4. Design pattern rationale and trade-offs

The project intentionally uses multiple GoF patterns to mirror the requested assignment and to make the code easier to reason about.

### 4.1 Singleton (`SessionManager`)

The singleton pattern is appropriate because the application has a single, process-wide notion of authentication state. If each module kept its own session map, the system could drift into inconsistent login state. The singleton centralises session creation, lookup, invalidation, and expiry.

**Trade-off:** a process-wide in-memory session store is easy to reason about, but it is not shared across multiple application instances. For a distributed deployment, a server-side cache or database-backed session layer would be needed.

### 4.2 Builder (`CarListingBuilder`)

The builder pattern is ideal for complex domain objects with required and optional attributes. It prevents constructors from becoming unwieldy and ensures validation is co-located with the fields it validates.

**Trade-off:** it adds a layer of indirection compared to a direct constructor, but in return it reduces bugs and makes the code read more clearly.

### 4.3 Observer (`WatchObserver`)

The observer pattern is well suited to a watchlist: a car may change price or availability, and many renters may want to be notified independently without coupling the listing code to notification logic.

**Trade-off:** the event system adds abstract layers, but it keeps the subject clean and makes it easy to extend with new event types such as booking releases or new watch evaluation.

### 4.4 Mediator (`static/js/mediator.js`)

The mediator pattern simplifies the front-end by reducing direct component coupling. Different UI widgets can react to the same events without knowing about one another.

**Trade-off:** the mediator becomes a central coordination point, so large front-end logic can become complex if too many components depend on it.

### 4.5 Proxy (`PaymentProxy`)

The proxy pattern protects the application from directly invoking a payment processor. It performs validation and audit logging before performing the real transaction, which improves security and maintains separation of concerns.

**Trade-off:** the extra validation layer adds some overhead, but it is worth it because it ensures the system never sends an unsecured or unauthorised payment request.

### 4.6 Chain of responsibility (`build_recovery_chain`)

This pattern is appropriate because password recovery is a sequence of checks that should be easy to order, extend, and test. Each security question is independent and should be evaluated in a consistent order.

**Trade-off:** the chain adds object indirection, but it reduces `if/elif` complexity and makes future rule changes easier.

---

## 5. Implementation notes and operational considerations

Several practical design decisions support reliability and maintainability:

- **Transactions and DB triggers**: the booking flow uses `BEGIN IMMEDIATE` to acquire an exclusive write lock and re-check availability inside the transaction, then relies on the database trigger as a second safety net.
- **Password safety**: passwords and recovery answers are hashed using Werkzeug's secure password hashing, and answers are normalised before hashing so case and whitespace variations do not matter.
- **Session safety**: the session manager stores only token hashes in memory, never the raw token.
- **Notification simulation**: in-app notifications are written to the database and mirrored to a simulated email outbox, which helps demo and testing without requiring a full mail server.
- **Validation reuse**: the Builder validates listing fields and price checks are reused by service methods so create and edit flows remain consistent.

---

## 6. Conclusion

DriveShare demonstrates a coherent application built around key design patterns and database constraints. Each pattern addresses a real maintenance problem: state management, object construction, watch notifications, UI coordination, payment security, and recovery validation.

The result is a system that is not only feature-complete for the specified assignment, but also structured in a way that makes the code easier to test, extend, and explain. The project’s core value lies not only in the user-facing rental functionality, but also in how each pattern is used to enforce separation of concerns, safety, and reliability.king` aborts any insert that overlaps an active booking of the same car. || `payments` | One per booking (`booking_id` unique), payer, payee, amount and a simulated reference. |
| `watches` | Renter's Observer criteria: `max_price` and/or `start_time`–`end_time`. Unique per (renter, car). |
| `notifications` | In-app notifications (`kind`: booking / payment / watch / message / review). Each one is mirrored to the email outbox. |
| `messages` | Direct messages between users, optionally linked to a car. |
| `reviews` | 1–5 rating and comment. Unique (`booking_id`, `reviewer_id`), so each side can review a rental once. |

**Overlap rule.** Two windows [s1, e1) and [s2, e2) overlap exactly when `s1 < e2 AND s2 < e1`. Back-to-back rentals (one ends at 10:00 and the next starts at 10:00) are therefore allowed.

**Pricing.** Every started 24-hour period counts as one day: `total = ceil(hours / 24) × price_per_day`, with a minimum of one day.

---

## 4. User-interface screenshots

| | |
|---|---|
| ![](screenshots/01_home.png) Home / search hero | ![](screenshots/02_register.png) Registration with 3 security questions |
| ![](screenshots/04_search_mediator.png) Live search (Mediator) | ![](screenshots/05_car_detail_quote.png) Car page – live quote (Mediator) |
| ![](screenshots/06_double_booking_blocked.png) Overlapping dates blocked; Watch form highlighted | ![](screenshots/07_list_car_builder.png) List a car (Builder) |
| ![](screenshots/08_owner_booking_request.png) Owner confirms a request | ![](screenshots/09_manage_listing.png) Manage price & availability (Observer trigger) |
| ![](screenshots/10_renter_pay_button.png) Pay button (Proxy) | ![](screenshots/11_payment_done.png) Payment complete – balance updated |
| ![](screenshots/12_watchlist.png) Watch list | ![](screenshots/13_notifications_renter.png) Renter notifications (watch alert, payment) |
| ![](screenshots/14_messaging.png) Messaging | ![](screenshots/15_notifications_owner.png) Owner notifications |
| ![](screenshots/16_rental_history_owner.png) Rental history (owner) | ![](screenshots/17_profile_reviews.png) Profile & reviews |
| ![](screenshots/18_password_recovery_chain.png) Password recovery (Chain) – wrong answer rejected | ![](screenshots/19_about_patterns.png) Pattern overview page |

---

## 5. Testing

`tests/test_patterns.py` contains 19 pytest tests:

- Singleton identity and the session life-cycle.
- Builder required fields, Director presets, and invalid windows.
- Observer: price drop, and a watch triggered when a booking is released.
- No double booking, at both the service level and the DB-trigger level, including back-to-back bookings.
- Proxy: rejects pending bookings, the wrong user, the wrong amount and double payment, and creates the real gateway lazily.
- Chain: identifies which link failed, a full successful pass, and lockout.
- Security helpers: password rules and answer normalisation handle non-string input; notifications are written to the email outbox, including with a relative path.
- Two end-to-end HTTP tests covering register → recover → login, and book → confirm → pay → review → message → notifications.
