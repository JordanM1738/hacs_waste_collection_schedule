"""Unit tests for Shawinigan waste collection schedule source."""

from custom_components.waste_collection_schedule.waste_collection_schedule.source import (
    shawinigan_ca,
)
import os
import sys
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".")))


class TestShawiniganMetadata:
    """Test module metadata"""

    def test_title_exists(self):
        """Test that TITLE is defined"""
        assert hasattr(shawinigan_ca, "TITLE")
        assert shawinigan_ca.TITLE == "Shawinigan"

    def test_description_exists(self):
        """Test that DESCRIPTION is defined"""
        assert hasattr(shawinigan_ca, "DESCRIPTION")
        assert len(shawinigan_ca.DESCRIPTION) > 0

    def test_url_exists(self):
        """Test that URL is defined"""
        assert hasattr(shawinigan_ca, "URL")
        assert shawinigan_ca.URL.startswith("https://")

    def test_country_exists(self):
        """Test that COUNTRY is defined"""
        assert hasattr(shawinigan_ca, "COUNTRY")
        assert shawinigan_ca.COUNTRY == "CA"

    def test_test_cases_defined(self):
        """Test that TEST_CASES are defined"""
        assert hasattr(shawinigan_ca, "TEST_CASES")
        assert isinstance(shawinigan_ca.TEST_CASES, dict)
        assert len(shawinigan_ca.TEST_CASES) > 0

    def test_layers_map_defined(self):
        """Test that LAYERS map is defined"""
        assert hasattr(shawinigan_ca, "LAYERS")
        assert 0 in shawinigan_ca.LAYERS  # Recyclage
        assert 1 in shawinigan_ca.LAYERS  # Ordures
        assert 4 in shawinigan_ca.LAYERS  # Compost


class TestSourceInstantiation:
    """Test Source class instantiation"""

    def test_source_init_with_address(self):
        """Test Source can be instantiated with address"""
        source = shawinigan_ca.Source(address="123 Main St, Shawinigan, QC")
        assert source._address == "123 Main St, Shawinigan, QC"

    def test_source_init_strips_whitespace(self):
        """Test that address is stripped of whitespace"""
        source = shawinigan_ca.Source(address="  456 Oak Ave  ")
        assert source._address == "456 Oak Ave"

    def test_all_test_cases_instantiate(self):
        """Test that all TEST_CASES can create a Source"""
        for test_name, params in shawinigan_ca.TEST_CASES.items():
            source = shawinigan_ca.Source(**params)
            assert source is not None
            assert hasattr(source, "fetch")


class TestWasteTypeMapping:
    """Test waste type icon mapping"""

    def test_layer_0_recyclage(self):
        """Test Layer 0 is recyclage with correct icon"""
        assert shawinigan_ca.LAYERS[0]["type"] == "RECYCLAGE"
        assert shawinigan_ca.LAYERS[0]["icon"] == "mdi:recycle"

    def test_layer_1_ordures(self):
        """Test Layer 1 is ordures with correct icon"""
        assert shawinigan_ca.LAYERS[1]["type"] == "ORDURES"
        assert shawinigan_ca.LAYERS[1]["icon"] == "mdi:trash-can"

    def test_layer_4_compost(self):
        """Test Layer 4 is compost with correct icon"""
        assert shawinigan_ca.LAYERS[4]["type"] == "COMPOST"
        assert shawinigan_ca.LAYERS[4]["icon"] == "mdi:leaf"


