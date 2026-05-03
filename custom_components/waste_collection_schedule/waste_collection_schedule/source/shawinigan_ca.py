"""Source for Shawinigan, Canada waste collection schedule.

Uses ArcGIS REST API with spatial queries to determine collection districts
based on address coordinates, then extracts collection schedules from districts.
"""

import logging
from datetime import date, datetime, timedelta

from waste_collection_schedule import Collection  # type: ignore[attr-defined]
from waste_collection_schedule.exceptions import SourceArgumentNotFound
from waste_collection_schedule.service.ArcGis import (
    ArcGisError,
    epoch_ms_to_date,
    geocode,
    query_feature_layer,
)

_LOGGER = logging.getLogger(__name__)

TITLE = "Shawinigan"
DESCRIPTION = "Source for Shawinigan, Canada waste collection schedule."
URL = "https://geoweb.shawinigan.ca/CollecteMatieresResiduelles/"
COUNTRY = "CA"

TEST_CASES = {
    "Shawinigan": {"address": "1760 Avenue de la Paix, Shawinigan, QC G9N 6H7"},
}

PARAM_DESCRIPTIONS = {
    "en": {
        "address": "Street address including city and postal code (e.g., '1760 Avenue de la Paix, Shawinigan, QC G9N 6H7')",
    },
}

PARAM_TRANSLATIONS = {
    "en": {
        "address": "Street Address",
    },
}

# Layer IDs for collection types
LAYERS = {
    0: {"type": "RECYCLAGE", "icon": "mdi:recycle"},     # Blue Bin Pickup
    1: {"type": "ORDURES", "icon": "mdi:trash-can"},     # Grey Bin Pickup
    # Christmas Tree Collection
    2: {"type": "SAPIN", "icon": "mdi:pine-tree"},
    3: {"type": "FEUILLES", "icon": "mdi:leaf-maple"},   # Leaf Pickup
    4: {"type": "COMPOST", "icon": "mdi:leaf"},          # Green Bin Pickup
}

MAPSERVER_BASE = "https://geoweb.shawinigan.ca/arcgis/rest/services/MunicipalServices_DeTravail/MapServer"
HOLIDAYS_LAYER = 6

_WEEKDAY_MAP = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


class Source:
    def __init__(self, address: str):
        self._address = address.strip()

    def fetch(self) -> list[Collection]:
        """Fetch waste collection schedule for the specified address."""
        try:
            location = geocode(self._address, timeout=20)
        except ArcGisError as e:
            raise SourceArgumentNotFound("address", self._address) from e

        today = date.today()
        end_date = today + timedelta(days=365)

        # Step 1: fetch all raw layer attributes
        raw_layers: dict[int, dict] = {}
        for layer_id in LAYERS:
            try:
                features = query_feature_layer(
                    f"{MAPSERVER_BASE}/{layer_id}",
                    geometry=location,
                    out_fields="*",
                )
                if features:
                    raw_layers[layer_id] = features[0]
            except ArcGisError:
                _LOGGER.debug("No data for layer %d", layer_id)

        if not raw_layers:
            raise SourceArgumentNotFound("address", self._address)

        # Step 2: collect explicit dates grouped by weekday (for bi-weekly calibration)
        # RECYCLAGE is bi-weekly and alternates with ORDURES on the same weekday;
        # ORDURES has explicit dates → use them to pick the correct week parity.
        explicit_by_weekday: dict[int, set[date]] = {}
        for attrs in raw_layers.values():
            schedule_str = attrs.get("SCHEDULE", "")
            schedule_type = attrs.get("SCHEDULETYPE", "").lower()
            day_name = attrs.get("NAME", "")
            if "irregularly" in schedule_type or "," in schedule_str:
                wd = _weekday_num(day_name)
                if wd >= 0:
                    for d in _parse_irregular(schedule_str, today, end_date):
                        explicit_by_weekday.setdefault(wd, set()).add(d)

        # Step 3: fetch holidays per impact field
        all_holidays = _get_holidays_by_field()

        # Step 4: generate Collection entries
        entries: list[Collection] = []
        for layer_id, attrs in raw_layers.items():
            layer_info = LAYERS[layer_id]
            schedule_str = attrs.get("SCHEDULE", "")
            schedule_type = attrs.get("SCHEDULETYPE", "").lower()
            day_name = attrs.get("NAME", "")
            holiday_field = attrs.get("HOLIDAYFIELD") or "IMPACTGARB"
            layer_holidays = all_holidays.get(holiday_field, {})
            description = attrs.get("DESCRIPT") or None

            collection_dates = _parse_schedule(
                schedule_str, schedule_type, day_name,
                today, end_date, explicit_by_weekday,
            )
            for d in collection_dates:
                d = layer_holidays.get(d, d)
                entries.append(
                    Collection(
                        date=d, t=layer_info["type"], icon=layer_info["icon"],
                        description=description)
                )

        if not entries:
            raise SourceArgumentNotFound("address", self._address)

        return sorted(entries, key=lambda x: x.date)

    def _parse_schedule(
        self,
        schedule_str: str,
        schedule_type: str,
        day_name: str,
        start_date: date,
        end_date: date,
    ) -> list[date]:
        """Public wrapper kept for unit-test compatibility."""
        return _parse_schedule(schedule_str, schedule_type, day_name, start_date, end_date)


