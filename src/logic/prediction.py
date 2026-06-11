import io
import json
import warnings
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
import shutil
import pathlib
import importlib_resources
import os
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from src.logic.i18n import translate

# Fix Prophet/CmdStanPy AttributeError if a broken local cmdstan exists
try:
  local_cmdstan = pathlib.Path(str(importlib_resources.files("prophet") / "stan_model" / "cmdstan-2.33.1"))
  if local_cmdstan.exists() and not (local_cmdstan / "makefile").exists():
    backup_path = local_cmdstan.with_name("cmdstan-2.33.1.bak")
    if not backup_path.exists():
      try:
        shutil.move(str(local_cmdstan), str(backup_path))
      except OSError:
        shutil.rmtree(local_cmdstan, ignore_errors=True)
except Exception:
  pass

# PyTorch LSTM architecture for time series
class LSTMRegressor(nn.Module):
  def __init__(self, input_dim=1, hidden_dim=16, num_layers=1):
    super().__init__()
    self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
    self.linear = nn.Linear(hidden_dim, 1)

  def forward(self, x):
    # LSTM returns (output, (hn, cn))
    # We take the output of the last sequence step
    out, _ = self.lstm(x)
    pred = self.linear(out[:, -1, :])
    return pred

def prepare_time_series(df, product=None, city=None):
  """
  Filters and aggregates data into a continuous monthly time series.
  Fills missing months with 0.0 to ensure regular frequency.
  """
  df = df.copy()
  df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
  df = df.dropna(subset=["Data"])

  # Filter based on user selection
  if product and product != "Todos" and product != "All":
    df = df[df["Produto"] == product]
  if city and city != "Todas" and city != "All":
    df = df[df["Cidade"] == city]

  # Aggregate weights to monthly frequency
  df_grouped = df.groupby(df["Data"].dt.to_period("M"))["Peso (ton)"].sum().reset_index()
  df_grouped["Data"] = df_grouped["Data"].dt.to_timestamp()

  if df_grouped.empty:
    return pd.Series(dtype=float)

  # Reindex to fill any gaps in dates
  min_date = df_grouped["Data"].min()
  max_date = df_grouped["Data"].max()
  full_range = pd.date_range(start=min_date, end=max_date, freq="MS")
  
  df_grouped = df_grouped.set_index("Data").reindex(full_range, fill_value=0.0)
  return df_grouped["Peso (ton)"]

def calculate_metrics(y_true, y_pred):
  """
  Calculates MAE, RMSE, and MAPE metrics.
  """
  y_true = np.array(y_true, dtype=float)
  y_pred = np.array(y_pred, dtype=float)

  mae = float(np.mean(np.abs(y_true - y_pred)))
  rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
  
  # Avoid division by zero by replacing 0s in true values with a tiny epsilon
  # or filtering them out for MAPE calculation
  mask = y_true != 0.0
  if np.any(mask):
    mape = float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100.0)
  else:
    mape = 0.0

  return mae, rmse, mape

def get_quality_badge(mape, lang="pt"):
  """
  Determines quality classification based on MAPE score.
  """
  if mape < 10.0:
    return translate("Excelente", lang), "success"
  elif mape < 20.0:
    return translate("Bom", lang), "success"
  elif mape < 50.0:
    return translate("Regular", lang), "warning"
  else:
    return translate("Ruim", lang), "danger"

def forecast_sarima(train_series, test_len, horizon):
  """
  Trains a SARIMA model using statsmodels.
  Uses s=12 if dataset length is enough, else s=0 (standard ARIMA).
  """
  from statsmodels.tsa.statespace.sarimax import SARIMAX

  # Ensure data is floats
  train_data = train_series.values.astype(float)
  n_samples = len(train_data)
  
  # Determine seasonal period
  s = 12 if n_samples >= 24 else 0
  
  try:
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")

      if s == 12:
        # Robust default seasonal order
        model = SARIMAX(
          train_data,
          order=(1, 1, 1),
          seasonal_order=(1, 0, 1, 12),
          enforce_stationarity=False,
          enforce_invertibility=False
        )
      else:
        model = SARIMAX(
          train_data,
          order=(1, 1, 1),
          enforce_stationarity=False,
          enforce_invertibility=False
        )
      
      fit_model = model.fit(disp=False, maxiter=50)
      
      # Predict test and future
      test_preds = fit_model.forecast(steps=test_len)
      
      # Predict future from the end of the train + test data
      # To forecast future, we refit the model on the full historical series
      full_data = np.concatenate([train_data, fit_model.endog[len(train_data):] if test_len == 0 else test_preds])
      if s == 12:
        model_full = SARIMAX(
          full_data,
          order=(1, 1, 1),
          seasonal_order=(1, 0, 1, 12),
          enforce_stationarity=False,
          enforce_invertibility=False
        )
      else:
        model_full = SARIMAX(
          full_data,
          order=(1, 1, 1),
          enforce_stationarity=False,
          enforce_invertibility=False
        )
      fit_full = model_full.fit(disp=False, maxiter=50)
      future_preds = fit_full.forecast(steps=horizon)
      
      params_summary = f"SARIMAX(1,1,1)x(1,0,1,12)" if s == 12 else "ARIMA(1,1,1)"
      params_summary += f"\nAIC: {fit_full.aic:.2f}"
      
      return list(test_preds), list(future_preds), params_summary
  except Exception as e:
    # Fallback to simple double exponential smoothing approximation if SARIMA fails
    return forecast_fallback(train_data, test_len, horizon, f"SARIMA failed, fallback used. Error: {str(e)}")

