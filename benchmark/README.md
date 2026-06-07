# Granum Benchmarking

This directory stores the generated output files (`.xlsx`) from running the benchmarking suite for the Granum project optimization model.

## Running the Benchmark (Docker)

To avoid discrepancies caused by different operating systems, it is recommended to run the benchmarking script **inside** the Docker container.

The `docker-compose.yml` file is configured to map the `benchmark` and `scripts` directories between the Docker container and your host machine. This means you can run the script inside the container and the resulting `.xlsx` files will be saved in this `benchmark` directory on your local machine.

### Prerequisites

Make sure the Docker environment is running:

```bash
docker-compose up -d
```

### Execution Command

To execute the benchmarking script inside the running `app` container, open your terminal (from the project root) and run the following command:

```bash
docker-compose exec app python scripts/benchmark_model.py
```

### Outputs

Once the script completes, the following files will be generated in this directory:
- `benchmark_results.xlsx`: Detailed results for each test case iteration.
- `benchmark_supply_biggest.xlsx`: The largest generated supply dataset.
- `benchmark_demand_biggest.xlsx`: The largest generated demand dataset.