# ---------------------------------------------------------------------------
# Module-level helpers (stateless, easy to unit-test)
# ---------------------------------------------------------------------------

def _weekday_num(day_name: str) -> int:
    return _WEEKDAY_MAP.get((day_name or "").strip().lower(), -1)


def _parse_irregular(schedule_str: str, start_date: date, end_date: date) -> list[date]:
    dates = []
    for part in schedule_str.split(","):
        part = part.strip()
        try:
            d = datetime.strptime(part, "%Y-%m-%d").date()
            if start_date <= d <= end_date:
                dates.append(d)
        except ValueError:
            continue
    return dates


def _biweekly_from(anchor: date, end_date: date) -> list[date]:
    dates = []
    current = anchor
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=14)
    return dates


def _parse_schedule(
    schedule_str: str,
    schedule_type: str,
    day_name: str,
    start_date: date,
    end_date: date,
    exclude_dates: dict[int, set[date]] | None = None,
) -> list[date]:
    """Parse a Shawinigan MapServer SCHEDULE field and return collection dates.

    For bi-weekly schedules the correct week-parity is determined by choosing
    the sequence that does NOT overlap with the explicit dates of other layers
    that share the same weekday (ORDURES alternates with RECYCLAGE).
    """
    if not schedule_str:
        return []

    schedule_type = (schedule_type or "").lower()
    weekday = _weekday_num(day_name)

    # --- Explicit list of dates ("Irregularly") ---
    if "irregularly" in schedule_type or "," in schedule_str:
        return _parse_irregular(schedule_str, start_date, end_date)

    # --- Weekly / bi-weekly pattern ---
    if "week" not in schedule_type or weekday < 0:
        return []

    # First occurrence of this weekday on or after start_date
    days_ahead = (weekday - start_date.weekday()) % 7
    anchor_a = start_date + timedelta(days=days_ahead)

    if "2" in schedule_type or "bi" in schedule_type:
        # Two candidate sequences offset by 7 days
        seq_a = _biweekly_from(anchor_a, end_date)
        seq_b = _biweekly_from(anchor_a + timedelta(days=7), end_date)

        excluded = (exclude_dates or {}).get(weekday)
        if excluded:
            overlap_a = sum(1 for d in seq_a if d in excluded)
            overlap_b = sum(1 for d in seq_b if d in excluded)
            # Pick the sequence with fewer conflicts with other layers
            return seq_b if overlap_b < overlap_a else seq_a

        return seq_a  # fallback: no calibration data

    # Weekly
    dates = []
    current = anchor_a
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=7)
    return dates


def _get_holidays_by_field() -> dict[str, dict[date, date]]:
    """Return holiday adjustments grouped by impact field name.

    query_feature_layer already unwraps the 'attributes' dict, so each
    element of the returned list IS the attributes dict directly.
    The impact values look like "OneDayFrwd", "OneDayBack", "None".
    """
    result: dict[str, dict[date, date]] = {}
    try:
        features = query_feature_layer(
            f"{MAPSERVER_BASE}/{HOLIDAYS_LAYER}",
            where="1=1",
            out_fields="*",
        )
        for attrs in features:          # attrs is already the attributes dict
            holiday_ms = attrs.get("HOLIDAYDATE")
            if not holiday_ms:
                continue
            holiday_date = epoch_ms_to_date(holiday_ms)
            # Iterate over all IMPACT* fields dynamically — robust against new collection types
            impact_fields = [k for k in attrs if k.startswith("IMPACT")]
            for field in impact_fields:
                val = (attrs.get(field) or "").lower()
                if "frwd" in val or "forward" in val:
                    result.setdefault(field, {})[
                        holiday_date] = holiday_date + timedelta(days=1)
                elif "back" in val:
                    result.setdefault(field, {})[
                        holiday_date] = holiday_date - timedelta(days=1)
    except ArcGisError:
        _LOGGER.debug("Could not fetch holidays")
    return result
