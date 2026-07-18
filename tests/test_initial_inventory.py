import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import pyomo.environ as pyo
from src.logic.optimization import run_deterministic_model

class TestInitialInventory(unittest.TestCase):
  @patch('src.logic.optimization.SolverFactory')
  def test_initial_inventory_deterministic(self, mock_solver_factory):
    df_supply = pd.DataFrame([
      {"Cidade": "Sorriso - MT", "Produto": "Soja", "Data": "2026-01", "Peso (ton)": 100.0}
    ])
    
    df_warehouses = pd.DataFrame([
      {
        "CDA": "WH-001",
        "Status": "Existente",
        "Armazenador": "CONAB",
        "Município": "Brasília",
        "UF": "DF",
        "Tipo": "Silo",
        "Cap. Estática (t)": 200.0,
        "Cap. Recepção (t)": 50.0,
        "Cap. Expedição (t)": 50.0,
        "Cap. Estática Máxima (t)": 0.0,
        "Custo de Abertura ($)": 0.0
      }
    ])
    
    df_compat = pd.DataFrame([
      {"Produto": "Soja", "Silo": "☑", "Convencional": "☐"}
    ])
    
    df_dist_supply_wh = pd.DataFrame([
      {"Origem": "Sorriso - MT", "WH-001 - CONAB - Brasília": 100.0}
    ])
    
    df_dist_wh_demand = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "São Paulo - SP": 200.0}
    ])
    
    df_dist_wh_wh = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "WH-001 - CONAB - Brasília": 0.0}
    ])
    
    df_demand = pd.DataFrame([
      {"Cidade": "São Paulo - SP", "Produto": "Soja", "Latitude": -23.5505, "Longitude": -46.6333, "Data": "2026-01", "Peso (ton)": 100.0}
    ])
    
    df_freight = pd.DataFrame([
      {"Estado": "MT", "Frete Tonelada Km": 0.3},
      {"Estado": "DF", "Frete Tonelada Km": 0.3}
    ])
    
    df_storage = pd.DataFrame([
      {"Produto": "Soja", "Armazenar": 10.0}
    ])

    # Initial inventory setup
    df_initial_inventory = pd.DataFrame([
      {"CDA": "WH-001", "Produto": "Soja", "Estoque Inicial (t)": 50.0}
    ])

    mock_solver = MagicMock()
    mock_solver_factory.return_value = mock_solver
    
    # Custom solve method to verify model parameters
    def mock_solve(model, **kwargs):
      # Assert that InitialInventory has been initialized correctly in Pyomo
      self.assertEqual(pyo.value(model.InitialInventory["WH-001", "Soja"]), 50.0)
      
      for var in model.component_objects(pyo.Var, active=True):
        for index in var:
          var[index].value = 0.0
      
      model.FlowOD["Sorriso - MT", "WH-001", "Soja", "2026-01"].value = 0.0
      model.FlowDC["WH-001", "São Paulo - SP", "Soja", "2026-01"].value = 0.0
      model.Inventory["WH-001", "Soja", "2026-01"].value = 50.0
      
      for d in model.Destinations_cand:
        model.WarehouseOpen[d].value = 0.0
        model.CandStaticCapacity[d].value = 0.0
          
      for d in model.Destinations:
        model.IsExpanded[d].value = 0.0
        model.ExpandedCapacity[d].value = 0.0
        if d in model.BulkEligible:
          model.IsBulkified[d].value = 0.0
          model.BulkCapacity[d].value = 0.0
              
      mock_res = MagicMock()
      mock_res.solver.status = pyo.SolverStatus.ok
      mock_res.solver.termination_condition = pyo.TerminationCondition.optimal
      return mock_res

    mock_solver.solve = mock_solve
    
    log_filename, results = run_deterministic_model(
      df_supply=df_supply,
      df_warehouses=df_warehouses,
      df_compat=df_compat,
      df_dist_supply_wh=df_dist_supply_wh,
      df_dist_wh_demand=df_dist_wh_demand,
      df_dist_wh_wh=df_dist_wh_wh,
      df_demand=df_demand,
      df_freight=df_freight,
      df_storage=df_storage,
      df_initial_inventory=df_initial_inventory,
      input_allocation_days=30,
      interhub_factor=1.0,
      solver_gap=0.01,
      solver_time_limit=60,
      ratio_expand_rec=1.0,
      ratio_expand_ship=1.0,
      solver_name="cbc"
    )
    
    self.assertIsNotNone(results)
    self.assertEqual(results["inventory"][0]["Quantidade (ton)"], 50.0)

  @patch('src.logic.optimization.SolverFactory')
  def test_supply_demand_check_with_inventory(self, mock_solver_factory):
    # Supply = 40.0, Demand = 100.0, Initial Inventory = 80.0
    df_supply = pd.DataFrame([
      {"Cidade": "Sorriso - MT", "Produto": "Soja", "Data": "2026-01", "Peso (ton)": 40.0}
    ])
    df_warehouses = pd.DataFrame([
      {
        "CDA": "WH-001",
        "Status": "Existente",
        "Armazenador": "CONAB",
        "Município": "Brasília",
        "UF": "DF",
        "Tipo": "Silo",
        "Cap. Estática (t)": 200.0,
        "Cap. Recepção (t)": 50.0,
        "Cap. Expedição (t)": 50.0,
        "Cap. Estática Máxima (t)": 0.0,
        "Custo de Abertura ($)": 0.0
      }
    ])
    df_compat = pd.DataFrame([
      {"Produto": "Soja", "Silo": "☑", "Convencional": "☐"}
    ])
    df_dist_supply_wh = pd.DataFrame([
      {"Origem": "Sorriso - MT", "WH-001 - CONAB - Brasília": 100.0}
    ])
    df_dist_wh_demand = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "São Paulo - SP": 200.0}
    ])
    df_dist_wh_wh = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "WH-001 - CONAB - Brasília": 0.0}
    ])
    df_demand = pd.DataFrame([
      {"Cidade": "São Paulo - SP", "Produto": "Soja", "Latitude": -23.5505, "Longitude": -46.6333, "Data": "2026-01", "Peso (ton)": 100.0}
    ])
    df_freight = pd.DataFrame([
      {"Estado": "MT", "Frete Tonelada Km": 0.3},
      {"Estado": "DF", "Frete Tonelada Km": 0.3}
    ])
    df_storage = pd.DataFrame([
      {"Produto": "Soja", "Armazenar": 10.0}
    ])

    # Case A: Initial Inventory is 80.0. Supply (40) + Inventory (80) = 120 >= Demand (100). Check should pass.
    df_initial_inventory_pass = pd.DataFrame([
      {"CDA": "WH-001", "Produto": "Soja", "Estoque Inicial (t)": 80.0}
    ])
    
    mock_solver = MagicMock()
    mock_solver_factory.return_value = mock_solver
    
    def mock_solve(model, **kwargs):
      for var in model.component_objects(pyo.Var, active=True):
        for index in var:
          var[index].value = 0.0
      
      model.FlowOD["Sorriso - MT", "WH-001", "Soja", "2026-01"].value = 0.0
      model.FlowDC["WH-001", "São Paulo - SP", "Soja", "2026-01"].value = 0.0
      model.Inventory["WH-001", "Soja", "2026-01"].value = 80.0
      
      for d in model.Destinations_cand:
        model.WarehouseOpen[d].value = 0.0
        model.CandStaticCapacity[d].value = 0.0
          
      for d in model.Destinations:
        model.IsExpanded[d].value = 0.0
        model.ExpandedCapacity[d].value = 0.0
        if d in model.BulkEligible:
          model.IsBulkified[d].value = 0.0
          model.BulkCapacity[d].value = 0.0
              
      mock_res = MagicMock()
      mock_res.solver.status = pyo.SolverStatus.ok
      mock_res.solver.termination_condition = pyo.TerminationCondition.optimal
      return mock_res

    mock_solver.solve = mock_solve

    # Should run without raising ValueError because of enough initial inventory
    try:
      run_deterministic_model(
        df_supply=df_supply,
        df_warehouses=df_warehouses,
        df_compat=df_compat,
        df_dist_supply_wh=df_dist_supply_wh,
        df_dist_wh_demand=df_dist_wh_demand,
        df_dist_wh_wh=df_dist_wh_wh,
        df_demand=df_demand,
        df_freight=df_freight,
        df_storage=df_storage,
        df_initial_inventory=df_initial_inventory_pass,
        input_allocation_days=30,
        interhub_factor=1.0,
        solver_gap=0.01,
        solver_time_limit=60,
        ratio_expand_rec=1.0,
        ratio_expand_ship=1.0,
        solver_name="cbc"
      )
    except ValueError as e:
      self.fail(f"run_deterministic_model raised ValueError unexpectedly: {e}")

    # Case B: Initial Inventory is 10.0. Supply (40) + Inventory (10) = 50 < Demand (100). Check should fail.
    df_initial_inventory_fail = pd.DataFrame([
      {"CDA": "WH-001", "Produto": "Soja", "Estoque Inicial (t)": 10.0}
    ])

    with self.assertRaises(ValueError):
      run_deterministic_model(
        df_supply=df_supply,
        df_warehouses=df_warehouses,
        df_compat=df_compat,
        df_dist_supply_wh=df_dist_supply_wh,
        df_dist_wh_demand=df_dist_wh_demand,
        df_dist_wh_wh=df_dist_wh_wh,
        df_demand=df_demand,
        df_freight=df_freight,
        df_storage=df_storage,
        df_initial_inventory=df_initial_inventory_fail,
        input_allocation_days=30,
        interhub_factor=1.0,
        solver_gap=0.01,
        solver_time_limit=60,
        ratio_expand_rec=1.0,
        ratio_expand_ship=1.0,
        solver_name="cbc"
      )

  def test_callback_capacity_validation(self):
    import dash
    from src.view.view import manage_initial_inventory
    
    df_arm = pd.DataFrame([{
      "CDA": "WH-001",
      "Status": "Existente",
      "Armazenador": "CONAB",
      "Município": "Brasília",
      "Cap. Estática (t)": 100.0
    }])
    stored_warehouses = df_arm.to_json(date_format='iso', orient='split')
    
    df_prod = pd.DataFrame([{"Produto": "Soja"}])
    stored_data = df_prod.to_json(date_format='iso', orient='split')
    
    df_init = pd.DataFrame([{
      "CDA": "WH-001",
      "Armazenador": "CONAB",
      "Município": "Brasília",
      "Cap. Estática (t)": 100.0,
      "Produto": "Soja",
      "Estoque Inicial (t)": 10.0
    }])
    stored_init_inv = df_init.to_json(date_format='iso', orient='split')
    
    with patch('dash.callback_context') as mock_ctx:
      mock_ctx.triggered = [{'prop_id': 'btn-add-initial-inventory.n_clicks'}]
      
      res_store, res_err, err_msg, _ = manage_initial_inventory(
        active_tab="tab-prod-warehouses",
        stored_data=stored_data,
        stored_warehouses=stored_warehouses,
        upload_contents=None,
        n_add=1,
        timestamp=None,
        stored_init_inv=stored_init_inv,
        table_data=None,
        form_product="Soja",
        form_warehouse="WH-001",
        form_amount=150.0,
        upload_filename=None,
        lang="pt"
      )
      
      self.assertEqual(res_store, dash.no_update)
      self.assertTrue(res_err)
      self.assertIn("excede a capacidade estática", err_msg)

