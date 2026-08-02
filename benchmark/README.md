# SiloDSS Benchmarking

This directory contains the configurations, reference spreadsheets, and outputs of the automated benchmarking suite.

> [!IMPORTANT]
> The spreadsheets in this directory (`Edited_Supply.xlsx`, `Edited_Demand.xlsx`, `Warehouses.xlsx`, etc.) contain **example data provided by the developers** to demonstrate the model functionality. You should update or replace these files with your own custom data for your specific use cases.

---

## Reference Input Files (Base Data Pools)

The benchmarking script uses the files in this directory to sample and scale up the optimization problem size:

*   **`Edited_Supply.xlsx`**: The base supply data containing production points (cities, coordinates, products, monthly production).
*   **`Edited_Demand.xlsx`**: The base domestic demand data containing consumption points.
*   **`Warehouses.xlsx`**: A registry of candidate and existing warehouses used for sizing.
*   **`Armazens_Cadastrados_SICARM.txt`**: A semi-colon separated database of registered warehouses in Brazil. Used to draw extra warehouse nodes when the problem size exceeds the list in `Warehouses.xlsx`.
*   **Cost & Tariff Files**:
    *   `Tarifa_de_Armazenagem.xlsx`: Product storage tariff reference rates.
    *   `Valor_Tonelada_km.xlsx`: Freight rate per kilometer for transportation.

---

## Configuration & Logic

The benchmarking runs are driven by **`benchmark_config.json`**. The script executes in a loop, scaling the problem size upwards at each iteration (e.g. +5 supply nodes, +5 demand nodes, +10 warehouses).

*   **Feasibility Scaling & Warning**: The script supports a feasibility scaling mechanism configured via `"enable_feasibility_scaling"` and `"feasibility_scaling_factor"` inside `benchmark_config.json`.
    *   **Purpose**: During artificial benchmark runs, random sampling of subset nodes can easily result in mathematical infeasibility (total supply < total domestic demand). If enabled, the script dynamically scales up the production weights during deficit periods by the scaling factor to keep the stress-test loop executing.
    *   **Real Case Studies Warning**: This feature is **only advisable for benchmark testing**. In actual real-world optimization models, this option should be turned off. Your true supply data must naturally exceed the domestic demand. If it falls short, the optimization model will trigger Big-M penalties (for recourse unmet demand and static emergency capacity), which will heavily inflate the objective function cost and distort realistic operational costs. If feasibility scaling is disabled and a sampled iteration has a supply deficit, the script will raise a validation error and exit.
*   **Warehouse Sizing**: Any extra warehouses added from the SICARM text registry are split 50/50: half are set as Existing, and the other half are converted to Candidates. The construction costs for new Candidates are estimated dynamically using the average cost-to-capacity ratio from the base candidate sheet (~R$ 1,148.75 / ton) and the expansion/upgrade costs are configured in `benchmark_config.json`.
*   **Routing**: The local OSRM Docker container calculates exact driving distances dynamically.

---

## Running the Benchmark (Docker)

To run the benchmarking suite inside the preconfigured Docker container (where Pyomo and solvers are set up):

### 1. Run with Open Source Solver (CBC)
Ensure `"solver_name": "cbc"` is set in `benchmark_config.json`, then run:
```bash
docker-compose exec app python scripts/benchmark_model.py
```

### 2. Run with Gurobi (Stateless / Secure)
To run with Gurobi without mounting local directories or checking secrets into version control, pass the license content as an environment variable (`GUROBI_LICENSE_DATA`):

#### In PowerShell (Host):
```powershell
# 1. Load the gurobi.lic file contents into a shell variable
$lic = Get-Content secrets/gurobi.lic -Raw

# 2. Inject it into the container and execute the script
docker-compose exec -e GUROBI_LICENSE_DATA="$lic" app python scripts/benchmark_model.py
```

#### Reverting to Fallback (Older Docker Versions):
```bash
docker-compose exec app env GUROBI_LICENSE_DATA="$lic" python scripts/benchmark_model.py
```

---

## Generated Output Files

Once the script completes (terminating after an iteration's solve time exceeds 600s), the following files are exported to this directory:

*   **`benchmark_results_summary.xlsx`**: A spreadsheet summarizing performance metrics (solved status, objective value, execution time, variables, constraints, and candidate warehouse decisions) for all iterations.
*   **`last_supply.xlsx`**, **`last_demand.xlsx`**, **`last_warehouses.xlsx`**: GUI-ready Excel spreadsheets containing the datasets of the final run. These can be uploaded directly in the Dash web interface to replicate and visually verify results.
*   **`last_configurations.json`**: The config file of the final run.
*   **`last_prediction_results.json`**: Time-series forecast data if prediction-based stochastic mode was active.