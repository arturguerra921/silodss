import pandas as pd
import numpy as np
import io

def run_test():
    # Setup variables representing an infinite demand series (None weights and coordinates)
    start_yr = 2026
    end_yr = 2027
    prod_val_normalized = "Soja"
    city_val = "Cidade X"
    lat_val = None
    lon_val = None
    
    dates_list = pd.date_range(
        start=f"{start_yr}-01-01", 
        end=f"{end_yr}-12-01", 
        freq='MS'
    ).strftime('%Y-%m').tolist()
    
    new_rows = []
    for t, dt_str in enumerate(dates_list):
        new_rows.append({
          'Produto': prod_val_normalized,
          'Cidade': city_val,
          'Latitude': lat_val,
          'Longitude': lon_val,
          'Data': dt_str,
          'Peso (ton)': None
        })

    # Existing dataframe (contains finite demand data)
    # Let's say existing df has float coordinates and integer/float weight
    df = pd.DataFrame({
        'Produto': ["Soja"],
        'Cidade': ["Cidade Y"],
        'Latitude': [-15.5],
        'Longitude': [-47.5],
        'Data': ["2026-01"],
        'Peso (ton)': [100.0]
    })
    df = df.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
    })

    print("Existing df types:")
    print(df.dtypes)
    
    new_rows_df = pd.DataFrame(new_rows)
    print("New rows df before astype:")
    print(new_rows_df.head(2))
    
    new_rows_df = new_rows_df.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
    })
    
    print("New rows df after astype:")
    print(new_rows_df.dtypes)
    
    df = pd.concat([df, new_rows_df], ignore_index=True)
    print("Concatenated df:")
    print(df.head(5))
    
    json_data = df.to_json(date_format='iso', orient='split')
    print("JSON serialization successful!")

if __name__ == "__main__":
    run_test()
