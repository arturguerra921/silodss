"""
Automated Benchmarking Script for the Optimization Model

Prerequisites:
1. OSRM Docker Server:
Make sure the OSRM Docker container is running locally and accessible on port 5000
before executing this script locally.
Run: `docker-compose up -d osrm`

2. CBC Solver:
Since you are running this outside the main Docker container, you MUST have the 'cbc'
solver installed on your host machine to execute Pyomo optimization routines.
- Windows: Download binaries from https://github.com/coin-or/Cbc/releases, extract, and add the 'bin' folder to your system PATH.
- Ubuntu/Debian: `sudo apt-get install coinor-cbc`
- macOS: `brew install cbc`
"""
import os
import time
import pandas as pd
import numpy as np

# =============================================================================
# MODEL PARAMETERS CONFIGURATION
# =============================================================================
FORCE_MILP = False # Set to True to force the use of the MILP model regardless of other inputs
TOGGLE_MIN_MAX_CAPACITY = False # Set to True to use MILP model
INPUT_MIN_LOAD = None
INPUT_MAX_LOAD = None
INPUT_ALLOCATION_DAYS = 1.0
INPUT_MIN_FREIGHT = None
INPUT_MAX_FREIGHT = None
TOGGLE_PARETO = False
TOGGLE_USE_RECEPTION = False

# =============================================================================
# DATA GENERATION CONFIGURATION
# =============================================================================
INICIAL_OFERTAS = 30
INICIAL_ARMAZENS = 2
MAX_RECEPTION_PERCENTAGE = 0.2
GAPS = [0.05, 0.01]
TIME_LIMIT_SECONDS = 600  # Maximum time in seconds for the solver per iteration

# =============================================================================
# FILE PATHS
# =============================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUNICIPIOS_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'municipios.csv')
ESTADOS_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'estados.csv')
ARMAZENS_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'Armazens_Cadastrados_Base.csv')
TARIFA_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'Tarifa_de_Armazenagem.csv')
FRETE_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'Valor_Tonelada_km.csv')

PRODUTOS = ['Soja', 'Milho', 'Trigo', 'Arroz', 'Café', 'Feijão', 'Sorgo', 'Algodão', 'Aveia']

def load_base_data():
    if not all(os.path.exists(f) for f in [MUNICIPIOS_CSV, ESTADOS_CSV, ARMAZENS_CSV]):
        raise FileNotFoundError("One or more base CSV files are missing in src/view/assets/data/.")

    df_municipios = pd.read_csv(MUNICIPIOS_CSV)
    df_estados = pd.read_csv(ESTADOS_CSV)

    if '\ufeffcodigo_uf' in df_estados.columns:
        df_estados.rename(columns={'\ufeffcodigo_uf': 'codigo_uf'}, inplace=True)

    df_municipios = pd.merge(df_municipios, df_estados[['codigo_uf', 'uf']], on='codigo_uf', how='left')
    df_municipios['nome_formatado'] = df_municipios['nome'] + ' - ' + df_municipios['uf']

    df_armazens = pd.read_csv(ARMAZENS_CSV, sep=';', skiprows=1, encoding='latin1')

    def parse_number(val):
        if pd.isna(val) or val == '':
            return np.nan
        if isinstance(val, (int, float)):
            return float(val)
        val = str(val).strip()
        if not val:
            return np.nan
        val = val.replace('.', '').replace(',', '.')
        try:
            return float(val)
        except ValueError:
            return np.nan

    df_armazens['_cap_estatica_num'] = df_armazens['Capacidade (t)'].apply(parse_number)
    df_armazens['_cap_recepcao_num'] = df_armazens['Capacidade de Recepção'].apply(parse_number)

    filtro_armazens_validos = (df_armazens['_cap_estatica_num'] > 0) & (df_armazens['_cap_recepcao_num'] > 0)
    df_armazens_validos = df_armazens[filtro_armazens_validos].copy()

    total_armazens_validos = len(df_armazens_validos)
    if total_armazens_validos == 0:
        raise ValueError("Nenhum armazém com capacidades válidas encontrado.")

    return df_municipios, df_armazens_validos