class TestFetchMethod:
    """Test fetch() method with mocked data"""

    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
    )
    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer"
    )
    def test_fetch_returns_collection_list(self, mock_query, mock_geocode):
        """Test that fetch returns a list of Collections"""
        # Mock geocode to return coordinates
        mock_geocode.return_value = {"x": -8096727.38, "y": 5865698.33}

        # Mock query responses for layers 0, 1, 4 - with dates in valid range
        def query_side_effect(url, **kwargs):
            if "/0" in url:  # Recyclage
                return [
                    {
                        "DISTRICTID": "S2",
                        "SCHEDULE": "0001000",
                        "SCHEDULETYPE": "2 Week",
                        "NAME": "Wednesday",
                    }
                ]
            elif "/1" in url:  # Ordures
                # Use dates within the next year from today
                return [
                    {
                        "DISTRICTID": "S2",
                        "SCHEDULE": "2026-05-13,2026-05-27,2026-06-10",
                        "SCHEDULETYPE": "Irregularly",
                        "NAME": "Wednesday",
                    }
                ]
            elif "/4" in url:  # Compost
                return []
            elif "/6" in url:  # Holidays
                return []
            return []

        mock_query.side_effect = query_side_effect

        source = shawinigan_ca.Source(address="test address")
        collections = source.fetch()

        assert isinstance(collections, list)
        assert len(collections) > 0

    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
    )
    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer"
    )
    def test_fetch_collection_has_required_fields(self, mock_query, mock_geocode):
        """Test that Collection objects have required fields"""
        mock_geocode.return_value = {"x": -8096727.38, "y": 5865698.33}

        def query_side_effect(url, **kwargs):
            if "/1" in url:  # Ordures
                return [
                    {
                        "DISTRICTID": "S2",
                        "SCHEDULE": "2026-05-13,2026-05-27",
                        "SCHEDULETYPE": "Irregularly",
                        "NAME": "Wednesday",
                    }
                ]
            elif "/6" in url:  # Holidays
                return []
            return []

        mock_query.side_effect = query_side_effect

        source = shawinigan_ca.Source(address="test")
        collections = source.fetch()

        assert len(collections) >= 1
        collection = collections[0]
        assert hasattr(collection, "date")
        assert hasattr(collection, "type")
        assert hasattr(collection, "icon")
        assert isinstance(collection.date, date)

    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
    )
    def test_fetch_with_geocode_error(self, mock_geocode):
        """Test fetch raises exception when geocoding fails"""
        from waste_collection_schedule.exceptions import SourceArgumentNotFound
        from waste_collection_schedule.service.ArcGis import ArcGisError

        mock_geocode.side_effect = ArcGisError("Geocode failed")

        source = shawinigan_ca.Source(address="nonexistent address")

        with pytest.raises(SourceArgumentNotFound):
            source.fetch()

    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
    )
    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer"
    )
    def test_fetch_with_no_results(self, mock_query, mock_geocode):
        """Test fetch raises exception when no data returned"""
        from waste_collection_schedule.exceptions import SourceArgumentNotFound

        mock_geocode.return_value = {"x": -8096727.38, "y": 5865698.33}
        mock_query.return_value = []

        source = shawinigan_ca.Source(address="test")

        with pytest.raises(SourceArgumentNotFound):
            source.fetch()


class TestScheduleParsing:
    """Test schedule parsing logic"""

    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
    )
    @patch(
        "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer"
    )
    def test_parse_irregular_schedule(self, mock_query, mock_geocode):
        """Test parsing irregularly scheduled dates"""
        mock_geocode.return_value = {"x": -8096727.38, "y": 5865698.33}

        def query_side_effect(url, **kwargs):
            if "/1" in url:  # Ordures
                return [
                    {
                        "DISTRICTID": "S2",
                        "SCHEDULE": "2026-05-01,2026-05-15,2026-05-29",
                        "SCHEDULETYPE": "Irregularly",
                        "NAME": "Friday",
                    }
                ]
            elif "/6" in url:  # Holidays
                return []
            return []

        mock_query.side_effect = query_side_effect

        source = shawinigan_ca.Source(address="test")
        collections = source.fetch()

        dates = {c.date for c in collections}
        assert date(2026, 5, 1) in dates
        assert date(2026, 5, 15) in dates
        assert date(2026, 5, 29) in dates

    def test_parse_schedule_irregular(self):
        """Test _parse_schedule with irregular schedule"""
        source = shawinigan_ca.Source(address="test")

        dates = source._parse_schedule(
            "2026-05-01,2026-05-15,2026-05-29",
            "irregularly",
            "Friday",
            date(2026, 5, 1),
            date(2026, 6, 30),
        )

        assert date(2026, 5, 1) in dates
        assert date(2026, 5, 15) in dates
        assert date(2026, 5, 29) in dates


