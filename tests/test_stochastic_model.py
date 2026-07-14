import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import pyomo.environ as pyo
import json
from src.logic.optimization import run_stochastic_model, compute_evpi_vss

class TestStochasticModel(unittest.TestCase):
  @patch('src.logic.optimization.SolverFactory')
  def test_run_stochastic_model_success(self, mock_solver_factory):
    # 1. Build small mock dataset
    df_supply = pd.DataFrame([
      {"Cidade": "Sorriso - MT", "Produto": "Soja", "Data": "2026-01", "Peso (ton)": 150.0}
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
    
    # Mock forecast predictions
    mock_prediction_results = {
      "supply_Sorriso - MT_Soja": {
        "status": "success",
        "series_type": "supply",
        "product": "Soja",
        "city": "Sorriso - MT",
        "future_dates": ["2026-01"],
        "future_preds": [150.0],
        "wmape": 15.0
      },
      "demand_São Paulo - SP_Soja": {
        "status": "success",
        "series_type": "demand",
        "product": "Soja",
        "city": "São Paulo - SP",
        "future_dates": ["2026-01"],
        "future_preds": [100.0],
        "wmape": 15.0
      }
    }
    
    # Setup mock solver behaviour
    mock_solver = MagicMock()
    mock_solver_factory.return_value = mock_solver
    
    def mock_solve(model, **kwargs):
      # Assign mock values to variables so post-solve pyo.value calls succeed
      for var in model.component_objects(pyo.Var, active=True):
        for index in var:
          var[index].value = 0.0
      
      # Set specific flows for each scenario to represent mock solution
      for s in ['pessimista', 'esperado', 'otimista']:
        model.FlowOD["Sorriso - MT", "WH-001", "Soja", "2026-01", s].value = 100.0
        model.FlowDC["WH-001", "São Paulo - SP", "Soja", "2026-01", s].value = 100.0
        model.Inventory["WH-001", "Soja", "2026-01", s].value = 0.0
      
      # Candidates open vars (even if empty)
      for d in model.Destinations_cand:
        model.WarehouseOpen[d].value = 0.0
        model.CandStaticCapacity[d].value = 0.0
          
      for d in model.Destinations:
        model.IsExpanded[d].value = 0.0
        model.ExpandedCapacity[d].value = 0.0
        if d in model.BulkEligible:
          model.IsBulkified[d].value = 0.0
          model.BulkCapacity[d].value = 0.0
              
      # Return optimal status mock
      mock_res = MagicMock()
      mock_res.solver.status = pyo.SolverStatus.ok
      mock_res.solver.termination_condition = pyo.TerminationCondition.optimal
      return mock_res

    mock_solver.solve = mock_solve
    
    # Run stochastic model
    log_filename, results = run_stochastic_model(
      df_supply=df_supply,
      df_warehouses=df_warehouses,
      df_compat=df_compat,
      df_dist_supply_wh=df_dist_supply_wh,
      df_dist_wh_demand=df_dist_wh_demand,
      df_dist_wh_wh=df_dist_wh_wh,
      df_demand=df_demand,
      df_freight=df_freight,
      df_storage=df_storage,
      scenario_probabilities={"pessimista": 0.33, "esperado": 0.34, "otimista": 0.33},
      error_source="prediction",
      supply_error_pct=15.0,
      demand_error_pct=15.0,
      prediction_results=mock_prediction_results,
      detailed_log=False,
      toggle_pareto=False,
      input_allocation_days=30,
      interhub_factor=0.85,
      solver_gap=1.0,
      solver_time_limit=30,
      ratio_expand_rec=0.10,
      ratio_expand_ship=0.10,
      max_expand_capacity=5000,
      expand_fixed_cost=50000,
      expand_var_cost=100,
      max_bulk_capacity=500,
      bulk_fixed_cost=30000,
      bulk_var_cost=200,
      bulk_eligible_types=["Silo"],
      lang="pt"
    )
    
    # Assert results
    self.assertIsNotNone(log_filename)
    self.assertEqual(results["model_type"], "stochastic")
    self.assertEqual(results["status"], "optimal")
    self.assertIn("scenario_routes", results)
    self.assertIn("scenario_kpis", results)
    self.assertIn("scenario_warehouse_metrics", results)
    self.assertIn("scenario_inventory", results)
    
    # Verify expected kpis are filled
    self.assertIn("routes", results)
    self.assertIn("kpis", results)
    self.assertIn("inventory", results)

  def test_pre_solve_warnings(self):
    # Set supply = 100, demand = 100. WMAPE is 15%.
    # In pessimistic scenario: supply = 85.0, demand = 115.0.
    # This should trigger the pre-optimization feasibility check failure.
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
    mock_prediction_results = {
      "supply_Sorriso - MT_Soja": {
        "status": "success",
        "series_type": "supply",
        "product": "Soja",
        "city": "Sorriso - MT",
        "future_dates": ["2026-01"],
        "future_preds": [100.0],
        "wmape": 15.0
      },
      "demand_São Paulo - SP_Soja": {
        "status": "success",
        "series_type": "demand",
        "product": "Soja",
        "city": "São Paulo - SP",
        "future_dates": ["2026-01"],
        "future_preds": [100.0],
        "wmape": 15.0
      }
    }

    with self.assertRaises(ValueError) as ctx:
      run_stochastic_model(
        df_supply=df_supply,
        df_warehouses=df_warehouses,
        df_compat=df_compat,
        df_dist_supply_wh=df_dist_supply_wh,
        df_dist_wh_demand=df_dist_wh_demand,
        df_dist_wh_wh=df_dist_wh_wh,
        df_demand=df_demand,
        df_freight=df_freight,
        df_storage=df_storage,
        scenario_probabilities={"pessimista": 0.33, "esperado": 0.34, "otimista": 0.33},
        error_source="prediction",
        supply_error_pct=15.0,
        demand_error_pct=15.0,
        prediction_results=mock_prediction_results,
        detailed_log=False,
        toggle_pareto=False,
        input_allocation_days=30,
        interhub_factor=0.85,
        solver_gap=1.0,
        solver_time_limit=30,
        ratio_expand_rec=0.10,
        ratio_expand_ship=0.10,
        max_expand_capacity=5000,
        expand_fixed_cost=50000,
        expand_var_cost=100,
        max_bulk_capacity=500,
        bulk_fixed_cost=30000,
        bulk_var_cost=200,
        bulk_eligible_types=["Silo"],
        lang="pt"
      )
    self.assertIn("Erro: Oferta total", str(ctx.exception))

if __name__ == '__main__':
  unittest.main()
