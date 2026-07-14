import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import pyomo.environ as pyo
from src.logic.optimization import run_deterministic_model

class TestDeterministicModel(unittest.TestCase):
  @patch('src.logic.optimization.SolverFactory')
  def test_run_deterministic_model_success(self, mock_solver_factory):
    # 1. Build small feasible mock dataset
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
    
    # Setup mock solver behaviour
    mock_solver = MagicMock()
    mock_solver_factory.return_value = mock_solver
    
    def mock_solve(model, **kwargs):
      # Assign mock values to variables so post-solve pyo.value calls succeed
      for var in model.component_objects(pyo.Var, active=True):
        for index in var:
          var[index].value = 0.0
      
      # Set specific flows to represent mock solution
      model.FlowOD["Sorriso - MT", "WH-001", "Soja", "2026-01"].value = 100.0
      model.FlowDC["WH-001", "São Paulo - SP", "Soja", "2026-01"].value = 100.0
      model.Inventory["WH-001", "Soja", "2026-01"].value = 0.0
      
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
    
    # Run model
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
    self.assertEqual(results["status"], "optimal")
    self.assertIn("routes", results)
    self.assertIn("kpis", results)
    self.assertIn("warehouse_decisions", results)
    self.assertIn("inventory", results)
    
    # Verify KPI structures
    kpis = results["kpis"]
    self.assertEqual(kpis["total_tons"], 100.0)
    self.assertGreater(kpis["total_km"], 0)
    self.assertGreater(kpis["total_freight_cost"], 0)
    
    # Verify route entries
    routes = results["routes"]
    self.assertTrue(len(routes) >= 2)
    
    od_route = next(r for r in routes if r["Tipo de Rota"] == "Origem -> Armazém")
    self.assertEqual(od_route["Origem"], "Sorriso - MT")
    self.assertEqual(od_route["Destino"], "WH-001 - CONAB - Brasília")
    self.assertEqual(od_route["Quantidade (ton)"], 100.0)

  @patch('src.logic.optimization.SolverFactory')
  def test_run_deterministic_model_infeasible_pre_check(self, mock_solver_factory):
    # Supply = 50, Demand = 100
    df_supply = pd.DataFrame([
      {"Cidade": "Sorriso - MT", "Produto": "Soja", "Data": "2026-01", "Peso (ton)": 50.0}
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

    with self.assertRaises(ValueError) as ctx:
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
        lang="pt"
      )
    self.assertIn("Erro: Oferta total", str(ctx.exception))

  @patch('src.logic.optimization.SolverFactory')
  def test_run_deterministic_model_with_interhub_penalty(self, mock_solver_factory):
    # Test case to verify interhub_factor > 1 (penalty) works correctly and multiplies costs.
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
      },
      {
        "CDA": "WH-002",
        "Status": "Existente",
        "Armazenador": "CONAB",
        "Município": "Goiânia",
        "UF": "GO",
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
      {"Origem": "Sorriso - MT", "WH-001 - CONAB - Brasília": 100.0, "WH-002 - CONAB - Goiânia": 150.0}
    ])
    df_dist_wh_demand = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "São Paulo - SP": 200.0},
      {"Origem": "WH-002 - CONAB - Goiânia", "São Paulo - SP": 200.0}
    ])
    df_dist_wh_wh = pd.DataFrame([
      {"Origem": "WH-001 - CONAB - Brasília", "WH-001 - CONAB - Brasília": 0.0, "WH-002 - CONAB - Goiânia": 100.0},
      {"Origem": "WH-002 - CONAB - Goiânia", "WH-001 - CONAB - Brasília": 100.0, "WH-002 - CONAB - Goiânia": 0.0}
    ])
    df_demand = pd.DataFrame([
      {"Cidade": "São Paulo - SP", "Produto": "Soja", "Latitude": -23.5505, "Longitude": -46.6333, "Data": "2026-01", "Peso (ton)": 100.0}
    ])
    df_freight = pd.DataFrame([
      {"Estado": "MT", "Frete Tonelada Km": 0.3},
      {"Estado": "DF", "Frete Tonelada Km": 0.3},
      {"Estado": "GO", "Frete Tonelada Km": 0.3}
    ])
    df_storage = pd.DataFrame([
      {"Produto": "Soja", "Armazenar": 10.0}
    ])

    mock_solver = MagicMock()
    mock_solver_factory.return_value = mock_solver

    def mock_solve(model, **kwargs):
      for var in model.component_objects(pyo.Var, active=True):
        for index in var:
          var[index].value = 0.0

      model.FlowOD["Sorriso - MT", "WH-001", "Soja", "2026-01"].value = 100.0
      model.FlowDD["WH-001", "WH-002", "Soja", "2026-01"].value = 50.0
      model.FlowDC["WH-001", "São Paulo - SP", "Soja", "2026-01"].value = 50.0
      model.FlowDC["WH-002", "São Paulo - SP", "Soja", "2026-01"].value = 50.0
      model.Inventory["WH-001", "Soja", "2026-01"].value = 0.0
      model.Inventory["WH-002", "Soja", "2026-01"].value = 0.0

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

    # Run with interhub_factor = 1.5 (penalty)
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
      detailed_log=False,
      toggle_pareto=False,
      input_allocation_days=30,
      interhub_factor=1.5,
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

    self.assertEqual(results["status"], "optimal")
    routes = results["routes"]
    interhub_route = next(r for r in routes if r["Tipo de Rota"] == "Interhub")
    self.assertEqual(interhub_route["Origem"], "WH-001 - CONAB - Brasília")
    self.assertEqual(interhub_route["Destino"], "WH-002 - CONAB - Goiânia")
    # Cost = 50.0 * 1.5 * 100.0 * 0.3 = 2250.0
    self.assertAlmostEqual(interhub_route["Custo Frete (R$)"], 2250.0)

if __name__ == '__main__':
  unittest.main()
