from src.logic.i18n import translate
import pyomo.environ as pyo
from pyomo.opt import SolverFactory
import pandas as pd
import sys
import io
import tempfile
import os
import math
import time

def safe_parse_numeric(val):
    if pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    # If it's a string, clean the Brazilian format
    val_str = str(val).strip()
    if not val_str:
        return 0.0
    return float(val_str.replace('.', '').replace(',', '.'))

def run_deterministic_model(
    df_supply,
    df_warehouses,
    df_compat,
    df_dist_supply_wh,
    df_dist_wh_demand,
    df_dist_wh_wh,
    df_demand,
    df_freight,
    df_storage,
    detailed_log=False,
    toggle_pareto=False,
    input_allocation_days=None,
    transshipment_discount=None,
    solver_gap=None,
    solver_time_limit=None,
    ratio_expand_rec=None,
    ratio_expand_ship=None,
    max_expand_capacity=None,
    expand_fixed_cost=None,
    expand_var_cost=None,
    max_bulk_capacity=None,
    bulk_fixed_cost=None,
    bulk_var_cost=None,
    bulk_eligible_types=None,
    lang="pt"
):
    """
    Executes the deterministic multi-period MILP optimization model.
    Organizes supply, multi-period inventory, transshipment routing, customers demand,
    and facility upgrades/locations.
    """
    start_time = time.time()

    # =========================================================================
    # 1. DATA PREPARATION & PARSING
    # =========================================================================

    # Deduplicate supply origin names (same logic as OSRM/distance calculations)
    if 'Latitude' in df_supply.columns and 'Longitude' in df_supply.columns:
        origins_df = df_supply[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
        city_counts = origins_df['Cidade'].value_counts()
        duplicates = city_counts[city_counts > 1].index

        def rename_city(row):
            if row['Cidade'] in duplicates:
                return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
            return row['Cidade']

        df_supply['Cidade'] = df_supply.apply(rename_city, axis=1)

    # Unique chronological time periods (months) from supply dates
    periods = sorted(df_supply['Data'].dropna().unique().tolist())
    prev_period_map = {p: periods[i-1] for i, p in enumerate(periods) if i > 0}
    all_products = df_supply['Produto'].unique().tolist()
    
    # 1.1 Supply dict: {(origin, product, period): tons}
    supply_dict = df_supply.groupby(['Cidade', 'Produto', 'Data'])['Peso (ton)'].sum().to_dict()

    # 1.2 Parse Warehouses (existing and candidate hubs)
    existing_warehouses_list = []
    candidate_warehouses_list = []
    all_warehouses_list = []
    
    static_capacity = {}
    reception_capacity = {}
    shipping_capacity = {}
    opening_cost = {}
    max_cand_static_capacity = {}
    warehouse_type = {}
    warehouse_uf = {}
    demand_initial_inventory = {}
    
    cda_to_name = {}

    for _, row in df_warehouses.iterrows():
        cda = str(row['CDA']).strip()
        status = str(row['Status']).strip()
        all_warehouses_list.append(cda)
        warehouse_type[cda] = str(row['Tipo']).strip()
        warehouse_uf[cda] = str(row['UF']).strip()
        
        # Format the CDA display name for results visualization
        parts = []
        if pd.notna(row['CDA']):
            parts.append(str(row['CDA']).strip())
        if 'Armazenador' in row and pd.notna(row['Armazenador']):
            parts.append(str(row['Armazenador']).strip())
        if 'Município' in row and pd.notna(row['Município']):
            parts.append(str(row['Município']).strip())
            
        cda_to_name[cda] = " - ".join(parts) if parts else cda

        if status == 'Existente':
            existing_warehouses_list.append(cda)
            static_capacity[cda] = safe_parse_numeric(row['Cap. Estática (t)'])
            reception_capacity[cda] = safe_parse_numeric(row['Cap. Recepção (t)'])
            shipping_capacity[cda] = safe_parse_numeric(row['Cap. Expedição (t)'])
            demand_initial_inventory[cda] = safe_parse_numeric(row['Estoque Inicial (t)'])
        else: # Candidate
            candidate_warehouses_list.append(cda)
            opening_cost[cda] = safe_parse_numeric(row['Custo de Abertura ($)'])
            max_cand_static_capacity[cda] = safe_parse_numeric(row['Cap. Estática Máxima (t)'])
            demand_initial_inventory[cda] = 0.0

    # 1.3 Product Compatibility
    compat_dict = {}
    if not df_compat.empty:
        for _, row in df_compat.iterrows():
            prod = row['Produto']
            for col in df_compat.columns:
                if col != 'Produto':
                    compat_dict[(prod, col)] = (row[col] == '☑')

    prod_dest_compat = {}
    for prod in all_products:
        for cda in all_warehouses_list:
            t = warehouse_type.get(cda)
            if t and (prod, t) in compat_dict:
                prod_dest_compat[(prod, cda)] = compat_dict[(prod, t)]
            else:
                prod_dest_compat[(prod, cda)] = True # fallback default

    # 1.4 Initial inventory mapping distributed across compatible products
    initial_inventory_dp = {}
    for d in all_warehouses_list:
        for p in all_products:
            initial_inventory_dp[(d, p)] = 0.0
            
    for d in existing_warehouses_list:
        compat_prods = [p for p in all_products if prod_dest_compat.get((p, d), True)]
        total_init_stock = demand_initial_inventory.get(d, 0.0)
        if compat_prods and total_init_stock > 0:
            split_stock = total_init_stock / len(compat_prods)
            for p in compat_prods:
                initial_inventory_dp[(d, p)] = split_stock

    # 1.5 Bulkification eligibility based on type selection
    bulk_eligible_types_set = set(bulk_eligible_types or [])
    bulk_eligible_list = [
        d for d in all_warehouses_list
        if warehouse_type.get(d) in bulk_eligible_types_set
    ]

    # 1.6 Parse Customer Demand Data & Coordinates Matching
    demand_df = df_demand.copy()
    city_coords_df = demand_df[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts = city_coords_df['Cidade'].value_counts()
    duplicates = city_counts[city_counts > 1].index
    
    def get_city_display(row):
        if row['Cidade'] in duplicates:
            return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
        return row['Cidade']
        
    demand_df['Cliente'] = demand_df.apply(get_city_display, axis=1)
    
    Customers = demand_df['Cliente'].unique().tolist()
    
    # Classify Customer nodes into Domestic vs Export
    Customers_exp = set()
    for _, row in demand_df.iterrows():
        if pd.isna(row['Peso (ton)']):
            Customers_exp.add(row['Cliente'])
            
    Customers_dom = set(Customers) - Customers_exp
    
    Customers_exp = list(Customers_exp)
    Customers_dom = list(Customers_dom)

    # Pre-calculate monthly product supply sum for export clearing sinks
    total_supply_pt = {}
    for (o, p, t), val in supply_dict.items():
        total_supply_pt[(p, t)] = total_supply_pt.get((p, t), 0.0) + val

    demand_min = {}
    demand_max = {}
    
    for c in Customers_dom:
        for p in all_products:
            for t in periods:
                demand_min[(c, p, t)] = 0.0
                
    for c in Customers_exp:
        for p in all_products:
            for t in periods:
                demand_max[(c, p, t)] = total_supply_pt.get((p, t), 0.0)

    for _, row in demand_df.iterrows():
        c = row['Cliente']
        p = row['Produto']
        t = row['Data']
        val = row['Peso (ton)']
        
        if t not in periods:
            continue
            
        if c in Customers_dom:
            if pd.notna(val):
                demand_min[(c, p, t)] = float(val)
        else:
            if pd.notna(val):
                demand_max[(c, p, t)] = float(val)

    # 1.7 Parse Distance Matrices
    distance_od = {}
    for _, row in df_dist_supply_wh.iterrows():
        orig = row['Origem']
        for col in df_dist_supply_wh.columns:
            if col != 'Origem':
                cda = col.split(' - ')[0].strip() if ' - ' in str(col) else str(col).strip()
                val = row[col]
                if pd.notna(val) and str(val).strip().upper() != 'N/A':
                    distance_od[(orig, cda)] = safe_parse_numeric(val)

    distance_dc = {}
    for _, row in df_dist_wh_demand.iterrows():
        orig_wh = row['Origem']
        cda = orig_wh.split(' - ')[0].strip() if ' - ' in str(orig_wh) else str(orig_wh).strip()
        for col in df_dist_wh_demand.columns:
            if col != 'Origem':
                val = row[col]
                if pd.notna(val) and str(val).strip().upper() != 'N/A':
                    distance_dc[(cda, col)] = safe_parse_numeric(val)

    distance_dd = {}
    for _, row in df_dist_wh_wh.iterrows():
        orig_wh = row['Origem']
        cda1 = orig_wh.split(' - ')[0].strip() if ' - ' in str(orig_wh) else str(orig_wh).strip()
        for col in df_dist_wh_wh.columns:
            if col != 'Origem':
                cda2 = col.split(' - ')[0].strip() if ' - ' in str(col) else str(col).strip()
                val = row[col]
                if pd.notna(val) and str(val).strip().upper() != 'N/A':
                    distance_dd[(cda1, cda2)] = safe_parse_numeric(val)

    # 1.8 Parse Freight Rates (Valor_Tonelada_km)
    try:
        df_freight['Frete_Num'] = df_freight['Frete Tonelada Km'].apply(safe_parse_numeric)
        freight_dict = df_freight.set_index('Estado')['Frete_Num'].to_dict()
        avg_freight = df_freight['Frete_Num'].mean()
    except Exception:
        freight_dict = {}
        avg_freight = 0.3

    freight_origin = {}
    for orig in df_supply['Cidade'].unique():
        uf = str(orig).split('-')[-1].strip() if '-' in str(orig) else None
        freight_origin[orig] = freight_dict.get(uf, avg_freight)
        
    freight_dest = {}
    for d in all_warehouses_list:
        uf = warehouse_uf.get(d)
        freight_dest[d] = freight_dict.get(uf, avg_freight)

    # 1.9 Parse Storage Tariff
    storage_cost = {}
    try:
        import unicodedata
        def normalize_str(s):
            if pd.isna(s):
                return ""
            s_str = str(s).strip()
            s_nfkd = unicodedata.normalize('NFKD', s_str)
            s_ascii = s_nfkd.encode('ASCII', 'ignore').decode('utf-8')
            return s_ascii.lower()

        df_storage['Cost'] = df_storage['Armazenar'].apply(safe_parse_numeric)
        df_storage['Prod_Norm'] = df_storage['Produto'].apply(normalize_str)
        cost_dict = df_storage.set_index('Prod_Norm')['Cost'].to_dict()
        fallback_cost = cost_dict.get('outros', 50.0)

        for prod in all_products:
            prod_norm = normalize_str(prod)
            val = cost_dict.get(prod_norm, fallback_cost)
            for d in all_warehouses_list:
                storage_cost[(d, prod)] = val
    except Exception as e:
        print(f"Error processing storage tariffs: {e}")
        for prod in all_products:
            for d in all_warehouses_list:
                storage_cost[(d, prod)] = 50.0

    # =========================================================================
    # 2. SPARSE ROUTE BUILDING & PARETO FILTER
    # =========================================================================
    
    valid_routes_od = []
    for o in df_supply['Cidade'].unique():
        for p in all_products:
            dests = []
            for d in all_warehouses_list:
                if (o, d) in distance_od and prod_dest_compat.get((p, d), True):
                    dests.append((d, distance_od[(o, d)]))
            if dests:
                if toggle_pareto:
                    dests.sort(key=lambda x: x[1])
                    limit = max(1, math.ceil(len(dests) * 0.20))
                    dests = dests[:limit]
                for d, _ in dests:
                    valid_routes_od.append((o, d, p))

    valid_routes_dc = []
    for d in all_warehouses_list:
        for p in all_products:
            if prod_dest_compat.get((p, d), True):
                custs = []
                for c in Customers:
                    if (d, c) in distance_dc:
                        custs.append((c, distance_dc[(d, c)]))
                if custs:
                    if toggle_pareto:
                        custs.sort(key=lambda x: x[1])
                        limit = max(1, math.ceil(len(custs) * 0.20))
                        custs = custs[:limit]
                    for c, _ in custs:
                        valid_routes_dc.append((d, c, p))

    valid_routes_dd = []
    for d1 in all_warehouses_list:
        for p in all_products:
            if prod_dest_compat.get((p, d1), True):
                d2s = []
                for d2 in all_warehouses_list:
                    if d1 != d2 and (d1, d2) in distance_dd and prod_dest_compat.get((p, d2), True):
                        d2s.append((d2, distance_dd[(d1, d2)]))
                if d2s:
                    if toggle_pareto:
                        d2s.sort(key=lambda x: x[1])
                        limit = max(1, math.ceil(len(d2s) * 0.20))
                        d2s = d2s[:limit]
                    for d2, _ in d2s:
                        valid_routes_dd.append((d1, d2, p))

    # =========================================================================
    # 3. PYOMO CONCRETE MODEL CONSTRUCTION
    # =========================================================================
    model = pyo.ConcreteModel()
    
    # Define Sets
    model.Origins = pyo.Set(initialize=df_supply['Cidade'].unique().tolist())
    model.Destinations = pyo.Set(initialize=all_warehouses_list)
    model.Destinations_exist = pyo.Set(initialize=existing_warehouses_list)
    model.Destinations_cand = pyo.Set(initialize=candidate_warehouses_list)
    model.BulkEligible = pyo.Set(initialize=bulk_eligible_list)
    model.Customers = pyo.Set(initialize=Customers)
    model.Customers_dom = pyo.Set(initialize=Customers_dom)
    model.Customers_exp = pyo.Set(initialize=Customers_exp)
    model.Products = pyo.Set(initialize=all_products)
    model.TimePeriods = pyo.Set(initialize=periods, ordered=True)
    
    model.ValidRoutesOD = pyo.Set(initialize=valid_routes_od, dimen=3)
    model.ValidRoutesDC = pyo.Set(initialize=valid_routes_dc, dimen=3)
    model.ValidRoutesDD = pyo.Set(initialize=valid_routes_dd, dimen=3)

    # Define Parameters
    def supply_init(m, o, p, t):
        return supply_dict.get((o, p, t), 0.0)
    model.Supply = pyo.Param(model.Origins, model.Products, model.TimePeriods, initialize=supply_init)

    def demand_min_init(m, c, p, t):
        return demand_min.get((c, p, t), 0.0)
    model.DemandMin = pyo.Param(model.Customers_dom, model.Products, model.TimePeriods, initialize=demand_min_init)

    def demand_max_init(m, c, p, t):
        return demand_max.get((c, p, t), 0.0)
    model.DemandMax = pyo.Param(model.Customers_exp, model.Products, model.TimePeriods, initialize=demand_max_init)

    def static_cap_init(m, d):
        return static_capacity.get(d, 0.0)
    model.StaticCapacity = pyo.Param(model.Destinations_exist, initialize=static_cap_init)

    def recep_cap_init(m, d):
        return reception_capacity.get(d, 0.0)
    model.ReceptionCapacity = pyo.Param(model.Destinations_exist, initialize=recep_cap_init)

    def ship_cap_init(m, d):
        return shipping_capacity.get(d, 0.0)
    model.ShippingCapacity = pyo.Param(model.Destinations_exist, initialize=ship_cap_init)

    def init_inv_init(m, d, p):
        return initial_inventory_dp.get((d, p), 0.0)
    model.InitialInventory = pyo.Param(model.Destinations, model.Products, initialize=init_inv_init)

    def open_cost_init(m, d):
        return opening_cost.get(d, 0.0)
    model.OpeningCost = pyo.Param(model.Destinations_cand, initialize=open_cost_init)

    def max_cand_static_init(m, d):
        return max_cand_static_capacity.get(d, 0.0)
    model.MaxCandStaticCapacity = pyo.Param(model.Destinations_cand, initialize=max_cand_static_init)

    def storage_tariff_init(m, d, p):
        return storage_cost.get((d, p), 50.0)
    model.StorageTariff = pyo.Param(model.Destinations, model.Products, initialize=storage_tariff_init)

    def freight_origin_init(m, o):
        return freight_origin.get(o, avg_freight)
    model.FreightOrigin = pyo.Param(model.Origins, initialize=freight_origin_init)

    def freight_dest_init(m, d):
        return freight_dest.get(d, avg_freight)
    model.FreightDest = pyo.Param(model.Destinations, initialize=freight_dest_init)

    def dist_od_init(m, o, d):
        return distance_od.get((o, d), 999999.0)
    model.DistanceOD = pyo.Param(model.Origins, model.Destinations, initialize=dist_od_init)

    def dist_dc_init(m, d, c):
        return distance_dc.get((d, c), 999999.0)
    model.DistanceDC = pyo.Param(model.Destinations, model.Customers, initialize=dist_dc_init)

    def dist_dd_init(m, d1, d2):
        return distance_dd.get((d1, d2), 999999.0)
    model.DistanceDD = pyo.Param(model.Destinations, model.Destinations, initialize=dist_dd_init)

    model.TransshipmentDiscount = pyo.Param(initialize=float(transshipment_discount))
    model.Days = pyo.Param(initialize=float(input_allocation_days))
    
    # Upgrade parameters
    def max_expand_init(m, d):
        return float(max_expand_capacity)
    model.MaxExpandCapacity = pyo.Param(model.Destinations, initialize=max_expand_init)
    
    def expand_fixed_cost_init(m, d):
        return float(expand_fixed_cost)
    model.ExpandFixedCost = pyo.Param(model.Destinations, initialize=expand_fixed_cost_init)
    
    def expand_var_cost_init(m, d):
        return float(expand_var_cost)
    model.ExpandVarCost = pyo.Param(model.Destinations, initialize=expand_var_cost_init)
    
    def max_bulk_init(m, d):
        return float(max_bulk_capacity)
    model.MaxBulkCapacity = pyo.Param(model.Destinations, initialize=max_bulk_init)
    
    def bulk_fixed_cost_init(m, d):
        return float(bulk_fixed_cost)
    model.BulkFixedCost = pyo.Param(model.Destinations, initialize=bulk_fixed_cost_init)
    
    def bulk_var_cost_init(m, d):
        return float(bulk_var_cost)
    model.BulkVarCost = pyo.Param(model.Destinations, initialize=bulk_var_cost_init)
    
    model.RatioExpandRec = pyo.Param(initialize=float(ratio_expand_rec))
    model.RatioExpandShip = pyo.Param(initialize=float(ratio_expand_ship))

    # Decision Variables
    model.FlowOD = pyo.Var(model.ValidRoutesOD, model.TimePeriods, within=pyo.NonNegativeReals)
    model.FlowDC = pyo.Var(model.ValidRoutesDC, model.TimePeriods, within=pyo.NonNegativeReals)
    model.FlowDD = pyo.Var(model.ValidRoutesDD, model.TimePeriods, within=pyo.NonNegativeReals)
    model.Inventory = pyo.Var(model.Destinations, model.Products, model.TimePeriods, within=pyo.NonNegativeReals)
    model.CandStaticCapacity = pyo.Var(model.Destinations_cand, within=pyo.NonNegativeReals)
    model.ExpandedCapacity = pyo.Var(model.Destinations, within=pyo.NonNegativeReals)
    model.BulkCapacity = pyo.Var(model.Destinations, within=pyo.NonNegativeReals)
    
    model.WarehouseOpen = pyo.Var(model.Destinations_cand, within=pyo.Binary)
    model.IsExpanded = pyo.Var(model.Destinations, within=pyo.Binary)
    model.IsBulkified = pyo.Var(model.Destinations, within=pyo.Binary)

    # Helper function to represent open decision variables / fixed parameter
    def get_open_expr(m, d):
        if d in m.Destinations_exist:
            return 1
        else:
            return m.WarehouseOpen[d]

    # =========================================================================
    # 4. OBJECTIVE FUNCTION DEFINITION
    # =========================================================================
    
    # 4.1 Freight cost from supply origins to warehouse hubs (OD)
    freight_od_expr = sum(
        model.FlowOD[o, d, p, t] * (model.DistanceOD[o, d] * model.FreightOrigin[o])
        for (o, d, p) in model.ValidRoutesOD
        for t in model.TimePeriods
    )
    
    # 4.2 Freight cost from warehouses to demand customers (DC)
    freight_dc_expr = sum(
        model.FlowDC[d, c, p, t] * (model.DistanceDC[d, c] * model.FreightDest[d])
        for (d, c, p) in model.ValidRoutesDC
        for t in model.TimePeriods
    )
    
    # 4.3 Freight cost of transshipments between warehouses (DD) with discount factor alpha
    freight_dd_expr = sum(
        model.FlowDD[d1, d2, p, t] * (model.TransshipmentDiscount * model.DistanceDD[d1, d2] * model.FreightDest[d1])
        for (d1, d2, p) in model.ValidRoutesDD
        for t in model.TimePeriods
    )
    
    # 4.4 Cumulative storage holding tariffs per product per warehouse per period
    storage_cost_expr = sum(
        model.Inventory[d, p, t] * model.StorageTariff[d, p]
        for d in model.Destinations
        for p in model.Products
        for t in model.TimePeriods
    )
    
    # 4.5 Fixed construction/opening cost of candidate warehouses
    opening_cost_expr = sum(
        model.WarehouseOpen[d] * model.OpeningCost[d]
        for d in model.Destinations_cand
    )
    
    # 4.6 Fixed and variable capital costs of static capacity expansion projects
    expand_cost_expr = sum(
        model.IsExpanded[d] * model.ExpandFixedCost[d] + model.ExpandedCapacity[d] * model.ExpandVarCost[d]
        for d in model.Destinations
    )
    
    # 4.7 Fixed and variable capital costs of bulkification modernization projects
    bulk_cost_expr = sum(
        model.IsBulkified[d] * model.BulkFixedCost[d] + model.BulkCapacity[d] * model.BulkVarCost[d]
        for d in model.BulkEligible
    )
    
    def obj_rule(m):
        return freight_od_expr + freight_dc_expr + freight_dd_expr + storage_cost_expr + opening_cost_expr + expand_cost_expr + bulk_cost_expr
        
    model.Objective = pyo.Objective(rule=obj_rule, sense=pyo.minimize, doc="Total Supply Chain Minimization Objective")

    # =========================================================================
    # 5. MODEL CONSTRAINTS
    # =========================================================================

    # 5.1 Supply Allocation Bound (Hard Equality constraint: all supply must be dispatched)
    def supply_allocation_rule(m, o, p, t):
        valid_dests = [d for d_ in m.Destinations if (o, d_, p) in m.ValidRoutesOD]
        if not valid_dests:
            return pyo.Constraint.Skip
        return sum(m.FlowOD[o, d, p, t] for d in valid_dests) == m.Supply[o, p, t]
        
    model.SupplyAllocationConstraint = pyo.Constraint(model.Origins, model.Products, model.TimePeriods, rule=supply_allocation_rule, doc="Restrição de Limite de Oferta (Dispatch)")

    # 5.2 Inventory Balance and Conservation (temporal carryover loop)
    def inventory_balance_rule(m, d, p, t):
        # Gathering inflows (supply flows + transshipment inputs)
        valid_origins = [o for o in m.Origins if (o, d, p) in m.ValidRoutesOD]
        valid_trans_in = [d1 for d1 in m.Destinations if (d1, d, p) in m.ValidRoutesDD]
        
        inflow = sum(m.FlowOD[o, d, p, t] for o in valid_origins) + \
                 sum(m.FlowDD[d1, d, p, t] for d1 in valid_trans_in)
                 
        # Gathering outflows (customer flows + transshipment outputs)
        valid_customers = [c for c in m.Customers if (d, c, p) in m.ValidRoutesDC]
        valid_trans_out = [d2 for d2 in m.Destinations if (d, d2, p) in m.ValidRoutesDD]
        
        outflow = sum(m.FlowDC[d, c, p, t] for c in valid_customers) + \
                  sum(m.FlowDD[d, d2, p, t] for d2 in valid_trans_out)
                  
        # Check index for boundary condition using predecessor map
        if t == periods[0]:
            prev_inv = m.InitialInventory[d, p]
        else:
            prev_t = prev_period_map[t]
            prev_inv = m.Inventory[d, p, prev_t]
            
        return m.Inventory[d, p, t] == prev_inv + inflow - outflow
        
    model.InventoryBalanceConstraint = pyo.Constraint(model.Destinations, model.Products, model.TimePeriods, rule=inventory_balance_rule, doc="Restrição de Balanço e Conservação de Estoque")

    # 5.3 Static Capacity Bound (Existing vs Candidate static limit)
    def static_capacity_rule(m, d, t):
        total_inv = sum(m.Inventory[d, p, t] for p in m.Products)
        if d in m.Destinations_exist:
            return total_inv <= m.StaticCapacity[d] + m.ExpandedCapacity[d]
        else:
            return total_inv <= m.CandStaticCapacity[d] + m.ExpandedCapacity[d]
            
    model.StaticCapacityConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, rule=static_capacity_rule, doc="Restrição de Capacidade Estática Efetiva")

    # 5.4 Physical Reception Handling Bound
    def reception_handling_rule(m, d, t):
        inflow_sum = sum(
            m.FlowOD[o, d, p, t] for (o, d_, p) in m.ValidRoutesOD if d_ == d
        ) + sum(
            m.FlowDD[d1, d, p, t] for (d1, d_, p) in m.ValidRoutesDD if d_ == d
        )
        
        bulk_increase = m.BulkCapacity[d] if d in m.BulkEligible else 0.0
        
        if d in m.Destinations_exist:
            max_inflow = (m.ReceptionCapacity[d] + m.RatioExpandRec * m.ExpandedCapacity[d] + bulk_increase) * m.Days
        else: # Candidate
            max_inflow = (m.RatioExpandRec * m.CandStaticCapacity[d] + m.RatioExpandRec * m.ExpandedCapacity[d] + bulk_increase) * m.Days
            
        return inflow_sum <= max_inflow

    # 5.5 Physical Shipping Handling Bound
    def shipping_handling_rule(m, d, t):
        outflow_sum = sum(
            m.FlowDC[d, c, p, t] for (d_, c, p) in m.ValidRoutesDC if d_ == d
        ) + sum(
            m.FlowDD[d, d2, p, t] for (d_, d2, p) in m.ValidRoutesDD if d_ == d
        )
        
        bulk_increase = m.BulkCapacity[d] if d in m.BulkEligible else 0.0
        
        if d in m.Destinations_exist:
            max_outflow = (m.ShippingCapacity[d] + m.RatioExpandShip * m.ExpandedCapacity[d] + bulk_increase) * m.Days
        else: # Candidate
            max_outflow = (m.RatioExpandShip * m.CandStaticCapacity[d] + m.RatioExpandShip * m.ExpandedCapacity[d] + bulk_increase) * m.Days
            
        return outflow_sum <= max_outflow
        
    model.ReceptionHandlingConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, rule=reception_handling_rule, doc="Restrição de Limite Físico de Recepção (Handling)")
    model.ShippingHandlingConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, rule=shipping_handling_rule, doc="Restrição de Limite Físico de Expedição (Handling)")

    # 5.6 Mutual Exclusion of Modifications (Expansion vs Bulkification)
    def mutual_exclusion_rule(m, d):
        h_val = get_open_expr(m, d)
        if d in m.BulkEligible:
            return m.IsExpanded[d] + m.IsBulkified[d] <= h_val
        else:
            return m.IsExpanded[d] <= h_val
            
    model.MutualExclusionConstraint = pyo.Constraint(model.Destinations, rule=mutual_exclusion_rule, doc="Restrição de Exclusividade de Modernização")

    # 5.7 Bulkification Compatibility and Bounding Locks
    def bulk_eligibility_lock_rule_var(m, d):
        if d not in m.BulkEligible:
            return m.IsBulkified[d] == 0
        return pyo.Constraint.Skip
        
    def bulk_eligibility_lock_rule_cap(m, d):
        if d not in m.BulkEligible:
            return m.BulkCapacity[d] == 0
        return pyo.Constraint.Skip
        
    model.BulkEligibilityLockVar = pyo.Constraint(model.Destinations, rule=bulk_eligibility_lock_rule_var, doc="Trava de Inelegibilidade de Granelização (Var)")
    model.BulkEligibilityLockCap = pyo.Constraint(model.Destinations, rule=bulk_eligibility_lock_rule_cap, doc="Trava de Inelegibilidade de Granelização (Cap)")

    # 5.8 Sizing bounds for candidate warehouses
    def cand_static_bounding_rule(m, d):
        return m.CandStaticCapacity[d] <= m.WarehouseOpen[d] * m.MaxCandStaticCapacity[d]
        
    model.CandStaticBoundingConstraint = pyo.Constraint(model.Destinations_cand, rule=cand_static_bounding_rule, doc="Limite de Dimensionamento de Novo Hub")

    # 5.9 upgrade bounding rules for physical expansion and bulkification capacity
    def bulk_bounding_rule(m, d):
        return m.BulkCapacity[d] <= m.IsBulkified[d] * m.MaxBulkCapacity[d]
        
    def expand_bounding_rule(m, d):
        return m.ExpandedCapacity[d] <= m.IsExpanded[d] * m.MaxExpandCapacity[d]
        
    model.BulkBoundingConstraint = pyo.Constraint(model.BulkEligible, rule=bulk_bounding_rule, doc="Limite Contínuo de Granelização")
    model.ExpandBoundingConstraint = pyo.Constraint(model.Destinations, rule=expand_bounding_rule, doc="Limite Contínuo de Expansão Estática")

    # 5.10 Customer Demand Satisfaction (Domestic Strict Equality vs Export Max upper bound)
    def domestic_demand_rule(m, c, p, t):
        valid_dests = [d for d_ in m.Destinations if (d_, c, p) in m.ValidRoutesDC]
        if not valid_dests:
            return pyo.Constraint.Skip
        return sum(m.FlowDC[d, c, p, t] for d in valid_dests) == m.DemandMin[c, p, t]

    def export_demand_rule(m, c, p, t):
        valid_dests = [d for d_ in m.Destinations if (d_, c, p) in m.ValidRoutesDC]
        if not valid_dests:
            return pyo.Constraint.Skip
        return sum(m.FlowDC[d, c, p, t] for d in valid_dests) <= m.DemandMax[c, p, t]
        
    model.DomesticDemandConstraint = pyo.Constraint(model.Customers_dom, model.Products, model.TimePeriods, rule=domestic_demand_rule, doc="Restrição de Atendimento da Demanda Interna")
    model.ExportDemandConstraint = pyo.Constraint(model.Customers_exp, model.Products, model.TimePeriods, rule=export_demand_rule, doc="Restrição Quota Máxima de Exportação (Sink)")

    # =========================================================================
    # 6. SOLVER WRAPPER & EXECUTION
    # =========================================================================

    old_stdout = sys.stdout
    log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
    os.makedirs(log_dir, exist_ok=True)

    # Clean old logs to save disk space
    now = time.time()
    for filename in os.listdir(log_dir):
        filepath = os.path.join(log_dir, filename)
        if os.path.isfile(filepath):
            if os.stat(filepath).st_mtime < now - 3600:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

    log_fd, log_path = tempfile.mkstemp(suffix='.txt', prefix='optimization_log_', dir=log_dir)
    log_filename = os.path.basename(log_path)
    new_stdout = os.fdopen(log_fd, 'w', encoding='utf-8')
    sys.stdout = new_stdout

    try:
        if detailed_log:
            model.pprint()
            
        print("\n" + translate("Chamando solver CBC...", lang))
        solver = SolverFactory('cbc')
        
        if solver_time_limit is not None:
            solver.options['sec'] = int(solver_time_limit)
        else:
            solver.options['sec'] = 1200
            
        if solver_gap is not None:
            try:
                gap_val = float(solver_gap)
                if gap_val > 1.0:
                    gap_val = gap_val / 100.0
                solver.options['ratioGap'] = gap_val
            except Exception:
                solver.options['ratioGap'] = 0.01

        # Run solver
        results = solver.solve(model, tee=True)
        
        print("\n" + translate("=== STATUS DA OTIMIZAÇÃO ===", lang))
        print(translate("Status do Solver: {status}", lang).format(status=results.solver.status))
        print(translate("Condição de Término: {condition}", lang).format(condition=results.solver.termination_condition))

    finally:
        new_stdout.flush()
        new_stdout.close()
        sys.stdout = old_stdout

    # =========================================================================
    # 7. POST-OPTIMIZATION RESULTS COLLECTION
    # =========================================================================
    
    results_status = results.solver.termination_condition
    is_optimal = results_status == pyo.TerminationCondition.optimal
    
    # Initialize basic stats
    results_dict = {
        "status": "optimal" if is_optimal else str(results_status),
        "objective": 0.0,
        "routes": [],
        "kpis": {
            "total_tons": 0.0,
            "total_km": 0.0,
            "total_freight_cost": 0.0,
            "total_storage_cost": 0.0,
            "total_opening_cost": 0.0,
            "total_expand_cost": 0.0,
            "total_bulk_cost": 0.0,
            "execution_time": time.time() - start_time,
        },
        "model_stats": {
            "total_variables": sum(1 for _ in model.component_data_objects(pyo.Var, active=True)),
            "total_constraints": sum(1 for _ in model.component_data_objects(pyo.Constraint, active=True)),
            "binary_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain == pyo.Binary),
            "integer_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Integers, pyo.NonNegativeIntegers, pyo.PositiveIntegers)),
            "continuous_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Reals, pyo.NonNegativeReals, pyo.PositiveReals))
        },
        "warnings": [],
        "warehouse_decisions": [],
        "inventory": []
    }

    if is_optimal:
        # Populate optimal costs
        results_dict["objective"] = pyo.value(model.Objective)
        
        total_freight_cost = sum(
            pyo.value(model.FlowOD[o, d, p, t]) * (model.DistanceOD[o, d] * model.FreightOrigin[o])
            for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
        ) + sum(
            pyo.value(model.FlowDC[d, c, p, t]) * (model.DistanceDC[d, c] * model.FreightDest[d])
            for (d, c, p) in model.ValidRoutesDC for t in model.TimePeriods
        ) + sum(
            pyo.value(model.FlowDD[d1, d2, p, t]) * (model.TransshipmentDiscount * model.DistanceDD[d1, d2] * model.FreightDest[d1])
            for (d1, d2, p) in model.ValidRoutesDD for t in model.TimePeriods
        )
        
        total_storage_cost = sum(
            pyo.value(model.Inventory[d, p, t]) * model.StorageTariff[d, p]
            for d in model.Destinations for p in model.Products for t in model.TimePeriods
        )
        
        total_opening_cost = sum(
            pyo.value(model.WarehouseOpen[d]) * model.OpeningCost[d]
            for d in model.Destinations_cand
        )
        
        total_expand_cost = sum(
            pyo.value(model.IsExpanded[d]) * model.ExpandFixedCost[d] + pyo.value(model.ExpandedCapacity[d]) * model.ExpandVarCost[d]
            for d in model.Destinations
        )
        
        total_bulk_cost = sum(
            pyo.value(model.IsBulkified[d]) * model.BulkFixedCost[d] + pyo.value(model.BulkCapacity[d]) * model.BulkVarCost[d]
            for d in model.BulkEligible
        )
        
        total_tons = sum(
            pyo.value(model.FlowOD[o, d, p, t])
            for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
        )
        
        total_km = sum(
            pyo.value(model.FlowOD[o, d, p, t]) * model.DistanceOD[o, d]
            for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
        ) + sum(
            pyo.value(model.FlowDC[d, c, p, t]) * model.DistanceDC[d, c]
            for (d, c, p) in model.ValidRoutesDC for t in model.TimePeriods
        ) + sum(
            pyo.value(model.FlowDD[d1, d2, p, t]) * model.DistanceDD[d1, d2]
            for (d1, d2, p) in model.ValidRoutesDD for t in model.TimePeriods
        )

        results_dict["kpis"] = {
            "total_tons": total_tons,
            "total_km": total_km,
            "total_freight_cost": total_freight_cost,
            "total_storage_cost": total_storage_cost,
            "total_opening_cost": total_opening_cost,
            "total_expand_cost": total_expand_cost,
            "total_bulk_cost": total_bulk_cost,
            "execution_time": time.time() - start_time
        }

        # Populate routes for visualization (all levels)
        routes_list = []
        
        # OD flows
        for (o, d, p) in model.ValidRoutesOD:
            for t in model.TimePeriods:
                val = pyo.value(model.FlowOD[o, d, p, t])
                if val > 1e-4:
                    dist = pyo.value(model.DistanceOD[o, d])
                    freight = val * dist * pyo.value(model.FreightOrigin[o])
                    routes_list.append({
                        "Origem": o,
                        "Destino": cda_to_name.get(d, d),
                        "Produto": p,
                        "Quantidade (ton)": val,
                        "Período": t,
                        "Tipo de Rota": "Origem -> Armazém",
                        "Distancia (km)": dist,
                        "Custo Frete (R$)": freight,
                        "Custo Armazenagem (R$)": 0.0,
                        "Custo Total (R$)": freight
                    })
                    
        # DC flows
        for (d, c, p) in model.ValidRoutesDC:
            for t in model.TimePeriods:
                val = pyo.value(model.FlowDC[d, c, p, t])
                if val > 1e-4:
                    dist = pyo.value(model.DistanceDC[d, c])
                    freight = val * dist * pyo.value(model.FreightDest[d])
                    routes_list.append({
                        "Origem": cda_to_name.get(d, d),
                        "Destino": c,
                        "Produto": p,
                        "Quantidade (ton)": val,
                        "Período": t,
                        "Tipo de Rota": "Armazém -> Cliente",
                        "Distancia (km)": dist,
                        "Custo Frete (R$)": freight,
                        "Custo Armazenagem (R$)": 0.0,
                        "Custo Total (R$)": freight
                    })
                    
        # DD flows
        for (d1, d2, p) in model.ValidRoutesDD:
            for t in model.TimePeriods:
                val = pyo.value(model.FlowDD[d1, d2, p, t])
                if val > 1e-4:
                    dist = pyo.value(model.DistanceDD[d1, d2])
                    freight = val * pyo.value(model.TransshipmentDiscount) * dist * pyo.value(model.FreightDest[d1])
                    routes_list.append({
                        "Origem": cda_to_name.get(d1, d1),
                        "Destino": cda_to_name.get(d2, d2),
                        "Produto": p,
                        "Quantidade (ton)": val,
                        "Período": t,
                        "Tipo de Rota": "Transbordo",
                        "Distancia (km)": dist,
                        "Custo Frete (R$)": freight,
                        "Custo Armazenagem (R$)": 0.0,
                        "Custo Total (R$)": freight
                    })
                    
        results_dict["routes"] = routes_list

        # Warehouse upgrade sizing decisions & computed Turnover post-solve
        wh_decisions_list = []
        for d in all_warehouses_list:
            is_cand = d in candidate_warehouses_list
            is_open = True if not is_cand else (pyo.value(model.WarehouseOpen[d]) > 0.5)
            cand_static = 0.0 if not is_cand else pyo.value(model.CandStaticCapacity[d])
            
            is_exp = pyo.value(model.IsExpanded[d]) > 0.5
            exp_cap = pyo.value(model.ExpandedCapacity[d])
            
            is_bulk = pyo.value(model.IsBulkified[d]) > 0.5 if d in bulk_eligible_list else False
            bulk_cap = pyo.value(model.BulkCapacity[d]) if d in bulk_eligible_list else 0.0
            
            # Post-solve DynCap turnover metrics (academic / post-optimization evaluation)
            total_outflow = sum(
                pyo.value(model.FlowDC[d_, c, p, t])
                for (d_, c, p) in model.ValidRoutesDC if d_ == d
                for t in model.TimePeriods
            ) + sum(
                pyo.value(model.FlowDD[d_, d2, p, t])
                for (d_, d2, p) in model.ValidRoutesDD if d_ == d
                for t in model.TimePeriods
            )
            
            final_stock = sum(
                pyo.value(model.Inventory[d, p, periods[-1]])
                for p in all_products
            )
            
            dyn_cap_raw = total_outflow + final_stock
            
            # Annualize DynCap and Turnover
            num_periods = len(periods)
            annualization_factor = 12.0 / num_periods if num_periods > 0 else 1.0
            dyn_cap_annual = dyn_cap_raw * annualization_factor
            
            if not is_cand:
                effective_static = static_capacity.get(d, 0.0) + exp_cap
            else:
                effective_static = cand_static + exp_cap
                
            turnover_annual = dyn_cap_annual / effective_static if effective_static > 0.0 else 0.0
            
            wh_decisions_list.append({
                "CDA": d,
                "Name": cda_to_name.get(d, d),
                "IsCandidate": is_cand,
                "IsOpen": is_open,
                "DecidedStaticCapacity": cand_static if is_cand else static_capacity.get(d, 0.0),
                "IsExpanded": is_exp,
                "ExpandedVolume": exp_cap,
                "IsBulkified": is_bulk,
                "BulkCapacityAdded": bulk_cap,
                "TotalOutflow": total_outflow,
                "FinalStock": final_stock,
                "DynamicCapacity": dyn_cap_annual,
                "DynamicCapacityRaw": dyn_cap_raw,
                "EffectiveStaticCapacity": effective_static,
                "TurnoverRatio": turnover_annual
            })
            
        results_dict["warehouse_decisions"] = wh_decisions_list

        # Inventory per warehouse per period
        inventory_records = []
        for d in all_warehouses_list:
            for p in all_products:
                for t in periods:
                    val = pyo.value(model.Inventory[d, p, t])
                    inventory_records.append({
                        "CDA": d,
                        "Name": cda_to_name.get(d, d),
                        "Produto": p,
                        "Período": t,
                        "Quantidade (ton)": val
                    })
        results_dict["inventory"] = inventory_records

    return log_filename, results_dict
