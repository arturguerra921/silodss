# SiloDSS
**A Decision Support System for Agricultural Logistics and Optimization**

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/arturguerra921/silodss)](LICENSE)
[![Tests Status](https://img.shields.io/badge/tests-passed-green)](#running-tests)

---

## Overview

SiloDSS is a professional, bilingual (English/Portuguese) Decision Support System (DSS) designed to optimize multi-period agricultural product distribution networks. The application minimizes total logistics cost—including transport freight, storage, transshipment, infrastructure opening, capacity expansion, and bulkification—by employing Mixed-Integer Linear Programming (MILP) models. 

Integrating real-road network routing via the Open Source Routing Machine (OSRM) and advanced statistical/neural forecasting models, SiloDSS empowers planners to evaluate complex logistics strategies and manage risks across deterministic and stochastic scenarios.

---

## Key Features

* **Forecasting & Predictive Modeling**: Predict future supply and demand trends using SARIMA, Prophet, XGBoost, and LSTM neural networks, complete with error metrics (WMAPE, RMSE, MAE) and residual diagnostics.
* **OSRM Road Network Routing**: Compute exact highway distances and durations across Brazil, falling back dynamically to Haversine geodesic calculations in remote areas.
* **Comprehensive Logistics Modeling**: Optimize storage tariffs, state-specific freight rates, warehouse-to-warehouse transshipment discounts, capacity expansion, and bulkification.
* **Deterministic & Two-Stage Stochastic Optimization**: Support standard single-scenario optimization or hedge strategic decisions against multiple uncertain scenarios (Pessimistic, Expected, Optimistic).
* **Interactive Dashboard**: Feature-rich, bilingual UI built with Dash and Bootstrap Components following a strict 8pt grid system.
* **Bilingual Support (i18n)**: Fully localized translation interface allowing instantaneous switching between Portuguese and English.

---

## Technical Stack

* **Language**: Python 3.10+ (Python 3.12.13 recommended)
* **Frontend/UI**: Dash, Plotly, Dash Bootstrap Components
* **Optimization**: Pyomo (using Mixed-Integer Linear Programming) solved with CBC
* **Routing**: Open Source Routing Machine (OSRM), Requests
* **Data Processing**: Pandas, OpenPyXL
* **Forecasting**: Statsmodels (SARIMA), Prophet, XGBoost, TensorFlow/Keras (LSTM)

---

## Getting Started

### Prerequisites

* **Git**: To clone the repository.
* **Python**: Version 3.10 or higher.
* **Docker Desktop**: Required to run the OSRM routing engine.

---

### 1. Docker Setup (Recommended)

Docker automatically manages both the SiloDSS web application and the local OSRM routing server.

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/arturguerra921/silodss.git
   cd silodss
   ```

2. **Generate OSRM Map Data (One-Time Setup)**:
   This downloads and processes the latest map of Brazil (approx. 400-500 MB) for OSRM. Ensure Docker is running.
   ```bash
   python scripts/setup_osrm.py
   ```
   *Note: This can take 20-60 minutes depending on your computer's performance.*

3. **Launch all Services**:
   ```bash
   docker-compose up -d --build
   ```

4. **Access the App**:
   Navigate to **http://localhost:8050** in your browser.

---

### 2. Local Development Setup

For faster development iterations, run the Dash server locally while keeping the OSRM routing service running inside Docker.

1. **Start OSRM Service**:
   ```bash
   docker-compose up -d osrm
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -e .
   ```

4. **Run Server**:
   ```bash
   python run_server.py
   ```
   The local application will be available at **http://localhost:8050**.

---

## Dashboard Tab-by-Tab Workflow

SiloDSS organizes the planning workflow into 10 structured steps represented as tabs in the user interface.

---

### 1. Oferta (Supply)
Configure the time horizon and enter multi-year monthly supply datasets for agricultural products.
* **Timespan Configuration**: Define custom session-wide start and end years (e.g., 2026 to 2035). This locks once data is loaded to maintain consistency across all tabs.
* **Import & Auto-detection**: Import Excel/CSV files. The system automatically detects the start/end range and adjusts the configuration.
* **Manual Entry & Patterns**: Manually insert series per product-city combination using either **Constant Value** or **Linear Growth/Decline** patterns.
* **Data Inspection**: View the monthly supply trends through interactive Plotly charts and modify/delete specific entries in the editable DataTable.

---

### 2. Demanda (Demand)
Manage destination/client consumption requirements across the same temporal horizon.
* **Horizon Inheritance**: Automatically inherits the start and end years locked in the *Oferta* tab.
* **Manual & File Input**: Add monthly demand series for product-destination combinations via file upload or manual forms.
* **Filtering & Trends**: Cross-filter by product and city, visualize monthly trends, and edit or delete records inline.

---

### 3. Previsão (Prediction)
Run forecasting models on historical supply and demand series to predict future values.
* **Algorithm Selection**: Choose between statistical algorithms (**SARIMA**, **Prophet**) or machine learning/neural network models (**XGBoost**, **LSTM**).
* **Validation Parameters**: Set the test split size (months) to calculate accuracy metrics and choose the future prediction horizon.
* **Accuracy KPIs**: View quality metrics including **WMAPE (%)** (Weighted Mean Absolute Percentage Error), **RMSE**, and **MAE**, alongside a qualitative rating indicator (Excellent, Good, Regular, Bad).
* **Diagnostics**: Analyze forecast charts alongside residuals time-series and histogram plots to verify model fit.

---

### 4. Armazéns (Warehouses)
Manage the storage network, specifying existing assets and potential candidate hubs.
* **Warehouse Types**: Classify structures (e.g., Silo, Graneleiro, Convencional) and status (Existente / Candidato).
* **Location Mapping**: Select the municipality; the system resolves coordinates automatically, allowing manual overrides when needed.
* **Capabilities & Limits**: Specify static capacity, daily reception/shipping limits, and dynamic capacity multipliers.
* **Upgrades & Costs**: Define maximum expansion capacity, fixed/variable expansion costs, bulkification capabilities/costs, and opening investment costs for candidates.

---

### 5. Produto e Armazéns (Product & Warehouses)
Establish compatibility rules between agricultural products and storage structures.
* **Bespoke Matrix**: Map products to compatible warehouse types (e.g., specifying if Soy can be stored in a Conventional warehouse vs. a Silo).
* **Policy Enforcement**: Uncompatible combinations are automatically excluded from the optimization flow.

---

### 6. Custos (Costs)
Define the financial tariffs driving the optimization objective.
* **Storage Tariffs**: Edit monthly storage costs per ton for each product. Includes a mandatory "Outros" fallback row for unlisted items.
* **Freight rates**: Configure transportation costs per state (R$/ton-km) in an editable table.
* **Spreadsheet Utility**: Supports bulk template downloads and CSV/Excel uploads for quick setup.

---

### 7. Matriz de Distâncias (Distance Matrix)
Calculate the spatial routing matrix representing the physical logistics network.
* **Segment Breakdown**: Computes distances for three key corridors: Supply to Warehouses, Warehouses to Demand, and Warehouses to Warehouses.
* **Routing Engine**: Leverages OSRM for real highway distance and time calculations.
* **Fallback Mode**: Automatically detects failed queries and falls back to geodesic (Haversine) calculations, highlighted on the map as straight red lines.
* **Map & Detail**: Click on any cell in the generated distance table to visualize the exact route on the interactive Plotly map.

---

### 8. Configuração do Modelo (Model Configuration)
Fine-tune constraints and specify the mathematical optimization behavior.
* **Model Type**: Select between **Deterministic** (nominal expected values) and **Two-Stage Stochastic** (multi-scenario risk hedging).
* **Stochastic Probability & Errors**: Assign probability weights to Pessimistic, Expected, and Optimistic scenarios, and choose to derive errors from forecasting WMAPEs or manual percentages.
* **General Constants**: Configure operational days per period, transshipment discount factors (\(\alpha\)), solver gap limit, and solver timeout.
* **Physical Extensions & Bulkification**: Toggle whether Pyomo can dynamically decide to expand capacity or bulkify warehouses, respecting custom limits and costs.
* **Pareto Route Filtering**: Option to keep only the top 20% shortest routes per origin to accelerate solver speed (80/20 rule).

---

### 9. Resultados (Results)
Execute the optimization solver and analyze the resulting logistics network.
* **Global KPIs**: View total optimal cost, tons moved, total distance traveled, freight cost, storage cost, opening cost, expansion cost, and bulkification cost.
* **Decision Highlights**: Count opened candidates, expansions, bulkifications, and total infrastructure investments.
* **Details & Export**: Review the interactive warehouse performance table (turnover ratios, outflows, ending stocks) and download Excel/PDF reports.
* **Network Flow Map**: Inspect the optimal routing decisions on the interactive flow map.

---

### 10. Comparação de Cenários (Scenario Comparison)
Available only after executing a Stochastic optimization run.
* **Stochastic Value Analysis**: Calculates **EVPI** (Expected Value of Perfect Information) and **VSS** (Value of Stochastic Solution) to evaluate the economic benefit of hedging against uncertainty.
* **Scenario Performance**: Compare KPIs side-by-side across Pessimistic, Expected, and Optimistic scenarios.
* **Visual Breakdown**: Grouped bar charts illustrate cost components per scenario, and line charts plot the aggregated warehouse inventory evolution over time.

---

## Mathematical Formulations

SiloDSS solves a multi-period, multi-commodity, capacitated transshipment problem with facility location, capacity expansion, and technology upgrading.

* For the single-scenario formulation, see [deterministic_model.md](deterministic_model.md).
* For the two-stage stochastic programming formulation, see [stochastic_model.md](stochastic_model.md).

---

## Running Tests

To run the backend test suite and verify optimization, forecasting, and data-parsing logic:
```bash
python -m unittest discover tests
```

---

## Project Structure

```
silodss/
├── docker-compose.yml       # Docker services configuration
├── pyproject.toml           # Package metadata and dependencies
├── run_server.py            # Local execution script
├── wsgi.py                  # Gunicorn entry point
├── deterministic_model.md   # Mathematical model details
├── stochastic_model.md      # Stochastic model details
├── tests/                   # Backend unit tests
├── benchmark/               # Benchmark scripts
├── scripts/                 # Setup scripts (setup_osrm.py)
└── src/
    ├── locales/             # i18n English/Portuguese translation files
    ├── logic/               # Optimization, OSRM, prediction, and utility logic
    └── view/                # Dash layouts, callbacks, themes, and page definitions
```
