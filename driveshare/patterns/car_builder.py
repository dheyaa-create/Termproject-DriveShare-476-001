"""
car_builder.py  -  BUILDER PATTERN
=================================

Problem
-------
A car listing has six *required* attributes (make, model, year, mileage,
pick-up location, daily price) and many *optional* ones (type, seats,
transmission, fuel type, features, description, availability windows).
A constructor with a dozen positional parameters is unreadable and easy to
call incorrectly, and validation would be scattered across the code.

Solution
--------
``CarListingBuilder`` assembles a ``CarListing`` step by step through a fluent
interface. Each ``set_*`` / ``add_*`` method validates its own input and
returns ``self`` so calls can be chained. ``build()`` checks that every
required part was supplied and returns an immutable ``CarListing`` product.

``CarListingDirector`` knows a few common recipes (e.g. an "economy sedan"),
showing how the same builder can produce different preset configurations.
It is used by the demo seed script.

Example
-------
    listing = (CarListingBuilder(owner_id=1)
               .set_model("Toyota", "Camry")
               .set_year(2021)
               .set_mileage(24000)
               .set_location("Ann Arbor, MI")
               .set_price_per_day(55)
               .set_transmission("Automatic")          # optional
               .add_availability("2026-11-10T09:00", "2026-11-30T18:00")
               .build())
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

TIME_FMT = "%Y-%m-%dT%H:%M"


class ListingValidationError(ValueError):
    """Raised when the builder receives invalid or incomplete data."""


def parse_time(value):
    """Parse an HTML ``datetime-local`` string (``YYYY-MM-DDTHH:MM``)."""
    try:
        return datetime.strptime(value[:16], TIME_FMT)
    except (TypeError, ValueError):
        raise ListingValidationError(f"Invalid date/time: {value!r}")


def validate_price(price):
    """Shared rule for a daily price (used by the builder and by price updates)."""
    try:
        price = round(float(price), 2)
    except (TypeError, ValueError):
        raise ListingValidationError("Price must be a number.")
    if price <= 0:
        raise ListingValidationError("Price must be greater than zero.")
    return price


def validate_window(start, end):
    """Shared rule for an availability window; returns normalised ISO strings."""
    s, e = parse_time(start), parse_time(end)
    if e <= s:
        raise ListingValidationError("Availability end must be after its start.")
    return s.strftime(TIME_FMT), e.strftime(TIME_FMT)


@dataclass(frozen=True)
class CarListing:
    """The *product* created by the builder (immutable once built)."""
    owner_id: int
    make: str
    model: str
    year: int
    mileage: int
    location: str
    price_per_day: float
    car_type: Optional[str] = None
    seats: Optional[int] = None
    transmission: Optional[str] = None
    fuel_type: Optional[str] = None
    features: Tuple[str, ...] = ()
    description: Optional[str] = None
    availability: Tuple[Tuple[str, str], ...] = ()

    @property
    def title(self):
        """Return the conventional year/make/model label for the listing."""
        return f"{self.year} {self.make} {self.model}"


class CarListingBuilder:
    """Fluent builder for ``CarListing`` objects."""

    REQUIRED = ("make", "model", "year", "mileage", "location", "price_per_day")

    def __init__(self, owner_id):
        """Start a builder for the owner who will publish the new listing."""
        if not owner_id:
            raise ListingValidationError("A listing needs an owner.")
        self._owner_id = owner_id
        self._data = {}
        self._features: List[str] = []
        self._availability: List[Tuple[str, str]] = []

    # ---------------- required parts ---------------- #
    def set_model(self, make, model):
        """Set the required make and model after trimming surrounding spaces."""
        make, model = (make or "").strip(), (model or "").strip()
        if not make or not model:
            raise ListingValidationError("Make and model are required.")
        self._data["make"], self._data["model"] = make, model
        return self

    def set_year(self, year):
        """Set a numeric model year within the supported historical range."""
        try:
            year = int(year)
        except (TypeError, ValueError):
            raise ListingValidationError("Year must be a number.")
        if not 1950 <= year <= datetime.now().year + 1:
            raise ListingValidationError("Year is out of range.")
        self._data["year"] = year
        return self

    def set_mileage(self, mileage):
        """Set non-negative mileage as an integer number of miles."""
        try:
            mileage = int(mileage)
        except (TypeError, ValueError):
            raise ListingValidationError("Mileage must be a whole number.")
        if mileage < 0:
            raise ListingValidationError("Mileage cannot be negative.")
        self._data["mileage"] = mileage
        return self

    def set_location(self, location):
        """Set the required pick-up location after trimming whitespace."""
        location = (location or "").strip()
        if not location:
            raise ListingValidationError("Pick-up location is required.")
        self._data["location"] = location
        return self

    def set_price_per_day(self, price):
        """Set the required daily price using the shared positive-price rule."""
        self._data["price_per_day"] = validate_price(price)
        return self

    # ---------------- optional parts ---------------- #
    def set_car_type(self, car_type):
        """Set an optional vehicle category when a non-empty value is supplied."""
        if car_type:
            self._data["car_type"] = car_type.strip()
        return self

    def set_seats(self, seats):
        """Set optional seating capacity, constrained to 1 through 15 seats."""
        if seats not in (None, ""):
            seats = int(seats)
            if not 1 <= seats <= 15:
                raise ListingValidationError("Seats must be between 1 and 15.")
            self._data["seats"] = seats
        return self

    def set_transmission(self, transmission):
        """Set an optional transmission label."""
        if transmission:
            self._data["transmission"] = transmission.strip()
        return self

    def set_fuel_type(self, fuel_type):
        """Set an optional fuel-type label."""
        if fuel_type:
            self._data["fuel_type"] = fuel_type.strip()
        return self

    def add_feature(self, feature):
        """Append one trimmed feature, ignoring empty and duplicate values."""
        feature = (feature or "").strip()
        if feature and feature not in self._features:
            self._features.append(feature)
        return self

    def set_features(self, features_csv):
        """Convenience: accept a comma separated string of features."""
        for f in (features_csv or "").split(","):
            self.add_feature(f)
        return self

    def set_description(self, description):
        """Set the optional human-readable listing description."""
        if description:
            self._data["description"] = description.strip()
        return self

    def add_availability(self, start, end):
        """Add one window in which the car may be rented."""
        if not start and not end:
            return self                      # an empty form row is ignored
        self._availability.append(validate_window(start, end))
        return self

    # ---------------- product ---------------- #
    def build(self):
        """Validate completeness and return the immutable ``CarListing``."""
        missing = [f for f in self.REQUIRED if f not in self._data]
        if missing:
            raise ListingValidationError("Missing required field(s): " + ", ".join(missing))
        return CarListing(
            owner_id=self._owner_id,
            features=tuple(self._features),
            availability=tuple(sorted(self._availability)),
            **self._data,
        )


class CarListingDirector:
    """
    Optional *Director* that encodes reusable construction recipes.
    The client still provides the variable parts (location, price, ...).
    """

    @staticmethod
    def economy_sedan(builder, make, model, year, location, price):
        """Configure the builder with the project's standard economy-sedan recipe."""
        return (builder.set_model(make, model).set_year(year).set_mileage(30000)
                .set_location(location).set_price_per_day(price)
                .set_car_type("Sedan").set_seats(5).set_transmission("Automatic")
                .set_fuel_type("Gasoline").set_features("Bluetooth, Backup camera"))

    @staticmethod
    def family_suv(builder, make, model, year, location, price):
        """Configure the builder with the project's standard family-SUV recipe."""
        return (builder.set_model(make, model).set_year(year).set_mileage(20000)
                .set_location(location).set_price_per_day(price)
                .set_car_type("SUV").set_seats(7).set_transmission("Automatic")
                .set_fuel_type("Hybrid").set_features("AWD, Apple CarPlay, Roof rack"))
