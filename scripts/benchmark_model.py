"""
Refactored Automated Benchmarking Script for the SiloDSS Optimization Model

This script reads configurations from 'benchmark/benchmark_config.json' and executes
increasing optimization problem sizes for both deterministic and stochastic models.
It queries the local OSRM Docker container for distances and saves final iteration
datasets in a format that can be directly uploaded to the graphical user interface.
"""

import os
import sys
import time
import json
import random
import math
import tempfile
import pandas as pd
import numpy as np

# Resolve project root and append to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.logic.osrm import OSRMClient
from src.logic.optimization import run_deterministic_model, run_stochastic_model
from src.logic.prediction import forecast_sarima, forecast_prophet, prepare_time_series

# =============================================================================
# FILE PATHS CONSTANTS
# =============================================================================
MUNICIPIOS_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'municipios.csv')
ESTADOS_CSV = os.path.join(PROJECT_ROOT, 'src', 'view', 'assets', 'data', 'estados.csv')
SICARM_TXT = os.path.join(PROJECT_ROOT, 'benchmark', 'Armazens_Cadastrados_SICARM.txt')

SUPPLY_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Edited_Supply.xlsx')
DEMAND_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Edited_Demand.xlsx')
WAREHOUSES_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Warehouses.xlsx')
INVENTORY_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Initial_Inventory.xlsx')

# Costs are configured directly in benchmark_config.json or inside Warehouses.xlsx
STORAGE_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Tarifa_de_Armazenagem.xlsx')
FREIGHT_XLSX = os.path.join(PROJECT_ROOT, 'benchmark', 'Valor_Tonelada_km.xlsx')

CONFIG_PATH = os.path.join(PROJECT_ROOT, 'benchmark', 'benchmark_config.json')

# Predefined port cities for export demand nodes
PORTS_POOL = [
    "Santos - SP", "Paranaguá - PR", "Rio Grande - RS", "São Francisco do Sul - SC",
    "Vitória - ES", "Itaqui - MA", "Suape - PE", "Pecém - CE", "Porto Alegre - RS",
    "Salvador - BA"
]

