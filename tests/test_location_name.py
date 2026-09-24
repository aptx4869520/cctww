import unittest
from unittest.mock import Mock, patch

import requests

from backend import location_name
from backend.location_name import (
    build_cctv_display_name,
    needs_location_enrichment,
    resolve_town_from_coordinates,
)
from backend.schema import CCTV


class LocationNameTests(unittest.TestCase):
    def setUp(self):
        location_name._town_cache.clear()

    def test_keeps_already_clear_location_name(self):
        camera = CCTV(
            cctvID="clear",
            cctv_name="蘇澳鎮蘇南公路/蘇花路叉路(順)",
            road_name="台9線",
            lon="121.850000",
            lat="24.600000",
        )
        resolver = Mock(return_value="蘇澳鎮")

        self.assertEqual(
            build_cctv_display_name(camera, town_resolver=resolver),
            "蘇澳鎮蘇南公路/蘇花路叉路(順)",
        )
        resolver.assert_not_called()

    def test_enriches_route_mileage_and_camera_code(self):
        samples = (
            ("台26線72K+700", "牡丹鄉・台26線附近"),
            ("220K.873 麥寮(南向)", "麥寮鄉・台61線附近"),
            ("CCTV-T66-E-0.11", "梧棲區・台61線附近"),
        )
        for description, expected in samples:
            with self.subTest(description=description):
                camera = CCTV(
                    cctvID=description,
                    cctv_name=description,
                    road_name="台61線" if description != "台26線72K+700" else "台26線",
                    lon="120.7",
                    lat="24.2",
                )
                town = expected.split("・", 1)[0]
                self.assertEqual(
                    build_cctv_display_name(
                        camera,
                        town_resolver=lambda _lon, _lat: town,
                    ),
                    expected,
                )

    def test_lookup_failure_keeps_original_name(self):
        camera = CCTV(
            cctvID="fallback",
            cctv_name="台26線72K+700",
            road_name="台26線",
            lon="120.8",
            lat="22.1",
        )

        self.assertEqual(
            build_cctv_display_name(
                camera,
                town_resolver=lambda _lon, _lat: None,
            ),
            "台26線72K+700",
        )

    def test_low_information_detection_is_narrow(self):
        self.assertTrue(needs_location_enrichment("台9丁線 029K+400"))
        self.assertTrue(needs_location_enrichment("8K+500"))
        self.assertTrue(needs_location_enrichment("CCTV-T72-E-0.035-M"))
        self.assertFalse(needs_location_enrichment("苑裡地下道"))
        self.assertFalse(needs_location_enrichment("萬里區濱海公路、瑪鍊路口"))

    def test_official_api_xml_returns_town_name(self):
        response = Mock()
        response.content = """<?xml version='1.0' encoding='UTF-8'?>
        <townVillageItem><ctyName>彰化縣</ctyName><townName>芬園鄉</townName></townVillageItem>
        """.encode("utf-8")
        response.raise_for_status.return_value = None
        with patch("backend.location_name.requests.get", return_value=response):
            self.assertEqual(
                resolve_town_from_coordinates("120.635324", "24.030304"),
                "芬園鄉",
            )

    def test_official_api_error_returns_none(self):
        with patch(
            "backend.location_name.requests.get",
            side_effect=requests.RequestException("offline"),
        ):
            self.assertIsNone(resolve_town_from_coordinates("121.1", "23.1"))

    def test_retries_only_known_official_certificate_error(self):
        response = Mock()
        response.content = (
            "<townVillageItem><townName>北區</townName></townVillageItem>"
        ).encode("utf-8")
        response.raise_for_status.return_value = None
        certificate_error = requests.exceptions.SSLError(
            "Missing Subject Key Identifier"
        )
        with patch(
            "backend.location_name.requests.get",
            side_effect=[certificate_error, response],
        ) as request:
            self.assertEqual(
                resolve_town_from_coordinates("120.698659", "24.156250"),
                "北區",
            )
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("verify", request.call_args_list[0].kwargs)
        self.assertFalse(request.call_args_list[1].kwargs["verify"])


if __name__ == "__main__":
    unittest.main()