def forecast_prophet(train_series, test_len, horizon):
  """
  Trains a Prophet model.
  """
  from prophet import Prophet

  # Format DataFrame for Prophet
  df_prophet = pd.DataFrame({
    "ds": train_series.index,
    "y": train_series.values.astype(float)
  })

  try:
    model = Prophet(
      yearly_seasonality=True,
      weekly_seasonality=False,
      daily_seasonality=False
    )
    model.fit(df_prophet)
    
    # Forecast on test set period
    future_test = model.make_future_dataframe(periods=test_len, freq="MS")
    forecast_test = model.predict(future_test)
    test_preds = forecast_test.iloc[-test_len:]["yhat"].values if test_len > 0 else []

    # Fit full series for future forecast
    df_full = pd.DataFrame({
      "ds": train_series.index.tolist() + [train_series.index[-1] + pd.DateOffset(months=i) for i in range(1, test_len + 1)],
      "y": list(train_series.values.astype(float)) + list(test_preds)
    })
    
    model_full = Prophet(
      yearly_seasonality=True,
      weekly_seasonality=False,
      daily_seasonality=False
    )
    model_full.fit(df_full)
    
    future_horizon = model_full.make_future_dataframe(periods=horizon, freq="MS")
    forecast_horizon = model_full.predict(future_horizon)
    future_preds = forecast_horizon.iloc[-horizon:]["yhat"].values

    params_summary = "Prophet Regressor (yearly_seasonality=True)\nSeasonality Mode: additive"
    return list(test_preds), list(future_preds), params_summary
  except Exception as e:
    return forecast_fallback(train_series.values.astype(float), test_len, horizon, f"Prophet failed, fallback used. Error: {str(e)}")