def load_config():
    """Load benchmark configuration from JSON or fallback to defaults."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load config from {CONFIG_PATH}. Using defaults. Error: {e}")
    
    # Return defaults if file not found or load fails
    return {
        "model_type": "deterministic",
        "solver_name": "cbc",
        "solver_gap": 1.0,
        "solver_time_limit": 600,
        "error_source": "manual",
        "supply_error_pct": 15.0,
        "demand_error_pct": 15.0,
        "scenario_probabilities": {"pessimista": 0.33, "esperado": 0.34, "otimista": 0.33},
        "toggle_pareto": False,
        "input_allocation_days": 30,
        "interhub_factor": 1.0,
        "toggle_direct_arcs": False,
        "expansion_enabled": False,
        "ratio_expand_rec": 0.10,
        "ratio_expand_ship": 0.10,
        "max_expand_capacity": 5000,
        "expand_fixed_cost": 50000,
        "expand_var_cost": 100,
        "bulk_enabled": False,
        "max_bulk_capacity": 500,
        "bulk_fixed_cost": 30000,
        "bulk_var_cost": 200,
        "bulk_eligible_types": ["Silo"],
        "initial_sizes": {"supply": 5, "demand_domestic": 5, "demand_export": 1, "warehouses": 20},
        "increment_steps": {"supply": 5, "demand_domestic": 5, "demand_export": 1, "warehouses": 10},
        "periods": ["2021-01", "2021-02", "2021-03", "2021-04", "2021-05", "2021-06", "2021-07", "2021-08", "2021-09", "2021-10", "2021-11", "2021-12"]
    }

def clean_sicarm_warehouses():
    """Load and clean registered warehouses from SICARM database txt file."""
    if not os.path.exists(SICARM_TXT):
        print(f"Warning: SICARM txt file not found at {SICARM_TXT}.")
        return pd.DataFrame()

    try:
        with open(SICARM_TXT, 'r', encoding='utf-8', errors='ignore') as f:
            df = pd.read_csv(f, sep=';')
    except Exception:
        with open(SICARM_TXT, 'r', encoding='latin1', errors='ignore') as f:
            df = pd.read_csv(f, sep=';')
    
    # Strip whitespace from column names and string cells
    df.columns = df.columns.str.strip()
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.strip()

    cleaned_list = []
    for idx, row in df.iterrows():
        cda = str(row.get('identificacao_armazem', '')).strip()
        if not cda:
            cda = f"SICARM-{idx+1:05d}"
            
        mun_raw = str(row.get('nom_municipio', '')).split('-')[0].strip().title()
        uf = str(row.get('uf', '')).strip().upper()
        
        species = str(row.get('dsc_especie_armazem', '')).lower()
        wh_type = 'Silo' if ('silo' in species or 'granel' in species) else 'Convencional'
        
        def parse_val(v):
            if pd.isna(v) or str(v).strip() == '':
                return 0.0
            try:
                return float(str(v).replace('.', '').replace(',', '.'))
            except ValueError:
                return 0.0
        
        cap_est = parse_val(row.get('qtd_capacidade_estatica(t)', 0))
        cap_rec = parse_val(row.get('qtd_capacidade_recepcao(t)', 0))
        cap_exp = parse_val(row.get('qtd_capacidade_expedicao(t)', 0))
        
        lat = parse_val(row.get('latitude', np.nan))
        lon = parse_val(row.get('longitude', np.nan))
        
        provider = str(row.get('nome_armazenador', 'SICARM DEPOSIT')).strip()
        
        # Skip invalid CDAs or zero static capacity
        if cap_est <= 0.0:
            continue
            
        cleaned_list.append({
            'CDA': cda,
            'Status': 'Existing',
            'Municipality': mun_raw,
            'UF': uf,
            'Latitude': lat,
            'Longitude': lon,
            'Storage Provider': provider,
            'Type': wh_type,
            'Static Cap. (t)': cap_est,
            'Recep. Cap. (t)': cap_rec,
            'Exped. Cap. (t)': cap_exp,
            'Max Static Cap. (t)': 0.0,
            'Opening Cost ($)': 0.0,
            'Transshipment Cost ($/t)': 9.56
        })
        
    return pd.DataFrame(cleaned_list)

def load_cities_lookup():
    """Load standard municipalities and states mapping for coordinate fallbacks."""
    if not os.path.exists(MUNICIPIOS_CSV) or not os.path.exists(ESTADOS_CSV):
        raise FileNotFoundError("Base municipality or state files are missing in src/view/assets/data/.")
        
    df_mun = pd.read_csv(MUNICIPIOS_CSV)
    df_est = pd.read_csv(ESTADOS_CSV)
    
    if '\ufeffcodigo_uf' in df_est.columns:
        df_est.rename(columns={'\ufeffcodigo_uf': 'codigo_uf'}, inplace=True)
        
    df = pd.merge(df_mun, df_est[['codigo_uf', 'uf']], on='codigo_uf', how='left')
    df['Cidade_UF'] = df['nome'] + ' - ' + df['uf']
    return df

def generate_sampled_datasets(config, df_cities, df_sicarm, supply_size, demand_dom_size, demand_exp_size, warehouse_size):
    """
    Generate supply, demand, warehouses, and initial inventory dataframes 
    matching the requested sizes and maintaining the realistic magnitude of parameters.
    """
    random.seed(42)
    np.random.seed(42)
    
    # 1. LOAD BASE SHEETS
    df_base_supply = pd.read_excel(SUPPLY_XLSX)
    df_base_demand = pd.read_excel(DEMAND_XLSX)
    df_base_warehouses = pd.read_excel(WAREHOUSES_XLSX)
    
    # Generate historical periods if prediction is active
    is_prediction_active = config.get("prediction_method") in ["prophet", "sarima", "xgboost", "lstm"]
    if is_prediction_active:
        # If predictions are run, the history is the entire dataset in the base files
        all_periods = sorted(df_base_supply['Data'].dropna().unique().tolist())
    else:
        all_periods = config["periods"]

    # Deduplicate product list
    all_products = sorted(df_base_supply['Produto'].dropna().unique().tolist())
    
    
    # 2. SUPPLY GENERATION
    unique_supply_cities = df_base_supply['Cidade'].unique().tolist()
    sampled_supply_cities = []
    
    if supply_size <= len(unique_supply_cities):
        sampled_supply_cities = random.sample(unique_supply_cities, supply_size)
        df_supply = df_base_supply[df_base_supply['Cidade'].isin(sampled_supply_cities)].copy()
    else:
        # Take all existing and sample extra from municipios database
        sampled_supply_cities = list(unique_supply_cities)
        extra_count = supply_size - len(unique_supply_cities)
        
        # Exclude existing ones from pool
        pool_cities = df_cities[~df_cities['Cidade_UF'].isin(sampled_supply_cities)]
        extra_sampled = pool_cities.sample(n=extra_count, random_state=42)
        
        extra_rows = []
        for _, r_city in extra_sampled.iterrows():
            new_city_name = r_city['Cidade_UF']
            lat = r_city['latitude']
            lon = r_city['longitude']
            sampled_supply_cities.append(new_city_name)
            
            # Replicate profile of a random base city
            base_city = random.choice(unique_supply_cities)
            df_base_profile = df_base_supply[df_base_supply['Cidade'] == base_city]
            for _, row in df_base_profile.iterrows():
                new_row = row.copy()
                new_row['Cidade'] = new_city_name
                new_row['Latitude'] = lat
                new_row['Longitude'] = lon
                extra_rows.append(new_row)
                
        df_supply = pd.concat([df_base_supply, pd.DataFrame(extra_rows)], ignore_index=True)
    
    # Filter periods for supply
    df_supply = df_supply[df_supply['Data'].isin(all_periods)].copy()
    
    # 3. DOMESTIC DEMAND GENERATION
    unique_demand_cities = df_base_demand['Cidade'].unique().tolist()
    sampled_demand_cities = []
    
    if demand_dom_size <= len(unique_demand_cities):
        sampled_demand_cities = random.sample(unique_demand_cities, demand_dom_size)
        df_demand_dom = df_base_demand[df_base_demand['Cidade'].isin(sampled_demand_cities)].copy()
    else:
        sampled_demand_cities = list(unique_demand_cities)
        extra_count = demand_dom_size - len(unique_demand_cities)
        
        # Exclude supply/demand duplicates
        pool_cities = df_cities[~df_cities['Cidade_UF'].isin(sampled_supply_cities + sampled_demand_cities)]
        extra_sampled = pool_cities.sample(n=extra_count, random_state=43)
        
        extra_rows = []
        for _, r_city in extra_sampled.iterrows():
            new_city_name = r_city['Cidade_UF']
            lat = r_city['latitude']
            lon = r_city['longitude']
            sampled_demand_cities.append(new_city_name)
            
            # Replicate domestic demand profile
            base_city = random.choice(unique_demand_cities)
            df_base_profile = df_base_demand[df_base_demand['Cidade'] == base_city]
            for _, row in df_base_profile.iterrows():
                new_row = row.copy()
                new_row['Cidade'] = new_city_name
                new_row['Latitude'] = lat
                new_row['Longitude'] = lon
                extra_rows.append(new_row)
                
        df_demand_dom = pd.concat([df_base_demand, pd.DataFrame(extra_rows)], ignore_index=True)
        
    df_demand_dom = df_demand_dom[df_demand_dom['Data'].isin(all_periods)].copy()
    
    # 4. EXPORT DEMAND GENERATION
    df_demand_exp_rows = []
    sampled_ports = PORTS_POOL[:demand_exp_size]
    
    if demand_exp_size > len(PORTS_POOL):
        # Sample additional random cities as ports
        extra_ports_count = demand_exp_size - len(PORTS_POOL)
        pool_cities = df_cities[~df_cities['Cidade_UF'].isin(sampled_supply_cities + sampled_demand_cities + PORTS_POOL)]
        extra_ports = pool_cities.sample(n=extra_ports_count, random_state=44)['Cidade_UF'].tolist()
        sampled_ports = PORTS_POOL + extra_ports
        
    for port in sampled_ports:
        # Lookup lat/lon
        port_info = df_cities[df_cities['Cidade_UF'] == port]
        if not port_info.empty:
            lat = float(port_info.iloc[0]['latitude'])
            lon = float(port_info.iloc[0]['longitude'])
        else:
            # Fallback coordinates
            lat, lon = -23.96, -46.33 # Santos approximate
            
        for prod in all_products:
            for dt in all_periods:
                df_demand_exp_rows.append({
                    'Produto': prod,
                    'Cidade': port,
                    'Latitude': lat,
                    'Longitude': lon,
                    'Data': dt,
                    'Peso (ton)': np.nan # NaN indicates export port / infinite demand
                })
                
    df_demand_exp = pd.DataFrame(df_demand_exp_rows)
    df_demand = pd.concat([df_demand_dom, df_demand_exp], ignore_index=True)
    
    # 5. WAREHOUSES GENERATION
    if warehouse_size <= len(df_base_warehouses):
        df_warehouses = df_base_warehouses.sample(n=warehouse_size, random_state=42).copy()
    else:
        df_warehouses = df_base_warehouses.copy()
        extra_count = warehouse_size - len(df_base_warehouses)
        
        if not df_sicarm.empty:
            # Sample from SICARM
            available_sicarm = df_sicarm[~df_sicarm['CDA'].isin(df_warehouses['CDA'])]
            if len(available_sicarm) >= extra_count:
                df_extra_wh = available_sicarm.sample(n=extra_count, random_state=42).copy()
            else:
                df_extra_wh = available_sicarm.copy()
                
            # Calculate dynamic opening cost ratio from candidate warehouses in df_base_warehouses
            cand_base = df_base_warehouses[df_base_warehouses['Status'].str.strip().str.lower() == 'candidate']
            if not cand_base.empty:
                avg_ratio = (cand_base['Opening Cost ($)'] / cand_base['Max Static Cap. (t)'].replace(0, np.nan)).mean()
                if pd.isna(avg_ratio) or np.isinf(avg_ratio):
                    avg_ratio = 1148.75
            else:
                avg_ratio = 1148.75
                
            # Rename columns to match standard GUI format
            gui_col_map = {
                'CDA': 'CDA',
                'Status': 'Status',
                'Municipality': 'Municipality',
                'UF': 'UF',
                'Latitude': 'Latitude',
                'Longitude': 'Longitude',
                'Storage Provider': 'Storage Provider',
                'Type': 'Type',
                'Static Cap. (t)': 'Static Cap. (t)',
                'Recep. Cap. (t)': 'Recep. Cap. (t)',
                'Exped. Cap. (t)': 'Exped. Cap. (t)',
                'Max Static Cap. (t)': 'Max Static Cap. (t)',
                'Opening Cost ($)': 'Opening Cost ($)',
                'Transshipment Cost ($/t)': 'Transshipment Cost ($/t)'
            }
            df_extra_wh = df_extra_wh.rename(columns=gui_col_map)
            
            # Split df_extra_wh in half: half Existing, half Candidate
            df_extra_wh = df_extra_wh.reset_index(drop=True)
            num_extra = len(df_extra_wh)
            half = num_extra // 2
            for idx in range(num_extra):
                if idx >= half:
                    # Convert to Candidate
                    orig_cap = df_extra_wh.loc[idx, 'Static Cap. (t)']
                    df_extra_wh.loc[idx, 'Status'] = 'Candidate'
                    df_extra_wh.loc[idx, 'Max Static Cap. (t)'] = orig_cap
                    df_extra_wh.loc[idx, 'Static Cap. (t)'] = 0.0
                    df_extra_wh.loc[idx, 'Opening Cost ($)'] = round(orig_cap * avg_ratio, 2)
                    
            df_warehouses = pd.concat([df_warehouses, df_extra_wh], ignore_index=True)
            
    # 7. FORMAT DATA FOR OPTIMIZATION FUNCTION
    # The optimization code expects Portuguese headers for warehouses and inventory.
    # Map from GUI English output headers to model Portuguese headers
    # Warehouses:
    wh_map = {
        'CDA': 'CDA',
        'Status': 'Status',
        'Municipality': 'Município',
        'UF': 'UF',
        'Latitude': 'Latitude',
        'Longitude': 'Longitude',
        'Storage Provider': 'Armazenador',
        'Type': 'Tipo',
        'Static Cap. (t)': 'Cap. Estática (t)',
        'Recep. Cap. (t)': 'Cap. Recepção (t)',
        'Exped. Cap. (t)': 'Cap. Expedição (t)',
        'Max Static Cap. (t)': 'Cap. Estática Máxima (t)',
        'Opening Cost ($)': 'Custo de Abertura ($)',
        'Transshipment Cost ($/t)': 'Custo de Transbordo ($/t)'
    }
    
    def clean_weight(val):
        if pd.isna(val) or val is None or str(val).strip() == '∞' or str(val).strip() == '':
            return np.nan
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).strip().replace('.', '').replace(',', '.')
            return float(s)
        except Exception:
            return np.nan

    df_opt_supply = df_supply.copy()
    df_opt_supply['Peso (ton)'] = df_opt_supply['Peso (ton)'].apply(clean_weight)

    df_opt_demand = df_demand.copy()
    df_opt_demand['Peso (ton)'] = df_opt_demand['Peso (ton)'].apply(clean_weight)

    # Check config for feasibility scaling option
    enable_scaling = config.get("enable_feasibility_scaling", False)
    scaling_factor = config.get("feasibility_scaling_factor", 1.1)




    if enable_scaling:
        # Ensure supply-demand feasibility for each product and period
        for p in all_products:
            for t in all_periods:
                df_dem_sub = df_opt_demand[(df_opt_demand['Produto'] == p) & (df_opt_demand['Data'] == t)]
                total_dem = df_dem_sub['Peso (ton)'].dropna().sum()
                
                df_sup_sub = df_opt_supply[(df_opt_supply['Produto'] == p) & (df_opt_supply['Data'] == t)]
                total_sup = df_sup_sub['Peso (ton)'].sum()
                
                if total_sup < total_dem * scaling_factor:
                    needed_sup = total_dem * scaling_factor
                    if total_sup > 1e-4:
                        factor = needed_sup / total_sup
                        # Scale weights in df_opt_supply
                        mask_opt = (df_opt_supply['Produto'] == p) & (df_opt_supply['Data'] == t)
                        df_opt_supply.loc[mask_opt, 'Peso (ton)'] = (df_opt_supply.loc[mask_opt, 'Peso (ton)'] * factor).round(2)
                        # Scale weights in df_supply (GUI file)
                        mask_gui = (df_supply['Produto'] == p) & (df_supply['Data'] == t)
                        df_supply.loc[mask_gui, 'Peso (ton)'] = (df_supply.loc[mask_gui, 'Peso (ton)'] * factor).round(2)
                    else:
                        mask_opt = (df_opt_supply['Produto'] == p) & (df_opt_supply['Data'] == t)
                        count_opt = mask_opt.sum()
                        if count_opt > 0:
                            df_opt_supply.loc[mask_opt, 'Peso (ton)'] = round(needed_sup / count_opt, 2)
                            
                        mask_gui = (df_supply['Produto'] == p) & (df_supply['Data'] == t)
                        count_gui = mask_gui.sum()
                        if count_gui > 0:
                            df_supply.loc[mask_gui, 'Peso (ton)'] = round(needed_sup / count_gui, 2)

    df_opt_warehouses = df_warehouses.rename(columns=wh_map)
    if 'Status' in df_opt_warehouses.columns:
        df_opt_warehouses['Status'] = df_opt_warehouses['Status'].fillna('Existente').astype(str).str.strip().apply(
            lambda x: 'Candidato' if 'candidato' in x.lower() or 'candidate' in x.lower() else 'Existente'
        )
    
    return df_opt_supply, df_opt_demand, df_opt_warehouses, df_supply, df_demand, df_warehouses

def build_benchmark_distance_matrices(df_supply, df_demand, df_warehouses, toggle_direct_arcs, client):
    """
    Computes all distance matrices required by the optimization model using OSRM.
    """
    # 1. Supply Origins
    origins_df = df_supply[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts = origins_df['Cidade'].value_counts()
    duplicates = city_counts[city_counts > 1].index
    
    origins_df['Cidade_Display'] = origins_df.apply(
        lambda r: f"{r['Cidade']} ({r['Latitude']:.4f}, {r['Longitude']:.4f})"
        if r['Cidade'] in duplicates else r['Cidade'],
        axis=1
    )
    origins_coords = list(zip(origins_df['Latitude'], origins_df['Longitude']))
    origin_names = origins_df['Cidade_Display'].tolist()
    
    # 2. Warehouses Destinations
    wh_coords = list(zip(df_warehouses['Latitude'], df_warehouses['Longitude']))
    # Replicate view.py label construction
    wh_labels = []
    for _, row in df_warehouses.iterrows():
        parts = []
        cda_val = row.get('CDA')
        armaz_val = row.get('Armazenador')
        mun_val = row.get('Município')
        
        if pd.notna(cda_val) and str(cda_val).strip():
            parts.append(str(cda_val).strip())
        if pd.notna(armaz_val) and str(armaz_val).strip():
            parts.append(str(armaz_val).strip())
        if pd.notna(mun_val) and str(mun_val).strip():
            parts.append(str(mun_val).strip())
            
        wh_labels.append(" - ".join(parts) if parts else str(cda_val))
        
    # 3. Demand Customers
    demand_df = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    demand_city_counts = demand_df['Cidade'].value_counts()
    demand_duplicates = demand_city_counts[demand_city_counts > 1].index
    
    demand_df['Cidade_Display'] = demand_df.apply(
        lambda r: f"{r['Cidade']} ({r['Latitude']:.4f}, {r['Longitude']:.4f})"
        if r['Cidade'] in demand_duplicates else r['Cidade'],
        axis=1
    )
    demand_coords = list(zip(demand_df['Latitude'], demand_df['Longitude']))
    demand_names = demand_df['Cidade_Display'].tolist()
    
    # Call OSRM
    t_start = time.time()
    matrix_supply_wh = client.get_distance_matrix(origins_coords, wh_coords)
    matrix_wh_demand = client.get_distance_matrix(wh_coords, demand_coords)
    matrix_wh_wh = client.get_distance_matrix(wh_coords, wh_coords)
    
    # Format and convert to km
    df_dist_supply_wh = pd.DataFrame(matrix_supply_wh, columns=wh_labels)
    df_dist_supply_wh = (df_dist_supply_wh / 1000.0).round(2)
    df_dist_supply_wh.insert(0, 'Origem', origin_names)
    
    df_dist_wh_demand = pd.DataFrame(matrix_wh_demand, columns=demand_names)
    df_dist_wh_demand = (df_dist_wh_demand / 1000.0).round(2)
    df_dist_wh_demand.insert(0, 'Origem', wh_labels)
    
    df_dist_wh_wh = pd.DataFrame(matrix_wh_wh, columns=wh_labels)
    df_dist_wh_wh = (df_dist_wh_wh / 1000.0).round(2)
    df_dist_wh_wh.insert(0, 'Origem', wh_labels)
    
    df_dist_supply_demand = pd.DataFrame()
    if toggle_direct_arcs:
        matrix_supply_demand = client.get_distance_matrix(origins_coords, demand_coords)
        df_dist_supply_demand = pd.DataFrame(matrix_supply_demand, columns=demand_names)
        df_dist_supply_demand = (df_dist_supply_demand / 1000.0).round(2)
        df_dist_supply_demand.insert(0, 'Origem', origin_names)
        
    matrix_time = time.time() - t_start
    return df_dist_supply_wh, df_dist_wh_demand, df_dist_wh_wh, df_dist_supply_demand, matrix_time

def run_predictions_on_the_fly(df_supply, df_demand, config):
    """
    Run time-series forecast on the fly to simulate the prediction results store.
    Supports both SARIMA and Prophet, configured in benchmark_config.json.
    """
    active_periods = config["periods"]
    first_active = active_periods[0]
    
    df_supply = df_supply.copy()
    df_demand = df_demand.copy()
    
    def clean_val(val):
        if pd.isna(val) or val is None or str(val).strip() == '∞' or str(val).strip() == '':
            return np.nan
        try:
            if isinstance(val, (int, float)):
                return float(val)
            s = str(val).strip().replace('.', '').replace(',', '.')
            return float(s)
        except Exception:
            return np.nan
            
    df_supply['Peso (ton)'] = df_supply['Peso (ton)'].apply(clean_val)
    df_demand['Peso (ton)'] = df_demand['Peso (ton)'].apply(clean_val)

    # The history is the entire input dataset
    df_supply_hist = df_supply.copy()
    df_demand_hist = df_demand.copy()
    
    method = config.get("prediction_method", "sarima").strip().lower()
    test_len = config.get("validation_period", 12)
    horizon = config.get("forecast_horizon", 12)
    
    # Determine the future dates based on the max date in the history
    max_date_val = pd.to_datetime(df_supply['Data'].max())
    future_dates = [str((max_date_val + pd.DateOffset(months=i)).strftime('%Y-%m')) for i in range(1, horizon + 1)]
    
    preds_dict = {}
    
    def run_forecast(series):
        if method == "prophet":
            return forecast_prophet(series, test_len, horizon)
        else:
            return forecast_sarima(series, test_len, horizon)
    
    # 1. Supply Forecaster
    unique_supply = df_supply_hist[['Produto', 'Cidade']].drop_duplicates().values
    print(f"\nProphet/SARIMA prediction running on {len(unique_supply)} supply series and the demand series using method '{method}'...")
    for prod, city in unique_supply:
        combo_key = f"supply_{prod}_{city}"
        df_combo = df_supply_hist[(df_supply_hist['Produto'] == prod) & (df_supply_hist['Cidade'] == city)]
        series = prepare_time_series(df_combo, prod, city)
        
        if len(series) >= test_len + 6:
            try:
                print(f"  [Prediction] Forecasting supply for product '{prod}' in city '{city}' ({len(series)} historical periods)...")
                test_preds, future_preds, _ = run_forecast(series)
                wmape = 15.0
                if test_len > 0 and len(test_preds) == test_len:
                    actuals = series.iloc[-test_len:].values
                    sum_act = np.sum(actuals)
                    if sum_act > 1e-4:
                        wmape = float(np.sum(np.abs(actuals - test_preds)) / sum_act * 100.0)
                    else:
                        wmape = 0.0
                preds_dict[combo_key] = {
                    "status": "success",
                    "series_type": "supply",
                    "product": prod,
                    "city": city,
                    "future_dates": future_dates,
                    "future_preds": list(future_preds),
                    "wmape": wmape
                }
                print(f"    Success. WMAPE: {wmape:.2f}%")
            except Exception as e:
                import traceback
                print(f"    Failed to forecast supply for {prod}_{city}: {e}")
                traceback.print_exc()
        else:
            print(f"  [Prediction] Skipped supply forecast for {prod}_{city}: Insufficient data ({len(series)} historical periods, needed {test_len + 6})")
                
    # 2. Demand Forecaster
    unique_demand = df_demand_hist[['Produto', 'Cidade']].drop_duplicates().values
    for prod, city in unique_demand:
        combo_key = f"demand_{prod}_{city}"
        df_combo = df_demand_hist[(df_demand_hist['Produto'] == prod) & (df_demand_hist['Cidade'] == city)]
        
        # Check if infinite demand (Porto)
        is_infinite = df_demand[df_demand['Cidade'] == city]['Peso (ton)'].isna().all()
        if is_infinite:
            preds_dict[combo_key] = {
                "status": "success",
                "is_infinite_demand": True,
                "series_type": "demand",
                "product": prod,
                "city": city,
                "future_dates": future_dates,
                "future_preds": [None] * horizon,
                "wmape": 0.0
            }
            print(f"  [Prediction] Infinite demand node '{city}' for product '{prod}' mapped directly (no forecasting needed).")
            continue
            
        series = prepare_time_series(df_combo, prod, city)
        if len(series) >= test_len + 6:
            try:
                print(f"  [Prediction] Forecasting demand for product '{prod}' in city '{city}' ({len(series)} historical periods)...")
                test_preds, future_preds, _ = run_forecast(series)
                wmape = 15.0
                if test_len > 0 and len(test_preds) == test_len:
                    actuals = series.iloc[-test_len:].values
                    sum_act = np.sum(actuals)
                    if sum_act > 1e-4:
                        wmape = float(np.sum(np.abs(actuals - test_preds)) / sum_act * 100.0)
                    else:
                        wmape = 0.0
                preds_dict[combo_key] = {
                    "status": "success",
                    "series_type": "demand",
                    "product": prod,
                    "city": city,
                    "future_dates": future_dates,
                    "future_preds": list(future_preds),
                    "wmape": wmape
                }
                print(f"    Success. WMAPE: {wmape:.2f}%")
            except Exception as e:
                import traceback
                print(f"    Failed to forecast demand for {prod}_{city}: {e}")
                traceback.print_exc()
        else:
            print(f"  [Prediction] Skipped demand forecast for {prod}_{city}: Insufficient data ({len(series)} historical periods, needed {test_len + 6})")
                 
    return preds_dict

def extract_gap_from_log(log_filepath):
    """Parse output solver log file to extract MIP Gap."""
    if not os.path.exists(log_filepath):
        return 0.0
    try:
        with open(log_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        import re
        # Look for "Gap da Solução (MIP Gap): X.XXXX%"
        match = re.search(r"Gap da Solução \(MIP Gap\):\s*([\d\.]+)%", content)
        if match:
            return float(match.group(1))
        # Look for "MIP Gap: X.XXXX%"
        match_alt = re.search(r"MIP Gap:\s*([\d\.]+)%", content)
        if match_alt:
            return float(match_alt.group(1))
    except Exception as e:
        print(f"Error parsing log file for gap: {e}")
    return 0.0

def merge_predictions_into_df(df_data, prediction_results, series_type):
    """Replicate GUI forecast merging logic from view.py on the fly."""
    if not prediction_results:
        return df_data.copy()
        
    forecast_rows = []
    coords_dict = df_data.groupby(['Produto', 'Cidade'])[['Latitude', 'Longitude']].first().to_dict('index') if not df_data.empty else {}
    
    for combo_key, combo_val in prediction_results.items():
        if not isinstance(combo_val, dict) or combo_val.get('status') != 'success':
            continue
            
        s_type = combo_val.get('series_type')
        if s_type != series_type:
            continue
            
        prod = combo_val.get('product')
        city = combo_val.get('city')
        future_dates = combo_val.get('future_dates', [])
        future_preds = combo_val.get('future_preds', [])
        is_infinite_demand = combo_val.get('is_infinite_demand', False)
        
        coords = coords_dict.get((prod, city), {'Latitude': 0.0, 'Longitude': 0.0})
        for d, val in zip(future_dates, future_preds):
            val_to_append = float(val) if (val is not None and not is_infinite_demand) else np.nan
            forecast_rows.append({
                "Produto": prod,
                "Cidade": city,
                "Latitude": coords.get('Latitude', 0.0),
                "Longitude": coords.get('Longitude', 0.0),
                "Data": d,
                "Peso (ton)": val_to_append
            })
            
    if forecast_rows:
        df_forecast = pd.DataFrame(forecast_rows)
        df_data = pd.concat([df_data, df_forecast], ignore_index=True)
        df_data = df_data.sort_values(by=["Produto", "Cidade", "Data"])
        
    return df_data

def main():
    print("=== Starting Refactored Automated Benchmarking ===")
    
    # Check for Gurobi license content passed as environment variable (Stateless Option B)
    gurobi_lic_data = os.environ.get("GUROBI_LICENSE_DATA")
    if gurobi_lic_data:
        try:
            # Write to a temporary file that persists during script execution
            fd, temp_lic_path = tempfile.mkstemp(suffix=".lic", prefix="gurobi_stateless_")
            with os.fdopen(fd, 'w', encoding='utf-8') as temp_file:
                temp_file.write(gurobi_lic_data.strip())
            os.environ["GRB_LICENSE_FILE"] = temp_lic_path
            print(f"[GUROBI] Loaded license content from GUROBI_LICENSE_DATA environment variable.")
        except Exception as e:
            print(f"Warning: Failed to setup stateless Gurobi license: {e}")

    config = load_config()
    
    # Load costs reference sheets
    try:
        df_storage_raw = pd.read_excel(STORAGE_XLSX)
        df_freight = pd.read_excel(FREIGHT_XLSX)
    except Exception as e:
        print(f"Error loading cost reference spreadsheets: {e}")
        return
        
    # Clean storage sheet (look for legacy naming public/private)
    df_storage = df_storage_raw.copy()
    if 'Armazenar' not in df_storage.columns:
        if 'Armazenar_Publico' in df_storage.columns:
            df_storage['Armazenar'] = df_storage['Armazenar_Publico']
        elif 'Armazenar_Privado' in df_storage.columns:
            df_storage['Armazenar'] = df_storage['Armazenar_Privado']
        else:
            df_storage['Armazenar'] = 45.0 # global default fallback
            
    print("Loading base files for sampling pool...")
    df_cities = load_cities_lookup()
    df_sicarm = clean_sicarm_warehouses()
    
    # Set up loop configurations
    initial_sizes = config["initial_sizes"]
    steps = config["increment_steps"]
    
    supply_size = initial_sizes["supply"]
    demand_dom_size = initial_sizes["demand_domestic"]
    demand_exp_size = initial_sizes["demand_export"]
    warehouse_size = initial_sizes["warehouses"]
    
    osrm_url = os.environ.get('OSRM_URL', 'http://localhost:5000')
    osrm_client = OSRMClient(base_url=osrm_url)
    
    benchmark_dir = os.path.join(PROJECT_ROOT, "benchmark")
    os.makedirs(benchmark_dir, exist_ok=True)
    log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
    os.makedirs(log_dir, exist_ok=True)
    
    all_runs_summary = []
    iteration_idx = 1
    
    # Replicate GUI expansion / bulkification toggles
    exp_enabled = config.get("expansion_enabled", False)
    bulk_enabled = config.get("bulk_enabled", False)
    
    while True:
        print(f"\n====================================================================")
        print(f"ITERATION {iteration_idx} | Model Type: {config['model_type'].upper()}")
        print(f"Sizes: Supply={supply_size} | Domestic Demand={demand_dom_size} | Export Demand={demand_exp_size} | Warehouses={warehouse_size}")
        print(f"====================================================================")
        
        # 1. Generate Sampled Sets
        (df_opt_supply, df_opt_demand, df_opt_warehouses,
         df_gui_supply, df_gui_demand, df_gui_warehouses) = generate_sampled_datasets(
             config, df_cities, df_sicarm,
             supply_size, demand_dom_size, demand_exp_size, warehouse_size
         )
         
        # Dynamically build compatibility matrix
        # Columns: Produto, types of warehouses
        products_list = df_opt_supply['Produto'].unique().tolist()
        wh_types = df_opt_warehouses['Tipo'].dropna().unique().tolist()
        compat_data = {wt: ['☑'] * len(products_list) for wt in wh_types}
        df_compat = pd.DataFrame(compat_data)
        df_compat.insert(0, "Produto", products_list)
        
        # 2. Build Distance Matrices
        print("Calculating distance matrices via OSRM...")
        df_dist_supply_wh, df_dist_wh_demand, df_dist_wh_wh, df_dist_supply_demand, dist_time = build_benchmark_distance_matrices(
            df_opt_supply, df_opt_demand, df_opt_warehouses, config["toggle_direct_arcs"], osrm_client
        )
        print(f"Distance calculation completed in {dist_time:.2f} seconds.")
        
        # 3. Forecast Predictions (if prediction option is enabled)
        prediction_results = None
        is_prediction_active = config.get("prediction_method") in ["prophet", "sarima", "xgboost", "lstm"]
        if is_prediction_active:
            print("Running forecasting models on the fly...")
            t_pred_start = time.time()
            prediction_results = run_predictions_on_the_fly(df_gui_supply, df_gui_demand, config)
            print(f"Forecasting completed in {time.time() - t_pred_start:.2f} seconds.")
            
            # Replicate GUI merging on the fly
            max_date_val = pd.to_datetime(df_gui_supply['Data'].max())
            first_active = (max_date_val + pd.DateOffset(months=1)).strftime('%Y-%m')
            
            # Keep only the historical periods (prior to first active period)
            df_opt_supply = df_opt_supply[df_opt_supply['Data'] < first_active].copy()
            df_opt_demand = df_opt_demand[df_opt_demand['Data'] < first_active].copy()
            
            # Merge forecasted values for active periods
            df_opt_supply = merge_predictions_into_df(df_opt_supply, prediction_results, 'supply')
            df_opt_demand = merge_predictions_into_df(df_opt_demand, prediction_results, 'demand')

            
        # 4. Execute Optimization Model
        print("Executing optimization model...")
        log_filepath = os.path.join(log_dir, f"benchmark_log_iter_{iteration_idx}.txt")
        t_solve_start = time.time()
        
        try:
            if config["model_type"] == "stochastic":
                log_filename, results_dict = run_stochastic_model(
                    df_supply=df_opt_supply,
                    df_warehouses=df_opt_warehouses,
                    df_compat=df_compat,
                    df_dist_supply_wh=df_dist_supply_wh,
                    df_dist_wh_demand=df_dist_wh_demand,
                    df_dist_wh_wh=df_dist_wh_wh,
                    df_demand=df_opt_demand,
                    df_freight=df_freight,
                    df_storage=df_storage,
                    scenario_probabilities=config["scenario_probabilities"],
                    error_source=config["error_source"],
                    supply_error_pct=config["supply_error_pct"],
                    demand_error_pct=config["demand_error_pct"],
                    prediction_results=prediction_results,
                    df_initial_inventory=None,
                    df_dist_supply_demand=df_dist_supply_demand if config["toggle_direct_arcs"] else None,
                    detailed_log=False,
                    toggle_pareto=config["toggle_pareto"],
                    input_allocation_days=config["input_allocation_days"],
                    interhub_factor=config["interhub_factor"],
                    solver_gap=config["solver_gap"],
                    solver_time_limit=config["solver_time_limit"],
                    ratio_expand_rec=config["ratio_expand_rec"],
                    ratio_expand_ship=config["ratio_expand_ship"],
                    max_expand_capacity=config["max_expand_capacity"] if exp_enabled else None,
                    expand_fixed_cost=config["expand_fixed_cost"] if exp_enabled else None,
                    expand_var_cost=config["expand_var_cost"] if exp_enabled else None,
                    max_bulk_capacity=config["max_bulk_capacity"] if bulk_enabled else None,
                    bulk_fixed_cost=config["bulk_fixed_cost"] if bulk_enabled else None,
                    bulk_var_cost=config["bulk_var_cost"] if bulk_enabled else None,
                    bulk_eligible_types=config["bulk_eligible_types"] if bulk_enabled else None,
                    lang="pt",
                    log_path=log_filepath,
                    solver_name=config["solver_name"]
                )
            else:
                # Deterministic
                log_filename, results_dict = run_deterministic_model(
                    df_supply=df_opt_supply,
                    df_warehouses=df_opt_warehouses,
                    df_compat=df_compat,
                    df_dist_supply_wh=df_dist_supply_wh,
                    df_dist_wh_demand=df_dist_wh_demand,
                    df_dist_wh_wh=df_dist_wh_wh,
                    df_demand=df_opt_demand,
                    df_freight=df_freight,
                    df_storage=df_storage,
                    df_initial_inventory=None,
                    df_dist_supply_demand=df_dist_supply_demand if config["toggle_direct_arcs"] else None,
                    detailed_log=False,
                    toggle_pareto=config["toggle_pareto"],
                    input_allocation_days=config["input_allocation_days"],
                    interhub_factor=config["interhub_factor"],
                    solver_gap=config["solver_gap"],
                    solver_time_limit=config["solver_time_limit"],
                    ratio_expand_rec=config["ratio_expand_rec"],
                    ratio_expand_ship=config["ratio_expand_ship"],
                    max_expand_capacity=config["max_expand_capacity"] if exp_enabled else None,
                    expand_fixed_cost=config["expand_fixed_cost"] if exp_enabled else None,
                    expand_var_cost=config["expand_var_cost"] if exp_enabled else None,
                    max_bulk_capacity=config["max_bulk_capacity"] if bulk_enabled else None,
                    bulk_fixed_cost=config["bulk_fixed_cost"] if bulk_enabled else None,
                    bulk_var_cost=config["bulk_var_cost"] if bulk_enabled else None,
                    bulk_eligible_types=config["bulk_eligible_types"] if bulk_enabled else None,
                    lang="pt",
                    log_path=log_filepath,
                    solver_name=config["solver_name"]
                )
            
            solve_time = time.time() - t_solve_start
            optimal_value = results_dict.get("objective", 0.0)
            status = results_dict.get("status", "unknown")
            
            # Extract models variables counts
            model_stats = results_dict.get("model_stats", {})
            tot_vars = model_stats.get("total_variables", 0)
            tot_cons = model_stats.get("total_constraints", 0)
            bin_vars = model_stats.get("binary_variables", 0)
            cont_vars = model_stats.get("continuous_variables", 0)
            
            # Extract decision metrics
            wh_decisions = results_dict.get("warehouse_decisions", [])
            opened_candidates = sum(1 for w in wh_decisions if w.get("IsCandidate") and w.get("IsOpen"))
            expanded_warehouses = sum(1 for w in wh_decisions if w.get("IsExpanded"))
            bulkified_warehouses = sum(1 for w in wh_decisions if w.get("IsBulkified"))
            
            # Parse MIP gap from generated solver log file
            achieved_gap = extract_gap_from_log(log_filepath)
            
            # Print detailed solver logs for verification/debugging
            if os.path.exists(log_filepath):
                print(f"\n==================== SOLVER DETAILED LOG (ITERATION {iteration_idx}) ====================", flush=True)
                try:
                    with open(log_filepath, 'r', encoding='utf-8', errors='ignore') as f_log:
                        print(f_log.read(), flush=True)
                except Exception as e_log:
                    print(f"Error reading solver log: {e_log}", flush=True)
                print("==================================================================================\n", flush=True)

            print(f"Run Finished. Status: {status} | Objective: {optimal_value:,.2f}")
            print(f"Variables: {tot_vars} (Binary: {bin_vars}) | Constraints: {tot_cons}")
            print(f"Decisions: Candidate Opened={opened_candidates}, Expanded={expanded_warehouses}, Bulkified={bulkified_warehouses}")
            print(f"Solve Time: {solve_time:.2f} seconds | MIP Gap: {achieved_gap:.4f}%")
            
            # Record summary data
            run_summary = {
                "Iteration": iteration_idx,
                "Model Type": config["model_type"],
                "Solver": config["solver_name"],
                "Supply Nodes": supply_size,
                "Domestic Demand Nodes": demand_dom_size,
                "Export Demand Nodes": demand_exp_size,
                "Warehouses Count": warehouse_size,
                "Distance Matrix Time (s)": dist_time,
                "Solve Time (s)": solve_time,
                "MIP Gap Achieved (%)": achieved_gap,
                "Optimal Value (R$)": optimal_value,
                "Total Variables": tot_vars,
                "Continuous Variables": cont_vars,
                "Binary Variables": bin_vars,
                "Total Constraints": tot_cons,
                "Candidate Opened Count": opened_candidates,
                "Expanded Count": expanded_warehouses,
                "Bulkified Count": bulkified_warehouses,
                "Status": status
            }
            all_runs_summary.append(run_summary)
            
            # Check stop condition: solver/solve time > 600s
            is_limit_reached = (solve_time >= 600.0 or status == "timeout_nfs")
            
            if is_limit_reached:
                print(f"\n[!] STOP CONDITION MET: Computation time ({solve_time:.2f}s) exceeded 600 seconds limit.")
                print("Exporting final datasets and configurations...")
                try:
                    is_prediction_active = (config["error_source"] == "prediction")
                    if is_prediction_active:
                        max_date_val = pd.to_datetime(df_gui_supply['Data'].max())
                        first_active = (max_date_val + pd.DateOffset(months=1)).strftime('%Y-%m')
                        df_gui_supply_to_save = df_gui_supply[df_gui_supply['Data'] < first_active].copy()
                        df_gui_demand_to_save = df_gui_demand[df_gui_demand['Data'] < first_active].copy()
                    else:
                        df_gui_supply_to_save = df_gui_supply
                        df_gui_demand_to_save = df_gui_demand

                    df_gui_supply_to_save.to_excel(os.path.join(benchmark_dir, 'last_supply.xlsx'), index=False)
                    df_gui_demand_to_save.to_excel(os.path.join(benchmark_dir, 'last_demand.xlsx'), index=False)
                    df_gui_warehouses.to_excel(os.path.join(benchmark_dir, 'last_warehouses.xlsx'), index=False)
                    
                    # Save prediction results json if applicable
                    if prediction_results:
                        with open(os.path.join(benchmark_dir, 'last_prediction_results.json'), 'w', encoding='utf-8') as f_out:
                            json.dump(prediction_results, f_out, indent=2, ensure_ascii=False)
                            
                    # Save configurations
                    with open(os.path.join(benchmark_dir, 'last_configurations.json'), 'w', encoding='utf-8') as f_out:
                        json.dump(config, f_out, indent=2, ensure_ascii=False)
                        
                    print(f"Final datasets successfully exported to {benchmark_dir}")
                except Exception as ex:
                    print(f"Error saving final datasets: {ex}")
                break
                
        except Exception as e:
            print(f"Critical error during iteration {iteration_idx}: {e}")
            import traceback
            traceback.print_exc()
            break
            
        # Increment sizes
        supply_size += steps["supply"]
        demand_dom_size += steps["demand_domestic"]
        demand_exp_size += steps["demand_export"]
        warehouse_size += steps["warehouses"]
        iteration_idx += 1
        
    # Write summary report sheet
    if all_runs_summary:
        try:
            df_summary = pd.DataFrame(all_runs_summary)
            summary_path = os.path.join(benchmark_dir, 'benchmark_results_summary.xlsx')
            df_summary.to_excel(summary_path, index=False)
            print(f"\nSummary of all runs saved to {summary_path}")
        except Exception as e:
            print(f"Error writing summary spreadsheet: {e}")

if __name__ == "__main__":
    main()
