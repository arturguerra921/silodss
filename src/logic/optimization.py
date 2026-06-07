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

def run_optimization_model(df_supply, df_demand, df_compat, df_dist, df_freight, df_storage, detailed_log=False,
                           toggle_pareto=False, toggle_min_max_capacity=False, input_min_load=None, input_max_load=None,
                           toggle_use_reception=False, input_allocation_days=None, input_min_freight=None, input_max_freight=None, solver_gap=None, force_milp=False, lang="pt"):
    """
    Runs the linear optimization mathematical model for product allocation.
    """
    # Start of the timer to measure total time from call to solution
    start_time = time.time()

    # 1. Data preparation

    # Supply
    # First, apply the same deduplication logic to ensure names in df_supply match df_dist
    if 'Latitude' in df_supply.columns and 'Longitude' in df_supply.columns:
        origins_df = df_supply[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
        city_counts = origins_df['Cidade'].value_counts()
        duplicates = city_counts[city_counts > 1].index

        def rename_city(row):
            if row['Cidade'] in duplicates:
                return f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
            return row['Cidade']

        df_supply['Cidade'] = df_supply.apply(rename_city, axis=1)

    # Group by Cidade and Produto, sum over Peso (ton)
    supply = df_supply.groupby(['Cidade', 'Produto'])['Peso (ton)'].sum().to_dict()

    # Demand - Using Warehouse Capacity in tons (destination node)
    # Identify the capacity column correctly. Often it is 'Capacidade Estática (t)' or similar.
    cap_col = next((c for c in df_demand.columns if 'cap' in str(c).lower() or 'ton' in str(c).lower()), None)
    estoque_col = next((c for c in df_demand.columns if 'estoque' in str(c).lower()), None)

    # Identify Public/Private warehouse.
    armazenador_col = next((c for c in df_demand.columns if 'armazenador' in str(c).lower()), None)
    name_col = next((c for c in df_demand.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
    mun_col_dest = next((c for c in df_demand.columns if 'munic' in str(c).lower()), None)
    cda_col = next((c for c in df_demand.columns if 'cda' in str(c).lower()), None)
    reception_col = next((c for c in df_demand.columns if 'recep' in str(c).lower() or 'receb' in str(c).lower()), None)

    # Separate dictionaries for total capacity and initial inventory
    demand_total_capacity = {}
    demand_initial_inventory = {}
    demand_reception_capacity = {}
    is_public = {}

    # Store the mapping from CDA back to full formatted name for the final output
    cda_to_name = {}

    for idx, row in df_demand.iterrows():
        # Retrieve the CDA string
        if cda_col and pd.notna(row[cda_col]):
            cda = str(row[cda_col]).strip()
        else:
            cda = f"Dest {idx}"

        # Match the exact naming convention used in the distance matrix view (CDA - Armazem - Municipio)
        parts = []
        if cda_col and pd.notna(row[cda_col]):
            parts.append(str(row[cda_col]).strip())
        if name_col and pd.notna(row[name_col]):
            parts.append(str(row[name_col]).strip())
        if mun_col_dest and pd.notna(row[mun_col_dest]):
            parts.append(str(row[mun_col_dest]).strip())

        if parts:
            dest_name_full = " - ".join(parts)
        else:
            dest_name_full = f"Dest {idx}"

        cda_to_name[cda] = dest_name_full

        # Parse capacity correctly (cleaning Brazilian number formats)
        try:
            cap = safe_parse_numeric(row[cap_col]) if cap_col else 0.0
        except:
            cap = 0.0

        # Parse initial stock correctly
        try:
            estoque = safe_parse_numeric(row[estoque_col]) if estoque_col else 0.0
        except:
            estoque = 0.0

        # Parse reception capacity correctly
        try:
            recepcao = safe_parse_numeric(row[reception_col]) if reception_col else 0.0
        except:
            recepcao = 0.0

        # Now we keep capacity, inventory and reception separated
        demand_total_capacity[cda] = cap
        demand_initial_inventory[cda] = estoque
        demand_reception_capacity[cda] = recepcao

        # Determine if public or private
        if armazenador_col and str(row[armazenador_col]).upper() == "COMPANHIA NACIONAL DE ABASTECIMENTO":
            is_public[cda] = True
        else:
            is_public[cda] = False

    # Compatibility (Product x Warehouse)
    # The df_compat matrix has products in rows ('Produto') and columns for each warehouse type.
    # But we need to relate each 'Destination' (warehouse) with the 'Product' based on warehouse 'Type'.
    # Let's create a compatibility dictionary: (product, dest_name) -> bool

    # Identificar coluna de tipo no df_demand
    tipo_col = next((c for c in df_demand.columns if 'tipo' in str(c).lower()), None)

    # Build permissions dictionary from df_compat
    # df_compat has 'Produto' and columns with Warehouse Types, values '☑' or '☐'
    compat_dict = {}
    if not df_compat.empty:
        for _, row in df_compat.iterrows():
            prod = row['Produto']
            for t in df_compat.columns:
                if t != 'Produto':
                    # True se aceita
                    compat_dict[(prod, t)] = (row[t] == '☑')

    # Agora associar produto x destino
    prod_dest_compat = {}
    all_products = df_supply['Produto'].unique().tolist()

    for prod in all_products:
        for idx, row in df_demand.iterrows():
            if cda_col and pd.notna(row[cda_col]):
                cda = str(row[cda_col]).strip()
            else:
                cda = f"Dest {idx}"

            tipo_armazem = row[tipo_col] if tipo_col else None

            # If we have no type information, we assume it accepts (or we could reject, but assuming True is safer if it fails)
            if tipo_armazem and (prod, tipo_armazem) in compat_dict:
                prod_dest_compat[(prod, cda)] = compat_dict[(prod, tipo_armazem)]
            else:
                prod_dest_compat[(prod, cda)] = True # Default fallback

    # Matriz de Distâncias
    # df_dist tem 'Origem' e colunas com 'CDA - Armazem - Municipio' ...
    distance = {}
    for _, row in df_dist.iterrows():
        orig = row['Origem']
        for col in df_dist.columns:
            if col != 'Origem':
                dest_full_name = col
                # Retrieve the CDA from the first part of the column name
                # format: "CDA - Armazem - Municipio" -> split by " - " -> get [0]
                cda = dest_full_name.split(' - ')[0].strip() if ' - ' in str(dest_full_name) else str(dest_full_name).strip()

                try:
                    distance[(orig, cda)] = float(row[col])
                except:
                    # Se for "N/A" ou falhar
                    pass

    # Custos de Frete (Valor_Tonelada_km)
    # We need the cost for each origin. We'll use the average or by state.
    # df_freight tem 'Estado' e 'Frete Tonelada Km'.
    # To simplify, let's take the general average if we don't know the origin state,
    # or we can try to extract the state from the city name (Ex: 'Brasília - DF').

    # Parse Brazilian numbers for freight
    try:
        df_freight['Frete_Num'] = df_freight['Frete Tonelada Km'].apply(safe_parse_numeric)
        freight_dict = df_freight.set_index('Estado')['Frete_Num'].to_dict()
        avg_freight = df_freight['Frete_Num'].mean()
    except:
        freight_dict = {}
        avg_freight = 0.3 # default fallback

    freight_cost = {}
    for orig in df_supply['Cidade'].unique():
        # Tentativa de extrair UF
        uf = str(orig).split('-')[-1].strip() if '-' in str(orig) else None
        if uf in freight_dict:
            freight_cost[orig] = freight_dict[uf]
        else:
            freight_cost[orig] = avg_freight

    # Tarifas de Armazenagem
    # df_storage tem 'Produto', 'Armazenar_Publico', 'Armazenar_Privado'
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

        df_storage['Pub'] = df_storage['Armazenar_Publico'].apply(safe_parse_numeric)
        df_storage['Priv'] = df_storage['Armazenar_Privado'].apply(safe_parse_numeric)
        df_storage['Prod_Norm'] = df_storage['Produto'].apply(normalize_str)

        # Build lookup dictionaries
        pub_dict = df_storage.set_index('Prod_Norm')['Pub'].to_dict()
        priv_dict = df_storage.set_index('Prod_Norm')['Priv'].to_dict()

        # Try to find "outros" as fallback, otherwise use 50.0
        fallback_pub = pub_dict.get('outros', 50.0)
        fallback_priv = priv_dict.get('outros', 50.0)

        for prod in all_products:
            prod_norm = normalize_str(prod)
            pub_val = pub_dict.get(prod_norm, fallback_pub)
            priv_val = priv_dict.get(prod_norm, fallback_priv)

            for dest in demand_total_capacity.keys():
                if is_public.get(dest, False):
                    storage_cost[(dest, prod)] = pub_val
                else:
                    storage_cost[(dest, prod)] = priv_val

    except Exception as e:
        print(translate("Erro ao processar tarifas de armazenagem: {e}", lang).format(e=e))
        # Default fallback
        for prod in all_products:
            for dest in demand_total_capacity.keys():
                storage_cost[(dest, prod)] = 50.0


    # 2. Despacho: LP ou MILP

    use_milp = force_milp
    if not use_milp and toggle_min_max_capacity:
        if (input_min_load is not None and str(input_min_load).strip() != "") or \
           (input_max_load is not None and str(input_max_load).strip() != "") or \
           (input_min_freight is not None and str(input_min_freight).strip() != "") or \
           (input_max_freight is not None and str(input_max_freight).strip() != "") or \
           toggle_use_reception:
            use_milp = True

    if use_milp:
        return _run_milp_optimization_model(
            start_time=start_time,
            supply=supply, demand_total_capacity=demand_total_capacity,
            demand_initial_inventory=demand_initial_inventory,
            demand_reception_capacity=demand_reception_capacity,
            is_public=is_public, cda_to_name=cda_to_name,
            prod_dest_compat=prod_dest_compat, distance=distance,
            freight_cost=freight_cost, storage_cost=storage_cost, avg_freight=avg_freight,
            all_products=all_products, origins_list=df_supply['Cidade'].unique().tolist(),
            detailed_log=detailed_log,
            input_min_load=input_min_load, input_max_load=input_max_load,
            toggle_use_reception=toggle_use_reception, input_allocation_days=input_allocation_days,
            input_min_freight=input_min_freight, input_max_freight=input_max_freight,
            toggle_pareto=toggle_pareto,
            solver_gap=solver_gap,
            lang=lang
        )

    # 2. Pyomo Model Construction (Original LP)

    # Redirect output directly to a temporary file on disk (to avoid Out of Memory)
    old_stdout = sys.stdout

    log_dir = os.path.join(tempfile.gettempdir(), 'granum_logs')
    os.makedirs(log_dir, exist_ok=True)

    # Clean up old files so we don't run out of disk space

    now = time.time()
    for filename in os.listdir(log_dir):
        filepath = os.path.join(log_dir, filename)
        if os.path.isfile(filepath):
            # Deletes files created more than 1 hour ago
            if os.stat(filepath).st_mtime < now - 3600:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

    log_fd, log_path = tempfile.mkstemp(suffix='.txt', prefix='optimization_log_', dir=log_dir)
    log_filename = os.path.basename(log_path)
    new_stdout = os.fdopen(log_fd, 'w', encoding='utf-8')
    sys.stdout = new_stdout

    # Variables to hold structured results
    results_dict = {
        "status": "error",
        "objective": 0.0,
        "routes": [],
        "kpis": {
            "total_tons": 0.0,
            "total_km": 0.0,
            "total_freight_cost": 0.0,
            "total_storage_cost": 0.0,
            "execution_time": 0.0
        },
        "model_stats": {
            "total_variables": 0,
            "binary_variables": 0,
            "integer_variables": 0,
            "continuous_variables": 0,
            "total_constraints": 0,
            "iterations": 0,
            "nodes": 0
        },
        "warnings": {
            "capacity": [],
            "unallocated": [],
            "general": []
        }
    }

    try:
        print(translate("Iniciando a construção do modelo matemático...", lang))
        model = pyo.ConcreteModel(name="Alocacao_Armazens")

        # =========================================================================
        # 2.1 CONJUNTOS (SETS)
        # =========================================================================
        # Defines the indices over which the model will operate.

        model.Origins = pyo.Set(initialize=df_supply['Cidade'].unique().tolist(), doc=translate("Cidades de Origem da Oferta", lang))
        model.Destinations = pyo.Set(initialize=list(demand_total_capacity.keys()), doc=translate("Armazéns de Destino", lang))
        model.Products = pyo.Set(initialize=all_products, doc=translate("Tipos de Produtos", lang))

        # [PERFORMANCE BEST PRACTICE]
        # We pre-filter valid routes in Python before creating decision variables.
        # This avoids the 'combinatorial explosion' of empty variables in the solver, improving
        # significantly memory usage and optimization speed.
        valid_routes = []
        for o in model.Origins:
            for p in model.Products:
                compatible_dests = []
                # Reúne todos os destinos válidos para esta origem e produto
                for d in model.Destinations:
                    if (o, d) in distance and prod_dest_compat.get((p, d), False):
                        dist_val = distance[(o, d)]
                        # Armazena apenas a distância para o Pareto
                        compatible_dests.append((d, dist_val))

                if compatible_dests:
                    if toggle_pareto:
                        # Ordena pela menor distância
                        compatible_dests.sort(key=lambda x: x[1])
                        # Aplica a regra 80/20, arredondando sempre para cima
                        limit = max(1, math.ceil(len(compatible_dests) * 0.20))
                        compatible_dests = compatible_dests[:limit]

                    # Adiciona os destinos filtrados às rotas válidas
                    for d, _ in compatible_dests:
                        valid_routes.append((o, d, p))

        print(translate("Total de combinações (Origem x Destino x Produto) válidas: {val}", lang).format(val=len(valid_routes)))
        model.ValidRoutes = pyo.Set(initialize=valid_routes, dimen=3, doc=translate("Rotas Válidas (Origem, Destino, Produto)", lang))

        # =========================================================================
        # 2.2 PARÂMETROS (PARAMETERS)
        # =========================================================================
        # Valores fixos conhecidos fornecidos como dados de entrada para o modelo.

        # --- Parâmetros de Oferta e Demanda ---
        def supply_init(model, o, p):
            return supply.get((o, p), 0.0)
        model.Supply = pyo.Param(model.Origins, model.Products, initialize=supply_init, doc=translate("Oferta disponível por (Origem, Produto)", lang))

        def total_capacity_init(model, d):
            return demand_total_capacity.get(d, 0.0)
        model.TotalCapacity = pyo.Param(model.Destinations, initialize=total_capacity_init, doc=translate("Capacidade estática total do armazém (ton)", lang))

        def initial_inventory_init(model, d):
            return demand_initial_inventory.get(d, 0.0)
        model.InitialInventory = pyo.Param(model.Destinations, initialize=initial_inventory_init, doc=translate("Estoque inicial presente no armazém (ton)", lang))

        # --- Parâmetros de Custos e Distâncias ---
        def dist_init(model, o, d):
            return distance.get((o, d), 999999.0)
        model.Distance = pyo.Param(model.Origins, model.Destinations, initialize=dist_init, doc=translate("Distância entre Origem e Destino (km)", lang))

        def freight_init(model, o):
            return freight_cost.get(o, avg_freight)
        model.Freight = pyo.Param(model.Origins, initialize=freight_init, doc=translate("Custo unitário de frete (R$/ton-km) a partir da Origem", lang))

        def storage_init(model, d, p):
            return storage_cost.get((d, p), 50.0)
        model.Storage = pyo.Param(model.Destinations, model.Products, initialize=storage_init, doc=translate("Tarifa de armazenagem no Destino para o Produto (R$/ton)", lang))

        # --- Penalty Parameters (Big M) ---
        # We calculate a dynamic Big M based on maximum system costs
        max_freight = max(freight_cost.values()) if freight_cost else 0.0
        max_dist = max(distance.values()) if distance else 0.0
        max_storage = max(storage_cost.values()) if storage_cost else 0.0

        # Big M da Capacidade: ordens de grandeza maior que o custo de transportar e armazenar
        val_big_m_cap = (max_freight * max_dist + max_storage) * 1000
        if val_big_m_cap == 0:
            val_big_m_cap = 10000

        # Unallocated Big M: must be even higher than lack of capacity, forcing allocation whenever possible
        val_big_m_unalloc = val_big_m_cap * 10

        print(translate("Valor dinâmico para Big_M (Capacidade Artificial): {val:.2e}", lang).format(val=val_big_m_cap))
        print(translate("Valor dinâmico para Big_M (Oferta Não Alocada): {val:.2e}", lang).format(val=val_big_m_unalloc))

        model.BigMCapacity = pyo.Param(initialize=val_big_m_cap, doc=translate("Custo de penalização por tonelada de capacidade artificial", lang))
        model.BigMUnallocated = pyo.Param(initialize=val_big_m_unalloc, doc=translate("Custo de penalização por tonelada de oferta não alocada", lang))

        # =========================================================================
        # 2.3 DECISION VARIABLES
        # =========================================================================
        # Values the solver will attempt to determine to optimize the result.

        # Fluxo de produto (quantidade a ser transportada) em toneladas
        model.Flow = pyo.Var(model.ValidRoutes, domain=pyo.NonNegativeReals, doc=translate("Quantidade transportada (o, d, p)", lang))

        # Slack variables (Dummies) to ensure mathematical viability of the model
        model.DummyCapacity = pyo.Var(model.Destinations, domain=pyo.NonNegativeReals, doc=translate("Capacidade extra artificial alocada (ton)", lang))
        model.DummyUnallocated = pyo.Var(model.Origins, model.Products, domain=pyo.NonNegativeReals, doc=translate("Oferta não alocada a nenhum destino (ton)", lang))

        # =========================================================================
        # 2.4 OBJECTIVE FUNCTION
        # =========================================================================
        # Mathematical expression to be minimized (Minimize Costs).

        def objective_rule(model):
            # Custo normal do sistema = (Custo de Frete) + (Custo de Armazenagem)
            normal_costs = sum(
                (model.Flow[o, d, p] * model.Distance[o, d] * model.Freight[o]) +
                (model.Flow[o, d, p] * model.Storage[d, p])
                for (o, d, p) in model.ValidRoutes
            )

            # Penalty cost for violating logical constraints
            dummy_capacity_costs = sum(model.DummyCapacity[d] * model.BigMCapacity for d in model.Destinations)
            dummy_unallocated_costs = sum(model.DummyUnallocated[o, p] * model.BigMUnallocated for o in model.Origins for p in model.Products)

            return normal_costs + dummy_capacity_costs + dummy_unallocated_costs

        model.Objective = pyo.Objective(rule=objective_rule, sense=pyo.minimize, doc=translate("Minimização dos Custos Totais", lang))

        # =========================================================================
        # 2.5 CONSTRAINTS
        # =========================================================================
        # Rules that decision variables must strictly obey.

        # Constraint 1: Flow Conservation (Supply Limit)
        # The total available supply in an origin for a product MUST be routed,
        # whether via actual allocation (Flow) or slack (DummyUnallocated).
        def supply_rule(model, o, p):
            if model.Supply[o, p] <= 0:
                return pyo.Constraint.Skip

            valid_dests = [d for d in model.Destinations if (o, d, p) in model.ValidRoutes]
            if not valid_dests:
                # There are no valid routes, all supply goes to the dummy variable
                return model.DummyUnallocated[o, p] == model.Supply[o, p]

            flow_sum = sum(model.Flow[o, d, p] for d in valid_dests)
            return flow_sum + model.DummyUnallocated[o, p] == model.Supply[o, p]

        model.SupplyConstraint = pyo.Constraint(model.Origins, model.Products, rule=supply_rule, doc=translate("Restrição de Limite de Oferta", lang))

        # Constraint 2: Warehouse Capacity Limit
        # The total quantity arriving at a destination cannot exceed its real available capacity.
        # Available Capacity = (Total Capacity - Initial Inventory)
        # If the solver has no alternative, it will use DummyCapacity paying the penalty.
        def capacity_rule(model, d):
            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            if not valid_ops:
                return pyo.Constraint.Skip

            flow_sum = sum(model.Flow[o, d, p] for (o, p) in valid_ops)

            # Tratamento para evitar capacidade efetiva negativa caso estoque inicial > total
            # Extracting numerical value to allow boolean verification
            effective_cap = max(0.0, pyo.value(model.TotalCapacity[d]) - pyo.value(model.InitialInventory[d]))

            if effective_cap > 0:
                return flow_sum <= (model.TotalCapacity[d] - model.InitialInventory[d]) + model.DummyCapacity[d]
            else:
                # If there is effectively no capacity, the warehouse can only receive load generating Dummy
                return flow_sum <= model.DummyCapacity[d]

        model.CapacityConstraint = pyo.Constraint(model.Destinations, rule=capacity_rule, doc=translate("Restrição de Limite de Capacidade Efetiva", lang))

        # Show the model for debug only if requested by the user
        if detailed_log:
            model.pprint()

        results_dict["model_stats"]["total_variables"] = sum(1 for _ in model.component_data_objects(pyo.Var, active=True))
        results_dict["model_stats"]["total_constraints"] = sum(1 for _ in model.component_data_objects(pyo.Constraint, active=True))
        results_dict["model_stats"]["binary_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain == pyo.Binary)
        results_dict["model_stats"]["integer_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Integers, pyo.NonNegativeIntegers, pyo.PositiveIntegers))
        results_dict["model_stats"]["continuous_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Reals, pyo.NonNegativeReals, pyo.PositiveReals))

        # 3. Solucionar o modelo
        print("\n" + translate("Chamando solver CBC...", lang))
        solver = SolverFactory('cbc')
        # Time limit to prevent infinite locking
        solver.options['sec'] = 1200
        if solver_gap is not None:
            solver.options['ratioGap'] = solver_gap

        results = solver.solve(model, tee=True)

        print("\n" + translate("=== STATUS DA OTIMIZAÇÃO ===", lang))
        print(translate("Status do Solver: {status}", lang).format(status=results.solver.status))
        print(translate("Condição de Término: {condition}", lang).format(condition=results.solver.termination_condition))

        lower_bound = results.problem.lower_bound if results.problem.lower_bound is not None else "N/A"
        upper_bound = results.problem.upper_bound if results.problem.upper_bound is not None else "N/A"
        gap = "N/A"
        if isinstance(lower_bound, (int, float)) and isinstance(upper_bound, (int, float)) and upper_bound != 0:
            if lower_bound > -1e20 and upper_bound < 1e20: # Ensure valid bounds
                gap = abs(upper_bound - lower_bound) / abs(upper_bound)

        results_dict["kpis"]["lower_bound"] = lower_bound
        results_dict["kpis"]["upper_bound"] = upper_bound
        results_dict["kpis"]["gap"] = gap

        termination_condition = results.solver.termination_condition
        is_max_time_limit = termination_condition == pyo.TerminationCondition.maxTimeLimit

        if results.solver.status == pyo.SolverStatus.ok and (termination_condition == pyo.TerminationCondition.optimal or is_max_time_limit):
            print(translate("Solução Ótima Encontrada!", lang))

            objective_value = pyo.value(model.Objective)
            print(translate("Custo Total (Função Objetivo): R$ {val:,.2f}", lang).format(val=objective_value))

            results_dict["status"] = "optimal"
            results_dict["objective"] = objective_value

            print("\n" + translate("--- DETALHES DO FLUXO (Alocação) ---", lang))
            total_transported = 0
            total_km = 0.0
            total_freight_cost = 0.0
            total_storage_cost = 0.0

            for (o, d, p) in model.ValidRoutes:
                val = pyo.value(model.Flow[o, d, p])
                if val > 0.001:  # ignore floating point zeros
                    d_name = cda_to_name.get(d, d)
                    dist = pyo.value(model.Distance[o, d])
                    f_cost = pyo.value(model.Freight[o])
                    s_cost = pyo.value(model.Storage[d, p])

                    route_freight = val * dist * f_cost
                    route_storage = val * s_cost
                    route_total = route_freight + route_storage

                    print(translate("De: {o} | Para: {d} | Produto: {p} | Qtd: {val:.2f} ton", lang).format(o=o, d=d_name, p=p, val=val))

                    results_dict["routes"].append({
                        "Origem": o,
                        "Destino": d_name,
                        "Produto": p,
                        "Quantidade (ton)": val,
                        "Distancia (km)": dist,
                        "Custo Frete (R$)": route_freight,
                        "Custo Armazenagem (R$)": route_storage,
                        "Custo Total (R$)": route_total,
                        "Custo Frete Unitario (R$/ton-km)": f_cost,
                        "Custo Armaz. Unitario (R$/ton)": s_cost
                    })

                    total_transported += val
                    total_km += dist
                    total_freight_cost += route_freight
                    total_storage_cost += route_storage

            print("\n" + translate("Total de produtos alocados: {val:.2f} toneladas", lang).format(val=total_transported))

            results_dict["kpis"]["total_tons"] = total_transported
            results_dict["kpis"]["total_km"] = total_km
            results_dict["kpis"]["total_freight_cost"] = total_freight_cost
            results_dict["kpis"]["total_storage_cost"] = total_storage_cost

            # Check usage of Dummy variables
            dummy_cap_used = False
            print("\n" + translate("--- AVISOS: CAPACIDADE ARTIFICIAL (DUMMIES) ---", lang))
            for d in model.Destinations:
                d_val = pyo.value(model.DummyCapacity[d])
                if d_val > 0.001:
                    dummy_cap_used = True
                    d_name = cda_to_name.get(d, d)
                    msg = translate("O Armazém \'{d_name}\' precisou de capacidade de armazenamento artificial de {d_val:.2f} toneladas.", lang).format(d_name=d_name, d_val=d_val)
                    print(translate("ALERTA: {msg}", lang).format(msg=msg))
                    results_dict["warnings"]["capacity"].append(msg)

            if not dummy_cap_used:
                print(translate("Nenhuma capacidade artificial foi necessária. O modelo encontrou solução com as capacidades reais.", lang))

            dummy_unalloc_used = False
            print("\n" + translate("--- AVISOS: OFERTA SEM ROTAS / NÃO ALOCADA (DUMMIES) ---", lang))
            for o in model.Origins:
                for p in model.Products:
                    u_val = pyo.value(model.DummyUnallocated[o, p])
                    if u_val > 0.001:
                        dummy_unalloc_used = True
                        msg = translate("A origem \'{o}\' possui oferta de \'{p}\' não alocada: {u_val:.2f} toneladas.", lang).format(o=o, p=p, u_val=u_val)
                        print(translate("ALERTA: {msg}", lang).format(msg=msg))
                        results_dict["warnings"]["unallocated"].append(msg)

            if not dummy_unalloc_used:
                print(translate("Toda a oferta conseguiu ser escoada em rotas válidas para algum destino.", lang))

            if dummy_cap_used or dummy_unalloc_used:
                print("\n" + translate("Nota: Foram utilizadas variáveis dummies com custo elevado para impedir que o modelo falhasse por inviabilidade.", lang))
                print(translate("Custo de Capacidade Artificial (Big M) = {val:.2e}", lang).format(val=pyo.value(model.BigMCapacity)))
                print(translate("Custo de Oferta Não Alocada (Big M) = {val:.2e}", lang).format(val=pyo.value(model.BigMUnallocated)))

        else:
            if is_max_time_limit:
                print(translate("Limite de tempo atingido sem solução factível (NFS).", lang))
                results_dict["status"] = "timeout_nfs"
                results_dict["kpis"]["gap"] = "NFS"
                results_dict["warnings"]["general"].append(translate("O modelo não encontrou solução factível antes do tempo limite.", lang))
            else:
                print(translate("Não foi possível encontrar uma solução ótima. O modelo pode estar mal-condicionado.", lang))
                results_dict["status"] = "infeasible"
                results_dict["warnings"]["general"].append(translate("O modelo não encontrou solução ótima.", lang))

    except Exception as e:
        print("\n" + translate("ERRO DURANTE A OTIMIZAÇÃO: {err}", lang).format(err=str(e)))
        results_dict["status"] = "error"
        results_dict["warnings"]["general"].append(translate("Erro: {err}", lang).format(err=str(e)))
        import traceback
        # print_exc defaults to sys.stderr. Let's print formatting to sys.stdout
        # so it gets caught in our buffer!
        print(traceback.format_exc())

    finally:
        # Try to parse CBC solver output from the log file for iterations and nodes
        try:
            import re
            sys.stdout.flush()
            if 'log_path' in locals() and os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # CBC usually reports nodes and iterations
                    match_nodes = re.search(r'Enumerated nodes:\s+(\d+)', content)
                    match_iters = re.search(r'Total iterations:\s+(\d+)', content)
                    if match_nodes:
                        results_dict["model_stats"]["nodes"] = int(match_nodes.group(1))
                    if match_iters:
                        results_dict["model_stats"]["iterations"] = int(match_iters.group(1))
        except Exception as e:
            print(f"Error parsing log: {e}")

        # Registrar tempo total e imprimir no log
        end_time = time.time()
        total_time_seconds = end_time - start_time
        print("\n" + translate("Tempo de execução: {val:.2f} segundos.", lang).format(val=total_time_seconds))

        # Adds time to the results dictionary
        results_dict["kpis"]["execution_time"] = total_time_seconds

        # Close the temporary log file and restore stdout
        new_stdout.close()
        sys.stdout = old_stdout

    # Retornar o nome do arquivo de log salvo e os dados estruturados
    return log_filename, results_dict

def _run_milp_optimization_model(start_time, supply, demand_total_capacity, demand_initial_inventory,
                                 demand_reception_capacity, is_public, cda_to_name,
                                 prod_dest_compat, distance, freight_cost, storage_cost, avg_freight,
                                 all_products, origins_list, detailed_log,
                                 input_min_load, input_max_load, toggle_use_reception,
                                 input_allocation_days, input_min_freight, input_max_freight, toggle_pareto=False, solver_gap=None, lang="pt"):
    """
    Versão MILP do modelo, inclui restrições extras e variáveis binárias (RouteActive).
    """

    # Calculate days multiplier
    try:
        days = float(input_allocation_days) if input_allocation_days else 1.0
    except:
        days = 1.0

    # Parse numeric limits
    def parse_float(val):
        if val is None or str(val).strip() == "":
            return None
        try:
            return float(val)
        except:
            return None

    carga_min = parse_float(input_min_load)
    carga_max = parse_float(input_max_load)
    frete_min = parse_float(input_min_freight)
    frete_max = parse_float(input_max_freight)

    # Redirecionar output
    old_stdout = sys.stdout
    log_dir = os.path.join(tempfile.gettempdir(), 'granum_logs')
    os.makedirs(log_dir, exist_ok=True)

    now = time.time()
    for filename in os.listdir(log_dir):
        filepath = os.path.join(log_dir, filename)
        if os.path.isfile(filepath):
            if os.stat(filepath).st_mtime < now - 3600:
                try:
                    os.remove(filepath)
                except Exception:
                    pass

    log_fd, log_path = tempfile.mkstemp(suffix='.txt', prefix='optimization_log_milp_', dir=log_dir)
    log_filename = os.path.basename(log_path)
    new_stdout = os.fdopen(log_fd, 'w', encoding='utf-8')
    sys.stdout = new_stdout

    results_dict = {
        "status": "error",
        "objective": 0.0,
        "routes": [],
        "kpis": {
            "total_tons": 0.0,
            "total_km": 0.0,
            "total_freight_cost": 0.0,
            "total_storage_cost": 0.0,
            "execution_time": 0.0
        },
        "model_stats": {
            "total_variables": 0,
            "binary_variables": 0,
            "integer_variables": 0,
            "continuous_variables": 0,
            "total_constraints": 0,
            "iterations": 0,
            "nodes": 0
        },
        "warnings": {
            "capacity": [],
            "unallocated": [],
            "general": []
        }
    }

    try:
        print(translate("Iniciando a construção do modelo matemático (MILP com restrições de limite)...", lang))
        model = pyo.ConcreteModel(name="Alocacao_Armazens_MILP")

        # =========================================================================
        # 3.1 CONJUNTOS (SETS)
        # =========================================================================
        # Defines the indices over which the model will operate.
        model.Origins = pyo.Set(initialize=origins_list, doc=translate("Cidades de Origem da Oferta", lang))
        model.Destinations = pyo.Set(initialize=list(demand_total_capacity.keys()), doc=translate("Armazéns de Destino", lang))
        model.Products = pyo.Set(initialize=all_products, doc=translate("Tipos de Produtos", lang))

        valid_routes = []
        for o in model.Origins:
            for p in model.Products:
                compatible_dests = []
                # Reúne todos os destinos válidos para esta origem e produto
                for d in model.Destinations:
                    if (o, d) in distance and prod_dest_compat.get((p, d), False):
                        dist_val = distance[(o, d)]
                        # Armazena apenas a distância para o Pareto
                        compatible_dests.append((d, dist_val))

                if compatible_dests:
                    if toggle_pareto:
                        # Ordena pela menor distância
                        compatible_dests.sort(key=lambda x: x[1])
                        # Aplica a regra 80/20, arredondando sempre para cima
                        limit = max(1, math.ceil(len(compatible_dests) * 0.20))
                        compatible_dests = compatible_dests[:limit]

                    # Adiciona os destinos filtrados às rotas válidas
                    for d, _ in compatible_dests:
                        valid_routes.append((o, d, p))

        print(translate("Total de combinações (Origem x Destino x Produto) válidas: {val}", lang).format(val=len(valid_routes)))
        model.ValidRoutes = pyo.Set(initialize=valid_routes, dimen=3, doc=translate("Rotas Válidas (Origem, Destino, Produto)", lang))

        # =========================================================================
        # 3.2 PARÂMETROS (PARAMETERS)
        # =========================================================================
        # Valores fixos conhecidos fornecidos como dados de entrada para o modelo.

        # --- Constants and Logistics Limit Parameters ---
        model.Days = pyo.Param(initialize=days, within=pyo.Any, doc=translate("Dias de alocação", lang))
        model.FreightMin = pyo.Param(initialize=frete_min, within=pyo.Any, doc=translate("Carga mínima de frete por rota", lang))
        model.FreightMax = pyo.Param(initialize=frete_max, within=pyo.Any, doc=translate("Carga máxima de frete por rota", lang))

        def reception_min_init(model, d):
            return carga_min
        model.ReceptionMin = pyo.Param(model.Destinations, initialize=reception_min_init, within=pyo.Any, doc=translate("Carga mínima diária de recepção", lang))

        def reception_max_init(model, d):
            if toggle_use_reception:
                return demand_reception_capacity.get(d, 0.0)
            elif carga_max is not None:
                return carga_max
            return None

        model.ReceptionMax = pyo.Param(model.Destinations, initialize=reception_max_init, within=pyo.Any, doc=translate("Carga máxima diária de recepção ou capacidade do banco", lang))


        # --- Parâmetros de Oferta e Demanda ---
        def supply_init(model, o, p):
            return supply.get((o, p), 0.0)
        model.Supply = pyo.Param(model.Origins, model.Products, initialize=supply_init, doc=translate("Oferta disponível por (Origem, Produto)", lang))

        def total_capacity_init(model, d):
            return demand_total_capacity.get(d, 0.0)
        model.TotalCapacity = pyo.Param(model.Destinations, initialize=total_capacity_init, doc=translate("Capacidade estática total do armazém (ton)", lang))

        def initial_inventory_init(model, d):
            return demand_initial_inventory.get(d, 0.0)
        model.InitialInventory = pyo.Param(model.Destinations, initialize=initial_inventory_init, doc=translate("Estoque inicial presente no armazém (ton)", lang))

        # --- Parâmetros de Custos e Distâncias ---
        def dist_init(model, o, d):
            return distance.get((o, d), 999999.0)
        model.Distance = pyo.Param(model.Origins, model.Destinations, initialize=dist_init, doc=translate("Distância entre Origem e Destino (km)", lang))

        def freight_init(model, o):
            return freight_cost.get(o, avg_freight)
        model.Freight = pyo.Param(model.Origins, initialize=freight_init, doc=translate("Custo unitário de frete (R$/ton-km) a partir da Origem", lang))

        def storage_init(model, d, p):
            return storage_cost.get((d, p), 50.0)
        model.Storage = pyo.Param(model.Destinations, model.Products, initialize=storage_init, doc=translate("Tarifa de armazenagem no Destino para o Produto (R$/ton)", lang))

        max_freight = max(freight_cost.values()) if freight_cost else 0.0
        max_dist = max(distance.values()) if distance else 0.0
        max_storage = max(storage_cost.values()) if storage_cost else 0.0

        val_big_m_cap = (max_freight * max_dist + max_storage) * 1000
        if val_big_m_cap == 0:
            val_big_m_cap = 10000

        val_big_m_unalloc = val_big_m_cap * 10

        # --- Penalty Parameters (Big M) ---
        model.BigMCapacity = pyo.Param(initialize=val_big_m_cap, doc=translate("Custo de penalização por tonelada de capacidade artificial", lang))
        model.BigMUnallocated = pyo.Param(initialize=val_big_m_unalloc, doc=translate("Custo de penalização por tonelada de oferta não alocada", lang))

        # Big M para as Rotas (Indexado por ValidRoutes)
        def big_m_flow_init(model, o, d, p):
            f_max = pyo.value(model.FreightMax, exception=False)
            if f_max is not None:
                return f_max
            else:
                # The route's real ceiling is ONLY the supply from that origin (since capacity can expand with dummy)
                local_max = pyo.value(model.Supply[o, p])
                return local_max if local_max > 0 else 999999.0
                
        model.UpperFlow = pyo.Param(model.ValidRoutes, initialize=big_m_flow_init, doc=translate("Big M Dinâmico e Local por Rota", lang))

        # 2. Big M for Warehouses (Indexed by Destinations)
        def big_m_warehouse_init(model, d):
            # The absolute maximum a warehouse can receive is the sum of all supply pointed to it
            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            max_possible_arrival = sum(pyo.value(model.Supply[o, p]) for (o, p) in valid_ops)
            
            return max_possible_arrival if max_possible_arrival > 0 else 999999.0
            
        model.BigMWarehouse = pyo.Param(model.Destinations, initialize=big_m_warehouse_init, doc=translate("Big M Dinâmico por Armazém", lang))

        # =========================================================================
        # 3.3 DECISION VARIABLES
        # =========================================================================
        # Values the solver will attempt to determine to optimize the result.

        # Fluxo de produto (quantidade a ser transportada) em toneladas
        model.Flow = pyo.Var(model.ValidRoutes, domain=pyo.NonNegativeReals, doc=translate("Quantidade transportada (o, d, p)", lang))

        # Slack variables (Dummies) to ensure mathematical viability of the model
        model.DummyCapacity = pyo.Var(model.Destinations, domain=pyo.NonNegativeReals, doc=translate("Capacidade extra artificial alocada (ton)", lang))
        model.DummyUnallocated = pyo.Var(model.Origins, model.Products, domain=pyo.NonNegativeReals, doc=translate("Oferta não alocada a nenhum destino (ton)", lang))
        model.DummyReception = pyo.Var(model.Destinations, domain=pyo.NonNegativeReals, doc=translate("Capacidade de recepção diária extra artificial alocada (ton)", lang))

        # Binary Variables for Limits
        model.RouteActive = pyo.Var(model.ValidRoutes, domain=pyo.NonNegativeIntegers, doc=translate("Número de viagens na rota", lang))
        # model.WarehouseActive declared further down in the MILP Constraints section

        # =========================================================================
        # 3.4 OBJECTIVE FUNCTION
        # =========================================================================
        # Mathematical expression to be minimized (Minimize Costs).

        def objective_rule(model):
            normal_costs = sum(
                (model.Flow[o, d, p] * model.Distance[o, d] * model.Freight[o]) +
                (model.Flow[o, d, p] * model.Storage[d, p])
                for (o, d, p) in model.ValidRoutes
            )
            dummy_capacity_costs = sum(model.DummyCapacity[d] * model.BigMCapacity for d in model.Destinations)
            dummy_reception_costs = sum(model.DummyReception[d] * (model.BigMCapacity * 0.1) for d in model.Destinations)
            dummy_unallocated_costs = sum(model.DummyUnallocated[o, p] * model.BigMUnallocated for o in model.Origins for p in model.Products)
            return normal_costs + dummy_capacity_costs + dummy_reception_costs + dummy_unallocated_costs

        model.Objective = pyo.Objective(rule=objective_rule, sense=pyo.minimize, doc=translate("Minimização dos Custos Totais", lang))

        # =========================================================================
        # 3.5 CONSTRAINTS
        # =========================================================================
        # Rules that decision variables must strictly obey.

        # Constraint 1: Flow Conservation (Supply Limit)
        def supply_rule(model, o, p):
            if model.Supply[o, p] <= 0:
                return pyo.Constraint.Skip
            valid_dests = [d for d in model.Destinations if (o, d, p) in model.ValidRoutes]
            if not valid_dests:
                return model.DummyUnallocated[o, p] == model.Supply[o, p]
            flow_sum = sum(model.Flow[o, d, p] for d in valid_dests)
            return flow_sum + model.DummyUnallocated[o, p] == model.Supply[o, p]
        model.SupplyConstraint = pyo.Constraint(model.Origins, model.Products, rule=supply_rule, doc=translate("Restrição de Limite de Oferta", lang))

        # Constraint 2: Static Effective Capacity Limit
        def capacity_rule(model, d):
            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            if not valid_ops:
                return pyo.Constraint.Skip
            flow_sum = sum(model.Flow[o, d, p] for (o, p) in valid_ops)
            effective_cap = max(0.0, pyo.value(model.TotalCapacity[d]) - pyo.value(model.InitialInventory[d]))
            if effective_cap > 0:
                return flow_sum <= (model.TotalCapacity[d] - model.InitialInventory[d]) + model.DummyCapacity[d]
            else:
                return flow_sum <= model.DummyCapacity[d]
        model.CapacityConstraint = pyo.Constraint(model.Destinations, rule=capacity_rule, doc=translate("Restrição de Limite de Capacidade Efetiva", lang))

# =========================================================================
        # 3.6 MILP CONSTRAINTS (ADDITIONAL LOGISTICS LIMITS)
        # =========================================================================
        print("\n" + translate("--- CONFIGURAÇÕES DE LIMITES LOGÍSTICOS (MILP) ---", lang))
        print(translate("Dias de alocação considerados: {val}", lang).format(val=pyo.value(model.Days, exception=False)))
        if pyo.value(model.FreightMin, exception=False) is not None:
            print(translate("Carga mínima de frete por rota ativada: {val} ton", lang).format(val=pyo.value(model.FreightMin, exception=False)))
        if pyo.value(model.FreightMax, exception=False) is not None:
            print(translate("Carga máxima de frete por rota ativada: {val} ton", lang).format(val=pyo.value(model.FreightMax, exception=False)))

        if list(model.Destinations):
            if pyo.value(model.ReceptionMin[list(model.Destinations)[0]], exception=False) is not None:
                print(translate("Carga mínima diária de recepção ativada: {val1} ton/dia (Total: {val2} ton)", lang).format(val1=pyo.value(model.ReceptionMin[list(model.Destinations)[0]], exception=False), val2=pyo.value(model.ReceptionMin[list(model.Destinations)[0]], exception=False) * pyo.value(model.Days, exception=False)))
            if toggle_use_reception:
                print(translate("Capacidade máxima de recepção do banco de dados ativada.", lang))
            elif pyo.value(model.ReceptionMax[list(model.Destinations)[0]], exception=False) is not None: # Note: this assumes same for all if not toggle
                print(translate("Carga máxima diária de recepção ativada: {val} ton/dia", lang).format(val=pyo.value(model.ReceptionMax[list(model.Destinations)[0]], exception=False)))

        def route_active_max_rule(model, o, d, p):
            return model.Flow[o, d, p] <= model.RouteActive[o, d, p] * model.UpperFlow[o, d, p]
            
        model.RouteActiveMaxRule = pyo.Constraint(model.ValidRoutes, rule=route_active_max_rule, doc=translate("Limite máximo de frete ou local", lang))

        # Minimum Freight limit (optional)
        if pyo.value(model.FreightMin, exception=False) is not None:
            def route_active_min_rule(model, o, d, p):
                return model.Flow[o, d, p] >= model.RouteActive[o, d, p] * pyo.value(model.FreightMin, exception=False)
            model.RouteActiveMinRule = pyo.Constraint(model.ValidRoutes, rule=route_active_min_rule, doc=translate("Limite mínimo de frete na rota caso ela seja usada", lang))

        # Binary variable for warehouse activation:
        # If a warehouse is used (receives any flow), WarehouseActive = 1
        model.WarehouseActive = pyo.Var(model.Destinations, domain=pyo.Binary, doc=translate("1 se o armazém receber qualquer rota, 0 caso contrário", lang))

        # Link warehouse flow with its activation variable (WarehouseActive)
        def link_warehouse_active_rule(model, d):
            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            if not valid_ops:
                return model.WarehouseActive[d] == 0

            flow_sum = sum(model.Flow[o, d, p] for (o, p) in valid_ops)
            
            # Using clean parameter
            return flow_sum <= model.WarehouseActive[d] * model.BigMWarehouse[d]
            
        model.LinkWarehouseActive = pyo.Constraint(model.Destinations, rule=link_warehouse_active_rule, doc=translate("Vincula o armazém a rotas ativas", lang))

        # Minimum cargo reception limit in warehouse (optional)
        def min_reception_rule(model, d):
            reception_min_val = pyo.value(model.ReceptionMin[d], exception=False)
            if reception_min_val is None:
                return pyo.Constraint.Skip

            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            if not valid_ops:
                return pyo.Constraint.Skip
            flow_sum = sum(model.Flow[o, d, p] for (o, p) in valid_ops)
            return flow_sum >= model.WarehouseActive[d] * (reception_min_val * pyo.value(model.Days, exception=False))
        model.MinReceptionRule = pyo.Constraint(model.Destinations, rule=min_reception_rule, doc=translate("Recepção Mínima do Armazém se for ativado", lang))

        # Maximum cargo reception limit in warehouse (optional or by Database Reception Cap.)
        # Note: toggle_use_reception and carga_max are mutually exclusive in UI logic,
        # but here we explicitly state priority: database capacity overrides if activated.
        def max_reception_rule(model, d):
            valid_ops = [(o, p) for o in model.Origins for p in model.Products if (o, d, p) in model.ValidRoutes]
            if not valid_ops:
                return pyo.Constraint.Skip

            flow_sum = sum(model.Flow[o, d, p] for (o, p) in valid_ops)

            reception_max_val = pyo.value(model.ReceptionMax[d], exception=False)
            if reception_max_val is not None:
                limit = reception_max_val * pyo.value(model.Days, exception=False)
                # Flow can use dummy reception if limit is exceeded
                return flow_sum <= limit + model.DummyReception[d]
            return pyo.Constraint.Skip

        model.MaxReceptionRule = pyo.Constraint(model.Destinations, rule=max_reception_rule, doc=translate("Recepção Máxima no Armazém com tolerância de folga DummyReception", lang))

        


        results_dict["model_stats"]["total_variables"] = sum(1 for _ in model.component_data_objects(pyo.Var, active=True))
        results_dict["model_stats"]["total_constraints"] = sum(1 for _ in model.component_data_objects(pyo.Constraint, active=True))
        results_dict["model_stats"]["binary_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain == pyo.Binary)
        results_dict["model_stats"]["integer_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Integers, pyo.NonNegativeIntegers, pyo.PositiveIntegers))
        results_dict["model_stats"]["continuous_variables"] = sum(1 for v in model.component_data_objects(pyo.Var, active=True) if v.domain in (pyo.Reals, pyo.NonNegativeReals, pyo.PositiveReals))


        if detailed_log:
            model.pprint()

        print("\n" + translate("Chamando solver CBC (MILP)...", lang))
        solver = SolverFactory('cbc')
        solver.options['sec'] = 1200
        if solver_gap is not None:
            solver.options['ratioGap'] = solver_gap

        results = solver.solve(model, tee=True)

        print("\n" + translate("=== STATUS DA OTIMIZAÇÃO ===", lang))
        print(translate("Status do Solver: {status}", lang).format(status=results.solver.status))
        print(translate("Condição de Término: {condition}", lang).format(condition=results.solver.termination_condition))

        lower_bound = results.problem.lower_bound if results.problem.lower_bound is not None else "N/A"
        upper_bound = results.problem.upper_bound if results.problem.upper_bound is not None else "N/A"
        gap = "N/A"
        if isinstance(lower_bound, (int, float)) and isinstance(upper_bound, (int, float)) and upper_bound != 0:
            if lower_bound > -1e20 and upper_bound < 1e20: # Ensure valid bounds
                gap = abs(upper_bound - lower_bound) / abs(upper_bound)

        results_dict["kpis"]["lower_bound"] = lower_bound
        results_dict["kpis"]["upper_bound"] = upper_bound
        results_dict["kpis"]["gap"] = gap

        termination_condition = results.solver.termination_condition
        is_max_time_limit = termination_condition == pyo.TerminationCondition.maxTimeLimit

        if results.solver.status == pyo.SolverStatus.ok and (termination_condition == pyo.TerminationCondition.optimal or is_max_time_limit):
            print(translate("Solução Ótima Encontrada!", lang))
            objective_value = pyo.value(model.Objective)
            print(translate("Custo Total (Função Objetivo): R$ {val:,.2f}", lang).format(val=objective_value))

            results_dict["status"] = "optimal"
            results_dict["objective"] = objective_value

            print("\n" + translate("--- DETALHES DO FLUXO (Alocação) ---", lang))
            total_transported = 0
            total_km = 0.0
            total_freight_cost = 0.0
            total_storage_cost = 0.0

            for (o, d, p) in model.ValidRoutes:
                val = pyo.value(model.Flow[o, d, p])
                if val > 0.001:
                    d_name = cda_to_name.get(d, d)
                    dist = pyo.value(model.Distance[o, d])
                    f_cost = pyo.value(model.Freight[o])
                    s_cost = pyo.value(model.Storage[d, p])

                    route_freight = val * dist * f_cost
                    route_storage = val * s_cost
                    route_total = route_freight + route_storage

                    viagens = pyo.value(model.RouteActive[o, d, p])
                    viagens_val = int(round(viagens)) if viagens is not None else None

                    print(translate("De: {o} | Para: {d} | Produto: {p} | Qtd: {val:.2f} ton | Viagens: {viagens}", lang).format(o=o, d=d_name, p=p, val=val, viagens=viagens_val))

                    results_dict["routes"].append({
                        "Origem": o,
                        "Destino": d_name,
                        "Produto": p,
                        "Quantidade (ton)": val,
                        "Distancia (km)": dist,
                        "Custo Frete (R$)": route_freight,
                        "Custo Armazenagem (R$)": route_storage,
                        "Custo Total (R$)": route_total,
                        "Custo Frete Unitario (R$/ton-km)": f_cost,
                        "Custo Armaz. Unitario (R$/ton)": s_cost,
                        "Qtd. de Viagens": viagens_val
                    })

                    total_transported += val
                    total_km += dist
                    total_freight_cost += route_freight
                    total_storage_cost += route_storage

            print("\n" + translate("Total de produtos alocados: {val:.2f} toneladas", lang).format(val=total_transported))

            results_dict["kpis"]["total_tons"] = total_transported
            results_dict["kpis"]["total_km"] = total_km
            results_dict["kpis"]["total_freight_cost"] = total_freight_cost
            results_dict["kpis"]["total_storage_cost"] = total_storage_cost

            # Check usage of Dummy variables
            dummy_cap_used = False
            print("\n" + translate("--- AVISOS: CAPACIDADE ARTIFICIAL (DUMMIES) ---", lang))
            for d in model.Destinations:
                d_val = pyo.value(model.DummyCapacity[d])
                if d_val > 0.001:
                    dummy_cap_used = True
                    d_name = cda_to_name.get(d, d)
                    msg = translate("O Armazém \'{d_name}\' precisou de capacidade de armazenamento artificial de {d_val:.2f} toneladas.", lang).format(d_name=d_name, d_val=d_val)
                    print(translate("ALERTA: {msg}", lang).format(msg=msg))
                    results_dict["warnings"]["capacity"].append(msg)

            if not dummy_cap_used:
                print(translate("Nenhuma capacidade estática artificial foi necessária.", lang))

            if "reception" not in results_dict["warnings"]:
                results_dict["warnings"]["reception"] = []

            dummy_reception_used = False
            print("\n" + translate("--- AVISOS: RECEPÇÃO DIÁRIA ARTIFICIAL (DUMMIES) ---", lang))
            for d in model.Destinations:
                d_val = pyo.value(model.DummyReception[d])
                if d_val > 0.001:
                    dummy_reception_used = True
                    d_name = cda_to_name.get(d, d)
                    msg = translate("O Armazém \'{d_name}\' precisou de capacidade de recepção diária artificial de {d_val:.2f} toneladas.", lang).format(d_name=d_name, d_val=d_val)
                    print(translate("ALERTA: {msg}", lang).format(msg=msg))
                    results_dict["warnings"]["reception"].append(msg)

            if not dummy_reception_used:
                print(translate("Nenhuma capacidade de recepção artificial foi necessária.", lang))

            if "freight" not in results_dict["warnings"]:
                results_dict["warnings"]["freight"] = []

            dummy_unalloc_used = False
            print("\n" + translate("--- AVISOS: OFERTA SEM ROTAS / NÃO ALOCADA (DUMMIES) ---", lang))
            for o in model.Origins:
                for p in model.Products:
                    u_val = pyo.value(model.DummyUnallocated[o, p])
                    if u_val > 0.001:
                        dummy_unalloc_used = True

                        # Infer if non-allocation could be due to tight freight
                        if frete_min is not None or frete_max is not None:
                            msg = translate("A origem \'{o}\' possui oferta de \'{p}\' não alocada ({u_val:.2f} toneladas). Isso provavelmente ocorreu devido às restrições de carga de frete mínima/máxima impostas.", lang).format(o=o, p=p, u_val=u_val)
                            print(translate("ALERTA: {msg}", lang).format(msg=msg))
                            results_dict["warnings"]["freight"].append(msg)
                        else:
                            msg = translate("A origem \'{o}\' possui oferta de \'{p}\' não alocada: {u_val:.2f} toneladas.", lang).format(o=o, p=p, u_val=u_val)
                            print(translate("ALERTA: {msg}", lang).format(msg=msg))
                            results_dict["warnings"]["unallocated"].append(msg)

            if not dummy_unalloc_used:
                print(translate("Toda a oferta conseguiu ser escoada em rotas válidas.", lang))

            if dummy_cap_used or dummy_reception_used or dummy_unalloc_used:
                print("\n" + translate("Nota: Foram utilizadas variáveis dummies com custo elevado para impedir que o modelo falhasse por inviabilidade.", lang))

        else:
            if is_max_time_limit:
                print(translate("Limite de tempo atingido sem solução factível (NFS).", lang))
                results_dict["status"] = "timeout_nfs"
                results_dict["kpis"]["gap"] = "NFS"
                results_dict["warnings"]["general"].append(translate("O modelo não encontrou solução factível antes do tempo limite.", lang))
            else:
                print(translate("Não foi possível encontrar uma solução ótima.", lang))
                results_dict["status"] = "infeasible"
                results_dict["warnings"]["general"].append(translate("O modelo não encontrou solução ótima.", lang))

    except Exception as e:
        print("\n" + translate("ERRO DURANTE A OTIMIZAÇÃO: {err}", lang).format(err=str(e)))
        results_dict["status"] = "error"
        results_dict["warnings"]["general"].append(translate("Erro: {err}", lang).format(err=str(e)))
        import traceback
        print(traceback.format_exc())

    finally:
        try:
            import re
            sys.stdout.flush()
            if 'log_path' in locals() and os.path.exists(log_path):
                with open(log_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match_nodes = re.search(r'Enumerated nodes:\s+(\d+)', content)
                    match_iters = re.search(r'Total iterations:\s+(\d+)', content)
                    if match_nodes:
                        results_dict["model_stats"]["nodes"] = int(match_nodes.group(1))
                    if match_iters:
                        results_dict["model_stats"]["iterations"] = int(match_iters.group(1))
        except Exception as e:
            print(f"Error parsing log: {e}")

        end_time = time.time()
        total_time_seconds = end_time - start_time
        print("\n" + translate("Tempo de execução: {val:.2f} segundos.", lang).format(val=total_time_seconds))
        results_dict["kpis"]["execution_time"] = total_time_seconds

        new_stdout.close()
        sys.stdout = old_stdout

    return log_filename, results_dict