def forecast_xgboost(train_series, test_len, horizon):
  """
  Trains an XGBoost model using autoregressive lags.
  """
  import xgboost as xgb

  train_data = train_series.values.astype(float)
  n_samples = len(train_data)
  
  # Determine lag structure dynamically based on dataset size
  lags = [1, 2, 3]
  if n_samples >= 15:
    lags.append(12) # Include seasonal lag if enough data exists
  
  max_lag = max(lags)
  
  def build_features(data):
    X, y = [], []
    for i in range(max_lag, len(data)):
      features = [data[i - lag] for lag in lags]
      X.append(features)
      y.append(data[i])
    return np.array(X), np.array(y)

  try:
    if n_samples <= max_lag:
      raise ValueError("Not enough data points for lag structure.")

    X, y = build_features(train_data)
    model = xgb.XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X, y)

    # Recursive forecasting on test set
    test_preds = []
    current_history = list(train_data)
    for _ in range(test_len):
      feats = np.array([[current_history[-lag] for lag in lags]])
      pred = float(model.predict(feats)[0])
      test_preds.append(pred)
      current_history.append(pred)

    # Re-train on full data
    full_data = np.concatenate([train_data, test_preds])
    X_full, y_full = build_features(full_data)
    
    model_full = xgb.XGBRegressor(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
    model_full.fit(X_full, y_full)

    # Recursive forecasting on future horizon
    future_preds = []
    current_full_history = list(full_data)
    for _ in range(horizon):
      feats = np.array([[current_full_history[-lag] for lag in lags]])
      pred = float(model_full.predict(feats)[0])
      future_preds.append(pred)
      current_full_history.append(pred)

    params_summary = f"XGBRegressor(max_depth=3, n_estimators=50)\nLags used: {lags}"
    return test_preds, future_preds, params_summary
  except Exception as e:
    return forecast_fallback(train_data, test_len, horizon, f"XGBoost failed, fallback used. Error: {str(e)}")

def forecast_lstm(train_series, test_len, horizon):
  """
  Trains a PyTorch LSTM model using autoregressive sequencing.
  """
  train_data = train_series.values.astype(float)
  n_samples = len(train_data)
  
  # Lookback sequence length determined dynamically
  lookback = min(12, max(3, n_samples // 3))

  # MinMax Scaling
  min_val = float(train_data.min())
  max_val = float(train_data.max())
  range_val = max_val - min_val if max_val != min_val else 1.0
  
  scaled_train = (train_data - min_val) / range_val

  def create_sequences(data, seq_len):
    xs, ys = [], []
    for i in range(len(data) - seq_len):
      xs.append(data[i : i + seq_len])
      ys.append(data[i + seq_len])
    return np.array(xs), np.array(ys)

  try:
    if n_samples <= lookback:
      raise ValueError("Not enough data points for LSTM lookback.")

    X, y = create_sequences(scaled_train, lookback)
    
    # Format inputs for PyTorch [batch, seq_len, features]
    X_tensor = torch.tensor(X, dtype=torch.float32).unsqueeze(-1)
    y_tensor = torch.tensor(y, dtype=torch.float32).unsqueeze(-1)

    model = LSTMRegressor(input_dim=1, hidden_dim=16)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=0.01)

    # Fast training loop (suitable for background callback)
    epochs = 100
    model.train()
    for _ in range(epochs):
      optimizer.zero_grad()
      preds = model(X_tensor)
      loss = criterion(preds, y_tensor)
      loss.backward()
      optimizer.step()

    # Recursive forecasting for test set
    model.eval()
    test_preds_scaled = []
    current_seq = list(scaled_train[-lookback:])
    
    with torch.no_grad():
      for _ in range(test_len):
        input_tensor = torch.tensor([current_seq], dtype=torch.float32).unsqueeze(-1)
        pred = float(model(input_tensor)[0, 0])
        test_preds_scaled.append(pred)
        current_seq.pop(0)
        current_seq.append(pred)

    test_preds = [float(p * range_val + min_val) for p in test_preds_scaled]

    # Re-train on full data
    full_data = np.concatenate([train_data, test_preds])
    scaled_full = (full_data - min_val) / range_val
    X_full, y_full = create_sequences(scaled_full, lookback)

    X_full_tensor = torch.tensor(X_full, dtype=torch.float32).unsqueeze(-1)
    y_full_tensor = torch.tensor(y_full, dtype=torch.float32).unsqueeze(-1)

    model_full = LSTMRegressor(input_dim=1, hidden_dim=16)
    optimizer_full = optim.Adam(model_full.parameters(), lr=0.01)

    model_full.train()
    for _ in range(epochs):
      optimizer_full.zero_grad()
      preds = model_full(X_full_tensor)
      loss = criterion(preds, y_full_tensor)
      loss.backward()
      optimizer_full.step()

    model_full.eval()
    future_preds_scaled = []
    current_full_seq = list(scaled_full[-lookback:])

    with torch.no_grad():
      for _ in range(horizon):
        input_tensor = torch.tensor([current_full_seq], dtype=torch.float32).unsqueeze(-1)
        pred = float(model_full(input_tensor)[0, 0])
        future_preds_scaled.append(pred)
        current_full_seq.pop(0)
        current_full_seq.append(pred)

    future_preds = [float(p * range_val + min_val) for p in future_preds_scaled]

    params_summary = f"PyTorch LSTMRegressor(hidden_dim=16)\nSequence Lookback: {lookback}\nEpochs: {epochs}"
    return test_preds, future_preds, params_summary
  except Exception as e:
    return forecast_fallback(train_data, test_len, horizon, f"LSTM failed, fallback used. Error: {str(e)}")

def forecast_fallback(train_data, test_len, horizon, message="Fallback method used"):
  """
  Simple Linear Trend + Average Seasonality model as a robust mathematical fallback.
  """
  n = len(train_data)
  indices = np.arange(n)
  
  # Fit linear trend: y = a * x + b
  A = np.vstack([indices, np.ones(n)]).T
  slope, intercept = np.linalg.lstsq(A, train_data, rcond=None)[0]
  
  # Calculate seasonal indices if we have enough years
  seasonal_pattern = np.zeros(12)
  if n >= 24:
    for month_idx in range(12):
      month_values = [train_data[i] for i in range(month_idx, n, 12)]
      seasonal_pattern[month_idx] = np.mean(month_values) - (slope * month_idx + intercept)
  
  def predict_step(step_idx):
    trend = slope * step_idx + intercept
    seasonal = seasonal_pattern[step_idx % 12]
    return max(0.0, float(trend + seasonal))

  test_preds = [predict_step(n + i) for i in range(test_len)]
  
  # For future predictions, we extend beyond test
  future_preds = [predict_step(n + test_len + i) for i in range(horizon)]
  
  summary = f"Fallback Linear Trend + Seasonality Model\nReason: {message}\nSlope: {slope:.4f}"
  return test_preds, future_preds, summary
