# GranumDSS
**A Decision Support System for Agricultural Logistics and Optimization**

[![Build Status](https://img.shields.io/github/actions/workflow/status/arturguerra921/granum/main.yml?branch=main)](https://github.com/arturguerra921/granum/actions)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/arturguerra921/granum)](https://github.com/arturguerra921/granum/blob/main/LICENSE)

## Overview
GranumDSS is a comprehensive Decision Support System (DSS) developed to optimize the allocation of agricultural products in warehouses, minimizing freight and storage costs. It processes complex agricultural supply chain data, calculates optimal routes, and estimates operational costs using advanced mathematical modeling alongside Open Source Routing Machine (OSRM) integration.

## Key Features
* **Distance Matrix Generation**: Computes exact distances and durations using OSRM for real road networks, falling back to Haversine calculations when necessary.
* **Cost Calculation**: Accurately evaluates transportation costs considering distance, freight rates, and minimum route thresholds.
* **Route Optimization**: Employs Mixed-Integer Linear Programming (MILP) using Pyomo and the CBC solver to calculate optimal product allocations between supply origins and destination warehouses.
* **Multilingual Dashboard**: Features an interactive web-based interface built with Dash, offering translations between English and Portuguese for enhanced accessibility.
* **Data Visualization**: Provides rich data insights, scenario filtering (e.g., Pareto 80/20 analysis), and optimization reports tailored for supply chain professionals.

## Why GranumDSS?
Managing agricultural logistics is a complex, high-stakes operational challenge. GranumDSS is designed specifically to aid planners and decision-makers in navigating these complexities. By leveraging mathematical optimization and Operations Research techniques, the system moves beyond simple spreadsheets. It rigorously evaluates thousands of product-warehouse combinations, respecting constraints such as warehouse capacity, minimum reception volumes, and upper flow limits.

The result is a structured, data-driven approach to scenario exploration. Decision-makers can visualize the impact of different logistics strategies, dynamically adjust parameters, and ultimately minimize the total costs associated with grain storage and transport—turning raw data into actionable enterprise intelligence.

## Technical Stack
* **Language**: Python 3.10+
* **Frontend/Dashboard**: Dash, Plotly, Dash Bootstrap Components
* **Optimization**: Pyomo (with the CBC solver)
* **Routing**: Open Source Routing Machine (OSRM), Requests
* **Data Processing**: Pandas, OpenPyXL

## Getting Started

The recommended way to run GranumDSS is with Docker, as it manages both the application and the OSRM routing engine.

### Prerequisites

*   **Git**: To clone the repository.
*   **Python**: To execute the initial map setup script.
*   **Docker Desktop**: Must be installed and running to manage the application services.

### 1. Clone the Repository

First, clone the project to your local machine:
   ```bash
   git clone https://github.com/arturguerra921/granum.git
   cd granum
   ```

### 2. Generate OSRM Map Data (One-Time Setup)

Before launching the application, you must process the map data for the routing engine. This is a **one-time step** that can take **20-60 minutes** depending on your computer's performance.

This script will:
1.  Download the latest map of Brazil (approx. 400-500 MB).
2.  Use Docker to process the map into a format OSRM can use.

Run the following command from the project root:
```bash
python scripts/setup_osrm.py
```

> **Note:** Ensure Docker Desktop is running before executing this script. You will see a "OSRM processing complete" message when it's done.

### 3. Launch the Application

With the map data ready, you can now start all the services using Docker Compose:
   ```bash
   docker-compose up -d --build
   ```

### 4. Access the Application

Open your browser and navigate to: **http://localhost:8050**

---

### Alternative: Local Development Setup

This setup is for developers who wish to run the Python application on the host machine for faster iteration, while still using Docker for the OSRM service.

1.  **Complete the one-time map generation**: Follow steps 1 and 2 from the guide above.
2.  **Start only the OSRM service**: `docker-compose up -d osrm`
3.  **Install dependencies locally**: It's recommended to use a virtual environment. `pip install -e .`
4.  **Run the Dash server**: `python run_server.py`
5.  The application will be available at `http://localhost:8050` and will connect to the OSRM service running in Docker.

## Usage Workflow
The application is designed around a 7-step workflow, guiding the user through the data input and optimization process via a series of tabs:

1.  **Oferta (Supply)**: Input the quantity of products available by city. You can upload a spreadsheet or add data manually.
2.  **Armazéns (Warehouses)**: Manage the destination warehouses. A default database is provided, which can be updated with recent data from Conab or a custom user-provided file.
3.  **Produto e Armazéns (Product & Warehouses)**: Define compatibility rules, specifying which types of warehouses can store each product.
4.  **Custos (Costs)**: Configure storage tariffs and per-state freight costs (R$/ton-km).
5.  **Matriz de Distâncias (Distance Matrix)**: Calculate the road distance matrix between all supply origins and warehouse destinations.
6.  **Configuração do Modelo (Model Configuration)**: Set operational constraints for the optimization model, such as reception limits, freight rules, or applying the Pareto Principle to filter routes.
7.  **Resultados (Results)**: Run the optimization model and view the results, including key performance indicators, a map of the suggested logistic network, and downloadable reports.

## Running Tests
To run the backend test suite, execute the following command from the project root. This will automatically discover and run all tests within the `tests` directory:
```bash
python -m unittest discover tests
```

## Project Structure
```
granum/
├── docker-compose.yml       # Docker services configuration
├── pyproject.toml           # Project dependencies and metadata
├── run_server.py            # Local execution script
├── wsgi.py                  # Gunicorn entry point for production
├── src/
│   ├── view/                # Dash frontend, layout, and components
│   ├── logic/               # Core business logic (OSRM, Optimization, i18n)
│   ├── locales/             # Translation files (en.json, pt.json)
│   └── assets/              # Static assets (images, CSS)
├── tests/                   # Backend test suite
├── benchmark/               # Benchmarking scripts and output
└── scripts/                 # Utility scripts for OSRM setup and benchmarking
```
