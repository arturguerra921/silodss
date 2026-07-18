import io
import pandas as pd
from src.logic.i18n import translate

def validate_and_parse_supply_data(stored_supply_data, lang):
  """
  Validates the stored supply data and extracts timespan years and unique products.
  """
  if not stored_supply_data:
    raise ValueError(translate("Você precisa preencher a aba 'Oferta' antes de acessar a aba 'Demanda'.", lang))
  try:
    supply_df = pd.read_json(io.StringIO(stored_supply_data), orient='split')
    if supply_df.empty:
      raise ValueError(translate("Você precisa preencher a aba 'Oferta' antes de acessar a aba 'Demanda'.", lang))
    supply_dates = pd.to_datetime(supply_df['Data'], errors='coerce').dropna()
    if supply_dates.empty:
      raise ValueError(translate("Você precisa preencher a aba 'Oferta' antes de acessar a aba 'Demanda'.", lang))
    start_yr = supply_dates.min().year
    end_yr = supply_dates.max().year
    valid_products = set(supply_df['Produto'].unique())
    return start_yr, end_yr, valid_products
  except Exception as e:
    if isinstance(e, ValueError):
      raise e
    raise ValueError(translate("Erro ao ler dados da aba Oferta:", lang) + f" {str(e)}")


def safe_parse_numeric(val):
  """
  Safely parses a numeric value from string or number format, supporting Brazilian formatting.
  """
  if pd.isna(val):
    return 0.0
  if isinstance(val, (int, float)):
    return float(val)
  val_str = str(val).strip()
  if not val_str:
    return 0.0
  return float(val_str.replace('.', '').replace(',', '.'))

