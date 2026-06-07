import requests
import math
from typing import List, Tuple, Optional

class OSRMClient:
    def __init__(self, base_url: str = "http://osrm:5000", max_table_size: int = 100):
        self.base_url = base_url.rstrip("/")
        self.max_table_size = max_table_size

    def _haversine_distance(self, coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
        """
        Calculates the great-circle distance between two points on the Earth surface.
        """
        lat1, lon1 = coord1
        lat2, lon2 = coord2
        R = 6371000  # Earth radius in meters

        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)

        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _fallback_route(self, origin, destination):
        dist_straight = self._haversine_distance(origin, destination)
        return {
            'geometry': {
                'type': 'LineString',
                'coordinates': [[origin[1], origin[0]], [destination[1], destination[0]]]
            },
            'distance': dist_straight * 1.3,
            'duration': (dist_straight * 1.3) / (60 * 1000 / 3600),
            'type': 'fallback'
        }


    def get_distance_matrix(self, origins: List[Tuple[float, float]], destinations: List[Tuple[float, float]]) -> List[List[Optional[float]]]:
        """
        Calculates the distance matrix between origins and destinations using OSRM Table API.
        Falls back to Haversine distance * 1.3 (correction factor) if OSRM fails or returns None.

        Args:
            origins: List of (latitude, longitude) tuples.
            destinations: List of (latitude, longitude) tuples.

        Returns:
            A 2D list (matrix) where matrix[i][j] is the distance in meters from origins[i] to destinations[j].
        """
        if not origins or not destinations:
            return []

        # Initialize result matrix with None
        num_origins = len(origins)
        num_destinations = len(destinations)
        matrix = [[None for _ in range(num_destinations)] for _ in range(num_origins)]

        # Chunk processing to respect OSRM limits
        # We need to split origins and destinations such that the total number of coordinates
        # sent in one request does not exceed max_table_size.
        # Actually, for table service, max_table_size is typically the total number of coordinates in the URL.
        # Let's say we split origins into chunks of size A and destinations into chunks of size B
        # such that A + B <= max_table_size.
        # A safe bet is max_table_size // 2 for both.

        chunk_size = self.max_table_size // 2

        for i in range(0, num_origins, chunk_size):
            origin_chunk = origins[i : i + chunk_size]
            origin_indices = range(len(origin_chunk))

            for j in range(0, num_destinations, chunk_size):
                dest_chunk = destinations[j : j + chunk_size]
                dest_indices = range(len(origin_chunk), len(origin_chunk) + len(dest_chunk))

                # Prepare coordinates list: origins first, then destinations
                # OSRM expects: lon,lat
                coords = [f"{lon},{lat}" for lat, lon in origin_chunk] + \
                         [f"{lon},{lat}" for lat, lon in dest_chunk]

                coords_str = ";".join(coords)

                # Construct query
                # sources=0;1;2... (indices of origins in coords list)
                # destinations=3;4;5... (indices of destinations in coords list)
                sources_str = ";".join(map(str, origin_indices))
                dest_str = ";".join(map(str, dest_indices))

                url = f"{self.base_url}/table/v1/driving/{coords_str}?sources={sources_str}&destinations={dest_str}&annotations=distance"

                try:
                    response = requests.get(url)
                    response.raise_for_status()
                    data = response.json()

                    if data["code"] != "Ok":
                        print(f"OSRM Error: {data.get('message', 'Unknown error')}")
                        continue

                    distances = data["distances"]

                    # Check for extreme snapping (e.g. point in ocean snapped to coast)
                    # We look at the 'sources' and 'destinations' arrays in the response
                    bad_source_indices = set()
                    bad_dest_indices = set()

                    for idx, src in enumerate(data.get("sources", [])):
                        if src.get("distance", 0) > 50000:
                            bad_source_indices.add(idx)

                    for idx, dst in enumerate(data.get("destinations", [])):
                        if dst.get("distance", 0) > 50000:
                            bad_dest_indices.add(idx)

                    # Fill the result matrix
                    for r_idx, row in enumerate(distances):
                        for c_idx, dist in enumerate(row):
                            if r_idx in bad_source_indices or c_idx in bad_dest_indices:
                                matrix[i + r_idx][j + c_idx] = None # Will be handled by fallback
                            elif dist is not None:
                                matrix[i + r_idx][j + c_idx] = float(dist)
                            else:
                                matrix[i + r_idx][j + c_idx] = None

                except requests.RequestException as e:
                    print(f"Request failed: {e}")
                    # Keep None in matrix for failed chunks
                    pass

        # Fallback pass: If any cell is None, calculate estimated distance
        # Estimation: Haversine Distance * 1.3 (Tortuosity factor)
        for i in range(num_origins):
            for j in range(num_destinations):
                if matrix[i][j] is None:
                    dist_straight = self._haversine_distance(origins[i], destinations[j])
                    matrix[i][j] = dist_straight * 1.3

        return matrix

    def get_route(self, origin: Tuple[float, float], destination: Tuple[float, float]) -> Optional[dict]:
        """
        Calculates the route between an origin and a destination using OSRM Route API.

        Args:
            origin: (latitude, longitude) tuple.
            destination: (latitude, longitude) tuple.

        Returns:
            A dictionary containing:
            - 'geometry': Polyline string or coordinates (depending on request, here we use overview=full -> geometry string or geojson)
            - 'distance': Distance in meters.
            - 'duration': Duration in seconds.
            Returns None if unreachable.
        """
        # OSRM expects: lon,lat
        origin_str = f"{origin[1]},{origin[0]}"
        dest_str = f"{destination[1]},{destination[0]}"

        # Request full geometry (overview=full) and geometries=geojson for easy plotting in Plotly
        url = f"{self.base_url}/route/v1/driving/{origin_str};{dest_str}?overview=full&geometries=geojson"

        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if data["code"] != "Ok" or not data["routes"]:
                print(f"OSRM Route Error: {data.get('message', 'No route found')}")
                return self._fallback_route(origin, destination)

            # Check snapping distance of waypoints. Max allowed is 50km (50000 meters)
            waypoints = data.get("waypoints", [])
            for wp in waypoints:
                snap_dist = wp.get("distance", 0)
                if snap_dist > 50000:
                    print(f"OSRM Route snapped too far: {snap_dist}m. Falling back to straight line.")
                    return self._fallback_route(origin, destination)

            route = data["routes"][0]
            return {
                'geometry': route['geometry'],
                'distance': route['distance'],
                'duration': route['duration'],
                'type': 'osrm'
            }


        except requests.RequestException as e:
            print(f"Route request failed: {e}")
            return self._fallback_route(origin, destination)
