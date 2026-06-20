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
    
    cda_to_name = {}
    mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
    armaz_col = next((c for c in df_warehouses.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)

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
        if armaz_col and armaz_col in row and pd.notna(row[armaz_col]):
            parts.append(str(row[armaz_col]).strip())
        if mun_col and mun_col in row and pd.notna(row[mun_col]):
            parts.append(str(row[mun_col]).strip())
            
        cda_to_name[cda] = " - ".join(parts) if parts else cda

        if status == 'Existente':
            existing_warehouses_list.append(cda)
            static_capacity[cda] = safe_parse_numeric(row['Cap. Estática (t)'])
            reception_capacity[cda] = safe_parse_numeric(row['Cap. Recepção (t)'])
            shipping_capacity[cda] = safe_parse_numeric(row['Cap. Expedição (t)'])
        else: # Candidate
            candidate_warehouses_list.append(cda)
            opening_cost[cda] = safe_parse_numeric(row['Custo de Abertura ($)'])
            max_cand_static_capacity[cda] = safe_parse_numeric(row['Cap. Estática Máxima (t)'])

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

    # Pre-optimization feasibility check: total supply >= total demand in the first period
    if periods:
        p1 = periods[0]
        for p in all_products:
            tot_sup = sum(val for (o, prod, t), val in supply_dict.items() if prod == p and t == p1)
            tot_dem = sum(val for (c, prod, t), val in demand_min.items() if prod == p and t == p1)
            if tot_sup < tot_dem:
                msg = translate("Erro: Oferta total ({supply:.2f} ton) é menor que a demanda total ({demand:.2f} ton) no primeiro período ({period}) para o produto '{product}'.", lang).format(
                    supply=tot_sup,
                    demand=tot_dem,
                    period=str(p1),
                    product=p
                )
                raise ValueError(msg)

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
        return float(max_expand_capacity) if max_expand_capacity is not None else 0.0
    model.MaxExpandCapacity = pyo.Param(model.Destinations, initialize=max_expand_init)
    
    def expand_fixed_cost_init(m, d):
        return float(expand_fixed_cost) if expand_fixed_cost is not None else 0.0
    model.ExpandFixedCost = pyo.Param(model.Destinations, initialize=expand_fixed_cost_init)
    
    def expand_var_cost_init(m, d):
        return float(expand_var_cost) if expand_var_cost is not None else 0.0
    model.ExpandVarCost = pyo.Param(model.Destinations, initialize=expand_var_cost_init)
    
    def max_bulk_init(m, d):
        return float(max_bulk_capacity) if max_bulk_capacity is not None else 0.0
    model.MaxBulkCapacity = pyo.Param(model.Destinations, initialize=max_bulk_init)
    
    def bulk_fixed_cost_init(m, d):
        return float(bulk_fixed_cost) if bulk_fixed_cost is not None else 0.0
    model.BulkFixedCost = pyo.Param(model.Destinations, initialize=bulk_fixed_cost_init)
    
    def bulk_var_cost_init(m, d):
        return float(bulk_var_cost) if bulk_var_cost is not None else 0.0
    model.BulkVarCost = pyo.Param(model.Destinations, initialize=bulk_var_cost_init)
    
    model.RatioExpandRec = pyo.Param(initialize=float(ratio_expand_rec) if ratio_expand_rec is not None else 0.0)
    model.RatioExpandShip = pyo.Param(initialize=float(ratio_expand_ship) if ratio_expand_ship is not None else 0.0)

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

    # Fix variables to 0 if expansion or bulkification is disabled
    if max_expand_capacity is None:
        for d in model.Destinations:
            model.IsExpanded[d].fix(0)
            model.ExpandedCapacity[d].fix(0)
            
    if max_bulk_capacity is None:
        for d in model.Destinations:
            model.IsBulkified[d].fix(0)
            model.BulkCapacity[d].fix(0)

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
        valid_dests = [d for d in m.Destinations if (o, d, p) in m.ValidRoutesOD]
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
            prev_inv = 0.0
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
        valid_dests = [d for d in m.Destinations if (d, c, p) in m.ValidRoutesDC]
        if not valid_dests:
            return pyo.Constraint.Skip
        return sum(m.FlowDC[d, c, p, t] for d in valid_dests) == m.DemandMin[c, p, t]

    def export_demand_rule(m, c, p, t):
        valid_dests = [d for d in m.Destinations if (d, c, p) in m.ValidRoutesDC]
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
            
            # Warehouse-specific costs
            opening_cost_val = pyo.value(model.WarehouseOpen[d]) * pyo.value(model.OpeningCost[d]) if is_cand else 0.0
            expand_cost_val = pyo.value(model.IsExpanded[d]) * pyo.value(model.ExpandFixedCost[d]) + pyo.value(model.ExpandedCapacity[d]) * pyo.value(model.ExpandVarCost[d])
            bulk_cost_val = pyo.value(model.IsBulkified[d]) * pyo.value(model.BulkFixedCost[d]) + pyo.value(model.BulkCapacity[d]) * pyo.value(model.BulkVarCost[d]) if d in bulk_eligible_list else 0.0
            storage_cost_val = sum(
                pyo.value(model.Inventory[d, p, t]) * pyo.value(model.StorageTariff[d, p])
                for p in all_products
                for t in periods
            )
            total_wh_cost = opening_cost_val + expand_cost_val + bulk_cost_val + storage_cost_val

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
                "TurnoverRatio": turnover_annual,
                "OpeningCost": opening_cost_val,
                "ExpandCost": expand_cost_val,
                "BulkCost": bulk_cost_val,
                "StorageCost": storage_cost_val,
                "TotalCost": total_wh_cost
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


def build_stochastic_pyomo_model(
  df_supply,
  df_warehouses,
  df_compat,
  df_dist_supply_wh,
  df_dist_wh_demand,
  df_dist_wh_wh,
  df_demand,
  df_freight,
  df_storage,
  scenario_probabilities,
  error_source,
  supply_error_pct,
  demand_error_pct,
  prediction_results,
  toggle_pareto=False,
  input_allocation_days=None,
  transshipment_discount=None,
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
  Helper to construct the stochastic Pyomo concrete model.
  Returns the Pyomo model and parsed mappings for routing/result collection.
  """
  # 1. Date and metadata parsing
  if 'Latitude' in df_supply.columns and 'Longitude' in df_supply.columns:
    origins_df = df_supply[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts = origins_df['Cidade'].value_counts()
    duplicates = city_counts[city_counts > 1].index

    def rename_city(row):
      if row['Cidade'] in duplicates:
        return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
      return row['Cidade']

    df_supply = df_supply.copy()
    df_supply['Cidade'] = df_supply.apply(rename_city, axis=1)

  periods = sorted(df_supply['Data'].dropna().unique().tolist())
  prev_period_map = {periods[i]: periods[i-1] for i in range(1, len(periods))}
  all_products = df_supply['Produto'].unique().tolist()
  
  supply_dict = df_supply.groupby(['Cidade', 'Produto', 'Data'])['Peso (ton)'].sum().to_dict()

  # 2. Parse Warehouses
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
  
  cda_to_name = {}

  cols_wh = list(df_warehouses.columns)
  mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
  armaz_col = next((c for c in df_warehouses.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
  
  armaz_idx = cols_wh.index(armaz_col) if armaz_col in cols_wh else None
  mun_idx = cols_wh.index(mun_col) if mun_col in cols_wh else None

  try:
    cda_idx = cols_wh.index('CDA')
    status_idx = cols_wh.index('Status')
    cap_est_idx = cols_wh.index('Cap. Estática (t)')
    cap_rec_idx = cols_wh.index('Cap. Recepção (t)')
    cap_exp_idx = cols_wh.index('Cap. Expedição (t)')
    cust_ab_idx = cols_wh.index('Custo de Abertura ($)')
    cap_max_idx = cols_wh.index('Cap. Estática Máxima (t)')
    tipo_idx = cols_wh.index('Tipo')
    uf_idx = cols_wh.index('UF')
    
    for row in df_warehouses.itertuples(index=False):
      cda = str(row[cda_idx]).strip()
      status = str(row[status_idx]).strip()
      all_warehouses_list.append(cda)
      warehouse_type[cda] = str(row[tipo_idx]).strip()
      warehouse_uf[cda] = str(row[uf_idx]).strip()
      
      parts = [cda]
      if armaz_idx is not None and pd.notna(row[armaz_idx]):
        parts.append(str(row[armaz_idx]).strip())
      if mun_idx is not None and pd.notna(row[mun_idx]):
        parts.append(str(row[mun_idx]).strip())
      cda_to_name[cda] = " - ".join(parts) if len(parts) > 1 else cda

      if status == 'Existente':
        existing_warehouses_list.append(cda)
        static_capacity[cda] = safe_parse_numeric(row[cap_est_idx])
        reception_capacity[cda] = safe_parse_numeric(row[cap_rec_idx])
        shipping_capacity[cda] = safe_parse_numeric(row[cap_exp_idx])
      else:
        candidate_warehouses_list.append(cda)
        opening_cost[cda] = safe_parse_numeric(row[cust_ab_idx])
        max_cand_static_capacity[cda] = safe_parse_numeric(row[cap_max_idx])
  except (ValueError, IndexError):
    # Fallback to iterrows
    for _, row in df_warehouses.iterrows():
      cda = str(row['CDA']).strip()
      status = str(row['Status']).strip()
      all_warehouses_list.append(cda)
      warehouse_type[cda] = str(row['Tipo']).strip()
      warehouse_uf[cda] = str(row['UF']).strip()
      
      parts = []
      if pd.notna(row.get('CDA')):
        parts.append(str(row['CDA']).strip())
      if armaz_col and armaz_col in row and pd.notna(row[armaz_col]):
        parts.append(str(row[armaz_col]).strip())
      if mun_col and mun_col in row and pd.notna(row[mun_col]):
        parts.append(str(row[mun_col]).strip())
      cda_to_name[cda] = " - ".join(parts) if parts else cda

      if status == 'Existente':
        existing_warehouses_list.append(cda)
        static_capacity[cda] = safe_parse_numeric(row['Cap. Estática (t)'])
        reception_capacity[cda] = safe_parse_numeric(row['Cap. Recepção (t)'])
        shipping_capacity[cda] = safe_parse_numeric(row['Cap. Expedição (t)'])
      else:
        candidate_warehouses_list.append(cda)
        opening_cost[cda] = safe_parse_numeric(row['Custo de Abertura ($)'])
        max_cand_static_capacity[cda] = safe_parse_numeric(row['Cap. Estática Máxima (t)'])

  # Product compatibility
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
        prod_dest_compat[(prod, cda)] = True

  # Bulkification eligibility
  bulk_eligible_types_set = set(bulk_eligible_types or [])
  bulk_eligible_list = [
    d for d in all_warehouses_list
    if warehouse_type.get(d) in bulk_eligible_types_set
  ]

  # Parse Demand Data
  demand_df = df_demand.copy()
  if 'Latitude' in demand_df.columns and 'Longitude' in demand_df.columns:
    city_coords_df = demand_df[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts = city_coords_df['Cidade'].value_counts()
    duplicates = city_counts[city_counts > 1].index
    
    def get_city_display(row):
      if row['Cidade'] in duplicates:
        return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
      return row['Cidade']
      
    demand_df['Cliente'] = demand_df.apply(get_city_display, axis=1)
    
  Customers = demand_df['Cliente'].unique().tolist()
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

  # Scenario-dependent supply and demand calculations
  wmapes_supply = {}
  wmapes_demand = {}
  for (prod, city) in df_supply[['Produto', 'Cidade']].drop_duplicates().values:
    wmapes_supply[(prod, city)] = 0.15
    if error_source == 'manual':
      wmapes_supply[(prod, city)] = supply_error_pct / 100.0
    elif prediction_results:
      combo_res = prediction_results.get(f"supply_{prod}_{city}", {})
      if combo_res and combo_res.get('status') == 'success':
        wmapes_supply[(prod, city)] = float(combo_res.get('wmape', 15.0)) / 100.0

  for (prod, city) in df_demand[['Produto', 'Cidade']].drop_duplicates().values:
    wmapes_demand[(prod, city)] = 0.15
    if error_source == 'manual':
      wmapes_demand[(prod, city)] = demand_error_pct / 100.0
    elif prediction_results:
      combo_res = prediction_results.get(f"demand_{prod}_{city}", {})
      if combo_res and combo_res.get('status') == 'success':
        wmapes_demand[(prod, city)] = float(combo_res.get('wmape', 15.0)) / 100.0

  supply_dict_scenarios = {}
  for (o, p, t), val in supply_dict.items():
    wmape = wmapes_supply.get((p, o), 0.15)
    supply_dict_scenarios[(o, p, t, "esperado")] = val
    supply_dict_scenarios[(o, p, t, "pessimista")] = val * (1.0 - wmape)
    supply_dict_scenarios[(o, p, t, "otimista")] = val * (1.0 + wmape)

  demand_min_scenarios = {}
  for (c, p, t), val in demand_min.items():
    wmape = wmapes_demand.get((p, c), 0.15)
    demand_min_scenarios[(c, p, t, "esperado")] = val
    demand_min_scenarios[(c, p, t, "pessimista")] = val * (1.0 + wmape)
    demand_min_scenarios[(c, p, t, "otimista")] = val * (1.0 - wmape)

  # Pre-optimization feasibility check: total supply >= total demand in the first period for all scenarios
  if periods:
    p1 = periods[0]
    for s in ["esperado", "pessimista", "otimista"]:
      for p in all_products:
        tot_sup = sum(val for (o, prod, t, scen), val in supply_dict_scenarios.items() if prod == p and t == p1 and scen == s)
        tot_dem = sum(val for (c, prod, t, scen), val in demand_min_scenarios.items() if prod == p and t == p1 and scen == s)
        if tot_sup < tot_dem:
          msg = translate("Erro: Oferta total ({supply:.2f} ton) é menor que a demanda total ({demand:.2f} ton) no primeiro período ({period}) para o produto '{product}' no cenário '{scenario}'.", lang).format(
              supply=tot_sup,
              demand=tot_dem,
              period=str(p1),
              product=p,
              scenario=translate(s, lang)
          )
          raise ValueError(msg)

  # Distance Matrices
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

  # Freight
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

  # Storage Tariff
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
  except Exception:
    for prod in all_products:
      for d in all_warehouses_list:
        storage_cost[(d, prod)] = 50.0

  # Sparse Route Building
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

  # Pyomo Model
  model = pyo.ConcreteModel()
  
  # Sets
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

  model.Scenarios = pyo.Set(initialize=['pessimista', 'esperado', 'otimista'])

  # Params
  model.ScenarioProb = pyo.Param(model.Scenarios, initialize=scenario_probabilities)

  def supply_init(m, o, p, t, s):
    return supply_dict_scenarios.get((o, p, t, s), 0.0)
  model.Supply = pyo.Param(model.Origins, model.Products, model.TimePeriods, model.Scenarios, initialize=supply_init)

  def demand_min_init(m, c, p, t, s):
    return demand_min_scenarios.get((c, p, t, s), 0.0)
  model.DemandMin = pyo.Param(model.Customers_dom, model.Products, model.TimePeriods, model.Scenarios, initialize=demand_min_init)

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
    return float(max_expand_capacity) if max_expand_capacity is not None else 0.0
  model.MaxExpandCapacity = pyo.Param(model.Destinations, initialize=max_expand_init)
  
  def expand_fixed_cost_init(m, d):
    return float(expand_fixed_cost) if expand_fixed_cost is not None else 0.0
  model.ExpandFixedCost = pyo.Param(model.Destinations, initialize=expand_fixed_cost_init)
  
  def expand_var_cost_init(m, d):
    return float(expand_var_cost) if expand_var_cost is not None else 0.0
  model.ExpandVarCost = pyo.Param(model.Destinations, initialize=expand_var_cost_init)
  
  def max_bulk_init(m, d):
    return float(max_bulk_capacity) if max_bulk_capacity is not None else 0.0
  model.MaxBulkCapacity = pyo.Param(model.Destinations, initialize=max_bulk_init)
  
  def bulk_fixed_cost_init(m, d):
    return float(bulk_fixed_cost) if bulk_fixed_cost is not None else 0.0
  model.BulkFixedCost = pyo.Param(model.Destinations, initialize=bulk_fixed_cost_init)
  
  def bulk_var_cost_init(m, d):
    return float(bulk_var_cost) if bulk_var_cost is not None else 0.0
  model.BulkVarCost = pyo.Param(model.Destinations, initialize=bulk_var_cost_init)
  
  model.RatioExpandRec = pyo.Param(initialize=float(ratio_expand_rec) if ratio_expand_rec is not None else 0.0)
  model.RatioExpandShip = pyo.Param(initialize=float(ratio_expand_ship) if ratio_expand_ship is not None else 0.0)

  # First-Stage Decision Variables (Scenario-Independent)
  model.CandStaticCapacity = pyo.Var(model.Destinations_cand, within=pyo.NonNegativeReals)
  model.ExpandedCapacity = pyo.Var(model.Destinations, within=pyo.NonNegativeReals)
  model.BulkCapacity = pyo.Var(model.Destinations, within=pyo.NonNegativeReals)
  
  model.WarehouseOpen = pyo.Var(model.Destinations_cand, within=pyo.Binary)
  model.IsExpanded = pyo.Var(model.Destinations, within=pyo.Binary)
  model.IsBulkified = pyo.Var(model.Destinations, within=pyo.Binary)

  # Second-Stage Variables (Scenario-Dependent)
  model.FlowOD = pyo.Var(model.ValidRoutesOD, model.TimePeriods, model.Scenarios, within=pyo.NonNegativeReals)
  model.FlowDC = pyo.Var(model.ValidRoutesDC, model.TimePeriods, model.Scenarios, within=pyo.NonNegativeReals)
  model.FlowDD = pyo.Var(model.ValidRoutesDD, model.TimePeriods, model.Scenarios, within=pyo.NonNegativeReals)
  model.Inventory = pyo.Var(model.Destinations, model.Products, model.TimePeriods, model.Scenarios, within=pyo.NonNegativeReals)

  # Lock upgrade vars if disabled
  if max_expand_capacity is None:
    for d in model.Destinations:
      model.IsExpanded[d].fix(0)
      model.ExpandedCapacity[d].fix(0)
      
  if max_bulk_capacity is None:
    for d in model.Destinations:
      model.IsBulkified[d].fix(0)
      model.BulkCapacity[d].fix(0)

  def get_open_expr(m, d):
    if d in m.Destinations_exist:
      return 1
    return m.WarehouseOpen[d]

  # Constraints (replicated per scenario)
  def supply_allocation_rule(m, o, p, t, s):
    valid_dests = [d for d in m.Destinations if (o, d, p) in m.ValidRoutesOD]
    if not valid_dests:
      return pyo.Constraint.Skip
    return sum(m.FlowOD[o, d, p, t, s] for d in valid_dests) == m.Supply[o, p, t, s]
  model.SupplyAllocationConstraint = pyo.Constraint(model.Origins, model.Products, model.TimePeriods, model.Scenarios, rule=supply_allocation_rule)

  def inventory_balance_rule(m, d, p, t, s):
    valid_origins = [o for o in m.Origins if (o, d, p) in m.ValidRoutesOD]
    valid_trans_in = [d1 for d1 in m.Destinations if (d1, d, p) in m.ValidRoutesDD]
    inflow = sum(m.FlowOD[o, d, p, t, s] for o in valid_origins) + \
             sum(m.FlowDD[d1, d, p, t, s] for d1 in valid_trans_in)
             
    valid_customers = [c for c in m.Customers if (d, c, p) in m.ValidRoutesDC]
    valid_trans_out = [d2 for d2 in m.Destinations if (d, d2, p) in m.ValidRoutesDD]
    outflow = sum(m.FlowDC[d, c, p, t, s] for c in valid_customers) + \
              sum(m.FlowDD[d, d2, p, t, s] for d2 in valid_trans_out)
              
    if t == periods[0]:
      prev_inv = 0.0
    else:
      prev_t = prev_period_map[t]
      prev_inv = m.Inventory[d, p, prev_t, s]
        
    return m.Inventory[d, p, t, s] == prev_inv + inflow - outflow
  model.InventoryBalanceConstraint = pyo.Constraint(model.Destinations, model.Products, model.TimePeriods, model.Scenarios, rule=inventory_balance_rule)

  def static_capacity_rule(m, d, t, s):
    total_inv = sum(m.Inventory[d, p, t, s] for p in m.Products)
    if d in m.Destinations_exist:
      return total_inv <= m.StaticCapacity[d] + m.ExpandedCapacity[d]
    return total_inv <= m.CandStaticCapacity[d] + m.ExpandedCapacity[d]
  model.StaticCapacityConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, model.Scenarios, rule=static_capacity_rule)

  def reception_handling_rule(m, d, t, s):
    inflow_sum = sum(
      m.FlowOD[o, d, p, t, s] for (o, d_, p) in m.ValidRoutesOD if d_ == d
    ) + sum(
      m.FlowDD[d1, d, p, t, s] for (d1, d_, p) in m.ValidRoutesDD if d_ == d
    )
    bulk_increase = m.BulkCapacity[d] if d in m.BulkEligible else 0.0
    if d in m.Destinations_exist:
      max_inflow = (m.ReceptionCapacity[d] + m.RatioExpandRec * m.ExpandedCapacity[d] + bulk_increase) * m.Days
    else:
      max_inflow = (m.RatioExpandRec * m.CandStaticCapacity[d] + m.RatioExpandRec * m.ExpandedCapacity[d] + bulk_increase) * m.Days
    return inflow_sum <= max_inflow
  model.ReceptionHandlingConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, model.Scenarios, rule=reception_handling_rule)

  def shipping_handling_rule(m, d, t, s):
    outflow_sum = sum(
      m.FlowDC[d, c, p, t, s] for (d_, c, p) in m.ValidRoutesDC if d_ == d
    ) + sum(
      m.FlowDD[d, d2, p, t, s] for (d_, d2, p) in m.ValidRoutesDD if d_ == d
    )
    bulk_increase = m.BulkCapacity[d] if d in m.BulkEligible else 0.0
    if d in m.Destinations_exist:
      max_outflow = (m.ShippingCapacity[d] + m.RatioExpandShip * m.ExpandedCapacity[d] + bulk_increase) * m.Days
    else:
      max_outflow = (m.RatioExpandShip * m.CandStaticCapacity[d] + m.RatioExpandShip * m.ExpandedCapacity[d] + bulk_increase) * m.Days
    return outflow_sum <= max_outflow
  model.ShippingHandlingConstraint = pyo.Constraint(model.Destinations, model.TimePeriods, model.Scenarios, rule=shipping_handling_rule)

  def domestic_demand_rule(m, c, p, t, s):
    valid_dests = [d for d in m.Destinations if (d, c, p) in m.ValidRoutesDC]
    if not valid_dests:
      return pyo.Constraint.Skip
    return sum(m.FlowDC[d, c, p, t, s] for d in valid_dests) == m.DemandMin[c, p, t, s]
  model.DomesticDemandConstraint = pyo.Constraint(model.Customers_dom, model.Products, model.TimePeriods, model.Scenarios, rule=domestic_demand_rule)

  def export_demand_rule(m, c, p, t, s):
    valid_dests = [d for d in m.Destinations if (d, c, p) in m.ValidRoutesDC]
    if not valid_dests:
      return pyo.Constraint.Skip
    return sum(m.FlowDC[d, c, p, t, s] for d in valid_dests) <= m.DemandMax[c, p, t]
  model.ExportDemandConstraint = pyo.Constraint(model.Customers_exp, model.Products, model.TimePeriods, model.Scenarios, rule=export_demand_rule)

  # First-Stage constraints
  def mutual_exclusion_rule(m, d):
    h_val = get_open_expr(m, d)
    if d in m.BulkEligible:
      return m.IsExpanded[d] + m.IsBulkified[d] <= h_val
    return m.IsExpanded[d] <= h_val
  model.MutualExclusionConstraint = pyo.Constraint(model.Destinations, rule=mutual_exclusion_rule)

  def bulk_eligibility_lock_rule_var(m, d):
    if d not in m.BulkEligible:
      return m.IsBulkified[d] == 0
    return pyo.Constraint.Skip
  model.BulkEligibilityLockVar = pyo.Constraint(model.Destinations, rule=bulk_eligibility_lock_rule_var)
      
  def bulk_eligibility_lock_rule_cap(m, d):
    if d not in m.BulkEligible:
      return m.BulkCapacity[d] == 0
    return pyo.Constraint.Skip
  model.BulkEligibilityLockCap = pyo.Constraint(model.Destinations, rule=bulk_eligibility_lock_rule_cap)

  def cand_static_bounding_rule(m, d):
    return model.CandStaticCapacity[d] <= model.WarehouseOpen[d] * model.MaxCandStaticCapacity[d]
  model.CandStaticBoundingConstraint = pyo.Constraint(model.Destinations_cand, rule=cand_static_bounding_rule)

  def bulk_bounding_rule(m, d):
    return model.BulkCapacity[d] <= model.IsBulkified[d] * model.MaxBulkCapacity[d]
  model.BulkBoundingConstraint = pyo.Constraint(model.BulkEligible, rule=bulk_bounding_rule)
      
  def expand_bounding_rule(m, d):
    return model.ExpandedCapacity[d] <= model.IsExpanded[d] * model.MaxExpandCapacity[d]
  model.ExpandBoundingConstraint = pyo.Constraint(model.Destinations, rule=expand_bounding_rule)

  # Expected objective
  first_stage_cost = sum(
    model.WarehouseOpen[d] * model.OpeningCost[d] for d in model.Destinations_cand
  ) + sum(
    model.IsExpanded[d] * model.ExpandFixedCost[d] + model.ExpandedCapacity[d] * model.ExpandVarCost[d] for d in model.Destinations
  ) + sum(
    model.IsBulkified[d] * model.BulkFixedCost[d] + model.BulkCapacity[d] * model.BulkVarCost[d] for d in model.BulkEligible
  )

  def get_second_stage_cost_expr(s):
    freight_od_expr = sum(
      model.FlowOD[o, d, p, t, s] * (model.DistanceOD[o, d] * model.FreightOrigin[o])
      for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
    )
    freight_dc_expr = sum(
      model.FlowDC[d, c, p, t, s] * (model.DistanceDC[d, c] * model.FreightDest[d])
      for (d, c, p) in model.ValidRoutesDC for t in model.TimePeriods
    )
    freight_dd_expr = sum(
      model.FlowDD[d1, d2, p, t, s] * (model.TransshipmentDiscount * model.DistanceDD[d1, d2] * model.FreightDest[d1])
      for (d1, d2, p) in model.ValidRoutesDD for t in model.TimePeriods
    )
    storage_cost_expr = sum(
      model.Inventory[d, p, t, s] * model.StorageTariff[d, p]
      for d in model.Destinations for p in model.Products for t in model.TimePeriods
    )
    return freight_od_expr + freight_dc_expr + freight_dd_expr + storage_cost_expr

  def obj_rule(m):
    return first_stage_cost + sum(m.ScenarioProb[s] * get_second_stage_cost_expr(s) for s in m.Scenarios)

  model.Objective = pyo.Objective(rule=obj_rule, sense=pyo.minimize)

  return (model, cda_to_name, periods, prev_period_map, all_products, all_warehouses_list, 
          candidate_warehouses_list, bulk_eligible_list, static_capacity, demand_min, wmapes_supply, wmapes_demand)


def run_stochastic_model(
  df_supply,
  df_warehouses,
  df_compat,
  df_dist_supply_wh,
  df_dist_wh_demand,
  df_dist_wh_wh,
  df_demand,
  df_freight,
  df_storage,
  scenario_probabilities,
  error_source,
  supply_error_pct,
  demand_error_pct,
  prediction_results,
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
  Executes the two-stage stochastic programming optimization model.
  Hedging strategic decisions against Low, Expected, and High scenarios.
  """
  start_time = time.time()
  
  # Setup outputs redirection for log capturing
  old_stdout = sys.stdout
  log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
  os.makedirs(log_dir, exist_ok=True)
  log_fd, log_path = tempfile.mkstemp(suffix='.txt', prefix='stochastic_log_', dir=log_dir)
  log_filename = os.path.basename(log_path)
  new_stdout = os.fdopen(log_fd, 'w', encoding='utf-8')
  sys.stdout = new_stdout

  try:
    # Build stochastic Pyomo model
    (model, cda_to_name, periods, prev_period_map, all_products, all_warehouses_list, 
     candidate_warehouses_list, bulk_eligible_list, static_capacity, demand_min, 
     wmapes_supply, wmapes_demand) = build_stochastic_pyomo_model(
       df_supply=df_supply,
       df_warehouses=df_warehouses,
       df_compat=df_compat,
       df_dist_supply_wh=df_dist_supply_wh,
       df_dist_wh_demand=df_dist_wh_demand,
       df_dist_wh_wh=df_dist_wh_wh,
       df_demand=df_demand,
       df_freight=df_freight,
       df_storage=df_storage,
       scenario_probabilities=scenario_probabilities,
       error_source=error_source,
       supply_error_pct=supply_error_pct,
       demand_error_pct=demand_error_pct,
       prediction_results=prediction_results,
       toggle_pareto=toggle_pareto,
       input_allocation_days=input_allocation_days,
       transshipment_discount=transshipment_discount,
       ratio_expand_rec=ratio_expand_rec,
       ratio_expand_ship=ratio_expand_ship,
       max_expand_capacity=max_expand_capacity,
       expand_fixed_cost=expand_fixed_cost,
       expand_var_cost=expand_var_cost,
       max_bulk_capacity=max_bulk_capacity,
       bulk_fixed_cost=bulk_fixed_cost,
       bulk_var_cost=bulk_var_cost,
       bulk_eligible_types=bulk_eligible_types,
       lang=lang
     )

    # 3. Pre-solve feasibility checks
    pre_solve_warnings = []
    # Quick access supply totals per scenario (summed across all periods)
    for s in ['pessimista', 'esperado', 'otimista']:
        tot_supply = 0.0
        for (o, p, t_val), val in df_supply.groupby(['Cidade', 'Produto', 'Data'])['Peso (ton)'].sum().to_dict().items():
            wmape = wmapes_supply.get((p, o), 0.15)
            factor = (1.0 - wmape) if s == 'pessimista' else ((1.0 + wmape) if s == 'otimista' else 1.0)
            tot_supply += val * factor
            
        tot_demand = 0.0
        for (c, p, t_val), val in demand_min.items():
            wmape = wmapes_demand.get((p, c), 0.15)
            factor = (1.0 + wmape) if s == 'pessimista' else ((1.0 - wmape) if s == 'otimista' else 1.0)
            tot_demand += val * factor
            
        if tot_supply < tot_demand:
            pre_solve_warnings.append(
                translate("(Cenário {scenario}): A oferta total acumulada ({supply:.0f}t) é menor do que a demanda interna total acumulada ({demand:.0f}t). O modelo pode ficar inviável.", lang)
                .format(scenario=s.capitalize(), supply=tot_supply, demand=tot_demand)
            )

    if detailed_log:
      model.pprint()

    print("\n" + translate("Chamando solver CBC para alocação estocástica...", lang))
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

    results = solver.solve(model, tee=True)
    
    print("\n" + translate("=== STATUS DA OTIMIZAÇÃO ESTOCÁSTICA ===", lang))
    print(translate("Status do Solver: {status}", lang).format(status=results.solver.status))
    print(translate("Condição de Término: {condition}", lang).format(condition=results.solver.termination_condition))

  finally:
    new_stdout.flush()
    new_stdout.close()
    sys.stdout = old_stdout

  results_status = results.solver.termination_condition
  is_optimal = results_status == pyo.TerminationCondition.optimal

  results_dict = {
    "model_type": "stochastic",
    "status": "optimal" if is_optimal else str(results_status),
    "objective": 0.0,
    "expected_objective": 0.0,
    "scenario_objectives": {},
    "routes": [],
    "scenario_routes": {},
    "kpis": {},
    "scenario_kpis": {},
    "model_stats": {
      "total_variables": sum(1 for _ in model.component_data_objects(pyo.Var, active=True)),
      "total_constraints": sum(1 for _ in model.component_data_objects(pyo.Constraint, active=True)),
      "binary_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain == pyo.Binary),
      "integer_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Integers, pyo.NonNegativeIntegers, pyo.PositiveIntegers)),
      "continuous_variables": sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Reals, pyo.NonNegativeReals, pyo.PositiveReals))
    },
    "warnings": pre_solve_warnings,
    "warehouse_decisions": [],
    "scenario_warehouse_metrics": {},
    "inventory": [],
    "scenario_inventory": {}
  }

  if is_optimal:
    expected_obj = pyo.value(model.Objective)
    results_dict["objective"] = expected_obj
    results_dict["expected_objective"] = expected_obj

    # Calculate first-stage costs (identical across scenarios)
    total_opening_cost = sum(
      pyo.value(model.WarehouseOpen[d]) * pyo.value(model.OpeningCost[d])
      for d in model.Destinations_cand
    )
    total_expand_cost = sum(
      pyo.value(model.IsExpanded[d]) * pyo.value(model.ExpandFixedCost[d]) + pyo.value(model.ExpandedCapacity[d]) * pyo.value(model.ExpandVarCost[d])
      for d in model.Destinations
    )
    total_bulk_cost = sum(
      pyo.value(model.IsBulkified[d]) * pyo.value(model.BulkFixedCost[d]) + pyo.value(model.BulkCapacity[d]) * pyo.value(model.BulkVarCost[d])
      for d in model.BulkEligible
    )

    scenario_objectives = {}
    scenario_kpis = {}
    scenario_routes = {}
    scenario_inventory = {}
    scenario_warehouse_metrics = {}

    for s in ['pessimista', 'esperado', 'otimista']:
      freight_od_s = sum(
        pyo.value(model.FlowOD[o, d, p, t, s]) * (model.DistanceOD[o, d] * pyo.value(model.FreightOrigin[o]))
        for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
      )
      freight_dc_s = sum(
        pyo.value(model.FlowDC[d, c, p, t, s]) * (model.DistanceDC[d, c] * pyo.value(model.FreightDest[d]))
        for (d, c, p) in model.ValidRoutesDC for t in model.TimePeriods
      )
      freight_dd_s = sum(
        pyo.value(model.FlowDD[d1, d2, p, t, s]) * (pyo.value(model.TransshipmentDiscount) * model.DistanceDD[d1, d2] * pyo.value(model.FreightDest[d1]))
        for (d1, d2, p) in model.ValidRoutesDD for t in model.TimePeriods
      )
      total_freight_s = freight_od_s + freight_dc_s + freight_dd_s
      
      storage_s = sum(
        pyo.value(model.Inventory[d, p, t, s]) * pyo.value(model.StorageTariff[d, p])
        for d in model.Destinations for p in model.Products for t in model.TimePeriods
      )
      
      total_tons_s = sum(
        pyo.value(model.FlowOD[o, d, p, t, s])
        for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
      )
      
      total_km_s = sum(
        pyo.value(model.FlowOD[o, d, p, t, s]) * model.DistanceOD[o, d]
        for (o, d, p) in model.ValidRoutesOD for t in model.TimePeriods
      ) + sum(
        pyo.value(model.FlowDC[d, c, p, t, s]) * model.DistanceDC[d, c]
        for (d, c, p) in model.ValidRoutesDC for t in model.TimePeriods
      ) + sum(
        pyo.value(model.FlowDD[d1, d2, p, t, s]) * model.DistanceDD[d1, d2]
        for (d1, d2, p) in model.ValidRoutesDD for t in model.TimePeriods
      )

      scenario_obj = total_opening_cost + total_expand_cost + total_bulk_cost + total_freight_s + storage_s
      scenario_objectives[s] = scenario_obj

      scenario_kpis[s] = {
        "total_cost": scenario_obj,
        "total_tons": total_tons_s,
        "total_km": total_km_s,
        "total_freight_cost": total_freight_s,
        "total_storage_cost": storage_s,
        "total_opening_cost": total_opening_cost,
        "total_expand_cost": total_expand_cost,
        "total_bulk_cost": total_bulk_cost,
        "execution_time": time.time() - start_time
      }

      # Scenario routes
      routes_list = []
      for (o, d, p) in model.ValidRoutesOD:
        for t in model.TimePeriods:
          val = pyo.value(model.FlowOD[o, d, p, t, s])
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
      for (d, c, p) in model.ValidRoutesDC:
        for t in model.TimePeriods:
          val = pyo.value(model.FlowDC[d, c, p, t, s])
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
      for (d1, d2, p) in model.ValidRoutesDD:
        for t in model.TimePeriods:
          val = pyo.value(model.FlowDD[d1, d2, p, t, s])
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
      scenario_routes[s] = routes_list

      # Scenario inventory
      inv_list = []
      for d in all_warehouses_list:
        for p in all_products:
          for t in periods:
            val = pyo.value(model.Inventory[d, p, t, s])
            inv_list.append({
              "CDA": d,
              "Name": cda_to_name.get(d, d),
              "Produto": p,
              "Período": t,
              "Quantidade (ton)": val
            })
      scenario_inventory[s] = inv_list

      # Scenario warehouse metrics
      wh_metrics = []
      for d in all_warehouses_list:
        is_cand = d in candidate_warehouses_list
        is_open = True if not is_cand else (pyo.value(model.WarehouseOpen[d]) > 0.5)
        cand_static = 0.0 if not is_cand else pyo.value(model.CandStaticCapacity[d])
        is_exp = pyo.value(model.IsExpanded[d]) > 0.5
        exp_cap = pyo.value(model.ExpandedCapacity[d])
        is_bulk = pyo.value(model.IsBulkified[d]) > 0.5 if d in bulk_eligible_list else False
        bulk_cap = pyo.value(model.BulkCapacity[d]) if d in bulk_eligible_list else 0.0
        
        total_outflow = sum(
          pyo.value(model.FlowDC[d_, c, p, t, s])
          for (d_, c, p) in model.ValidRoutesDC if d_ == d
          for t in model.TimePeriods
        ) + sum(
          pyo.value(model.FlowDD[d_, d2, p, t, s])
          for (d_, d2, p) in model.ValidRoutesDD if d_ == d
          for t in model.TimePeriods
        )
        final_stock = sum(
          pyo.value(model.Inventory[d, p, periods[-1], s])
          for p in all_products
        )
        dyn_cap_raw = total_outflow + final_stock
        num_periods = len(periods)
        annualization_factor = 12.0 / num_periods if num_periods > 0 else 1.0
        dyn_cap_annual = dyn_cap_raw * annualization_factor
        
        if not is_cand:
          effective_static = static_capacity.get(d, 0.0) + exp_cap
        else:
          effective_static = cand_static + exp_cap
            
        turnover_annual = dyn_cap_annual / effective_static if effective_static > 0.0 else 0.0
        
        opening_c = pyo.value(model.WarehouseOpen[d]) * pyo.value(model.OpeningCost[d]) if is_cand else 0.0
        expand_c = pyo.value(model.IsExpanded[d]) * pyo.value(model.ExpandFixedCost[d]) + pyo.value(model.ExpandedCapacity[d]) * pyo.value(model.ExpandVarCost[d])
        bulk_c = pyo.value(model.IsBulkified[d]) * pyo.value(model.BulkFixedCost[d]) + pyo.value(model.BulkCapacity[d]) * pyo.value(model.BulkVarCost[d]) if d in bulk_eligible_list else 0.0
        storage_c = sum(pyo.value(model.Inventory[d, p, t, s]) * pyo.value(model.StorageTariff[d, p]) for p in all_products for t in periods)
        total_c = opening_c + expand_c + bulk_c + storage_c

        wh_metrics.append({
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
          "TurnoverRatio": turnover_annual,
          "OpeningCost": opening_c,
          "ExpandCost": expand_c,
          "BulkCost": bulk_c,
          "StorageCost": storage_c,
          "TotalCost": total_c
        })
      scenario_warehouse_metrics[s] = wh_metrics

    # Fill base attributes with Expected ("esperado") scenario for backward compatibility
    results_dict["scenario_objectives"] = scenario_objectives
    results_dict["scenario_kpis"] = scenario_kpis
    results_dict["scenario_routes"] = scenario_routes
    results_dict["scenario_inventory"] = scenario_inventory
    results_dict["scenario_warehouse_metrics"] = scenario_warehouse_metrics

    results_dict["routes"] = scenario_routes["esperado"]
    results_dict["inventory"] = scenario_inventory["esperado"]
    results_dict["kpis"] = scenario_kpis["esperado"]

    # Reconstruct warehouse decisions list for deterministic tab display
    wh_decisions_list = []
    for d in all_warehouses_list:
      is_cand = d in candidate_warehouses_list
      is_open = True if not is_cand else (pyo.value(model.WarehouseOpen[d]) > 0.5)
      cand_static = 0.0 if not is_cand else pyo.value(model.CandStaticCapacity[d])
      is_exp = pyo.value(model.IsExpanded[d]) > 0.5
      exp_cap = pyo.value(model.ExpandedCapacity[d])
      is_bulk = pyo.value(model.IsBulkified[d]) > 0.5 if d in bulk_eligible_list else False
      bulk_cap = pyo.value(model.BulkCapacity[d]) if d in bulk_eligible_list else 0.0

      wh_dec = next(item for item in scenario_warehouse_metrics["esperado"] if item["CDA"] == d)
      total_wh_cost = wh_dec["OpeningCost"] + wh_dec["ExpandCost"] + wh_dec["BulkCost"] + wh_dec["StorageCost"]

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
        "TotalOutflow": wh_dec["TotalOutflow"],
        "FinalStock": wh_dec["FinalStock"],
        "DynamicCapacity": wh_dec["DynamicCapacity"],
        "DynamicCapacityRaw": wh_dec["DynamicCapacityRaw"],
        "EffectiveStaticCapacity": wh_dec["EffectiveStaticCapacity"],
        "TurnoverRatio": wh_dec["TurnoverRatio"],
        "OpeningCost": wh_dec["OpeningCost"],
        "ExpandCost": wh_dec["ExpandCost"],
        "BulkCost": wh_dec["BulkCost"],
        "StorageCost": wh_dec["StorageCost"],
        "TotalCost": total_wh_cost
      })
    results_dict["warehouse_decisions"] = wh_decisions_list

  return log_filename, results_dict