def generate_test_pair(num_ofertas, num_armazens, df_municipios, df_armazens_validos):
    np.random.seed(42)  # Seed para manter exemplos consistentes

    total_armazens_validos = len(df_armazens_validos)

    # Base de Ofertas
    indices_municipios = np.random.choice(df_municipios.index, size=num_ofertas, replace=True)
    df_ofertas_base = df_municipios.loc[indices_municipios].copy().reset_index(drop=True)
    df_ofertas_base.rename(columns={'nome_formatado': 'Cidade', 'latitude': 'Latitude', 'longitude': 'Longitude'}, inplace=True)
    df_ofertas_base['Produto'] = np.random.choice(PRODUTOS, size=num_ofertas)

    # Base de Armazéns
    indices_armazens = np.random.choice(df_armazens_validos.index, size=num_armazens, replace=(num_armazens > total_armazens_validos))
    df_armazens_base = df_armazens_validos.loc[indices_armazens].copy().reset_index(drop=True)

    df_armazens_recorte = df_armazens_base.copy()
    total_estatica = df_armazens_recorte['_cap_estatica_num'].sum()
    total_recepcao = df_armazens_recorte['_cap_recepcao_num'].sum()
    recepcao_limite = total_recepcao * MAX_RECEPTION_PERCENTAGE

    df_armazens_final = df_armazens_recorte.drop(columns=['_cap_estatica_num', '_cap_recepcao_num'])

    # Calculate maximum weight based strictly on available capacity
    peso_maximo_permitido = min(total_estatica, recepcao_limite)

    df_ofertas_recorte = df_ofertas_base.copy()
    pesos_aleatorios = np.random.uniform(low=10, high=1000, size=num_ofertas)
    fator_normalizacao = peso_maximo_permitido / pesos_aleatorios.sum()
    pesos_normalizados = pesos_aleatorios * fator_normalizacao

    df_ofertas_recorte['Peso (ton)'] = np.round(pesos_normalizados, 2)
    diferenca = peso_maximo_permitido - df_ofertas_recorte['Peso (ton)'].sum()
    df_ofertas_recorte.loc[df_ofertas_recorte.index[-1], 'Peso (ton)'] += diferenca
    df_ofertas_recorte['Peso (ton)'] = np.round(df_ofertas_recorte['Peso (ton)'], 2)

    colunas_finais_ofertas = ["Produto", "Peso (ton)", "Cidade", "Latitude", "Longitude"]
    df_ofertas_final = df_ofertas_recorte[colunas_finais_ofertas]

    return df_ofertas_final, df_armazens_final

# =============================================================================
# BENCHMARK LOGIC
# =============================================================================
import sys
sys.path.append(PROJECT_ROOT)

from src.logic.osrm import OSRMClient
from src.logic.optimization import run_optimization_model

def construct_df_compat(df_ofertas, df_armazens):
    """
    Constructs an in-memory compatibility DataFrame:
    Products (rows) x Warehouse Types (columns).
    Fills all cells with '☑' indicating full compatibility.
    """
    products = df_ofertas['Produto'].unique().tolist()

    # Using 'Tipo do Armazém' from demand dataset
    # If not present, fallback to a default type
    type_col = next((c for c in df_armazens.columns if 'tipo' in str(c).lower()), None)

    if type_col and not df_armazens[type_col].empty:
        warehouse_types = df_armazens[type_col].dropna().unique().tolist()
    else:
        warehouse_types = ["Armazém Convencional", "Silo"]

    # Initialize the DataFrame
    data = {wt: ['☑'] * len(products) for wt in warehouse_types}
    df_compat = pd.DataFrame(data)
    df_compat.insert(0, "Produto", products)

    return df_compat

