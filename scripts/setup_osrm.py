import os
import subprocess
import sys
import shutil

# Configuration
OSM_PBF_URL = "https://download.geofabrik.de/south-america/brazil-latest.osm.pbf"
DATA_DIR = os.path.join(os.getcwd(), "data", "osrm")
OSM_PBF_FILE = "brazil-latest.osm.pbf"
OSRM_FILE_BASE = "brazil-latest.osrm"

def run_command(command, check=True):
    """Runs a shell command and prints output."""
    print(f"Running: {command}")
    try:
        subprocess.run(command, shell=True, check=check, text=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {command}")
        print(e)
        sys.exit(1)

def ensure_docker():
    """Checks if Docker is installed and running."""
    try:
        subprocess.run(["docker", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Docker is not installed or not in PATH.")
        sys.exit(1)

def download_pbf():
    """Downloads the Brazil OSM PBF file if it doesn't exist."""
    pbf_path = os.path.join(DATA_DIR, OSM_PBF_FILE)
    if os.path.exists(pbf_path):
        print(f"File {pbf_path} already exists. Skipping download.")
        return

    print(f"Downloading {OSM_PBF_URL}...")
    import urllib.request

    # Create directory if not exists
    os.makedirs(DATA_DIR, exist_ok=True)

    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = downloaded * 100 / total_size
            sys.stdout.write(f"\rDownloading... {percent:.2f}% ({downloaded / (1024*1024):.1f} MB)")
            sys.stdout.flush()

    urllib.request.urlretrieve(OSM_PBF_URL, pbf_path, reporthook=report)
    print("\nDownload complete.")

def process_osrm():
    """Runs OSRM extraction and contraction."""
    # Check if .osrm.hsgr exists (result of contraction)
    hsgr_path = os.path.join(DATA_DIR, f"{OSRM_FILE_BASE}.hsgr")
    if os.path.exists(hsgr_path):
        print(f"OSRM data {hsgr_path} already exists. Skipping processing.")
        return

    print("Processing OSRM data (Extract & Contract)...")

    # Create .stxxl config for disk-based processing (avoid OOM)
    # This tells OSRM to use a 50GB swap file in /data/stxxl (increase safety margin for whole Brazil)
    stxxl_path = os.path.join(DATA_DIR, ".stxxl")
    with open(stxxl_path, "w") as f:
        f.write("disk=/data/stxxl,50000,syscall")

    # 1. Extract
    # We mount the .stxxl file to /opt/.stxxl (where OSRM looks for it by default or we set env var)
    # Actually easier to just map it to /data/.stxxl and point STXXLCFG env var
    # Added --small-component-size 50000 to keep larger isolated networks (rural areas)
    extract_cmd = (
        f"docker run --rm -v \"{DATA_DIR}:/data\" -e STXXLCFG=/data/.stxxl osrm/osrm-backend "
        f"osrm-extract -p /opt/car.lua /data/{OSM_PBF_FILE} --small-component-size 50000"
    )
    print("Running extraction (this may take a while using disk swap)...")
    run_command(extract_cmd)

    # 2. Partition (MLD) - Partition the graph
    partition_cmd = (
        f"docker run --rm -v \"{DATA_DIR}:/data\" -e STXXLCFG=/data/.stxxl osrm/osrm-backend "
        f"osrm-partition /data/{OSRM_FILE_BASE}"
    )
    print("Running partitioning (MLD)...")
    run_command(partition_cmd)

    # 3. Customize (MLD) - Customize the graph
    customize_cmd = (
        f"docker run --rm -v \"{DATA_DIR}:/data\" -e STXXLCFG=/data/.stxxl osrm/osrm-backend "
        f"osrm-customize /data/{OSRM_FILE_BASE}"
    )
    print("Running customization (MLD)...")
    run_command(customize_cmd)

    # Cleanup stxxl file to free space
    stxxl_data = os.path.join(DATA_DIR, "stxxl")
    if os.path.exists(stxxl_data):
        try:
            os.remove(stxxl_data)
        except OSError:
            pass

    # Cleanup intermediate files? Maybe keep them for now.
    print("OSRM processing complete.")

def main():
    print("Starting OSRM Setup...")
    ensure_docker()

    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)

    download_pbf()
    process_osrm()

    print("\nSetup finished successfully!")
    print(f"Data is ready in {DATA_DIR}")
    print("You can now run 'docker-compose up' to start the application.")

if __name__ == "__main__":
    main()