class TestBiweeklyCalibration:
    """Regression tests for bi-weekly anchor calibration.

    RECYCLAGE is bi-weekly and alternates with ORDURES on the SAME weekday
    (mercredi / Wednesday in Shawinigan).  The code must pick the sequence
    that does NOT overlap with the explicit ORDURES dates.
    """

    def test_biweekly_picks_non_overlapping_sequence(self):
        """RECYCLAGE sequence must not overlap with ORDURES explicit dates."""
        # Wednesday = weekday 2 in Python (0=Monday)
        # ORDURES: Apr 29, May 13, May 27  → even Wednesdays from today
        # RECYCLAGE expected: May 6, May 20, Jun 3  → odd Wednesdays
        ordures_dates = {date(2026, 4, 29), date(
            2026, 5, 13), date(2026, 5, 27)}
        exclude = {2: ordures_dates}  # weekday 2 = Wednesday

        # Start from April 29 (a Wednesday itself → anchor_a = Apr 29)
        dates = shawinigan_ca._parse_schedule(
            "0001000", "2 week", "mercredi",
            date(2026, 4, 29), date(2026, 6, 30),
            exclude_dates=exclude,
        )

        date_set = set(dates)
        # Should NOT overlap with ORDURES
        assert not date_set & ordures_dates, "RECYCLAGE must not share dates with ORDURES"
        # Should contain the expected Shawinigan dates
        assert date(2026, 5, 6) in date_set
        assert date(2026, 5, 20) in date_set
        assert date(2026, 6, 3) in date_set

    def test_biweekly_fallback_without_exclude_data(self):
        """Without calibration data the code must still return a bi-weekly sequence."""
        dates = shawinigan_ca._parse_schedule(
            "0001000", "2 week", "Wednesday",
            date(2026, 5, 1), date(2026, 6, 30),
            exclude_dates=None,
        )
        assert len(dates) >= 3
        # Consecutive dates must be 14 days apart
        sorted_dates = sorted(dates)
        gaps = {(sorted_dates[i + 1] - sorted_dates[i]
                 ).days for i in range(len(sorted_dates) - 1)}
        assert gaps == {14}

    def test_biweekly_alternates_with_ordures_in_fetch(self):
        """Integration-style: RECYCLAGE result must alternate with ORDURES."""
        import unittest.mock as mock

        with (
            mock.patch(
                "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode"
            ) as mock_geocode,
            mock.patch(
                "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer"
            ) as mock_query,
        ):
            mock_geocode.return_value = {"x": -8096727.38, "y": 5865698.33}

            def query_side_effect(url, **kwargs):
                if "/0" in url:  # RECYCLAGE – bi-weekly Wednesday
                    return [{"DISTRICTID": "S2", "SCHEDULE": "0001000",
                             "SCHEDULETYPE": "2 Week", "NAME": "mercredi",
                             "HOLIDAYFIELD": "IMPACTRECY"}]
                if "/1" in url:  # ORDURES – explicit Wednesday dates
                    return [{"DISTRICTID": "SHS1",
                             "SCHEDULE": "2026-04-29,2026-05-13,2026-05-27",
                             "SCHEDULETYPE": "Irregularly", "NAME": "mercredi",
                             "HOLIDAYFIELD": "IMPACTGARB"}]
                if "/4" in url:  # COMPOST – no data
                    return []
                if "/6" in url:  # Holidays – no holidays
                    return []
                return []

            mock_query.side_effect = query_side_effect

            source = shawinigan_ca.Source(
                address="2230 Rue du Prieuré, Shawinigan")
            collections = source.fetch()

        recyclage = sorted(
            c.date for c in collections if c.type == "RECYCLAGE")
        ordures = sorted(c.date for c in collections if c.type == "ORDURES")

        # No date should appear in both
        assert not set(recyclage) & set(
            ordures), "RECYCLAGE and ORDURES must not share dates"
        # All RECYCLAGE dates must be Wednesdays
        for d in recyclage:
            assert d.weekday() == 2, f"{d} is not a Wednesday"
        # The first RECYCLAGE date must be May 6 (the Wednesday *after* Apr 29)
        assert recyclage[0] == date(2026, 5, 6)


