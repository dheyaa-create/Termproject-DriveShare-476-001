"""
observer.py  -  OBSERVER PATTERN
===============================

Problem
-------
Renters can "watch" a car and want to be told when it becomes available for
the dates they need and/or when its daily price drops to a target. The code
that changes a car (owner edits price, adds availability, a booking is
cancelled...) should not have to know who is watching or what each watcher
wants - otherwise the listing code becomes tangled with notification code.

Solution
--------
* ``CarListingSubject`` is the *Subject*. It keeps a list of observers and,
  whenever something about the car changes, calls ``notify_observers``.
* ``CarObserver`` is the abstract *Observer* interface with one method
  ``update(car, event)``.
* ``WatchObserver`` is the *Concrete Observer*: one per active row in the
  ``watches`` table. In ``update`` it checks the renter's own criteria
  (max price, desired dates) and, only if they are met, sends a notification.

``CarEventPublisher.publish`` is the single entry point used by the services:
it loads the car, attaches one ``WatchObserver`` per active watch, and fires
the event. Dependencies (the availability checker and the notifier) are
injected so this module has no knowledge of SQL or Flask.
"""

from abc import ABC, abstractmethod


class CarEvent:
    """Names of events a car listing can broadcast."""
    PRICE_CHANGED = "price_changed"
    AVAILABILITY_CHANGED = "availability_changed"
    BOOKING_RELEASED = "booking_released"      # booking cancelled / declined
    WATCH_CREATED = "watch_created"            # evaluate a new watch right away


# --------------------------------------------------------------------------- #
# Observer side                                                               #
# --------------------------------------------------------------------------- #
class CarObserver(ABC):
    """Abstract observer interface."""

    @abstractmethod
    def update(self, car, event):
        """Called by the subject. ``car`` is a dict snapshot of the listing."""


class WatchObserver(CarObserver):
    """
    Concrete observer representing one renter's watch on one car.

    :param watch: dict with renter_id, max_price, start_time, end_time
    :param is_available: callable(car_id, start, end) -> bool
    :param notifier: callable(user_id, kind, message, link) -> None
    """

    def __init__(self, watch, is_available, notifier):
        """Store the watch and injected callbacks used to evaluate and notify."""
        self.watch = watch
        self._is_available = is_available
        self._notifier = notifier
        self.triggered = False            # handy for unit tests / logging

    def criteria_met(self, car):
        """True when *all* criteria the renter set are satisfied."""
        max_price = self.watch.get("max_price")
        if max_price is not None and car["price_per_day"] > max_price:
            return False
        start, end = self.watch.get("start_time"), self.watch.get("end_time")
        if start and end and not self._is_available(car["id"], start, end):
            return False
        return True

    def update(self, car, event):
        """Notify the renter when this event makes all watch criteria true."""
        if not self.criteria_met(car):
            return
        parts = []
        if self.watch.get("max_price") is not None:
            parts.append(f"price is now ${car['price_per_day']:.2f}/day "
                         f"(your target: ${self.watch['max_price']:.2f})")
        if self.watch.get("start_time"):
            parts.append(f"it is available {self.watch['start_time'].replace('T', ' ')}"
                         f" to {self.watch['end_time'].replace('T', ' ')}")
        detail = " and ".join(parts) or "it matches your watch"
        title = f"{car['year']} {car['make']} {car['model']}"
        self._notifier(self.watch["renter_id"], "watch",
                       f"Good news! The {title} you are watching: {detail}.",
                       f"/cars/{car['id']}")
        self.triggered = True


# --------------------------------------------------------------------------- #
# Subject side                                                                #
# --------------------------------------------------------------------------- #
class CarListingSubject:
    """Subject that broadcasts changes of a single car listing."""

    def __init__(self, car):
        """Create a subject around the current snapshot of one car."""
        self.car = car
        self._observers = []

    def attach(self, observer):
        """Subscribe an observer once, preserving registration order."""
        if observer not in self._observers:
            self._observers.append(observer)

    def detach(self, observer):
        """Unsubscribe an observer if it is currently attached."""
        if observer in self._observers:
            self._observers.remove(observer)

    @property
    def observers(self):
        """Expose a read-only snapshot so callers cannot mutate subscriptions."""
        return tuple(self._observers)

    def notify_observers(self, event):
        """Broadcast the event to a snapshot of subscribers.

        Iterating over a copy ensures an observer can detach itself during an
        update without disrupting delivery to the remaining observers.
        """
        for observer in list(self._observers):
            observer.update(self.car, event)


class CarEventPublisher:
    """
    Glue used by the services. It turns persisted ``watches`` rows into live
    observers, attaches them to a subject and fires the event.
    """

    def __init__(self, load_car, load_watches, is_available, notifier, on_triggered=None):
        """Inject data access, availability, notification, and bookkeeping hooks."""
        self._load_car = load_car            # car_id -> dict | None
        self._load_watches = load_watches    # car_id -> list[dict]
        self._is_available = is_available
        self._notifier = notifier
        self._on_triggered = on_triggered    # watch dict -> None (bookkeeping)

    def publish(self, car_id, event, only_watch_id=None):
        """Load a car's observers, broadcast an event, and return triggered watches.

        ``only_watch_id`` is used when a renter first creates a watch so only
        that newly created watch is evaluated immediately.
        """
        car = self._load_car(car_id)
        if car is None or not car.get("is_active", 1):
            return []
        subject = CarListingSubject(car)
        for w in self._load_watches(car_id):
            if only_watch_id is None or w["id"] == only_watch_id:
                subject.attach(WatchObserver(w, self._is_available, self._notifier))
        subject.notify_observers(event)
        fired = [o.watch for o in subject.observers if o.triggered]
        if self._on_triggered:
            for w in fired:
                self._on_triggered(w)
        return fired