def build_distance_matrix(df_ofertas, df_armazens):
    """
    Uses the OSRM client to construct the distance matrix expected by the model.
    """
    osrm_url = os.environ.get('OSRM_URL', 'http://localhost:5000')
    client = OSRMClient(base_url=osrm_url)

    # Process Supply Origins (Cidade + Lat + Lon)
    # Deduplicate origins exactly like the model does
    origins_df = df_ofertas[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts = origins_df['Cidade'].value_counts()
    duplicates = city_counts[city_counts > 1].index

    def rename_city(row):
        if row['Cidade'] in duplicates:
            return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
        return row['Cidade']

    origins_df['Cidade'] = origins_df.apply(rename_city, axis=1)

    origins_coords = list(zip(origins_df['Latitude'], origins_df['Longitude']))
    origins_names = origins_df['Cidade'].tolist()

    # Process Demand Destinations (CDA - Armazem - Municipio)
    cda_col = next((c for c in df_armazens.columns if 'cda' in str(c).lower()), None)
    name_col = next((c for c in df_armazens.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
    mun_col = next((c for c in df_armazens.columns if 'munic' in str(c).lower()), None)
    lat_col_dest = next((c for c in df_armazens.columns if 'lat' in str(c).lower()), None)
    lon_col_dest = next((c for c in df_armazens.columns if 'long' in str(c).lower()), None)

    destinations_coords = []
    destinations_names = []

    for idx, row in df_armazens.iterrows():
        # Coordinates
        lat = row[lat_col_dest] if lat_col_dest else None
        lon = row[lon_col_dest] if lon_col_dest else None

        # If coordinates are missing, fallback to 0.0 (simulating fallback straight lines)
        if pd.isna(lat) or pd.isna(lon):
            lat, lon = 0.0, 0.0

        destinations_coords.append((float(lat), float(lon)))

        # Naming format expected by distance matrix processing
        parts = []
        if cda_col and pd.notna(row[cda_col]):
            parts.append(str(row[cda_col]).strip())
        if name_col and pd.notna(row[name_col]):
            parts.append(str(row[name_col]).strip())
        if mun_col and pd.notna(row[mun_col]):
            parts.append(str(row[mun_col]).strip())

        dest_name_full = " - ".join(parts) if parts else f"Dest {idx}"
        destinations_names.append(dest_name_full)

    # Time and generate the matrix using OSRMClient
    start_time = time.time()
    matrix_data = client.get_distance_matrix(origins_coords, destinations_coords)
    matrix_time = time.time() - start_time

    # Construct the final DataFrame
    # Columns: Origem, Dest1, Dest2...
    df_dist = pd.DataFrame(matrix_data, columns=destinations_names)

    # Convert meters to km and round to 2 decimal places
    # OSRM output is typically in meters, the model expects km
    # We round to 2 decimal places to exactly match the Dash interface logic
    df_dist = (df_dist / 1000.0).round(2)

    df_dist.insert(0, 'Origem', origins_names)

    return df_dist, matrix_time

def main():
    print("Starting Benchmark Execution...")

    # Load Cost Datasets
    try:
        df_storage = pd.read_csv(TARIFA_CSV, sep=';', encoding='utf-8')
        df_freight = pd.read_csv(FRETE_CSV, sep=';', encoding='latin1')
    except Exception as e:
        print(f"Error loading cost datasets: {e}")
        return

    print("Loading base data for generation...")
    df_municipios, df_armazens_validos = load_base_data()

    all_results = []
    benchmark_dir = os.path.join(PROJECT_ROOT, "benchmark")
    os.makedirs(benchmark_dir, exist_ok=True)

    for gap_val in GAPS:
        print(f"\n====================================================================")
        print(f"STARTING BENCHMARK SUITE FOR GAP = {gap_val*100}%")
        print(f"====================================================================")

        num_ofertas = INICIAL_OFERTAS
        num_armazens = INICIAL_ARMAZENS
        idx = 1

        results_for_gap = []

        while True:
            print(f"\n--- Iteration {idx} (Gap: {gap_val*100}%) ---")
            print(f"Supply Nodes: {num_ofertas} | Demand Nodes: {num_armazens}")

            df_supply, df_demand = generate_test_pair(num_ofertas, num_armazens, df_municipios, df_armazens_validos)

            # Construct dynamic matrices
            df_compat = construct_df_compat(df_supply, df_demand)
            df_dist, df_dist_time = build_distance_matrix(df_supply, df_demand)

            # Run model
            try:
                # We copy df_supply and df_demand to avoid pandas SettingWithCopyWarnings
                # when the model logic modifies them in-place.
                log_filename, results_dict = run_optimization_model(
                    df_supply=df_supply.copy(),
                    df_demand=df_demand.copy(),
                    df_compat=df_compat,
                    df_dist=df_dist,
                    df_freight=df_freight,
                    df_storage=df_storage,
                    detailed_log=False,
                    toggle_pareto=TOGGLE_PARETO,
                    toggle_min_max_capacity=TOGGLE_MIN_MAX_CAPACITY,
                    input_min_load=INPUT_MIN_LOAD,
                    input_max_load=INPUT_MAX_LOAD,
                    toggle_use_reception=TOGGLE_USE_RECEPTION,
                    input_allocation_days=INPUT_ALLOCATION_DAYS,
                    input_min_freight=INPUT_MIN_FREIGHT,
                    input_max_freight=INPUT_MAX_FREIGHT,
                    solver_gap=gap_val,
                    force_milp=FORCE_MILP,
                    lang="pt"
                )

                # Extract metrics
                execution_time = results_dict.get("kpis", {}).get("execution_time", 0.0)
                optimal_value = results_dict.get("objective", 0.0)
                status = results_dict.get("status", "unknown")
                gap_achieved = results_dict.get("kpis", {}).get("gap", "N/A")

                model_stats = results_dict.get("model_stats", {})
                tot_vars = model_stats.get("total_variables", 0)
                tot_cons = model_stats.get("total_constraints", 0)
                tot_iters = model_stats.get("iterations", 0)
                tot_nodes = model_stats.get("nodes", 0)
                bin_vars = model_stats.get("binary_variables", 0)
                int_vars = model_stats.get("integer_variables", 0)
                cont_vars = model_stats.get("continuous_variables", 0)

                print(f"Model Status: {status}")
                if status == 'error':
                    print(f"Warnings/Errors: {results_dict.get('warnings', {}).get('general', [])}")
                print(f"Distance Matrix Time: {df_dist_time:.2f}s")
                print(f"Resolution Time: {execution_time:.2f}s")
                print(f"Optimal Value: {optimal_value:.2f}")
                print(f"Gap Achieved: {gap_achieved}")

                res_record = {
                    "Gap Target": gap_val,
                    "Number of Supply Nodes": num_ofertas,
                    "Number of Demand Nodes": num_armazens,
                    "Distance Matrix Time (seconds)": df_dist_time,
                    "Resolution Time (seconds)": execution_time,
                    "Optimal Value": optimal_value,
                    "Gap Achieved": gap_achieved,
                    "Total Variables": tot_vars,
                    "Continuous Variables": cont_vars,
                    "Binary Variables": bin_vars,
                    "Integer Variables": int_vars,
                    "Total Constraints": tot_cons,
                    "Total Iterations": tot_iters,
                    "Enumerated Nodes": tot_nodes,
                    "Status": status
                }
                results_for_gap.append(res_record)
                all_results.append(res_record)

                if execution_time >= TIME_LIMIT_SECONDS or status == "timeout_nfs":
                    print(f"\n[!] Time limit of {TIME_LIMIT_SECONDS} seconds reached (Resolution Time: {execution_time:.2f}s). Stopping doubling for Gap {gap_val*100}%.\n")
                    break

            except Exception as e:
                print(f"Error during optimization run: {e}")
                import traceback
                traceback.print_exc()
                # On unexpected error, we can also decide to break
                break

            # Double the sizes for next iteration
            num_ofertas *= 2
            num_armazens *= 2
            idx += 1

        # End of while loop for current gap. Save the intermediate results.
        if results_for_gap:
            df_results_gap = pd.DataFrame(results_for_gap)
            csv_file = os.path.join(benchmark_dir, f"benchmark_results_gap_{int(gap_val*100)}.csv")
            pkl_file = os.path.join(benchmark_dir, f"benchmark_results_gap_{int(gap_val*100)}.pkl")
            xlsx_file = os.path.join(benchmark_dir, f"benchmark_results_gap_{int(gap_val*100)}.xlsx")
            try:
                df_results_gap.to_csv(csv_file, index=False)
                df_results_gap.to_pickle(pkl_file)
                df_results_gap.to_excel(xlsx_file, index=False)
                print(f"Results for Gap {gap_val*100}% exported to {csv_file}, {pkl_file}, and {xlsx_file}")
            except Exception as e:
                print(f"Failed to export results for gap {gap_val}: {e}")

        # Export the Last (Biggest) Dataset Generated for this gap
        try:
            if 'df_supply' in locals() and 'df_demand' in locals():
                supply_file = os.path.join(benchmark_dir, f"benchmark_supply_biggest_gap_{int(gap_val*100)}.xlsx")
                demand_file = os.path.join(benchmark_dir, f"benchmark_demand_biggest_gap_{int(gap_val*100)}.xlsx")
                df_supply.to_excel(supply_file, index=False)
                df_demand.to_excel(demand_file, index=False)
                print(f"Biggest datasets generated for gap {gap_val*100}% exported to:\n - {supply_file}\n - {demand_file}")
        except Exception as e:
            print(f"Failed to export biggest datasets for gap {gap_val}: {e}")

    print("\n====================================================================")
    print("BENCHMARK EXECUTION COMPLETED")
    print("====================================================================")

if __name__ == "__main__":
    main()