class TestHolidayHandling:
    """Regression tests for holiday attribute access and impact string parsing."""

    def test_holidays_read_flat_attrs_dict(self):
        """_get_holidays_by_field must handle flat attrs dicts (not nested)."""
        import unittest.mock as mock

        # query_feature_layer returns FLAT attrs dicts (ArcGis.py: line 143)
        sample_features = [
            {
                "HOLIDAYDATE": 1766620800000,  # Dec 25, 2025 UTC
                "IMPACTRECY": "OneDayFrwd",
                "IMPACTGARB": "OneDayFrwd",
                "IMPACTCOMP": "None",
            }
        ]

        with mock.patch(
            "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer",
            return_value=sample_features,
        ):
            result = shawinigan_ca._get_holidays_by_field()

        # Should have entries for IMPACTRECY and IMPACTGARB
        assert "IMPACTRECY" in result, "IMPACTRECY holidays missing"
        assert "IMPACTGARB" in result, "IMPACTGARB holidays missing"
        assert "IMPACTCOMP" not in result, "IMPACTCOMP should be absent (value=None)"

        dec25 = date(2025, 12, 25)
        dec26 = date(2025, 12, 26)
        assert result["IMPACTRECY"].get(dec25) == dec26
        assert result["IMPACTGARB"].get(dec25) == dec26

    def test_holiday_impact_onedayfrwd_parsed(self):
        """'OneDayFrwd' must push the date forward by 1 day."""
        import unittest.mock as mock

        # Dec 25 2025 in epoch ms
        christmas_ms = 1766620800000

        with mock.patch(
            "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer",
            return_value=[{
                "HOLIDAYDATE": christmas_ms,
                "IMPACTRECY": "OneDayFrwd",
                "IMPACTGARB": "None",
                "IMPACTCOMP": None,
            }],
        ):
            result = shawinigan_ca._get_holidays_by_field()

        dec25 = date(2025, 12, 25)
        assert result["IMPACTRECY"][dec25] == date(2025, 12, 26)

    def test_holiday_impact_none_not_stored(self):
        """Impact value 'None' must NOT produce an entry in the result."""
        import unittest.mock as mock

        with mock.patch(
            "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer",
            return_value=[{
                "HOLIDAYDATE": 1766620800000,
                "IMPACTRECY": "None",
                "IMPACTGARB": "None",
                "IMPACTCOMP": "None",
            }],
        ):
            result = shawinigan_ca._get_holidays_by_field()

        assert result == {}, "No holidays expected when impact is None"

    def test_holiday_applied_per_layer_field(self):
        """Each layer must use its own HOLIDAYFIELD to apply adjustments."""
        import unittest.mock as mock

        christmas_ms = 1766620800000

        def query_side_effect(url, **kwargs):
            if "/6" in url:  # Holidays layer
                return [{
                    "HOLIDAYDATE": christmas_ms,
                    "IMPACTRECY": "OneDayFrwd",   # RECYCLAGE pushed +1
                    "IMPACTGARB": "None",           # ORDURES unchanged
                    "IMPACTCOMP": "None",
                }]
            if "/0" in url:  # RECYCLAGE on Dec 25
                return [{"DISTRICTID": "S2",
                         "SCHEDULE": "2025-12-25",
                         "SCHEDULETYPE": "Irregularly", "NAME": "mercredi",
                         "HOLIDAYFIELD": "IMPACTRECY"}]
            if "/1" in url:  # ORDURES on Dec 25
                return [{"DISTRICTID": "SHS1",
                         "SCHEDULE": "2025-12-25",
                         "SCHEDULETYPE": "Irregularly", "NAME": "mercredi",
                         "HOLIDAYFIELD": "IMPACTGARB"}]
            return []

        with (
            mock.patch(
                "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.geocode",
                return_value={"x": -8096727.38, "y": 5865698.33},
            ),
            mock.patch(
                "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.query_feature_layer",
                side_effect=query_side_effect,
            ),
        ):
            source = shawinigan_ca.Source(address="test")
            # Need today <= Dec 25 2025 for dates to be in range
            with mock.patch(
                "custom_components.waste_collection_schedule.waste_collection_schedule.source.shawinigan_ca.date"
            ) as mock_date:
                mock_date.today.return_value = date(2025, 12, 1)
                mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
                collections = source.fetch()

        recyclage_dates = {
            c.date for c in collections if c.type == "RECYCLAGE"}
        ordures_dates = {c.date for c in collections if c.type == "ORDURES"}

        # RECYCLAGE (IMPACTRECY=OneDayFrwd): Dec 25 → Dec 26
        assert date(
            2025, 12, 26) in recyclage_dates, "RECYCLAGE must be shifted to Dec 26"
        assert date(2025, 12, 25) not in recyclage_dates

        # ORDURES (IMPACTGARB=None): stays Dec 25
        assert date(
            2025, 12, 25) in ordures_dates, "ORDURES must stay on Dec 25"