def compute_evpi_vss(
  df_supply,
  df_warehouses,
  df_compat,
  df_dist_supply_wh,
  df_dist_wh_demand,
  df_dist_wh_wh,
  df_demand,
  df_freight,
  df_storage,
  scenario_probabilities,
  error_source,
  supply_error_pct,
  demand_error_pct,
  prediction_results,
  stochastic_objective,
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
  Computes EVPI and VSS by running deterministic solves and fixing variables.
  """
  # 1. EVPI Calculations: Run 3 independent deterministic models (Low, Expected, High)
  ws_value = 0.0
  scenario_objectives = {}

  # Pre-calculate WMAPEs for perturbation
  wmapes_supply = {}
  wmapes_demand = {}
  for (prod, city) in df_supply[['Produto', 'Cidade']].drop_duplicates().values:
    wmapes_supply[(prod, city)] = 0.15
    if error_source == 'manual':
      wmapes_supply[(prod, city)] = supply_error_pct / 100.0
    elif prediction_results:
      combo_res = prediction_results.get(f"supply_{prod}_{city}", {})
      if combo_res and combo_res.get('status') == 'success':
        wmapes_supply[(prod, city)] = float(combo_res.get('wmape', 15.0)) / 100.0

  for (prod, city) in df_demand[['Produto', 'Cidade']].drop_duplicates().values:
    wmapes_demand[(prod, city)] = 0.15
    if error_source == 'manual':
      wmapes_demand[(prod, city)] = demand_error_pct / 100.0
    elif prediction_results:
      combo_res = prediction_results.get(f"demand_{prod}_{city}", {})
      if combo_res and combo_res.get('status') == 'success':
        wmapes_demand[(prod, city)] = float(combo_res.get('wmape', 15.0)) / 100.0

  expected_wh_decisions = []

  for s in ['pessimista', 'esperado', 'otimista']:
    # Perturb supply DataFrame
    df_supply_s = df_supply.copy()
    def perturb_supply(row):
      p = row['Produto']
      o = row['Cidade']
      wmape = wmapes_supply.get((p, o), 0.15)
      factor = (1.0 - wmape) if s == 'pessimista' else ((1.0 + wmape) if s == 'otimista' else 1.0)
      return row['Peso (ton)'] * factor
    df_supply_s['Peso (ton)'] = df_supply_s.apply(perturb_supply, axis=1)

    # Perturb demand DataFrame
    df_demand_s = df_demand.copy()
    def perturb_demand(row):
      p = row['Produto']
      c = row['Cidade']
      if pd.isna(row['Peso (ton)']):
        return row['Peso (ton)']
      wmape = wmapes_demand.get((p, c), 0.15)
      factor = (1.0 + wmape) if s == 'pessimista' else ((1.0 - wmape) if s == 'otimista' else 1.0)
      return row['Peso (ton)'] * factor
    df_demand_s['Peso (ton)'] = df_demand_s.apply(perturb_demand, axis=1)

    # Run deterministic solve
    _, det_res = run_deterministic_model(
      df_supply=df_supply_s,
      df_warehouses=df_warehouses,
      df_compat=df_compat,
      df_dist_supply_wh=df_dist_supply_wh,
      df_dist_wh_demand=df_dist_wh_demand,
      df_dist_wh_wh=df_dist_wh_wh,
      df_demand=df_demand_s,
      df_freight=df_freight,
      df_storage=df_storage,
      detailed_log=False,
      toggle_pareto=toggle_pareto,
      input_allocation_days=input_allocation_days,
      transshipment_discount=transshipment_discount,
      solver_gap=solver_gap,
      solver_time_limit=solver_time_limit,
      ratio_expand_rec=ratio_expand_rec,
      ratio_expand_ship=ratio_expand_ship,
      max_expand_capacity=max_expand_capacity,
      expand_fixed_cost=expand_fixed_cost,
      expand_var_cost=expand_var_cost,
      max_bulk_capacity=max_bulk_capacity,
      bulk_fixed_cost=bulk_fixed_cost,
      bulk_var_cost=bulk_var_cost,
      bulk_eligible_types=bulk_eligible_types,
      lang=lang
    )

    if det_res["status"] != "optimal":
      raise ValueError(f"Solver failed to find optimal solution for scenario {s}")

    prob = scenario_probabilities[s]
    ws_value += prob * det_res["objective"]
    scenario_objectives[s] = det_res["objective"]

    if s == 'esperado':
      expected_wh_decisions = det_res["warehouse_decisions"]

  evpi_value = stochastic_objective - ws_value

  # 2. VSS Calculations: Solve EEV problem by fixing first stage variables in stochastic model
  (model, cda_to_name, periods, prev_period_map, all_products, all_warehouses_list, 
   candidate_warehouses_list, bulk_eligible_list, static_capacity, demand_min, 
   wmapes_supply, wmapes_demand) = build_stochastic_pyomo_model(
     df_supply=df_supply,
     df_warehouses=df_warehouses,
     df_compat=df_compat,
     df_dist_supply_wh=df_dist_supply_wh,
     df_dist_wh_demand=df_dist_wh_demand,
     df_dist_wh_wh=df_dist_wh_wh,
     df_demand=df_demand,
     df_freight=df_freight,
     df_storage=df_storage,
     scenario_probabilities=scenario_probabilities,
     error_source=error_source,
     supply_error_pct=supply_error_pct,
     demand_error_pct=demand_error_pct,
     prediction_results=prediction_results,
     toggle_pareto=toggle_pareto,
     input_allocation_days=input_allocation_days,
     transshipment_discount=transshipment_discount,
     ratio_expand_rec=ratio_expand_rec,
     ratio_expand_ship=ratio_expand_ship,
     max_expand_capacity=max_expand_capacity,
     expand_fixed_cost=expand_fixed_cost,
     expand_var_cost=expand_var_cost,
     max_bulk_capacity=max_bulk_capacity,
     bulk_fixed_cost=bulk_fixed_cost,
     bulk_var_cost=bulk_var_cost,
     bulk_eligible_types=bulk_eligible_types,
     lang=lang
   )

  # Fix first-stage variables to expected deterministic choices
  for d in model.Destinations_cand:
    expected_dec = next((w for w in expected_wh_decisions if w["CDA"] == d), None)
    if expected_dec:
      model.WarehouseOpen[d].fix(1 if expected_dec["IsOpen"] else 0)
      model.CandStaticCapacity[d].fix(expected_dec["DecidedStaticCapacity"])
    else:
      model.WarehouseOpen[d].fix(0)
      model.CandStaticCapacity[d].fix(0.0)

  for d in model.Destinations:
    expected_dec = next((w for w in expected_wh_decisions if w["CDA"] == d), None)
    if expected_dec:
      model.IsExpanded[d].fix(1 if expected_dec["IsExpanded"] else 0)
      model.ExpandedCapacity[d].fix(expected_dec["ExpandedVolume"])
      if d in model.BulkEligible:
        model.IsBulkified[d].fix(1 if expected_dec["IsBulkified"] else 0)
        model.BulkCapacity[d].fix(expected_dec["BulkCapacityAdded"])
    else:
      model.IsExpanded[d].fix(0)
      model.ExpandedCapacity[d].fix(0.0)
      if d in model.BulkEligible:
        model.IsBulkified[d].fix(0)
        model.BulkCapacity[d].fix(0.0)

  # Run solver for fixed EEV stochastic model
  solver = SolverFactory('cbc')
  if solver_time_limit is not None:
    solver.options['sec'] = int(solver_time_limit)
  if solver_gap is not None:
    try:
      gap_val = float(solver_gap)
      if gap_val > 1.0:
        gap_val = gap_val / 100.0
      solver.options['ratioGap'] = gap_val
    except Exception:
      solver.options['ratioGap'] = 0.01

  results = solver.solve(model)
  if results.solver.termination_condition != pyo.TerminationCondition.optimal:
    raise ValueError("Solver failed to solve stochastic model with fixed deterministic decisions")

  eev_objective = pyo.value(model.Objective)
  vss_value = eev_objective - stochastic_objective

  # EVPI and VSS cannot be negative (enforced mathematically, but float precision could cause -0.0)
  return {
    "evpi": max(0.0, float(evpi_value)),
    "vss": max(0.0, float(vss_value)),
    "ws": float(ws_value),
    "eev": float(eev_objective)
  }
