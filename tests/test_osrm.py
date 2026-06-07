import unittest
from unittest.mock import patch, Mock
import sys
import os
import requests

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.logic.osrm import OSRMClient

class TestOSRMClient(unittest.TestCase):
    def setUp(self):
        self.client = OSRMClient(base_url="http://mock-osrm:5000", max_table_size=10)

    @patch('src.logic.osrm.requests.get')
    def test_get_distance_matrix_chunking(self, mock_get):
        # Create mock response
        # Chunk size will be max_table_size // 2 = 5
        # Origins: 7 (needs 2 chunks)
        # Destinations: 6 (needs 2 chunks)

        origins = [(lat, lon) for lat, lon in zip(range(7), range(7))]
        destinations = [(lat, lon) for lat, lon in zip(range(10, 16), range(10, 16))]

        # Expected chunks:
        # Origins: [0..4] (5 items), [5..6] (2 items)
        # Destinations: [0..4] (5 items), [5] (1 item)
        # Total requests: 2 * 2 = 4

        # Mock responses for each call
        # We need to simulate the OSRM response structure: {"code": "Ok", "distances": [[...]]}
        # The size of returned matrix depends on the chunk

        def side_effect(url):
            # Parse URL to determine chunk size
            # url contains coordinates and sources/destinations params
            # Simplified mock: just return a matrix of correct size filled with 1.0
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            query = urllib.parse.parse_qs(parsed.query)
            sources = query['sources'][0].split(';')
            dests = query['destinations'][0].split(';')

            num_rows = len(sources)
            num_cols = len(dests)

            distances = [[1.0 for _ in range(num_cols)] for _ in range(num_rows)]

            mock_resp = Mock()
            mock_resp.json.return_value = {"code": "Ok", "distances": distances}
            mock_resp.raise_for_status = Mock()
            return mock_resp

        mock_get.side_effect = side_effect

        matrix = self.client.get_distance_matrix(origins, destinations)

        self.assertEqual(len(matrix), 7)
        self.assertEqual(len(matrix[0]), 6)

        # Verify all values are 1.0 (from mock)
        for row in matrix:
            for val in row:
                self.assertEqual(val, 1.0)

        # Verify number of calls
        # 4 calls expected
        self.assertEqual(mock_get.call_count, 4)

    @patch('src.logic.osrm.requests.get')
    def test_get_distance_matrix_error(self, mock_get):
        origins = [(0,0)]
        destinations = [(1,1)]

        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = requests.exceptions.RequestException("Network Error")
        mock_get.return_value = mock_resp

        matrix = self.client.get_distance_matrix(origins, destinations)

        # Should return estimated distance (fallback), not None
        # Coords (0,0) to (1,1) is approx 157km * 1.3 = 204km
        self.assertIsNotNone(matrix[0][0])
        self.assertGreater(matrix[0][0], 0)

if __name__ == '__main__':
    unittest.main()
