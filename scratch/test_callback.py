import sys
import os
import io
import pandas as pd
import numpy as np

# Ensure workspace path is at the very beginning of sys.path
sys.path.insert(0, r'c:\Users\artur\Documents\GitHub\silodss')

import dash
# Mock callback_context
class MockCallbackContext:
    def __init__(self, triggered_prop):
        self.triggered = [triggered_prop]

dash.callback_context = MockCallbackContext({'prop_id': 'btn-demand-add-row.n_clicks', 'value': 1})

from src.view.view import update_demand_store

def run_callback_test():
    # Load some supply data from excel
    supply_df = pd.read_excel(r'examples\ofertas\ofertas_teste_10_nos.xlsx')
    # Normalize columns
    supply_df.columns = [col.strip() for col in supply_df.columns]
    
    # Add a mock Data column
    supply_df['Data'] = '2026-06'
    
    # We want to format supply_df as the json stored in stored-data
    stored_supply_data = supply_df.to_json(date_format='iso', orient='split')
    
    # Let's construct a stored_demand_data with some finite demand rows
    # so we are adding an infinite row to a non-empty demand store.
    df_existing_demand = pd.DataFrame({
        'Produto': ["Soja"],
        'Cidade': ["Belo Horizonte - MG"],
        'Latitude': [-19.9167],
        'Longitude': [-43.9342],
        'Data': ["2026-06"],
        'Peso (ton)': [50.0]
    })
    df_existing_demand = df_existing_demand.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
    })
    stored_demand_data = df_existing_demand.to_json(date_format='iso', orient='split')
    
    # Now invoke update_demand_store as if we are adding an infinite demand row
    print("Invoking update_demand_store with None lat/lon...")
    try:
        res = update_demand_store(
            None, # contents
            1, # n_add
            None, # timestamp
            None, # n_confirm_clear
            None, # filename
            stored_demand_data,
            "Soja", # prod_val
            None, # weight_val
            True, # infinite_val
            "Curitiba - PR", # city_val
            None, # lat_val
            None, # lon_val
            None, # table_data
            "pt", # lang
            "constant", # pattern_val
            None, # growth_val
            None, # filter_prod
            None, # filter_city
            stored_supply_data
        )
        print("Return values:")
        for idx, val in enumerate(res):
            print(f"res[{idx}]: {val}")
    except Exception as ex:
        import traceback
        print("Caught exception inside test script:")
        traceback.print_exc()

if __name__ == "__main__":
    run_callback_test()
