import io
import json
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw

from backend.cctv_validation import CCTVValidationError, validate_cctv
from backend.schema import CCTV, Option, Raw_question


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "image/jpeg", status_code: int = 200):
        self.body = body
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, chunk_size: int):
        yield self.body


def jpeg_bytes(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class CCTVValidationTests(unittest.TestCase):
    def setUp(self):
        self.cctv = CCTV(ID=99999, cctvID="test", stream_url="https://example.test/camera")

    def validate(self, response: FakeResponse):
        with patch("backend.cctv_validation.requests.get", return_value=response):
            return validate_cctv(self.cctv, force_refresh=True)

    def test_rejects_empty_or_black_image(self):
        black = Image.new("RGB", (160, 90), "black")
        with self.assertRaises(CCTVValidationError):
            self.validate(FakeResponse(jpeg_bytes(black)))

        white = Image.new("RGB", (160, 90), "white")
        with self.assertRaises(CCTVValidationError):
            self.validate(FakeResponse(jpeg_bytes(white)))

    def test_keeps_dark_image_when_road_details_are_visible(self):
        night = Image.new("RGB", (160, 90), (4, 4, 4))
        draw = ImageDraw.Draw(night)
        draw.line((45, 89, 72, 20), fill=(235, 235, 235), width=3)
        draw.line((115, 89, 88, 20), fill=(235, 235, 235), width=3)
        draw.rectangle((76, 35, 84, 45), fill=(255, 210, 80))

        result = self.validate(FakeResponse(jpeg_bytes(night)))

        self.assertLess(result.mean_brightness, 35)
        self.assertGreaterEqual(result.detail_score, 18)

    def test_rejects_html_and_invalid_image_bytes(self):
        with self.assertRaises(CCTVValidationError):
            self.validate(FakeResponse(b"<html>error</html>", "text/html"))
        with self.assertRaises(CCTVValidationError):
            self.validate(FakeResponse(b"not an image"))

    def test_rejects_image_body_below_minimum_size(self):
        with self.assertRaisesRegex(CCTVValidationError, "too small"):
            self.validate(FakeResponse(b"x" * 64))

    def test_extracts_first_frame_from_mjpeg(self):
        image = Image.new("RGB", (80, 60), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 70, 50), fill="black")
        frame = jpeg_bytes(image)
        body = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n--frame\r\n"

        result = self.validate(FakeResponse(body, "multipart/x-mixed-replace; boundary=frame"))

        self.assertEqual((result.width, result.height), (80, 60))
        self.assertGreaterEqual(result.median_brightness, 0)
        self.assertGreaterEqual(result.quality_score, 0)
        self.assertLessEqual(result.quality_score, 100)

    def test_retries_only_the_known_official_certificate_error(self):
        image = Image.new("RGB", (80, 60), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((10, 10, 70, 50), fill="black")
        certificate_error = __import__("requests").exceptions.SSLError(
            "Missing Subject Key Identifier"
        )
        with patch(
            "backend.cctv_validation.requests.get",
            side_effect=[certificate_error, FakeResponse(jpeg_bytes(image))],
        ) as request:
            validate_cctv(self.cctv, force_refresh=True)
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("verify", request.call_args_list[0].kwargs)
        self.assertFalse(request.call_args_list[1].kwargs["verify"])


class RetryLimitTests(unittest.TestCase):
    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_random_selection_stops_after_five_unusable_cameras(self, _pool):
        from backend import service

        cameras = [
            CCTV(ID=index, cctvID=str(index), stream_url=f"https://example.test/{index}")
            for index in range(1, 6)
        ]
        with (
            patch.object(service, "get_usable_cctv_candidates", return_value=[]),
            patch.object(service, "get_cctv_health_candidates", return_value=cameras),
            patch.object(
                service,
                "validate_and_record_cctv",
                side_effect=CCTVValidationError("bad"),
            ) as validate,
        ):
            with self.assertRaises(service.NoUsableCCTVError):
                service.sev_rancctv(require_usable=True)
        self.assertEqual(validate.call_count, 5)

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_random_selection_returns_the_third_usable_camera(self, _pool):
        from backend import service

        cameras = [
            CCTV(ID=index, cctvID=str(index), stream_url=f"https://example.test/{index}")
            for index in range(1, 6)
        ]
        validation = [
            CCTVValidationError("bad"),
            CCTVValidationError("bad"),
            Mock(),
        ]
        with (
            patch.object(service, "get_usable_cctv_candidates", return_value=[]),
            patch.object(service, "get_cctv_health_candidates", return_value=cameras),
            patch.object(
                service,
                "validate_and_record_cctv",
                side_effect=validation,
            ) as validate,
        ):
            selected = service.sev_rancctv(require_usable=True)
        self.assertEqual(selected.ID, 3)
        self.assertEqual(validate.call_count, 3)

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_random_selection_prefers_fresh_pool(self, _pool):
        from backend import service

        camera = CCTV(ID=9, cctvID="9", stream_url="https://example.test/9")
        with (
            patch.object(service, "get_usable_cctv_candidates", return_value=[camera]),
            patch.object(service, "get_cctv_health_candidates", return_value=[]) as bootstrap,
            patch.object(service, "validate_and_record_cctv", return_value=Mock()) as validate,
        ):
            selected = service.sev_rancctv(require_usable=True)
        self.assertEqual(selected.ID, 9)
        validate.assert_called_once_with(camera)
        bootstrap.assert_called_once()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_full_fresh_pool_does_not_query_fallback_candidates(self, _pool):
        from backend import service

        cameras = [
            CCTV(ID=index, cctvID=str(index), stream_url=f"https://example.test/{index}")
            for index in range(1, service.CCTV_SELECTION_CANDIDATE_SCAN_SIZE + 1)
        ]
        with (
            patch.object(service, "get_usable_cctv_candidates", return_value=cameras),
            patch.object(service, "get_cctv_health_candidates") as fallback,
            patch.object(service, "validate_and_record_cctv", return_value=Mock()),
        ):
            selected = service.sev_rancctv(require_usable=True)
        self.assertEqual(selected.ID, 1)
        fallback.assert_not_called()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_validation_records_success_and_failure(self, _pool):
        from backend import service

        camera = CCTV(ID=7, cctvID="7", stream_url="https://example.test/7")
        valid_result = Mock(quality_score=73.25)
        with (
            patch.object(service, "validate_cctv", return_value=valid_result),
            patch.object(service, "save_cctv_health") as save,
        ):
            self.assertIs(service.validate_and_record_cctv(camera), valid_result)
        success_args = save.call_args.args
        self.assertEqual(success_args[:4], (7, True, 73.25, None))
        self.assertIsInstance(success_args[4], datetime)

        with (
            patch.object(service, "validate_cctv", side_effect=CCTVValidationError("offline")),
            patch.object(service, "save_cctv_health") as save,
        ):
            with self.assertRaises(CCTVValidationError):
                service.validate_and_record_cctv(camera)
        failure_args = save.call_args.args
        self.assertEqual(failure_args[:4], (7, False, None, "offline"))
        self.assertIsInstance(failure_args[4], datetime)

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_pool_failure_never_saves_question(self, _pool):
        from backend import service

        with (
            patch.object(service, "get_game_question_cctvs", return_value=[]),
            patch.object(
                service,
                "sev_rancctv",
                side_effect=service.NoUsableCCTVError(),
            ),
            patch.object(service, "save_question") as save_question,
        ):
            with self.assertRaises(service.NoUsableCCTVError):
                service.create_question("game", 4)
        save_question.assert_not_called()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_selection_skips_excluded_road_without_using_a_validation_attempt(self, _pool):
        from backend import service

        cameras = [
            CCTV(ID=1, cctvID="1", cctv_name="甲地", road_name="台62線"),
            CCTV(ID=2, cctvID="2", cctv_name="乙地", road_name="台64線"),
        ]
        with (
            patch.object(service, "get_usable_cctv_candidates", return_value=cameras),
            patch.object(service, "get_cctv_health_candidates", return_value=[]),
            patch.object(service, "validate_and_record_cctv", return_value=Mock()) as validate,
        ):
            selected = service.sev_rancctv(
                require_usable=True,
                excluded_road_names={"台62線"},
            )
        self.assertEqual(selected.ID, 2)
        validate.assert_called_once_with(cameras[1])


class RepositoryPoolTests(unittest.TestCase):
    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_usable_pool_query_uses_freshness_cutoff_and_limit(self, _pool):
        from backend import repository

        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = []
        connection = Mock()
        connection.cursor.return_value = cursor
        cutoff = datetime(2026, 9, 24, 7, 0, 0)

        with patch.object(repository.cnxpool, "get_connection", return_value=connection):
            result = repository.get_usable_cctv_candidates(cutoff, 5)

        query, params = cursor.execute.call_args.args
        self.assertEqual(result, [])
        self.assertIn("h.is_usable = TRUE", query)
        self.assertIn("h.checked_at >= %s", query)
        self.assertEqual(params, (cutoff, 5))
        connection.close.assert_called_once_with()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_health_upsert_is_timestamp_guarded_and_committed(self, _pool):
        from backend import repository

        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        connection = Mock()
        connection.cursor.return_value = cursor
        checked_at = datetime(2026, 9, 24, 7, 0, 0)

        with patch.object(repository.cnxpool, "get_connection", return_value=connection):
            repository.save_cctv_health(7, True, 81.5, None, checked_at)

        query, params = cursor.execute.call_args.args
        self.assertIn("GREATEST(checked_at, VALUES(checked_at))", query)
        self.assertEqual(params, (7, True, 81.5, checked_at, None))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_health_candidates_exclude_seen_ids(self, _pool):
        from backend import repository

        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchall.return_value = []
        connection = Mock()
        connection.cursor.return_value = cursor
        cutoff = datetime(2026, 9, 24, 7, 0, 0)

        with patch.object(repository.cnxpool, "get_connection", return_value=connection):
            result = repository.get_cctv_health_candidates(cutoff, 3, {9, 2})

        query, params = cursor.execute.call_args.args
        self.assertEqual(result, [])
        self.assertIn("c.ID NOT IN (%s, %s)", query)
        self.assertIn("ROW_NUMBER() OVER", query)
        self.assertIn("PARTITION BY COALESCE", query)
        self.assertIn("ranked.road_rank ASC", query)
        self.assertIn("RAND()", query)
        self.assertNotIn("c.ID ASC", query)
        self.assertEqual(params, (cutoff, 2, 9, 3))
        connection.close.assert_called_once_with()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_health_upsert_rolls_back_on_database_error(self, _pool):
        from backend import repository

        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.execute.side_effect = RuntimeError("write failed")
        connection = Mock()
        connection.cursor.return_value = cursor
        checked_at = datetime(2026, 9, 24, 7, 0, 0)

        with (
            patch.object(repository.cnxpool, "get_connection", return_value=connection),
            self.assertRaises(repository.DatabaseError),
        ):
            repository.save_cctv_health(7, False, None, "offline", checked_at)

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.close.assert_called_once_with()

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_background_refresh_updates_a_bounded_batch(self, _pool):
        from backend import service

        cameras = [
            CCTV(ID=index, cctvID=str(index), stream_url=f"https://example.test/{index}")
            for index in range(1, 4)
        ]
        with (
            patch.object(service, "get_cctv_health_candidates", return_value=cameras) as candidates,
            patch.object(
                service,
                "validate_and_record_cctv",
                side_effect=[Mock(), CCTVValidationError("bad"), Mock()],
            ) as validate,
        ):
            result = service.refresh_cctv_pool(batch_size=3)
        self.assertEqual(result, {"checked": 3, "usable": 2, "unusable": 1})
        candidates.assert_called_once()
        self.assertEqual(validate.call_count, 3)
        self.assertTrue(all(call.kwargs["force_refresh"] for call in validate.call_args_list))

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_background_refresh_bootstraps_to_target_then_uses_regular_batch(self, _pool):
        from backend import service

        with (
            patch.object(service, "get_cctv_health_count", side_effect=[20, 50]),
            patch.object(service, "get_cctv_health_candidates", return_value=[]) as candidates,
        ):
            service.refresh_cctv_pool()
            service.refresh_cctv_pool()

        self.assertEqual(candidates.call_args_list[0].args[1], 30)
        self.assertEqual(candidates.call_args_list[1].args[1], 5)

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_options_have_unique_roads_and_display_names(self, _pool):
        from backend import service

        answer = CCTV(ID=1, cctvID="1", cctv_name="甲地", road_name="台1線")
        candidates = [
            CCTV(ID=2, cctvID="2", cctv_name="甲地另一鏡頭", road_name="台1線"),
            CCTV(ID=3, cctvID="3", cctv_name="甲地", road_name="台2線"),
            CCTV(ID=4, cctvID="4", cctv_name="乙地", road_name="台2線"),
            CCTV(ID=5, cctvID="5", cctv_name="丙地", road_name="台3線"),
            CCTV(ID=6, cctvID="6", cctv_name="丁地", road_name="台4線"),
        ]
        with patch.object(service, "get_random_cctvs", return_value=candidates):
            entries = service._build_unique_option_entries(answer, 4)

        roads = [camera.road_name for camera, _name in entries]
        names = [name for _camera, name in entries]
        self.assertEqual(len(set(roads)), 4)
        self.assertEqual(len(set(names)), 4)

    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_existing_unusable_question_is_removed_for_redraw(self, _pool):
        from backend import service

        raw = Raw_question(
            questionUUID="question",
            question_cctvintID=7,
            game_stage=2,
            options=[Option(id=index, name=str(index)) for index in range(4)],
        )
        camera = CCTV(ID=7, cctvID="test", stream_url="https://example.test/camera")
        with (
            patch.object(service, "get_gameID", return_value=10),
            patch.object(service, "get_life", return_value=3),
            patch.object(service, "get_current_stage", return_value=2),
            patch.object(service, "select_question", return_value=raw),
            patch.object(service, "sev_cctv_byid", return_value=camera),
            patch.object(
                service,
                "validate_and_record_cctv",
                side_effect=CCTVValidationError("bad"),
            ),
            patch.object(service, "delete_unusable_pending_question", return_value=True) as delete,
        ):
            question = service.search_question("game")
        self.assertIsNone(question)
        delete.assert_called_once_with(10, 2)


class ErrorContractTests(unittest.TestCase):
    @patch("mysql.connector.pooling.MySQLConnectionPool", return_value=Mock())
    def test_no_usable_cctv_error_keeps_old_and_new_message_keys(self, _pool):
        import asyncio
        import main

        response = asyncio.run(main.unusable_cctv_error(None, Exception()))
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body["msg"], "目前沒有可用的 CCTV，請稍後再試")
        self.assertEqual(body["message"], body["msg"])


if __name__ == "__main__":
    unittest.main()
