import unittest
import pandas as pd
import numpy as np
from src.view.pages.prediction import get_tab_prediction_layout
from src.logic.prediction import (
  prepare_time_series,
  calculate_metrics,
  get_quality_badge,
  forecast_sarima,
  forecast_xgboost,
  forecast_lstm,
  forecast_fallback
)

class TestPrediction(unittest.TestCase):
  def setUp(self):
    # Create small synthetic series for testing
    self.dates = pd.date_range(start="2020-01-01", periods=24, freq="MS")
    self.values = [100.0 + i + 5.0 * np.sin(i) for i in range(24)]
    self.df = pd.DataFrame({
      "Produto": ["Soja"] * 24,
      "Cidade": ["Brasília"] * 24,
      "Data": self.dates.strftime("%Y-%m"),
      "Peso (ton)": self.values
    })

  def test_prediction_layout(self):
    # Test layout creation
    layout = get_tab_prediction_layout(lang="pt")
    self.assertIsNotNone(layout)
    layout_en = get_tab_prediction_layout(lang="en")
    self.assertIsNotNone(layout_en)

  def test_prepare_time_series(self):
    # Test preprocessing
    series = prepare_time_series(self.df, product="Soja", city="Brasília")
    self.assertEqual(len(series), 24)
    self.assertEqual(series.index.freq, "MS")

  def test_calculate_metrics(self):
    # Test metrics helper
    y_true = [100.0, 110.0, 120.0]
    y_pred = [105.0, 108.0, 122.0]
    mae, rmse, mape, wmape = calculate_metrics(y_true, y_pred)
    self.assertGreater(mae, 0.0)
    self.assertGreater(rmse, 0.0)
    self.assertGreater(mape, 0.0)
    self.assertGreater(wmape, 0.0)

  def test_quality_badge(self):
    # Test badges
    lbl, color = get_quality_badge(5.0)
    self.assertEqual(color, "success")
    lbl, color = get_quality_badge(15.0)
    self.assertEqual(color, "success")
    lbl, color = get_quality_badge(30.0)
    self.assertEqual(color, "warning")
    lbl, color = get_quality_badge(60.0)
    self.assertEqual(color, "danger")

  def test_forecasting_models(self):
    series = prepare_time_series(self.df, product="Soja", city="Brasília")
    train = series.iloc[:-6]
    test_len = 6
    horizon = 6

    # Test SARIMA
    test_preds, future_preds, summary = forecast_sarima(train, test_len, horizon)
    self.assertEqual(len(test_preds), test_len)
    self.assertEqual(len(future_preds), horizon)

    # Test XGBoost
    test_preds, future_preds, summary = forecast_xgboost(train, test_len, horizon)
    self.assertEqual(len(test_preds), test_len)
    self.assertEqual(len(future_preds), horizon)

    # Test LSTM
    test_preds, future_preds, summary = forecast_lstm(train, test_len, horizon)
    self.assertEqual(len(test_preds), test_len)
    self.assertEqual(len(future_preds), horizon)

    # Test Fallback
    test_preds, future_preds, summary = forecast_fallback(train.values, test_len, horizon)
    self.assertEqual(len(test_preds), test_len)
    self.assertEqual(len(future_preds), horizon)

  def test_sync_prediction_dropdowns(self):
    from src.view.view import sync_prediction_dropdowns
    import json
    
    # Test when no predictions exist
    opts_s, dis_s, val_s, opts_p, dis_p, val_p, opts_c, dis_c, val_c = sync_prediction_dropdowns(
      None, None, None, None
    )
    self.assertTrue(dis_s)
    self.assertTrue(dis_p)
    self.assertTrue(dis_c)
    self.assertIsNone(val_s)
    self.assertIsNone(val_p)
    self.assertIsNone(val_c)

    # Test with prediction results
    mock_results = {
      "supply_Soja_Brasília": {"status": "success", "series_type": "supply", "product": "Soja", "city": "Brasília", "mape": 5.0},
      "demand_Milho_Goiânia": {"status": "success", "series_type": "demand", "product": "Milho", "city": "Goiânia", "mape": 12.0}
    }
    results_json = json.dumps(mock_results)
    
    opts_s, dis_s, val_s, opts_p, dis_p, val_p, opts_c, dis_c, val_c = sync_prediction_dropdowns(
      results_json, None, None, None
    )
    self.assertFalse(dis_s)
    self.assertFalse(dis_p)
    self.assertFalse(dis_c)
    self.assertEqual(val_s, "supply")  # defaults to 'supply' if present in available series
    self.assertEqual(val_p, "Soja")    # defaults to first product for 'supply'
    self.assertEqual(val_c, "Brasília") # defaults to first city for Soja in 'supply'

if __name__ == '__main__':
  unittest.main()
