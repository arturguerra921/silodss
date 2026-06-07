import pandas as pd
import io

def mock_parse(contents_decoded):
    try:
        # Simulate Conab CSV Parsing Rules:
        # 1. Encoding: iso-8859-1 (already decoded here for simulation)
        # 2. Separator: ;
        # 3. Skip Rows: 1 (Header is on line 2, index 1)
        # 4. Trailing Delimiter: Drop last column
        # 5. Disable automatic index: index_col=False

        # We assume contents_decoded is bytes here for decoding simulation
        # In the real app, we decode first. Here, let's assume it's already decoded string or handle bytes.

        decoded_str = contents_decoded.decode('iso-8859-1')

        df = pd.read_csv(
            io.StringIO(decoded_str),
            sep=';',
            encoding='iso-8859-1',
            skiprows=1,
            index_col=False  # Crucial for preventing index shift
        )

        # Drop the last column if it's completely empty (result of trailing delimiter)
        if not df.empty:
             # Check if the last column is completely null (standard behavior for trailing sep)
             if df.iloc[:, -1].isnull().all():
                 df = df.iloc[:, :-1]
             # Also handle "Unnamed" columns often created by pandas for trailing sep
             elif "Unnamed" in str(df.columns[-1]):
                 df = df.iloc[:, :-1]

        return df
    except Exception as e:
        print(f"Error: {e}")
        return None

# Test 1: Conab Format Simulation (Strict)
# Line 1: Metadata (Skip)
# Line 2: Header;With;Trailing;Semi;
# Line 3: Data1;Data2;Data3;Data4;
csv_content = """Metadata Row to Skip
CDA;Armazenador;Municipio;UF;
12345;Armazem A;Brasilia;DF;
""".encode('iso-8859-1')

df1 = mock_parse(csv_content)
assert df1 is not None
print("Columns:", df1.columns.tolist())
assert 'CDA' in df1.columns
assert 'UF' in df1.columns
# Verify alignment: CDA should be 12345, not index
assert df1.iloc[0]['CDA'] == 12345
# Verify trailing column dropped
assert 'Unnamed' not in str(df1.columns[-1])
assert len(df1.columns) == 4

print("Test 1 Passed")

# Test 2: Capacity Metric Logic
csv_content_cap = """Metadata
CDA;Armazenador;Capacidade (t);
1;A;1.000,50;
2;B;2000;
""".encode('iso-8859-1')

df2 = mock_parse(csv_content_cap)
print("Columns 2:", df2.columns.tolist())

capacity = 0
cap_col = next((c for c in df2.columns if 'cap' in str(c).lower() or 'ton' in str(c).lower()), None)
if cap_col:
    try:
        series_str = df2[cap_col].astype(str)
        series_clean = series_str.str.replace('.', '', regex=False).str.replace(',', '.', regex=False)
        capacity = pd.to_numeric(series_clean, errors='coerce').sum()
    except:
        capacity = 0

print(f"Calculated Capacity: {capacity}")
assert capacity == 3000.50
print("Test 2 Passed")
