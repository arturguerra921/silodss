import unittest
import math
import sys
import os

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.logic.osrm import OSRMClient

class TestHaversineDistance(unittest.TestCase):
    def setUp(self):
        self.client = OSRMClient()
        self.R = 6371000  # Earth radius in meters used in the implementation

    def test_identical_points(self):
        coord = (45.0, 90.0)
        dist = self.client._haversine_distance(coord, coord)
        self.assertEqual(dist, 0.0)

    def test_north_south_poles(self):
        coord1 = (90.0, 0.0)
        coord2 = (-90.0, 0.0)
        dist = self.client._haversine_distance(coord1, coord2)
        expected = math.pi * self.R
        self.assertAlmostEqual(dist, expected, places=2)

    def test_antipodal_points_equator(self):
        coord1 = (0.0, 0.0)
        coord2 = (0.0, 180.0)
        dist = self.client._haversine_distance(coord1, coord2)
        expected = math.pi * self.R
        self.assertAlmostEqual(dist, expected, places=2)

    def test_equator_quarter_circle(self):
        coord1 = (0.0, 0.0)
        coord2 = (0.0, 90.0)
        dist = self.client._haversine_distance(coord1, coord2)
        expected = (math.pi / 2) * self.R
        self.assertAlmostEqual(dist, expected, places=2)

    def test_across_180th_meridian(self):
        coord1 = (0.0, 179.0)
        coord2 = (0.0, -179.0)
        dist = self.client._haversine_distance(coord1, coord2)
        # 179 to -179 is 2 degrees apart
        expected = math.radians(2) * self.R
        self.assertAlmostEqual(dist, expected, places=2)

    def test_known_distance(self):
        # Brasilia to Sao Paulo
        # Approx coordinates
        bsb = (-15.7942, -47.8822)
        sp = (-23.5505, -46.6333)
        dist = self.client._haversine_distance(bsb, sp)
        # Expected distance is approx 870km
        self.assertGreater(dist, 800000)
        self.assertLess(dist, 900000)

if __name__ == '__main__':
    unittest.main()
