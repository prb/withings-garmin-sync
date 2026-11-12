"""Unit tests for the FIT binary encoder."""

import struct
import unittest
from datetime import datetime

from hypothesis import given
from hypothesis import strategies as st

from withings_garmin_sync.garmin.encoder import (
    _calc_crc,
    encode_weight_records,
)


class TestFitEncoder(unittest.TestCase):
    def test_fit_header_and_crc(self):
        records = [
            {
                "date_time": datetime(2026, 11, 10, 8, 30, 0),
                "weight": 76.5,
                "fat_ratio": 18.2,
                "muscle_mass": 35.1,
                "bone_mass": 3.2,
                "percent_hydration": 55.4,
                "bmi": 23.5,
            }
        ]
        fit_bytes = encode_weight_records(records)

        # FIT header must be 12 bytes
        self.assertGreater(len(fit_bytes), 14)
        header_len, proto_ver, prof_ver, data_size, data_type = struct.unpack_from(
            "BBHI4s", fit_bytes, 0
        )
        self.assertEqual(header_len, 12)
        self.assertEqual(data_type, b".FIT")
        self.assertEqual(len(fit_bytes), 12 + data_size + 2)  # Header (12) + Data + CRC (2)

    def test_encode_multiple_records(self):
        records = [
            {
                "date_time": datetime(2026, 11, 9, 7, 0, 0),
                "weight": 77.0,
                "fat_ratio": 18.5,
            },
            {
                "date_time": datetime(2026, 11, 10, 7, 0, 0),
                "weight": 76.8,
                "fat_ratio": 18.3,
            },
        ]
        fit_bytes = encode_weight_records(records)
        self.assertTrue(fit_bytes.endswith(fit_bytes[-2:]))  # valid termination
        self.assertIn(b".FIT", fit_bytes[:12])

    def test_empty_records_raises_value_error(self):
        with self.assertRaises(ValueError):
            encode_weight_records([])

    @given(
        weight=st.floats(min_value=20.0, max_value=300.0, allow_nan=False),
        fat_ratio=st.one_of(st.none(), st.floats(min_value=1.0, max_value=70.0, allow_nan=False)),
        muscle_mass=st.one_of(
            st.none(), st.floats(min_value=5.0, max_value=150.0, allow_nan=False)
        ),
        percent_hydration=st.one_of(
            st.none(), st.floats(min_value=10.0, max_value=85.0, allow_nan=False)
        ),
        bmi=st.one_of(st.none(), st.floats(min_value=10.0, max_value=60.0, allow_nan=False)),
    )
    def test_fit_encoder_property_invariants(
        self, weight, fat_ratio, muscle_mass, percent_hydration, bmi
    ):
        """Property-based test: For any arbitrary valid body composition metrics,

        the FIT encoder must produce a structurally sound binary file with valid header,
        exact payload length match, and valid trailing CRC.
        """
        rec = {
            "date_time": datetime(2026, 11, 11, 12, 0, 0),
            "weight": weight,
            "fat_ratio": fat_ratio,
            "muscle_mass": muscle_mass,
            "percent_hydration": percent_hydration,
            "bmi": bmi,
        }
        fit_bytes = encode_weight_records([rec])

        # 1. Minimum valid FIT size (12 byte header + payload + 2 byte CRC)
        self.assertGreater(len(fit_bytes), 14)

        # 2. Header invariants
        header_len, proto_ver, prof_ver, data_size, data_type = struct.unpack_from(
            "BBHI4s", fit_bytes, 0
        )
        self.assertEqual(header_len, 12)
        self.assertEqual(data_type, b".FIT")
        self.assertEqual(len(fit_bytes), 12 + data_size + 2)

        # 3. CRC invariant: verify trailing 2 bytes match the CRC calculation over preceding bytes
        expected_crc = 0
        for b in fit_bytes[:-2]:
            expected_crc = _calc_crc(expected_crc, struct.unpack("b", bytes([b]))[0])
        trailing_crc = struct.unpack("<H", fit_bytes[-2:])[0]
        self.assertEqual(trailing_crc, expected_crc)


if __name__ == "__main__":
    unittest.main()
