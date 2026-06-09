import base64
import io
import os
import pandas as pd
from dash import Dash, dcc, html, Input, Output, State, dash_table, no_update
import dash
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME
from src.view.pages.distance_matrix import get_tab_distance_matrix_layout
from src.view.pages.model_config import get_tab_model_config_layout
from src.view.pages.costs import get_tab_costs_layout
from src.view.pages.results import get_tab_results_layout
from src.logic.osrm import OSRMClient
from src.logic.optimization import run_optimization_model
from src.logic.i18n import translate
from src.logic.utils import validate_and_parse_supply_data
import dash
import time
from dash import DiskcacheManager
import diskcache
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import requests

def parse_brazilian_number(val):
    if pd.isna(val):
        return 0
    val_str = str(val).strip()
    # Strip out any blank spaces (e.g., converting 1 000,00 to 1000,00)
    val_str = val_str.replace(' ', '')
    # If the string contains both '.' and ',', assume '.' is thousands and ',' is decimal
    if '.' in val_str and ',' in val_str:
        val_str = val_str.replace('.', '').replace(',', '.')
    # If it only contains ',', it might be a decimal separator
    elif ',' in val_str:
        val_str = val_str.replace(',', '.')
    # If it only contains '.', leave it alone (could be US format decimal)
    return pd.to_numeric(val_str, errors='coerce')

# --- Data Loading ---
try:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'data')
    MUNICIPIOS_PATH = os.path.join(DATA_DIR, 'municipios.csv')
    ESTADOS_PATH = os.path.join(DATA_DIR, 'estados.csv')
    BASE_ARMAZENS_CREDENCIADOS_PATH = os.path.join(DATA_DIR, 'Armazens_Credenciados_Habilitados_Base.csv')
    BASE_ARMAZENS_CADASTRADOS_PATH = os.path.join(DATA_DIR, 'Armazens_Cadastrados_Base.csv')
    BASE_ARMAZENS_PERSONALIZADOS_PATH = os.path.join(DATA_DIR, 'Armazens_Personalizados_Base.csv')
    STORAGE_COSTS_PATH = os.path.join(DATA_DIR, 'Tarifa_de_Armazenagem.csv')
    FREIGHT_COSTS_PATH = os.path.join(DATA_DIR, 'Valor_Tonelada_km.csv')

    df_municipalities = pd.read_csv(MUNICIPIOS_PATH, encoding='utf-8-sig')
    df_states = pd.read_csv(ESTADOS_PATH, encoding='utf-8-sig')

    # Merge to get UF
    df_merged = pd.merge(df_municipalities, df_states[['codigo_uf', 'uf']], on='codigo_uf', how='left')

    # Create "Cidade - UF" column
    df_merged['cidade_uf'] = df_merged['nome'] + ' - ' + df_merged['uf']

    # Create options for dropdown
    CITY_OPTIONS = sorted(df_merged['cidade_uf'].unique().tolist())

    # Create lookup dictionary
    # Drop duplicates to ensure unique keys (though City-UF should be unique for municipalities)
    df_unique = df_merged.drop_duplicates(subset=['cidade_uf'])
    CITY_LOOKUP = df_unique.set_index('cidade_uf')[['latitude', 'longitude']].to_dict('index')

except Exception as e:
    print(f"Error loading geographical data: {e}")
    CITY_OPTIONS = []
    CITY_LOOKUP = {}


def flex_read_csv(file_bytes, **kwargs):
    """
    Tries to read a CSV file explicitly testing delimiters and encodings.
    Uses bytes to avoid preliminary decode errors.
    """
    delimiters = [';', ',', '\t']
    encodings = ['utf-8-sig', 'utf-8', 'iso-8859-1', 'cp1252']

    last_error = None
    for sep in delimiters:
        for enc in encodings:
            try:
                # Reset file pointer for each attempt
                file_bytes.seek(0)

                # We skip pandas engine='python' separator inference because it fails on 1-column CSVs
                # using on_bad_lines='skip' to avoid throwing exception on a single malformed line
                df = pd.read_csv(file_bytes, sep=sep, encoding=enc, on_bad_lines='skip', **kwargs)

                # If the file is parsed as 1 single column, check if the entire column
                # seems to be unread CSV text (e.g., col_name = "A;B;C").
                if len(df.columns) == 1 and sep != delimiters[-1]:
                    col_name = str(df.columns[0])
                    other_delims = [d for d in delimiters if d != sep]
                    if any(d in col_name for d in other_delims):
                        # Likely wrong separator, continue trying
                        continue

                return df
            except Exception as e:
                last_error = e
                continue

    raise ValueError(f"Failed to read CSV with all combinations. Last error: {last_error}")


def get_conab_txt_data():
    """Fetches the Conab TXT file, saves it locally, and returns a DataFrame.
    If the fetch fails, it falls back to the locally saved version."""
    conab_url = "https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt"
    local_txt_path = os.path.join(DATA_DIR, 'Armazens_Cadastrados_SICARM.txt')

    try:
        response = requests.get(conab_url, timeout=15)
        response.raise_for_status()

        # Save to local file
        with open(local_txt_path, 'w', encoding='iso-8859-1') as f:
            f.write(response.content.decode('iso-8859-1'))

        df = pd.read_csv(io.StringIO(response.content.decode('iso-8859-1')), sep=';', encoding='iso-8859-1', dtype=str)
    except Exception as e:
        print(f"Error fetching Conab TXT file from URL: {e}. Falling back to local file.")
        if os.path.exists(local_txt_path):
            df = pd.read_csv(local_txt_path, sep=';', encoding='iso-8859-1', dtype=str)
        else:
            print("Local Conab TXT file not found. Returning empty DataFrame.")
            return pd.DataFrame()
    return df


# Initialize diskcache manager for background callbacks
cache = diskcache.Cache("./cache")
background_callback_manager = DiskcacheManager(cache)

# Initialize app with Bootstrap theme and suppress callback exceptions
app = Dash(
    __name__,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    background_callback_manager=background_callback_manager
)
app.title = "SiloDSS"
app.config.suppress_callback_exceptions = True

# --- Layout Components ---

# 1. Navbar / Header

def serve_layout(lang="pt", dropdown_base_warehouses_val="credenciados"):
    navbar = dbc.Navbar(
        dbc.Container(
            [
                html.A(
                    dbc.Row(
                        [
                            dbc.Col(html.Img(src="/assets/logo.png", height="48px"), className="me-3"),
                            dbc.Col(
                                [
                                    html.H5(translate("SiloDSS", lang), className="navbar-brand-text mb-0"),
                                    html.Small(translate("Otimização de Alocação de Produtos", lang), className="navbar-subtext", style={"whiteSpace": "nowrap"}),
                                    html.Br(),
                                    html.Small(translate("Universidade de Brasília", lang), className="navbar-subtext", style={"whiteSpace": "nowrap"})
                                ],
                            ),
                        ],
                        align="center",
                        className="g-0",
                    ),
                    href="#",
                    style={"textDecoration": "none"},
                ),
                html.Div(
                [
                    dbc.Button(
                        [html.I(className="bi bi-question-circle me-2"), translate("Ajuda", lang)],
                        id="btn-help-modal",
                        color="none", className="btn-light-custom fw-bold me-2",
                        size="md",
                        style={"borderRadius": "8px"}
                    ),
                    dbc.DropdownMenu(
                        label=translate("🌎 ", lang) + lang.upper(),
                        id="lang-dropdown",
                        children=[
                            dbc.DropdownMenuItem(translate("🇧🇷 PT", lang), id="lang-pt", n_clicks=0),
                            dbc.DropdownMenuItem(translate("🇺🇸 EN", lang), id="lang-en", n_clicks=0),
                        ],
                        color="none",
                        toggle_class_name="btn-light-custom fw-bold",
                        toggle_style={"borderRadius": "8px", "color": "#000"},
                    )
                ],
                className="d-flex ms-auto"
            )
            ],
            fluid=True,
            className="d-flex justify-content-between align-items-center"
        ),
        className="navbar-custom mb-32 py-3 shadow-sm"
    )

    # Help Modal
    help_modal = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle([html.I(className="bi bi-info-circle-fill me-2 text-info-custom"), translate("Guia de Uso do SiloDSS", lang)]), close_button=True),
            dbc.ModalBody(
                [
                    html.P(translate("Bem-vindo ao SiloDSS! Este aplicativo foi desenvolvido para otimizar a alocação de produtos em armazéns, minimizando os custos de frete e armazenagem. Siga o fluxo de 1 a 8 nas abas para obter os resultados da operação:", lang), className="mb-4 text-muted"),

                    dbc.ListGroup([
                        dbc.ListGroupItem([
                            html.H5([html.Span("1.", className="badge bg-info-custom rounded-pill me-2"), translate("Oferta", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Insira a série histórica de oferta por cidade (peso mensal ao longo dos anos). Defina o horizonte temporal e carregue uma planilha ou insira os dados manualmente escolhendo o padrão de preenchimento (valor constante ou crescimento linear). Utilize os filtros de produto e cidade com cross-filtering dinâmico para analisar a evolução mensal no gráfico e editar a tabela.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("2.", className="badge bg-info-custom rounded-pill me-2"), translate("Demanda", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Insira a demanda por cidade. O horizonte temporal é o mesmo definido na aba de Oferta. Os produtos disponíveis são os mesmos da Oferta. Você pode marcar uma cidade como Porto (demanda infinita) para representar exportação. A visualização gráfica permite analisar a evolução por produto e cidade. No modo 'Total Geral', a agregação por produto desconsidera os nós de demanda infinita para exibir a soma finita.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("3.", className="badge bg-info-custom rounded-pill me-2"), translate("Armazéns", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Gerencie os armazéns que receberão os produtos. Uma base padrão é carregada automaticamente, mas você pode visualizar e atualizar esta lista baixando dados mais recentes da Conab ou enviando uma planilha personalizada.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("4.", className="badge bg-info-custom rounded-pill me-2"), translate("Produto e Armazéns", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Defina a compatibilidade. Indique quais tipos de armazéns podem estocar cada tipo de produto marcando ou desmarcando as caixas na tabela.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("5.", className="badge bg-info-custom rounded-pill me-2"), translate("Custos", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Configure as tarifas de armazenamento (público e privado) para cada produto e o valor do frete (tonelada/km) para cada estado. Você pode usar os valores padrão ou inserir novos, e as alterações nas tabelas são salvas automaticamente.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("6.", className="badge bg-info-custom rounded-pill me-2"), translate("Matriz de Distâncias", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("O sistema calcula todas as rotas possíveis entre as cidades de origem e os armazéns disponíveis. Clique em 'Calcular Matriz de Distâncias' para iniciar e aguarde a conclusão. Em seguida, você também pode visualizar qualquer rota diretamente no mapa interativo abaixo da tabela.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("7.", className="badge bg-info-custom rounded-pill me-2"), translate("Configuração do Modelo", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Configure as restrições da operação (como limites de recepção, regras de frete e uso do Princípio de Pareto) e rode o modelo de otimização matemática.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("8.", className="badge bg-info-custom rounded-pill me-2"), translate("Resultados", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Visualize as métricas globais da operação, explore as rotas sugeridas no mapa interativo e baixe o relatório final completo (Excel).", lang), className="mb-0 text-muted")
                        ], className="border-0 py-3"),
                    ], flush=True),
                ]
            ),
            dbc.ModalFooter(
                dbc.Button(translate("Entendi, vamos começar!", lang), id="close-help-modal", color="none", className="btn-info-custom", n_clicks=0)
            ),
        ],
        id="modal-help",
        size="lg",
        is_open=False,
        centered=True,
        scrollable=True
    )

    # 2. Tabs
    tabs = dbc.Tabs(
        [
            dbc.Tab(label=translate("Oferta", lang), tab_id="tab-input", label_class_name="px-4"),
            dbc.Tab(label=translate("Demanda", lang), tab_id="tab-demand", label_class_name="px-4"),
            dbc.Tab(label=translate("Armazéns", lang), tab_id="tab-warehouses", label_class_name="px-4"),
            dbc.Tab(label=translate("Produto e Armazéns", lang), tab_id="tab-prod-warehouses", label_class_name="px-4"),
            dbc.Tab(label=translate("Custos", lang), tab_id="tab-costs", label_class_name="px-4"),
            dbc.Tab(label=translate("Matriz de Distâncias", lang), tab_id="tab-distance-matrix", label_class_name="px-4"),
            dbc.Tab(label=translate("Configuração do Modelo", lang), tab_id="tab-config", label_class_name="px-4"),
            dbc.Tab(label=translate("Resultados", lang), tab_id="tab-results", label_class_name="px-4"),
        ],
        id="main-tabs",
        active_tab="tab-input",
        className="mb-32"
    )

    # 3. Tab 1 Content (Input)
    def get_tab1_layout():
        # Timespan Card
        timespan_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Horizonte Temporal", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-timespan", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Defina os anos de início e fim da série histórica. Uma vez inseridos dados, este intervalo é bloqueado.", lang),
                            target="help-timespan",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(translate("Ano Inicial", lang), className="fw-bold small mb-1"),
                                dbc.Input(id="input-start-year", type="number", min=2000, max=2100, value=2026, className="mb-16")
                            ], width=6),
                            dbc.Col([
                                dbc.Label(translate("Ano Final", lang), className="fw-bold small mb-1"),
                                dbc.Input(id="input-end-year", type="number", min=2000, max=2100, value=2035, className="mb-16")
                            ], width=6),
                        ], className="g-2"),
                        html.Div(className="d-grid", children=[
                            dbc.Button(translate("Limpar Base / Iniciar Nova", lang),
                                id='btn-clear-dataset',
                                color="none", className="btn-danger-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Upload Card
        upload_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Carregar Arquivo", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-upload", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Caso já possua uma planilha pronta (Excel .xlsx ou CSV), carregue-a aqui. Se não tiver, você pode adicionar dados manualmente abaixo.", lang),
                            target="help-upload",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dcc.Upload(
                            id='upload-data',
                            children=html.Div([
                                html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                                html.Span(translate('Arraste e solte ou ', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                                html.A(translate('Selecione', lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                html.Div(translate("Formatos: .xlsx, .csv", lang), className="text-muted small mt-2")
                            ]),
                            className="upload-box",
                            multiple=False,
                            accept='.xlsx, .csv'
                        )
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Add Data Card
        add_data_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Adicionar Dados", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-add", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Inserção manual de dados. Cada inserção será adicionada como uma nova linha na tabela ao lado.", lang),
                            target="help-add",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        html.P(translate("Adicione uma nova linha à planilha carregada.", lang), className="text-muted small mb-16"),
                        dbc.Row([
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Produto", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-product", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Nome do produto (ex: Soja, Milho). O sistema ajustará maiúsculas/minúsculas automaticamente e sugerirá produtos já cadastrados.", lang),
                                            target="help-product",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-product", type="text", placeholder=translate("Ex: Arroz", lang), list="list-suggested-products", className="mb-16"),
                                    html.Datalist(id="list-suggested-products", children=[])
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Base Peso (ton)", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-weight", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Peso inicial para preenchimento da série histórica.", lang),
                                            target="help-weight",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-weight", type="number", placeholder=translate("Ex: 100", lang), className="mb-16")
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Cidade", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-city", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Selecione a cidade de origem/destino. Digite para filtrar as opções.", lang),
                                            target="help-city",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dcc.Dropdown(
                                        id="input-city",
                                        options=[],
                                        placeholder=translate("Selecione a cidade...", lang),
                                        className="mb-16",
                                        searchable=True
                                    )
                                ],
                                width=12
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Latitude", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-lat", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Coordenada de latitude. Preenchida automaticamente ao selecionar a cidade.", lang),
                                            target="help-lat",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-lat", type="number", placeholder=translate("Lat", lang), className="mb-16", disabled=True)
                                ],
                                width=5
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Longitude", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-lon", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Coordenada de longitude. Preenchida automaticamente ao selecionar a cidade.", lang),
                                            target="help-lon",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-lon", type="number", placeholder=translate("Lon", lang), className="mb-16", disabled=True)
                                ],
                                width=5
                            ),
                            dbc.Col(
                                [
                                    dbc.Button("🔒", id="btn-manual-edit", color="none", className="btn-secondary-custom d-flex align-items-center justify-content-center w-100 mb-16", style={"height": "38px"}, n_clicks=0, title=translate("Editar Lat/Long manualmente", lang))
                                ],
                                width=2,
                                className="d-flex align-items-end"
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Padrão de Preenchimento", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-pattern", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Escolha como preencher a série histórica.", lang),
                                            target="help-pattern",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dcc.Dropdown(
                                        id="input-pattern",
                                        options=[
                                            {"label": translate("Valor Constante", lang), "value": "constant"},
                                            {"label": translate("Crescimento/Declínio Linear", lang), "value": "linear"}
                                        ],
                                        value="constant",
                                        clearable=False,
                                        className="mb-16"
                                    )
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Taxa Mensal (%)", lang), id="label-growth-rate", className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-growth-rate", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Taxa percentual de crescimento ou declínio a cada mês.", lang),
                                            target="help-growth-rate",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-growth-rate", type="number", placeholder="Ex: 0.5", step=0.01, disabled=True, className="mb-16")
                                ],
                                width=6
                            ),
                        ]),
                        html.Div(className="d-grid", children=[
                            dbc.Button(translate("Adicionar Linha", lang),
                                id='btn-add-row',
                                color="none", className="btn-primary-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Download Card
        download_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Exportar", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-export", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Salvar a planilha para usos futuros. Não é necessário exportar para continuar usando as funcionalidades nesta sessão.", lang),
                            target="help-export",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        html.P(translate("Baixe a planilha com os novos dados adicionados.", lang), className="text-muted small mb-16"),
                         html.Div(className="d-grid", children=[
                            dbc.Button(translate("Baixar Planilha (.xlsx)", lang),
                                id='btn-download',
                                n_clicks=0,
                                color="none", className="btn-success-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )


        # Data Table Card
        # Initial Empty DataFrame
        initial_df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])

        # Metrics Section
        metrics_section = dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-box-seam-fill fs-1 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Total Peso (ton)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-total-weight", children="0.00", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']}, **{"data-raw-value": "0"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-tags-fill fs-1 me-3", style={"color": UNB_THEME['UNB_GREEN']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Produtos Diferentes", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-unique-products", children="0", className="mb-0", style={"color": UNB_THEME['UNB_GREEN']}, **{"data-raw-value": "0"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
            ],
            className="mt-auto pt-3 g-3" # Push to bottom
        )

        data_table_card = dbc.Card(
            [
                dbc.CardHeader(translate("Visualização dos Dados", lang),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Row([
                            dbc.Col([
                                html.Label(translate("Filtro por Produto", lang), className="fw-bold small mb-1"),
                                dcc.Dropdown(id='filter-product', placeholder=translate("Todos", lang), clearable=True)
                            ], width=6, className="mb-16"),
                            dbc.Col([
                                html.Label(translate("Filtro por Cidade", lang), className="fw-bold small mb-1"),
                                dcc.Dropdown(id='filter-city', placeholder=translate("Todas", lang), clearable=True)
                            ], width=6, className="mb-16"),
                        ], className="g-3 mb-16"),
                        html.Div(id='chart-container', children=[
                            dcc.Graph(id='supply-chart', className="mb-24", style={"borderRadius": "8px", "border": f"1px solid {UNB_THEME['BORDER_LIGHT']}"})
                        ]),
                        dbc.Spinner(
                            html.Div(id='table-container', children=[
                                dash_table.DataTable(
                                    id='editable-table',
                                    data=initial_df.to_dict('records'), # Initially empty
                                    columns=[{'name': translate(i, lang), 'id': i, 'deletable': False, 'renamable': False} for i in initial_df.columns],
                                    editable=True,
                                    row_deletable=True,
                                    page_size=10,
                                    style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                    style_cell={
                                        'textAlign': 'left',
                                        'fontFamily': "'Roboto', sans-serif",
                                        'padding': '12px',
                                        'fontSize': 'var(--font-size-small)',
                                        'color': UNB_THEME['UNB_GRAY_DARK']
                                    },
                                    style_header={
                                        'backgroundColor': '#F8F9FA', # Standard light gray header background
                                        'color': UNB_THEME['UNB_BLUE'],
                                        'fontWeight': 'bold',
                                        'border': 'none',
                                        'padding': '12px',
                                        'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}"
                                    },
                                    style_data={
                                        'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}"
                                    },
                                    style_data_conditional=[
                                        {
                                            'if': {'row_index': 'odd'},
                                            'backgroundColor': '#f8f9fa'
                                        }
                                    ]
                                )
                            ], className="h-100"),
                            spinner_class_name="text-primary-custom"
                        ),
                        metrics_section
                    ],
                    className="card-body-custom d-flex flex-column"
                ),
            ],
            className="card-custom h-100",
            style={"minHeight": "600px"} # Increased min-height to ensure space
        )

        # Confirm Clear Dataset Modal
        confirm_clear_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Confirmar Limpeza", lang)), id="confirm-clear-header-title"),
                dbc.ModalBody(translate("Aviso: Se o progresso não for salvo ele será perdido. Recomendamos baixar os dados antes de limpar a base.", lang)),
                dbc.ModalFooter([
                    dbc.Button(translate("Cancelar", lang), id="btn-cancel-clear", className="me-2 btn-secondary-custom", color="secondary", n_clicks=0),
                    dbc.Button(translate("Limpar Base", lang), id="btn-confirm-clear", className="btn-danger-custom", color="danger", n_clicks=0)
                ]),
            ],
            id="confirm-clear-modal",
            is_open=False,
        )

        return html.Div([
            dbc.Row(
                [
                    dbc.Col([
                        dbc.Row([
                            dbc.Col(timespan_card, width=12, className="mb-24"),
                            dbc.Col(upload_card, width=12, className="mb-24"),
                            dbc.Col(add_data_card, width=12, className="mb-24"),
                            dbc.Col(download_card, width=12, className="mb-24")
                        ])
                    ], width=12, lg=3),

                    dbc.Col(data_table_card, width=12, lg=9, className="mb-24"),
                ]
            ),
            confirm_clear_modal
        ])


    def get_tab_demand_layout():
        # Timespan Card (Read-only, matches Supply)
        timespan_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Horizonte Temporal", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-timespan", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("O horizonte temporal é herdado da aba de Oferta e não pode ser editado aqui.", lang),
                            target="demand-help-timespan",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Row([
                            dbc.Col([
                                dbc.Label(translate("Ano Inicial", lang), className="fw-bold small mb-1"),
                                dbc.Input(id="demand-input-start-year", type="number", min=2000, max=2100, value=2026, disabled=True, className="mb-16")
                            ], width=6),
                            dbc.Col([
                                dbc.Label(translate("Ano Final", lang), className="fw-bold small mb-1"),
                                dbc.Input(id="demand-input-end-year", type="number", min=2000, max=2100, value=2035, disabled=True, className="mb-16")
                            ], width=6),
                        ], className="g-2"),
                        html.Div(className="d-grid", children=[
                            dbc.Button(translate("Limpar Demanda / Iniciar Nova", lang),
                                id='btn-clear-demand-dataset',
                                color="none", className="btn-danger-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Upload Card
        upload_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Carregar Arquivo", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-upload", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Caso já possua uma planilha pronta (Excel .xlsx ou CSV), carregue-a aqui. Se não tiver, você pode adicionar dados manualmente abaixo.", lang),
                            target="demand-help-upload",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dcc.Upload(
                            id='upload-demand-data',
                            children=html.Div([
                                html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                                html.Span(translate('Arraste e solte ou ', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                                html.A(translate('Selecione', lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                html.Div(translate("Formatos: .xlsx, .csv", lang), className="text-muted small mt-2")
                            ]),
                            className="upload-box",
                            multiple=False,
                            accept='.xlsx, .csv'
                        )
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Add Data Card
        add_data_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Adicionar Dados", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-add", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Inserção manual de dados. Cada inserção será adicionada como uma nova linha na tabela ao lado.", lang),
                            target="demand-help-add",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        html.P(translate("Adicione uma nova linha à planilha carregada.", lang), className="text-muted small mb-16"),
                        dbc.Row([
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Produto", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-product", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Nome do produto. Apenas produtos presentes na aba de Oferta podem ser selecionados.", lang),
                                            target="demand-help-product",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dcc.Dropdown(
                                        id="demand-input-product",
                                        options=[],
                                        placeholder=translate("Selecione o produto...", lang),
                                        className="mb-16",
                                        searchable=True
                                    )
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Base Peso (ton)", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-weight", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Peso inicial para preenchimento da série histórica. Deixe vazio para demanda infinita.", lang),
                                            target="demand-help-weight",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="demand-input-weight", type="number", placeholder=translate("Ex: 100", lang), className="mb-8"),
                                    dbc.Checkbox(id="demand-toggle-infinite", label=translate("Demanda Infinita", lang), value=False, className="small text-muted")
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Cidade", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-city", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Selecione a cidade de origem/destino. Digite para filtrar as opções.", lang),
                                            target="demand-help-city",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dcc.Dropdown(
                                        id="demand-input-city",
                                        options=[],
                                        placeholder=translate("Selecione a cidade...", lang),
                                        className="mb-16",
                                        searchable=True
                                    )
                                ],
                                width=12
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Latitude", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-lat", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Coordenada de latitude. Preenchida automaticamente ao selecionar a cidade.", lang),
                                            target="demand-help-lat",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="demand-input-lat", type="number", placeholder=translate("Lat", lang), className="mb-16", disabled=True)
                                ],
                                width=5
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Longitude", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-lon", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Coordenada de longitude. Preenchida automaticamente ao selecionar a cidade.", lang),
                                            target="demand-help-lon",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="demand-input-lon", type="number", placeholder=translate("Lon", lang), className="mb-16", disabled=True)
                                ],
                                width=5
                            ),
                            dbc.Col(
                                [
                                    dbc.Button("🔒", id="btn-demand-manual-edit", color="none", className="btn-secondary-custom d-flex align-items-center justify-content-center w-100 mb-16", style={"height": "38px"}, n_clicks=0, title=translate("Editar Lat/Long manualmente", lang))
                                ],
                                width=2,
                                className="d-flex align-items-end"
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Padrão de Preenchimento", lang), className="fw-bold small me-2 mb-0"),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-pattern", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Escolha como preencher a série histórica.", lang),
                                            target="demand-help-pattern",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dcc.Dropdown(
                                        id="demand-input-pattern",
                                        options=[
                                            {"label": translate("Valor Constante", lang), "value": "constant"},
                                            {"label": translate("Crescimento/Declínio Linear", lang), "value": "linear"}
                                        ],
                                        value="constant",
                                        clearable=False,
                                        className="mb-16"
                                    )
                                ],
                                width=6
                            ),
                            dbc.Col(
                                [
                                    html.Div([
                                        dbc.Label(translate("Taxa Mensal (%)", lang), id="demand-label-growth-rate", className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-growth-rate", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Taxa percentual de crescimento ou declínio a cada mês.", lang),
                                            target="demand-help-growth-rate",
                                        ),
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="demand-input-growth-rate", type="number", placeholder="Ex: 0.5", step=0.01, disabled=True, className="mb-16")
                                ],
                                width=6
                            ),
                        ]),
                        html.Div(className="d-grid", children=[
                            dbc.Button(translate("Adicionar Linha", lang),
                                id='btn-demand-add-row',
                                color="none", className="btn-primary-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Download Card
        download_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Exportar", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-export", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Salvar a planilha para usos futuros. Não é necessário exportar para continuar usando as funcionalidades nesta sessão.", lang),
                            target="demand-help-export",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        html.P(translate("Baixe a planilha com os novos dados adicionados.", lang), className="text-muted small mb-16"),
                        html.Div(className="d-grid", children=[
                            dbc.Button(translate("Baixar Planilha (.xlsx)", lang),
                                id='btn-demand-download',
                                n_clicks=0,
                                color="none", className="btn-success-custom"
                            ),
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Metrics Section
        metrics_section = dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-box-seam-fill fs-1 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Total Demanda (ton)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="demand-metric-total-weight", children="0.00", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']}, **{"data-raw-value": "0"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-tags-fill fs-1 me-3", style={"color": UNB_THEME['UNB_GREEN']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Produtos Diferentes", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="demand-metric-unique-products", children="0", className="mb-0", style={"color": UNB_THEME['UNB_GREEN']}, **{"data-raw-value": "0"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
            ],
            className="mt-auto pt-3 g-3"
        )

        initial_df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])

        data_table_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Visualização dos Dados", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="demand-help-viz", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Utilize os filtros para segmentar por produto ou cidade. No modo 'Total Geral' (sem filtros), a agregação desconsidera nós com demanda infinita (∞). Produtos com demanda infinita são representados com estrelas (★) amarelas próximas ao topo do gráfico.", lang),
                            target="demand-help-viz",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Row([
                            dbc.Col([
                                html.Label(translate("Filtro por Produto", lang), className="fw-bold small mb-1"),
                                dcc.Dropdown(id='demand-filter-product', placeholder=translate("Todos", lang), clearable=True)
                            ], width=6, className="mb-16"),
                            dbc.Col([
                                html.Label(translate("Filtro por Cidade", lang), className="fw-bold small mb-1"),
                                dcc.Dropdown(id='demand-filter-city', placeholder=translate("Todas", lang), clearable=True)
                            ], width=6, className="mb-16"),
                        ], className="g-3 mb-16"),
                        html.Div(id='demand-chart-container', children=[
                            dcc.Graph(id='demand-chart', className="mb-24", style={"borderRadius": "8px", "border": f"1px solid {UNB_THEME['BORDER_LIGHT']}"})
                        ]),
                        dbc.Spinner(
                             html.Div(id='demand-table-container', children=[
                                 dash_table.DataTable(
                                     id='demand-editable-table',
                                     data=initial_df.to_dict('records'),
                                     columns=[{'name': translate(i, lang), 'id': i, 'deletable': False, 'renamable': False} for i in initial_df.columns],
                                     editable=True,
                                     row_deletable=True,
                                     page_size=10,
                                     style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                     style_cell={
                                         'textAlign': 'left',
                                         'fontFamily': "'Roboto', sans-serif",
                                         'padding': '12px',
                                         'fontSize': 'var(--font-size-small)',
                                         'color': UNB_THEME['UNB_GRAY_DARK']
                                     },
                                     style_header={
                                         'backgroundColor': '#F8F9FA',
                                         'color': UNB_THEME['UNB_BLUE'],
                                         'fontWeight': 'bold',
                                         'border': 'none',
                                         'padding': '12px',
                                         'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}"
                                     },
                                     style_data={
                                         'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}"
                                     },
                                     style_data_conditional=[
                                         {
                                             'if': {'row_index': 'odd'},
                                             'backgroundColor': '#f8f9fa'
                                         }
                                     ]
                                 )
                             ], className="h-100"),
                             spinner_class_name="text-primary-custom"
                        ),
                        metrics_section
                    ],
                    className="card-body-custom d-flex flex-column"
                ),
            ],
            className="card-custom h-100",
            style={"minHeight": "600px"}
        )

        confirm_clear_demand_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Confirmar Limpeza da Demanda", lang)), id="confirm-clear-demand-header-title"),
                dbc.ModalBody(translate("Aviso: Se o progresso da demanda não for salvo ele será perdido. Recomendamos baixar os dados antes de limpar.", lang)),
                dbc.ModalFooter([
                    dbc.Button(translate("Cancelar", lang), id="btn-cancel-clear-demand", className="me-2 btn-secondary-custom", color="secondary", n_clicks=0),
                    dbc.Button(translate("Limpar Demanda", lang), id="btn-confirm-clear-demand", className="btn-danger-custom", color="danger", n_clicks=0)
                ]),
            ],
            id="confirm-clear-demand-modal",
            is_open=False,
        )

        # Modal to redirect if no supply data exists
        missing_demand_data_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Atenção", lang))),
                dbc.ModalBody(translate("Você precisa preencher a aba 'Oferta' antes de acessar a aba 'Demanda'.", lang)),
                dbc.ModalFooter(
                    dbc.Button(translate("Entendi", lang), id="btn-confirm-missing-demand", className="btn-primary-custom ms-auto", n_clicks=0)
                ),
            ],
            id="modal-missing-demand-data",
            is_open=False,
            backdrop="static",
            keyboard=False
        )

        return html.Div([
            dbc.Row(
                [
                    dbc.Col([
                        dbc.Row([
                            dbc.Col(timespan_card, width=12, className="mb-24"),
                            dbc.Col(upload_card, width=12, className="mb-24"),
                            dbc.Col(add_data_card, width=12, className="mb-24"),
                            dbc.Col(download_card, width=12, className="mb-24")
                        ])
                    ], width=12, lg=3),

                    dbc.Col(data_table_card, width=12, lg=9, className="mb-24"),
                ]
            ),
            confirm_clear_demand_modal,
            missing_demand_data_modal
        ])

    # 4. Tab Warehouses Content
    def get_tab_warehouses_layout(dropdown_base_warehouses_val="credenciados"):
        # Card 1: Select Base
        card_select_base = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Selecionar Base", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-select-base", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Selecione qual base de armazéns deseja utilizar para o modelo de otimização.", lang),
                            target="help-select-base",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dcc.Dropdown(
                            id="dropdown-base-warehouses",
                            options=[
                                {"label": translate("Armazéns Credenciados (Conab)", lang), "value": "credenciados"},
                                {"label": translate("Armazéns Cadastrados (SICARM)", lang), "value": "cadastrados"},
                                {"label": translate("Base Personalizada (Envio do usuário)", lang), "value": "personalizada"}
                            ],
                            value=dropdown_base_warehouses_val,
                            clearable=False,
                            className="mb-0"
                        )
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom mb-24"
        )

        # Card 2: Update and Save
        card_update_save = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Gerenciar Base", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-manage-base", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Essa função guardará a nova versão que será enviada para os futuros usos do aplicativo, substituindo a base que hoje é carregada automaticamente.", lang),
                            target="help-manage-base",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Button(translate("Atualizar a Base", lang), id="btn-update-base", color="none", className="btn-primary-custom w-100 mb-2"),
                        # Manage Container (Initially Hidden, dynamic content)
                        html.Div(
                            id="manage-base-container",
                            children=[
                                # Upload Component
                                html.Div(
                                    id="upload-update-container",
                                    children=[
                                        dcc.Upload(
                                            id='upload-update-base',
                                            children=html.Div([
                                                html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                                                html.Span(translate('Arraste e solte ou ', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                                                html.A(translate('Selecione', lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                                html.Div(translate("Formatos: .csv", lang), id="upload-format-hint", className="text-muted small mt-2")
                                            ]),
                                            className="upload-box",
                                            multiple=False,
                                            accept='.csv'
                                        )
                                    ],
                                    style={"display": "block"}
                                ),
                                # Download Example Button (for Personalizada)
                                html.Div(
                                    id="download-example-container",
                                    children=[
                                        dbc.Button(translate("Baixar Planilha Exemplo (.xlsx)", lang), id="btn-download-example", key=f"btn-dl-ex-{lang}", n_clicks=0, color="none", className="btn-outline-secondary-custom w-100 mt-2")
                                    ],
                                    style={"display": "none"}
                                ),
                                # Fetch Button (for Cadastrados)
                                html.Div(
                                    id="fetch-registered-container",
                                    children=[
                                        dbc.Button(translate("Baixar Dados da Conab", lang), id="btn-fetch-registered", key=f"btn-fetch-reg-{lang}", color="none", className="btn-primary-custom w-100 mt-2")
                                    ],
                                    style={"display": "none"}
                                )
                            ],
                            style={"display": "none"}
                        ),

                        # Save to base (Initially Hidden)
                        dbc.Button(translate("Salvar na Base", lang), id="btn-save-base", color="none", className="btn-success-custom w-100 mt-4", style={"display": "none"}),
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100"
        )

        # Metrics Section for Armazéns
        warehouses_metrics_section = dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-building-fill fs-1 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Unidades Armazenadoras", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-warehouses-count", children="0", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-bank2 fs-1 me-3", style={"color": "#FFC107"}), # Warning/Yellow color
                                        html.Div(
                                            [
                                                html.H6(translate("Unidades Armazenadoras Públicas", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-warehouses-public", children="0", className="mb-0", style={"color": "#FFC107"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-buildings-fill fs-1 me-3", style={"color": "#6C757D"}), # Secondary/Gray color
                                        html.Div(
                                            [
                                                html.H6(translate("Unidades Armazenadoras Privadas", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-warehouses-private", children="0", className="mb-0", style={"color": "#6C757D"})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
                dbc.Col(
                    dbc.Card(
                        dbc.CardBody(
                            [
                                html.Div(
                                    [
                                        html.I(className="bi bi-box-seam-fill fs-1 me-3", style={"color": UNB_THEME['UNB_GREEN']}),
                                        html.Div(
                                            [
                                                html.H6(translate("Capacidade Estática (t)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                                html.H3(id="metric-warehouses-capacity", children="0.00", className="mb-0", style={"color": UNB_THEME['UNB_GREEN']})
                                            ]
                                        )
                                    ],
                                    className="d-flex align-items-center justify-content-center py-2"
                                )
                            ],
                            className="p-3"
                        ),
                        className="shadow-sm border-0 h-100",
                        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                    ),
                    width=6
                ),
            ],
            className="mt-auto pt-3 g-3"
        )

        # Warehouses Table Card
        warehouses_table_card = dbc.Card(
            [
                dbc.CardHeader(translate("Tabela de Armazéns", lang),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                         dbc.Spinner(
                            html.Div(id='table-warehouses-container', children=[
                                dash_table.DataTable(
                                    id='table-warehouses',
                                    data=[],
                                    columns=[],
                                    editable=True,
                                    row_deletable=False,
                                    filter_action='native',
                                    page_size=10,
                                    style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                    style_cell={
                                        'textAlign': 'left',
                                        'fontFamily': "'Roboto', sans-serif",
                                        'padding': '12px',
                                        'fontSize': 'var(--font-size-small)',
                                        'color': UNB_THEME['UNB_GRAY_DARK']
                                    },
                                    style_header={
                                        'backgroundColor': '#F8F9FA',
                                        'color': UNB_THEME['UNB_BLUE'],
                                        'fontWeight': 'bold',
                                        'border': 'none',
                                        'padding': '12px',
                                        'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}"
                                    },
                                    style_data={
                                        'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}"
                                    },
                                    style_data_conditional=[
                                        {
                                            'if': {'row_index': 'odd'},
                                            'backgroundColor': '#f8f9fa'
                                        }
                                    ]
                                )
                            ], className="h-100"),
                            spinner_class_name="text-primary-custom"
                        ),
                        warehouses_metrics_section
                    ],
                    className="card-body-custom d-flex flex-column"
                ),
            ],
            className="card-custom h-100",
            style={"minHeight": "600px"}
        )

        # Modals
        tutorial_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(id="modal-tutorial-title"), close_button=True),
                dbc.ModalBody(id="modal-tutorial-body"),
                dbc.ModalFooter(
                    dbc.Button(translate("Entendi", lang), id="close-modal-tutorial", className="btn-primary-custom ms-auto", n_clicks=0)
                ),
            ],
            id="modal-tutorial",
            size="lg",
            is_open=False,
        )

        confirm_save_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Confirmar Salvamento", lang)), close_button=True),
                dbc.ModalBody(translate("Atenção: Esta ação irá sobrescrever a base de dados original de forma irreversível. A nova base enviada será utilizada para todos os futuros usos do aplicativo. Tem certeza que deseja continuar?", lang)),
                dbc.ModalFooter(
                    [
                        dbc.Button(translate("Cancelar", lang), id="cancel-save", color="none", className="btn-secondary-custom me-2", n_clicks=0),
                        dbc.Button(translate("Confirmar e Salvar", lang), id="confirm-save", color="none", className="btn-danger-custom", n_clicks=0),
                    ]
                ),
            ],
            id="modal-confirm-save",
            is_open=False,
        )

        missing_cdas_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Atenção: Capacidade de Recepção Não Encontrada", lang)), close_button=True),
                dbc.ModalBody(id="modal-missing-cdas-body", children=""),
                dbc.ModalFooter(
                    dbc.Button(translate("Fechar", lang), id="close-missing-cdas", className="btn-primary-custom ms-auto", n_clicks=0)
                ),
            ],
            id="modal-missing-cdas",
            is_open=False,
        )

        slowness_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Aviso de Desempenho", lang)), close_button=True),
                dbc.ModalBody(translate("Esta base possui mais de 1000 armazéns e isso pode causar lentidões na sua utilização.", lang)),
                dbc.ModalFooter(
                    dbc.Button(translate("Entendi", lang), id="close-slowness-modal", className="btn-primary-custom ms-auto", n_clicks=0)
                ),
            ],
            id="modal-slowness-warehouses",
            is_open=False,
        )

        return html.Div([
            dbc.Row(
                [
                    dbc.Col([
                        card_select_base,
                        html.Div(card_update_save, className="flex-grow-1 h-100")
                    ], width=12, lg=3, className="mb-24 d-flex flex-column h-100"),
                    dbc.Col(warehouses_table_card, width=12, lg=9, className="mb-24"),
                ]
            ),
            tutorial_modal,
            confirm_save_modal,
            missing_cdas_modal,
            slowness_modal
        ])

    # 5. Tab Product and Warehouses Content
    def get_tab_prod_warehouses_layout():
        # Table Card
        table_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Relação Produto x Tipo de Armazém", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-prod-warehouses", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Selecione quais tipos de armazém podem armazenar cada produto. Clique na célula para marcar (☑) ou desmarcar (☐).", lang),
                            target="help-prod-warehouses",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Spinner(
                            html.Div(id='table-prod-armazens-container', children=[
                                dash_table.DataTable(
                                    id='table-prod-armazens',
                                    data=[],
                                    columns=[{'name': translate('Produto', lang), 'id': 'Produto'}], # Initial column
                                    editable=False, # We handle clicks via active_cell
                                    row_deletable=False,
                                    page_size=15,
                                    style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                    style_cell={
                                        'textAlign': 'center',
                                        'fontFamily': "'Roboto', sans-serif",
                                        'padding': '12px',
                                        'fontSize': 'var(--font-size-small)',
                                        'color': UNB_THEME['UNB_GRAY_DARK']
                                    },
                                    style_cell_conditional=[
                                        {
                                            'if': {'column_id': 'Produto'},
                                            'textAlign': 'left',
                                            'fontWeight': 'bold'
                                        }
                                    ],
                                    style_header={
                                        'backgroundColor': '#F8F9FA',
                                        'color': UNB_THEME['UNB_BLUE'],
                                        'fontWeight': 'bold',
                                        'border': 'none',
                                        'padding': '12px',
                                        'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}",
                                        'textAlign': 'center'
                                    },
                                    style_data={
                                        'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}",
                                        'cursor': 'pointer',
                                        'fontSize': '1.5rem', # Checkbox size
                                    },
                                    style_data_conditional=[
                                        {
                                            'if': {'row_index': 'odd'},
                                            'backgroundColor': '#f8f9fa'
                                        },
                                        {
                                            'if': {'column_id': 'Produto'},
                                            'fontSize': 'var(--font-size-small)' # Product name size
                                        }
                                    ]
                                )
                            ], className="h-100"),
                            spinner_class_name="text-primary-custom"
                        ),
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom h-100",
            style={"minHeight": "600px"}
        )

        # Missing Data Modal
        missing_data_modal = dbc.Modal(
            [
                dbc.ModalHeader(dbc.ModalTitle(translate("Atenção", lang)), close_button=False),
                dbc.ModalBody(id="modal-missing-data-body", children=translate("Faltam dados.", lang)),
                dbc.ModalFooter(
                    dbc.Button(translate("Confirmar", lang), id="btn-confirm-missing-data", color="none", className="btn-primary-custom ms-auto", n_clicks=0)
                ),
            ],
            id="modal-missing-data",
            is_open=False,
            backdrop="static", # Prevent closing by clicking outside
            keyboard=False
        )

        return html.Div([
            dbc.Row(
                [
                    dbc.Col(table_card, width=12, className="mb-24"),
                ]
            ),
            missing_data_modal
        ])


    # Error Modal (Global)
    error_modal = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(translate("Atenção", lang)), close_button=True),
            dbc.ModalBody(id="modal-body-content", children="Ocorreu um erro."),
            dbc.ModalFooter(
                dbc.Button(translate("Fechar", lang), id="close-modal", className="btn-primary-custom ms-auto", n_clicks=0)
            ),
        ],
        id="error-modal",
        is_open=False,
    )

    # --- App Layout Assembly ---

    # Pre-render all tab layouts to ensure IDs exist for callbacks
    tab1_layout = get_tab1_layout()
    tab_demand_layout = get_tab_demand_layout()
    tab2_layout = get_tab_warehouses_layout(dropdown_base_warehouses_val)
    tab_prod_warehouses_layout = get_tab_prod_warehouses_layout()
    tab_costs_layout = get_tab_costs_layout(lang)
    tab_distance_matrix_layout = get_tab_distance_matrix_layout(lang)
    tab_config_layout = get_tab_model_config_layout(lang)
    tab_results_layout = get_tab_results_layout(lang)

    content_container = html.Div(
        [
            html.Div(id="tab-input-container", children=tab1_layout, style={"display": "block"}),
            html.Div(id="tab-demand-container", children=tab_demand_layout, style={"display": "none"}),
            html.Div(id="tab-warehouses-container", children=tab2_layout, style={"display": "none"}),
            html.Div(id="tab-prod-warehouses-container", children=tab_prod_warehouses_layout, style={"display": "none"}),
            html.Div(id="tab-costs-container", children=tab_costs_layout, style={"display": "none"}),
            html.Div(id="tab-distance-matrix-container", children=tab_distance_matrix_layout, style={"display": "none"}),
            html.Div(id="tab-config-container", children=tab_config_layout, style={"display": "none"}),
            html.Div(id="tab-results-container", children=tab_results_layout, style={"display": "none"}),
        ],
        id="tabs-content"
    )

    initial_store_df = pd.DataFrame(columns=['Produto', 'Cidade', 'Latitude', 'Longitude', 'Data', 'Peso (ton)'])

    return html.Div(
        [
            dcc.Store(id='stored-data', data=initial_store_df.to_json(date_format='iso', orient='split')),
            dcc.Store(id='stored-demand-data', data=initial_store_df.to_json(date_format='iso', orient='split')),
            dcc.Store(id='metrics-store', data={'weight': 0, 'count': 0}),
            dcc.Store(id='demand-metrics-store', data={'weight': 0, 'count': 0}),
            dcc.Store(id='store-warehouses'),
            dcc.Store(id='store-prod-warehouses'),
            dcc.Store(id='store-costs-storage'),
            dcc.Store(id='store-costs-freight'),
            dcc.Store(id='store-distance-matrix'),
            dcc.Store(id='store-model-results'),
            dcc.Store(id='store-model-log'),
            dcc.Store(id='store-help-seen', storage_type='local'),

            navbar,
            dbc.Container(
                [
                    tabs,
                    content_container,

                    error_modal,
                    help_modal
                ],
                fluid=True,
                className="px-4 pb-48"
            )
        ],
        style={
            'backgroundColor': UNB_THEME['APP_BACKGROUND'],
            'minHeight': '100vh'
        }
    )




initial_df = pd.DataFrame(columns=['Produto', 'Cidade', 'Latitude', 'Longitude', 'Data', 'Peso (ton)'])

app.layout = html.Div([
    dcc.Store(id='store-lang', storage_type='memory', data='pt'),
    dcc.Store(id='store-pending-lang', storage_type='memory', data=None),

    # Static Download Components (Prevents auto-download bug on language switch)
    dcc.Download(id='download-example-personalizada'),
    dcc.Download(id='download-dataframe-xlsx'),
    dcc.Download(id='download-demand-xlsx'),
    dcc.Download(id='download-storage-csv'),
    dcc.Download(id='download-freight-csv'),
    dcc.Download(id='download-matrix-xlsx'),
    dcc.Download(id='download-model-log'),
    dcc.Download(id='download-results-xlsx'),

    dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(id="modal-lang-switch-title"), close_button=True),
            dbc.ModalBody(id="modal-lang-switch-body"),
            dbc.ModalFooter([
                dbc.Button(id="btn-cancel-lang-switch", color="none", className="btn-secondary-custom me-2", n_clicks=0),
                dbc.Button(id="btn-confirm-lang-switch", color="none", className="btn-danger-custom", n_clicks=0),
            ]),
        ],
        id="modal-confirm-lang-switch",
        is_open=False,
    ),

    html.Div(id='page-content', children=serve_layout('pt'))
])


# --- Callbacks ---

@app.callback(
    [Output('store-lang', 'data'),
     Output('modal-confirm-lang-switch', 'is_open'),
     Output('modal-lang-switch-title', 'children'),
     Output('modal-lang-switch-body', 'children'),
     Output('btn-cancel-lang-switch', 'children'),
     Output('btn-confirm-lang-switch', 'children'),
     Output('store-pending-lang', 'data')],
    [Input('lang-pt', 'n_clicks'),
     Input('lang-en', 'n_clicks'),
     Input('btn-confirm-lang-switch', 'n_clicks'),
     Input('btn-cancel-lang-switch', 'n_clicks')],
    [State('store-lang', 'data'),
     State('stored-data', 'data'),
     State('stored-demand-data', 'data'),
     State('store-pending-lang', 'data')],
    prevent_initial_call=True
)
def update_language(pt_clicks, en_clicks, confirm_clicks, cancel_clicks, current_lang, stored_data, stored_demand_data, pending_lang):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, False, no_update, no_update, no_update, no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Handle language selector click
    if trigger_id in ('lang-pt', 'lang-en'):
        target_lang = 'pt' if trigger_id == 'lang-pt' else 'en'
        
        # If the clicked language is the same as the current language, do nothing
        if target_lang == current_lang:
            return no_update, False, no_update, no_update, no_update, no_update, None

        # Check if there is data in the stores
        has_data = False
        for data_str in [stored_data, stored_demand_data]:
            if data_str:
                try:
                    df = pd.read_json(io.StringIO(data_str), orient='split')
                    if not df.empty:
                        has_data = True
                        break
                except Exception:
                    pass

        if has_data:
            # Show confirmation modal
            pt_title = translate("Confirmar Troca de Idioma", "pt")
            en_title = translate("Confirmar Troca de Idioma", "en")
            title = f"{pt_title} / {en_title}"

            pt_body = translate("Trocar o idioma irá reiniciar a sessão e todos os dados carregados serão perdidos. Deseja continuar?", "pt")
            en_body = translate("Trocar o idioma irá reiniciar a sessão e todos os dados carregados serão perdidos. Deseja continuar?", "en")
            body = [
                html.P(pt_body, className="mb-2"),
                html.P(en_body, className="mb-0 text-muted", style={"fontStyle": "italic"})
            ]

            pt_cancel = translate("Cancelar", "pt")
            en_cancel = translate("Cancelar", "en")
            cancel_label = f"{pt_cancel} / {en_cancel}"

            pt_confirm = translate("Confirmar", "pt")
            en_confirm = translate("Confirmar", "en")
            confirm_label = f"{pt_confirm} / {en_confirm}"

            return no_update, True, title, body, cancel_label, confirm_label, target_lang
        else:
            # Switch language immediately since there is no data to lose
            return target_lang, False, no_update, no_update, no_update, no_update, None

    # Handle modal confirmation
    if trigger_id == 'btn-confirm-lang-switch':
        if pending_lang:
            return pending_lang, False, no_update, no_update, no_update, no_update, None
        return no_update, False, no_update, no_update, no_update, no_update, None

    # Handle modal cancellation or closing
    if trigger_id == 'btn-cancel-lang-switch':
        return no_update, False, no_update, no_update, no_update, no_update, None

    return no_update, False, no_update, no_update, no_update, no_update, no_update

@app.callback(
    Output('page-content', 'children'),
    [Input('store-lang', 'data')],
    State('dropdown-base-warehouses', 'value'),
    prevent_initial_call=True
)
def render_page(lang, dropdown_base_warehouses_val):
    if not lang:
        lang = 'pt'
    if not dropdown_base_warehouses_val:
        dropdown_base_warehouses_val = 'credenciados'
    return serve_layout(lang, dropdown_base_warehouses_val)




@app.callback(
    Output("modal-help", "is_open"),
    Output("store-help-seen", "data"),
    [Input("btn-help-modal", "n_clicks"),
     Input("close-help-modal", "n_clicks"),
     Input("main-tabs", "active_tab")], # Trigger on load
    [State("modal-help", "is_open"),
     State("store-help-seen", "data")]
)
def toggle_help_modal(n_open, n_close, active_tab, is_open, help_seen):
    ctx = dash.callback_context

    # In Dash, on initial load, triggered can be empty or contain all inputs.
    # The safest way in modern Dash is checking triggered_id (if available) or checking if n_open/n_close are truthy.

    # If no explicit trigger, it's the initial load
    if not ctx.triggered:
        if not help_seen:
            return True, True
        return is_open, help_seen

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Sometimes initial load triggers 'btn-help-modal' with None or 0 clicks.
    # We must explicitly verify that a user actually clicked it if it's the trigger.
    if trigger_id == "btn-help-modal":
        if n_open: # Only if it was actually clicked (>0)
            return True, True
        # If it was 0/None, it's just the initial load firing it.
        if not help_seen:
            return True, True

    if trigger_id == "close-help-modal" and n_close:
        return False, True

    if trigger_id == "main-tabs" and not help_seen:
        return True, True

    return is_open, help_seen


@app.callback(
    [Output("tab-input-container", "style"),
     Output("tab-demand-container", "style"),
     Output("tab-warehouses-container", "style"),
     Output("tab-prod-warehouses-container", "style"),
     Output("tab-costs-container", "style"),
     Output("tab-distance-matrix-container", "style"),
     Output("tab-config-container", "style"),
     Output("tab-results-container", "style")],
    Input("main-tabs", "active_tab")
)
def render_content(active_tab):
    base_styles = [{"display": "none"}] * 8

    if active_tab == 'tab-input':
        base_styles[0] = {"display": "block"}
    elif active_tab == 'tab-demand':
        base_styles[1] = {"display": "block"}
    elif active_tab == 'tab-warehouses':
        base_styles[2] = {"display": "block"}
    elif active_tab == 'tab-prod-warehouses':
        base_styles[3] = {"display": "block"}
    elif active_tab == 'tab-costs':
        base_styles[4] = {"display": "block"}
    elif active_tab == 'tab-distance-matrix':
        base_styles[5] = {"display": "block"}
    elif active_tab == 'tab-config':
        base_styles[6] = {"display": "block"}
    elif active_tab == 'tab-results':
        base_styles[7] = {"display": "block"}

    return tuple(base_styles)

# 1. City Dropdown Options (Server-side filtering)
@app.callback(
    Output("input-city", "options"),
    Input("input-city", "search_value"),
    State("input-city", "value")
)
def update_city_options(search_value, value):
    if not search_value:
        # If no search term, show the selected value (if any) or nothing (or top few)
        if value:
            return [{'label': value, 'value': value}]
        return []

    # Filter options based on search term
    filtered = [
        {'label': c, 'value': c}
        for c in CITY_OPTIONS
        if search_value.lower() in c.lower()
    ]

    # Limit results for performance
    filtered = filtered[:50]

    # Ensure current value is present
    if value:
        # Check if value is already in filtered
        if not any(f['value'] == value for f in filtered):
            filtered.insert(0, {'label': value, 'value': value})

    return filtered

# 2. City Selection -> Auto-fill Lat/Lon
@app.callback(
    [Output('input-lat', 'value'),
     Output('input-lon', 'value')],
    Input('input-city', 'value'),
    prevent_initial_call=True
)
def update_lat_lon(city_value):
    if not city_value or city_value not in CITY_LOOKUP:
        return no_update, no_update

    data = CITY_LOOKUP[city_value]
    return data['latitude'], data['longitude']

# 2. Manual Edit Toggle
@app.callback(
    [Output('input-lat', 'disabled'),
     Output('input-lon', 'disabled'),
     Output('btn-manual-edit', 'children')],
    Input('btn-manual-edit', 'n_clicks'),
    prevent_initial_call=True
)
def toggle_manual_edit(n_clicks):
    if n_clicks % 2 == 1:
        return False, False, "🔓" # Enable
    return True, True, "🔒" # Disable

# 2.b Toggle growth rate input field disabled state
@app.callback(
    [Output('input-growth-rate', 'disabled'),
     Output('label-growth-rate', 'style')],
    Input('input-pattern', 'value')
)
def toggle_growth_rate_disabled(pattern_val):
    if pattern_val == 'linear':
        return False, {'color': UNB_THEME['UNB_GRAY_DARK']}
    return True, {'color': '#9ca3af'}

# 2.c Toggle timespan inputs based on store emptiness
@app.callback(
    [Output('input-start-year', 'disabled'),
     Output('input-end-year', 'disabled')],
    Input('stored-data', 'data')
)
def toggle_timespan_inputs_disabled(stored_data):
    if stored_data is None:
        return False, False
    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        if df.empty:
            return False, False
        return True, True
    except:
        return False, False

# 2.d Sync UI start/end years with loaded data timespan
@app.callback(
    [Output('input-start-year', 'value'),
     Output('input-end-year', 'value')],
    Input('stored-data', 'data'),
    [State('input-start-year', 'value'),
     State('input-end-year', 'value')]
)
def update_timespan_values(stored_data, current_start, current_end):
    if stored_data is None:
        return no_update, no_update
    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        if df.empty:
            return current_start or 2026, current_end or 2035
        dates = pd.to_datetime(df['Data'], errors='coerce').dropna()
        if not dates.empty:
            return dates.min().year, dates.max().year
        return current_start or 2026, current_end or 2035
    except Exception as e:
        print(f"Error in update_timespan_values: {e}")
        return current_start or 2026, current_end or 2035

# Toggling the confirmation modal for clearing the dataset
@app.callback(
    Output('confirm-clear-modal', 'is_open'),
    [Input('btn-clear-dataset', 'n_clicks'),
     Input('btn-cancel-clear', 'n_clicks'),
     Input('btn-confirm-clear', 'n_clicks')],
    State('confirm-clear-modal', 'is_open'),
    prevent_initial_call=True
)
def toggle_confirm_clear_modal(n_open, n_cancel, n_confirm, is_open):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    if trigger_id == 'btn-clear-dataset':
        return True
    return False

# 3. Upload & Add Row -> Update Store
@app.callback(
    Output('stored-data', 'data'),
    Output('error-modal', 'is_open'),
    Output('modal-body-content', 'children'),
    Output('upload-data', 'contents'),
    [Input('upload-data', 'contents'),
     Input('btn-add-row', 'n_clicks'),
     Input('editable-table', 'data_timestamp'), # Track edits via timestamp
     Input('close-modal', 'n_clicks'),
     Input('btn-confirm-clear', 'n_clicks')],
    [State('upload-data', 'filename'),
     State('stored-data', 'data'),
     State('input-product', 'value'),
     State('input-weight', 'value'),
     State('input-city', 'value'),
     State('input-lat', 'value'),
     State('input-lon', 'value'),
     State('error-modal', 'is_open'),
     State('editable-table', 'data'),
     State('store-lang', 'data'),
     State('input-pattern', 'value'),
     State('input-growth-rate', 'value'),
     State('filter-product', 'value'),
     State('filter-city', 'value'),
     State('input-start-year', 'value'),
     State('input-end-year', 'value')]
)
def update_store(contents, n_add, timestamp, n_close, n_confirm_clear, filename, stored_data,
                 prod_val, weight_val, city_val, lat_val, lon_val,
                 is_open, table_data, lang='pt', pattern_val='constant', growth_val=None,
                 filter_prod=None, filter_city=None, start_year_val=None, end_year_val=None):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Close Modal
    if trigger_id == 'close-modal':
        return no_update, False, no_update, no_update

    # Clear Dataset
    if trigger_id == 'btn-confirm-clear':
        empty_df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])
        return empty_df.to_json(date_format='iso', orient='split'), False, no_update, None

    # Determine locked timespan limits
    start_yr = int(start_year_val) if start_year_val else 2026
    end_yr = int(end_year_val) if end_year_val else 2035

    # Upload Data
    if trigger_id == 'upload-data':
        if contents is None:
            return no_update, no_update, no_update, no_update

        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        try:
            if filename.endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(decoded))
            elif filename.endswith('.csv'):
                file_bytes = io.BytesIO(decoded)
                df = flex_read_csv(file_bytes)
            else:
                return no_update, True, translate("O arquivo deve ser Excel (.xlsx) ou CSV (.csv).", lang), None

            # Validate expected columns for long format
            expected_cols = ["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"]
            if not all(col in df.columns for col in expected_cols):
                return no_update, True, translate("Aviso: O arquivo carregado deve conter exatamente as colunas:", lang) + f" {', '.join(expected_cols)}.", None

            # Ensure that only expected columns are kept
            df = df[expected_cols]

            # Normalize "Produto" column
            df["Produto"] = df["Produto"].fillna('').astype(str).str.title()

            # Normalize "Data" column to YYYY-MM
            df["Data"] = pd.to_datetime(df["Data"], errors='coerce').dt.strftime('%Y-%m')
            df["Data"] = df["Data"].fillna('2026-01')

            # Parse numeric weight
            df["Peso (ton)"] = df["Peso (ton)"].apply(parse_brazilian_number)

            # Strict Validation against locked timespan
            has_existing_data = False
            if stored_data:
                try:
                    old_df = pd.read_json(io.StringIO(stored_data), orient='split')
                    has_existing_data = not old_df.empty
                except:
                    pass

            if has_existing_data:
                expected_dates = pd.date_range(
                    start=f"{start_yr}-01-01", 
                    end=f"{end_yr}-12-01", 
                    freq='MS'
                ).strftime('%Y-%m').tolist()

                uploaded_dates = sorted(df["Data"].dropna().unique().tolist())
                if uploaded_dates != expected_dates:
                    error_msg = translate("Aviso: O arquivo carregado não condiz com o horizonte temporal travado para esta sessão ({start} a {end}).", lang).format(start=start_yr, end=end_yr)
                    return no_update, True, error_msg, None
            else:
                # First upload validation: ensure the uploaded file has a valid monthly series structure
                dates = pd.to_datetime(df["Data"], errors='coerce').dropna()
                if dates.empty:
                    return no_update, True, translate("Aviso: O arquivo carregado deve conter datas válidas na coluna 'Data'.", lang), None
                
                min_yr_detected = dates.min().year
                max_yr_detected = dates.max().year
                
                expected_dates = pd.date_range(
                    start=f"{min_yr_detected}-01-01", 
                    end=f"{max_yr_detected}-12-01", 
                    freq='MS'
                ).strftime('%Y-%m').tolist()

                uploaded_dates = sorted(df["Data"].dropna().unique().tolist())
                if uploaded_dates != expected_dates:
                    error_msg = translate("Aviso: O arquivo carregado deve conter uma série histórica mensal contínua iniciando em janeiro e terminando em dezembro.", lang)
                    return no_update, True, error_msg, None

            return df.to_json(date_format='iso', orient='split'), False, no_update, None
        except Exception as e:
            print(f"Error processing file: {e}")
            return no_update, True, translate("Erro ao processar o arquivo. Verifique se é um arquivo válido.", lang), None

    # Add Row (Generates monthly series for locked timespan)
    if trigger_id == 'btn-add-row':
        if stored_data:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
        else:
            df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])

        if not prod_val or not weight_val or not city_val:
            return no_update, True, translate("Preencha Produto, Peso e Cidade para adicionar.", lang), no_update

        if start_yr > end_yr:
            return no_update, True, translate("Aviso: O Ano Inicial deve ser menor ou igual ao Ano Final.", lang), no_update

        try:
            base_weight = float(weight_val)
        except ValueError:
            return no_update, True, translate("O peso deve ser um valor numérico.", lang), no_update

        try:
            # Normalize Product Name
            prod_val_normalized = str(prod_val).title()

            # Generate monthly date list from start/end year inputs
            dates_list = pd.date_range(
                start=f"{start_yr}-01-01", 
                end=f"{end_yr}-12-01", 
                freq='MS'
            ).strftime('%Y-%m').tolist()

            # Growth rate logic
            growth_rate = 0.0
            if pattern_val == 'linear' and growth_val is not None:
                try:
                    growth_rate = float(growth_val) / 100.0
                except ValueError:
                    pass

            new_rows = []
            for t, dt_str in enumerate(dates_list):
                if pattern_val == 'linear':
                    val = base_weight * ((1 + growth_rate) ** t)
                else:
                    val = base_weight

                new_rows.append({
                    'Produto': prod_val_normalized,
                    'Cidade': city_val,
                    'Latitude': lat_val,
                    'Longitude': lon_val,
                    'Data': dt_str,
                    'Peso (ton)': round(val, 2)
                })

            new_rows_df = pd.DataFrame(new_rows)
            if df.empty:
                df = new_rows_df
            else:
                df = pd.concat([df, new_rows_df], ignore_index=True)
            return df.to_json(date_format='iso', orient='split'), False, no_update, no_update
        except Exception as e:
            print(f"Error adding row: {e}")
            return no_update, True, translate("Erro ao adicionar linha:", lang) + f" {str(e)}", no_update

    # Table Edited or Row Deleted
    if trigger_id == 'editable-table':
        try:
            if table_data is None or not stored_data:
                return no_update, no_update, no_update, no_update

            full_df = pd.read_json(io.StringIO(stored_data), orient='split')

            # Identify the filtered rows in the original dataframe
            filtered_indices = full_df.index
            if filter_prod:
                filtered_indices = filtered_indices[full_df.loc[filtered_indices, 'Produto'] == filter_prod]
            if filter_city:
                filtered_indices = filtered_indices[full_df.loc[filtered_indices, 'Cidade'] == filter_city]

            # 1. Update existing rows and identify deleted rows
            indices_in_table = set()
            for row in table_data:
                idx = row.get('_index')
                if idx is not None:
                    indices_in_table.add(idx)
                    if idx in full_df.index:
                        full_df.at[idx, 'Produto'] = str(row.get('Produto', '')).title()
                        full_df.at[idx, 'Cidade'] = row.get('Cidade')
                        full_df.at[idx, 'Latitude'] = row.get('Latitude')
                        full_df.at[idx, 'Longitude'] = row.get('Longitude')
                        full_df.at[idx, 'Data'] = row.get('Data')
                        full_df.at[idx, 'Peso (ton)'] = parse_brazilian_number(row.get('Peso (ton)'))

            # 2. Identify and drop deleted rows
            deleted_indices = set(filtered_indices) - indices_in_table
            if deleted_indices:
                full_df = full_df.drop(index=list(deleted_indices))

            return full_df.to_json(date_format='iso', orient='split'), False, no_update, no_update
        except Exception as e:
            print(f"Error updating store from table edit: {e}")
            return no_update, no_update, no_update, no_update

    return no_update, no_update, no_update, no_update


# 2. Store -> Render Table (Update Table Data)
@app.callback(
    Output('editable-table', 'data'),
    Output('editable-table', 'columns'),
    [Input('stored-data', 'data'),
     Input('main-tabs', 'active_tab'),
     Input('filter-product', 'value'),
     Input('filter-city', 'value')],
    State('store-lang', 'data')
)
def update_table_view(stored_data, active_tab, filter_prod, filter_city, lang='pt'):
    if active_tab != 'tab-input':
        return no_update, no_update

    if stored_data is None:
        return no_update, no_update

    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        
        # Filter the DataFrame based on chosen filters
        df_filtered = df.copy()
        if filter_prod:
            df_filtered = df_filtered[df_filtered['Produto'] == filter_prod]
        if filter_city:
            df_filtered = df_filtered[df_filtered['Cidade'] == filter_city]

        # Add original index as hidden column
        df_filtered['_index'] = df_filtered.index

        expected_cols = ["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"]
        columns = [{'name': translate(col, lang), 'id': col, 'deletable': False, 'renamable': False} for col in expected_cols]
        
        return df_filtered.to_dict('records'), columns
    except Exception as e:
        print(f"Error rendering table: {e}")
        return no_update, no_update

# 2.1 Update filter options based on stored data and resolve conflicts
@app.callback(
    [Output('filter-product', 'options'),
     Output('filter-city', 'options'),
     Output('filter-product', 'value'),
     Output('filter-city', 'value')],
    [Input('stored-data', 'data'),
     Input('filter-product', 'value'),
     Input('filter-city', 'value')]
)
def update_filter_options_and_resolve_conflicts(stored_data, selected_prod, selected_city):
    if stored_data is None:
        return [], [], None, None
    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        if df.empty:
            return [], [], None, None

        # Initial sets
        products = sorted(df['Produto'].dropna().unique().tolist())
        cities = sorted(df['Cidade'].dropna().unique().tolist())

        # Check for active selections
        prod_val = selected_prod
        city_val = selected_city

        # Cross-filtering logic
        if selected_city:
            # Products that exist in the selected city
            available_prods = df[df['Cidade'] == selected_city]['Produto'].dropna().unique().tolist()
            prod_options = [{'label': p, 'value': p} for p in sorted(available_prods)]
            # Resolve conflict if selected product isn't in this city
            if selected_prod and selected_prod not in available_prods:
                prod_val = None
        else:
            prod_options = [{'label': p, 'value': p} for p in products]

        if selected_prod:
            # Cities that have the selected product
            available_cities = df[df['Produto'] == selected_prod]['Cidade'].dropna().unique().tolist()
            city_options = [{'label': c, 'value': c} for c in sorted(available_cities)]
            # Resolve conflict if selected city doesn't have this product
            if selected_city and selected_city not in available_cities:
                city_val = None
        else:
            city_options = [{'label': c, 'value': c} for c in cities]

        return prod_options, city_options, prod_val, city_val
    except Exception as e:
        print(f"Error in cross-filtering: {e}")
        return [], [], None, None

# 2.2 Render Line Chart for Historical Series
@app.callback(
    Output('supply-chart', 'figure'),
    [Input('stored-data', 'data'),
     Input('filter-product', 'value'),
     Input('filter-city', 'value')],
    State('store-lang', 'data')
)
def update_chart(stored_data, filter_prod, filter_city, lang='pt'):
    if stored_data is None:
        return go.Figure()

    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        if df.empty:
            return go.Figure()

        # Parse Data column as datetime for correct chronological sorting
        df['dt_parsed'] = pd.to_datetime(df['Data'], errors='coerce')
        df = df.dropna(subset=['dt_parsed'])

        title_suffix = ""
        # Filter data
        if filter_prod and filter_city:
            df_plot = df[(df['Produto'] == filter_prod) & (df['Cidade'] == filter_city)]
            df_plot = df_plot.groupby('Data')['Peso (ton)'].sum().reset_index()
            df_plot['dt_parsed'] = pd.to_datetime(df_plot['Data'])
            df_plot = df_plot.sort_values('dt_parsed')
            title_suffix = f" - {filter_prod} ({filter_city})"
        elif filter_prod:
            df_plot = df[df['Produto'] == filter_prod]
            df_plot = df_plot.groupby('Data')['Peso (ton)'].sum().reset_index()
            df_plot['dt_parsed'] = pd.to_datetime(df_plot['Data'])
            df_plot = df_plot.sort_values('dt_parsed')
            title_suffix = f" - {filter_prod}"
        elif filter_city:
            df_plot = df[df['Cidade'] == filter_city]
            df_plot = df_plot.groupby('Data')['Peso (ton)'].sum().reset_index()
            df_plot['dt_parsed'] = pd.to_datetime(df_plot['Data'])
            df_plot = df_plot.sort_values('dt_parsed')
            title_suffix = f" - {filter_city}"
        else:
            # Aggregate all products/cities by month
            df_plot = df.groupby('Data')['Peso (ton)'].sum().reset_index()
            df_plot['dt_parsed'] = pd.to_datetime(df_plot['Data'])
            df_plot = df_plot.sort_values('dt_parsed')
            title_suffix = f" - {translate('Total Geral', lang)}"

        if df_plot.empty:
            return go.Figure()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_plot['Data'],
            y=df_plot['Peso (ton)'],
            mode='lines+markers',
            line=dict(color=UNB_THEME['UNB_BLUE'], width=3),
            marker=dict(size=6, color=UNB_THEME['UNB_BLUE_GREEN']),
            hovertemplate="<b>%{x}</b><br>" + translate("Peso (ton)", lang) + ": %{y:,.2f}<extra></extra>"
        ))

        fig.update_layout(
            title=dict(
                text=translate("Evolução Mensal da Oferta", lang) + title_suffix,
                font=dict(size=14, color=UNB_THEME['UNB_BLUE'], family="'Roboto', sans-serif"),
                x=0.02
            ),
            xaxis=dict(
                title=translate("Mês/Ano", lang),
                gridcolor='#F0F2F5',
                tickangle=-45,
                type='category' # ensures correct discrete sorting as strings
            ),
            yaxis=dict(
                title=translate("Peso (ton)", lang),
                gridcolor='#F0F2F5',
                zeroline=False
            ),
            margin=dict(l=50, r=20, t=50, b=40),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            height=350,
            hovermode='x unified'
        )

        return fig
    except Exception as e:
        print(f"Error rendering chart: {e}")
        return go.Figure()

# 2.1 Update Metrics Store
@app.callback(
    Output('metrics-store', 'data'),
    Input('stored-data', 'data'),
    State('store-lang', 'data')
)
def update_metrics(stored_data, lang='pt'):
    if stored_data is None:
        return {'weight': 0, 'count': 0}

    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')

        total_weight = 0
        unique_products = 0

        if not df.empty:
            if "Peso (ton)" in df.columns:
                try:
                    if pd.api.types.is_numeric_dtype(df["Peso (ton)"]):
                        total_weight = df["Peso (ton)"].sum()
                    else:
                        total_weight = df["Peso (ton)"].apply(parse_brazilian_number).sum()
                except Exception as e:
                    print(f"Error calculating weight: {e}")
                    total_weight = 0

            if "Produto" in df.columns:
                unique_products = df["Produto"].nunique()

        return {'weight': float(total_weight), 'count': int(unique_products)}
    except Exception as e:
        print(f"Error calculating metrics: {e}")
        return {'weight': 0, 'count': 0}

# 2.2 Product Suggestions (Datalist)
@app.callback(
    Output('list-suggested-products', 'children'),
    Input('stored-data', 'data'),
    State('store-lang', 'data')
)
def update_product_suggestions(stored_data, lang='pt'):
    if stored_data is None:
        return []

    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')
        if "Produto" in df.columns:
            # Get unique products, drop None/NaN, sort
            products = sorted(df["Produto"].dropna().unique().astype(str).tolist())
            return [html.Option(value=p) for p in products]
        return []
    except Exception as e:
        print(f"Error updating product suggestions: {e}")
        return []

# Client-side callback for animating metrics
app.clientside_callback(
    """
    function(data, lang) {
        if (!data) return window.dash_clientside.no_update;

        // Map dash lang to browser locale string
        const locale = lang === 'pt' ? 'pt-BR' : 'en-US';

        const animate = (id, endValue, isFloat) => {
            const el = document.getElementById(id);
            if (!el) return;

            // Get current value from dataset attribute or default to 0
            let startValue = parseFloat(el.dataset.rawValue) || 0;
            const duration = 1000; // 1 second
            const startTime = performance.now();

            const step = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);

                // Ease out cubic
                const ease = 1 - Math.pow(1 - progress, 3);

                const current = startValue + (endValue - startValue) * ease;

                if (isFloat) {
                    el.innerText = current.toLocaleString(locale, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                } else {
                    el.innerText = Math.round(current).toLocaleString(locale);
                }

                if (progress < 1) {
                    requestAnimationFrame(step);
                } else {
                     // Ensure final value is exact
                    if (isFloat) {
                        el.innerText = endValue.toLocaleString(locale, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                    } else {
                        el.innerText = endValue.toLocaleString(locale);
                    }
                    // Update the raw value in the dataset attribute
                    el.dataset.rawValue = endValue;
                }
            };

            requestAnimationFrame(step);
        };

        animate('metric-total-weight', data.weight, true);
        animate('metric-unique-products', data.count, false);

        return window.dash_clientside.no_update;
    }
    """,
    Output('metric-total-weight', 'id'), # Dummy output
    Input('metrics-store', 'data'),
    State('store-lang', 'data')
)

# 3. Download
@app.callback(
    Output("download-dataframe-xlsx", "data"),
    Input("btn-download", "n_clicks"),
    State('stored-data', 'data'),
    State('store-lang', 'data'),
    prevent_initial_call=True,
)
def download_data(n_clicks, stored_data, lang='pt'):
    if not n_clicks:
        return no_update

    if not stored_data:
        return no_update

    df = pd.read_json(io.StringIO(stored_data), orient='split')
    return dcc.send_data_frame(df.to_excel, translate("Edited_Supply.xlsx", lang), index=False)


# --- Armazéns Callbacks ---

# 4. Load Data to Store (and Handle Restore)
@app.callback(
    Output('store-warehouses', 'data'),
    Output('error-modal', 'is_open', allow_duplicate=True),
    Output('modal-body-content', 'children', allow_duplicate=True),
    Output('btn-save-base', 'style'), # New output for Save button visibility
    Output('modal-missing-cdas', 'is_open'),
    Output('modal-missing-cdas-body', 'children'),
    Output('upload-update-base', 'contents'),
    [Input('main-tabs', 'active_tab'),
     Input('dropdown-base-warehouses', 'value'),
     Input('upload-update-base', 'contents'),
     Input('btn-fetch-registered', 'n_clicks'),
     Input('table-warehouses', 'data_timestamp')],
    [State('store-warehouses', 'data'),
     State('table-warehouses', 'data'),
     State('upload-update-base', 'filename'),
     State('store-lang', 'data')],
    prevent_initial_call=True
)
def manage_warehouses_data(active_tab, dropdown_value, upload_contents, n_fetch, timestamp,
                         stored_data, table_data, upload_filename, lang='pt'):
    ctx = dash.callback_context

    def get_current_base_path(dropdown_val):
        if dropdown_val == 'cadastrados':
            return BASE_ARMAZENS_CADASTRADOS_PATH, "Armazéns Cadastrados"
        elif dropdown_val == 'personalizada':
            return BASE_ARMAZENS_PERSONALIZADOS_PATH, "Base Personalizada"
        else:
            return BASE_ARMAZENS_CREDENCIADOS_PATH, "Armazéns Credenciados e Habilitados"

    current_path, current_title = get_current_base_path(dropdown_value)

    if not ctx.triggered:
         # Initial Load if tab is active
        if active_tab == 'tab-warehouses' and not stored_data:
             try:
                # Load CSV
                df = pd.read_csv(current_path, sep=';', encoding='iso-8859-1', skiprows=1, index_col=False)

                # Drop trailing empty column if exists
                if not df.empty and "Unnamed" in str(df.columns[-1]):
                    df = df.iloc[:, :-1]

                return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update, False, no_update, None
             except Exception:
                return no_update, no_update, no_update, no_update, False, no_update, None
        return no_update, no_update, no_update, no_update, False, no_update, None

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Load from Base
    if trigger_id == 'main-tabs' and active_tab == 'tab-warehouses':
        if not stored_data:
            try:
                # Load CSV
                df = pd.read_csv(current_path, sep=';', encoding='iso-8859-1', skiprows=1, index_col=False)

                # Drop trailing empty column if exists
                if not df.empty and "Unnamed" in str(df.columns[-1]):
                    df = df.iloc[:, :-1]

                return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update, False, no_update, None
            except Exception:
                return no_update, no_update, no_update, no_update, False, no_update, None
        return no_update, no_update, no_update, no_update, False, no_update, None # Keep current state

    # Dropdown Base Changed
    if trigger_id == 'dropdown-base-warehouses':
        try:
            # When switching bases, we return empty data first if preferred, but store-warehouses already overwrites.
            # The main slowness issue is keeping old data in the table layout while new data loads,
            # or rendering many nodes repeatedly.
            # The return in the 'update_warehouses_table_view' callback rebuilds the UI. To prevent the data from
            # tab 3 (Matrices) from accumulating, we don't need to touch them until the update is triggered.
            # We just ensure the Store will be reset with the new base.
            df = pd.read_csv(current_path, sep=';', encoding='iso-8859-1', skiprows=1, index_col=False)

            # Drop trailing empty column if exists
            if not df.empty and "Unnamed" in str(df.columns[-1]):
                df = df.iloc[:, :-1]

            return df.to_json(date_format='iso', orient='split'), no_update, no_update, {"display": "none"}, False, no_update, None
        except Exception:
            return no_update, no_update, no_update, no_update, False, no_update, None

    # Update from Upload (CSV) or fetch
    if trigger_id == 'btn-fetch-registered' and dropdown_value == 'cadastrados':
        try:
            df_conab = get_conab_txt_data()
            if df_conab.empty:
                return no_update, True, translate("Erro ao buscar dados do Conab.", lang), no_update, False, no_update, None

            # Map the columns
            # identificacao_armazem to CDA
            # nome_armazenador to Armazenador
            # endereco to Endereço
            # nom_municipio to Município
            # UF is together with nom_municipio (e.g. BRASILIA - DF), need to split
            # remove telefone
            # email to Email
            # qtd_capacidade_estatica(t) to Capacidade (t)
            # latitude and longitude stay
            # Add Estoque Inicial = 0
            # qtd_capacidade_recepcao(t) to Capacidade de Recepção

            df_new = pd.DataFrame()
            df_new['CDA'] = df_conab['identificacao_armazem']
            df_new['Armazenador'] = df_conab['nome_armazenador']
            df_new['Endereço'] = df_conab['endereco']

            # Split Municipio and UF
            if 'nom_municipio' in df_conab.columns:
                # Based on raw data: "CRUZEIRO DO SUL-AC                                "
                # The separator is "-" and it can have trailing spaces
                split_mun = df_conab['nom_municipio'].astype(str).str.strip().str.rsplit('-', n=1, expand=True)
                if split_mun.shape[1] >= 2:
                    df_new['Município'] = split_mun[0].str.strip()
                    df_new['UF'] = split_mun[1].str.strip()
                else:
                    df_new['Município'] = df_conab['nom_municipio'].astype(str).str.strip()
                    df_new['UF'] = ""
            else:
                df_new['Município'] = ""
                df_new['UF'] = ""

            # Use UF column if it exists in the Conab data to be safer
            if 'uf' in df_conab.columns:
                # override any potential issue from split
                df_new['UF'] = df_conab['uf'].astype(str).str.strip()

            if 'dsc_tipo_armazem' in df_conab.columns:
                df_new['Tipo'] = df_conab['dsc_tipo_armazem'].fillna("Não Informado")
            else:
                df_new['Tipo'] = "Não Informado"
            # email column might be uppercase or lowercase, let's use a safe check
            email_col = next((c for c in df_conab.columns if 'email' in str(c).lower()), None)
            if email_col:
                df_new['Email'] = df_conab[email_col].fillna('')
            else:
                df_new['Email'] = ''
            df_new['Capacidade (t)'] = df_conab.get('qtd_capacidade_estatica(t)', 0)
            df_new['Latitude'] = df_conab.get('latitude', '')
            df_new['Longitude'] = df_conab.get('longitude', '')
            df_new['Estoque Inicial'] = 0
            if 'qtd_capacidade_recepcao(t)' in df_conab.columns:
                df_new['Capacidade de Recepção'] = df_conab['qtd_capacidade_recepcao(t)'].fillna(0)
            else:
                df_new['Capacidade de Recepção'] = 0

            return df_new.to_json(date_format='iso', orient='split'), no_update, no_update, {"display": "block"}, False, no_update, None

        except Exception as e:
            print(f"Error fetching and processing cadastrados: {e}")
            return no_update, True, translate("Erro ao processar dados do Conab:", lang) + f" {e}", no_update, False, no_update, None

    elif trigger_id == 'upload-update-base' and upload_contents:
        content_type, content_string = upload_contents.split(',')
        decoded = base64.b64decode(content_string)

        try:
            if dropdown_value == 'personalizada' and ('spreadsheetml' in content_type or upload_filename.endswith('.xlsx')):
                df = pd.read_excel(io.BytesIO(decoded))
            elif dropdown_value in ['personalizada', 'cadastrados']:
                # Personalizada e Cadastrados CSV: flexível
                file_bytes = io.BytesIO(decoded)
                df = flex_read_csv(file_bytes)

                # Drop the last column if it's completely empty (result of trailing delimiter)
                if not df.empty:
                    df = df.dropna(axis=1, how='all')
                    if not df.empty and "Unnamed" in str(df.columns[-1]):
                         df = df.iloc[:, :-1]
            else:
                # Conab CSV Parsing Rules (Credenciados):
                # 1. Encoding: iso-8859-1
                # 2. Separator: ;
                # 3. Skip Rows: 1 (Header is on line 2, index 1)
                # 4. Trailing Delimiter: Drop last column

                # Decode using iso-8859-1
                decoded_str = decoded.decode('iso-8859-1')

                df = pd.read_csv(
                    io.StringIO(decoded_str),
                    sep=';',
                    encoding='iso-8859-1',
                    skiprows=1 if dropdown_value == 'credenciados' else 0,
                    index_col=False
                )

                # Drop the last column if it's completely empty (result of trailing delimiter)
                if not df.empty:
                    df = df.dropna(axis=1, how='all')
                    if not df.empty and "Unnamed" in str(df.columns[-1]):
                         df = df.iloc[:, :-1]

            if df is not None:
                # If it is a Custom Base, check the expected columns
                if dropdown_value == 'personalizada':
                    import unicodedata

                    def normalize_string(s):
                            # Ensure we don't crash on NaN or float column names somehow
                        return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn').strip().lower()

                    expected_cols = ['CDA', 'Armazenador', 'Endereço', 'Município', 'UF', 'Tipo', 'Email', 'Capacidade (t)', 'Latitude', 'Longitude', 'Estoque Inicial', 'Capacidade de Recepção']
                    normalized_expected = {normalize_string(c): c for c in expected_cols}

                    # Rename columns if they match flexibly
                    rename_mapping = {}
                    for c in df.columns:
                        norm_c = normalize_string(c)
                        if norm_c in normalized_expected:
                            rename_mapping[c] = normalized_expected[norm_c]

                    df = df.rename(columns=rename_mapping)

                    # Only keep the expected columns to drop any unwanted extra columns
                    cols_to_keep = [c for c in df.columns if c in expected_cols]
                    df = df[cols_to_keep]

                    missing_cols = [c for c in expected_cols if c not in df.columns]
                    if missing_cols:
                        error_msg = html.Div([
                            html.Span(translate("Erro: A base personalizada deve conter as colunas:", lang) + f" {', '.join(expected_cols)}."),
                            html.Br(),
                            html.Br(),
                                html.Span(translate("Faltam:", lang) + f" {', '.join(missing_cols)}", className="text-danger fw-bold"),
                                html.Br(),
                                html.Span(translate("As colunas lidas no seu arquivo foram:", lang) + f" {', '.join([str(c) for c in rename_mapping.keys()])}", className="text-muted small")
                        ])
                        return no_update, True, error_msg, no_update, False, no_update, None

                if "Estoque Inicial" not in df.columns:
                    df["Estoque Inicial"] = 0

                # Remove "Telefone" if it's there in other bases
                if 'Telefone' in df.columns:
                    df = df.drop(columns=['Telefone'])

                # Format Latitude and Longitude
                for col in ['Latitude', 'Longitude']:
                    if col in df.columns:
                        # Convert to string, replace commas with dots, and strip whitespace
                        df[col] = df[col].astype(str).str.replace(',', '.').str.strip()

                        # Replace empty strings with NaN
                        df[col] = df[col].replace('', np.nan)

                        # Convert to numeric
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                        # Correct missing decimal points (e.g. -1149415 -> -11.49415)
                        # Brazilian latitudes are roughly between +5 and -35, longitudes between -30 and -75
                        def fix_coord(val, is_lat):
                            if pd.isna(val) or val == 0:
                                return val

                            # Convert to absolute value for magnitude check to handle both hemispheres
                            abs_val = abs(val)

                            # Valid limits for Brazil
                            min_val, max_val = (-35, 6) if is_lat else (-75, -28)

                            # Iteratively divide by 10 until within range
                            if val < min_val or val > max_val:
                                # We need to adjust magnitude.
                                # e.g. -1149415 -> -11.49415
                                # we want to shift the decimal point

                                # Using string manipulation for safer point placement when dividing
                                # Or iteratively divide:
                                val_iter = val
                                max_iters = 10
                                iters = 0
                                while (val_iter < min_val or val_iter > max_val) and iters < max_iters:
                                    val_iter /= 10.0
                                    iters += 1

                                if val_iter >= min_val and val_iter <= max_val:
                                    return val_iter

                            return val

                        df[col] = df[col].apply(lambda x: fix_coord(x, col == 'Latitude'))

                missing_cdas = []
                # Fetch external data and match CDA ONLY if dropdown_value is 'credenciados'
                if dropdown_value == 'credenciados':
                    df_conab = get_conab_txt_data()
                    if not df_conab.empty and 'CDA' in df.columns:
                        # Clean columns for matching
                        df_conab['identificacao_armazem'] = df_conab['identificacao_armazem'].astype(str).str.strip().str.upper()
                        df['CDA_temp'] = df['CDA'].astype(str).str.strip().str.upper()

                        # Merge data
                        df = pd.merge(df, df_conab[['identificacao_armazem', 'qtd_capacidade_recepcao(t)']],
                                      left_on='CDA_temp', right_on='identificacao_armazem', how='left')

                        # Fill 'Capacidade de Recepção' and identify missing
                        missing_mask = df['qtd_capacidade_recepcao(t)'].isna()
                        missing_cdas = df.loc[missing_mask, 'CDA'].tolist()

                        # If column already exists (maybe in future CSVs), update it, otherwise create it
                        df['Capacidade de Recepção'] = df['qtd_capacidade_recepcao(t)'].fillna(0).infer_objects(copy=False)

                        # Cleanup
                        df = df.drop(columns=['CDA_temp', 'identificacao_armazem', 'qtd_capacidade_recepcao(t)'])
                    else:
                        # Fallback if the data fetch failed or 'CDA' column missing
                        df['Capacidade de Recepção'] = 0
                        if 'CDA' in df.columns:
                            missing_cdas = df['CDA'].tolist()
                else:
                    # For personalizada and cadastrados, just ensure the column exists
                    if 'Capacidade de Recepção' not in df.columns:
                        df['Capacidade de Recepção'] = 0

                # Setup modal properties for missing CDAs
                modal_is_open = False
                modal_children = no_update

                if missing_cdas and dropdown_value == 'credenciados':
                    modal_is_open = True
                    list_items = [html.Li(cda) for cda in missing_cdas]
                    modal_children = html.Div([
                        html.P(translate("Os seguintes CDAs do seu arquivo não tiveram sua 'Capacidade de Recepção' encontrada na base atualizada do SICARM (Conab) e, portanto, foram definidos como 0:", lang)),
                        html.Ul(list_items, style={"maxHeight": "200px", "overflowY": "auto"})
                    ])

                return df.to_json(date_format='iso', orient='split'), no_update, no_update, {"display": "block"}, modal_is_open, modal_children, None
            else:
                return no_update, True, translate("Arquivo vazio ou inválido.", lang), no_update, False, no_update, None

        except Exception as e:
            print(f"Error reconstruction: {e}")
            return no_update, True, translate("Erro ao processar arquivo:", lang) + f" {e}", no_update, False, no_update, None

    # Table Edits (Auto-save)
    if trigger_id == 'table-warehouses':
        if table_data:
             df = pd.DataFrame(table_data)
             if "Estoque Inicial" not in df.columns:
                 df["Estoque Inicial"] = 0

             # Save to base (Auto-save)
             try:
                 with open(current_path, 'w', encoding='iso-8859-1') as f:
                     f.write(current_title + "\n")
                     df.to_csv(f, sep=';', index=False, lineterminator='\n')
             except Exception as e:
                 print(f"Error auto-saving armazens table edit: {e}")

             return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update, False, no_update, None
        return no_update, no_update, no_update, no_update, False, no_update, None

    return no_update, no_update, no_update, no_update, False, no_update, None

# 5. Render Armazéns Table and Metrics
@app.callback(
    Output('table-warehouses', 'data'),
    Output('table-warehouses', 'columns'),
    Output('metric-warehouses-count', 'children'),
    Output('metric-warehouses-capacity', 'children'),
    Output('metric-warehouses-public', 'children'),
    Output('metric-warehouses-private', 'children'),
    Output('modal-slowness-warehouses', 'is_open'),
    Input('main-tabs', 'active_tab'),
    Input('store-warehouses', 'data'),
    Input('store-lang', 'data')
)
def update_warehouses_table_view(active_tab, stored_data, lang='pt'):
    if active_tab != 'tab-warehouses':
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update

    if not stored_data:
        return [], [], "0", "0.00", "0", "0", False

    try:
        df = pd.read_json(io.StringIO(stored_data), orient='split')

        # Ensure 'Estoque Inicial' is in columns list, and ideally at a reasonable position or end
        if "Estoque Inicial" not in df.columns:
            df["Estoque Inicial"] = 0

        columns = [{'name': translate(i, lang), 'id': i, 'deletable': False, 'renamable': False} for i in df.columns]

        # Calculate Metrics
        count = len(df)

        # Try to find capacity column (case insensitive partial match)
        capacity = 0
        cap_col = next((c for c in df.columns if 'cap' in str(c).lower() or 'ton' in str(c).lower()), None)

        if cap_col:
            try:
                if pd.api.types.is_numeric_dtype(df[cap_col]):
                    # If pandas already parsed it as numbers, just sum it
                    capacity = df[cap_col].sum()
                else:
                    # If it's a string/object, safely clean it
                    capacity = df[cap_col].apply(parse_brazilian_number).sum()
            except Exception as e:
                print(f"Error calculating capacity: {e}")
                capacity = 0

        # Calculate Public vs Private
        # Requirement: Public = "Armazenador" == "COMPANHIA NACIONAL DE ABASTECIMENTO"
        # Private = All others
        public_count = 0
        private_count = 0

        armazenador_col = next((c for c in df.columns if 'armazenador' in str(c).lower()), None)
        if armazenador_col:
             public_mask = df[armazenador_col].astype(str).str.upper() == "COMPANHIA NACIONAL DE ABASTECIMENTO"
             public_count = public_mask.sum()
             private_count = len(df) - public_count

        # Format for display
        count_str = f"{count}"
        capacity_str = f"{capacity:,.2f}"
        public_str = f"{public_count}"
        private_str = f"{private_count}"

        # To ensure the column shows even if the JSON parsing somehow missed my initial addition,
        # we check the dicts too. `df.to_dict('records')` uses `df.columns` which now definitely has 'Estoque Inicial'.

        # Display performance warning if more than 1000 rows
        # But ensure it's not the first load since we only want to warn when switching or loading large dataset
        # To avoid overlaps with the tutorial modal, we'll only trigger lentidao
        # when actually displaying a new base from the store.
        is_slowness = count > 1000

        return df.to_dict('records'), columns, count_str, capacity_str, public_str, private_str, is_slowness
    except Exception as e:
        print(f"Error in update_warehouses_table_view: {e}")
        return [], [], "0", "0.00", "0", "0", False

# 5.1. Close slowness modal
@app.callback(
    Output("modal-slowness-warehouses", "is_open", allow_duplicate=True),
    Input("close-slowness-modal", "n_clicks"),
    State("modal-slowness-warehouses", "is_open"),
    prevent_initial_call=True
)
def close_slowness_modal(n_clicks, is_open):
    if n_clicks:
        return False
    return is_open


# 6. Save Confirmation Modal
@app.callback(
    Output("modal-confirm-save", "is_open"),
    [Input("btn-save-base", "n_clicks"),
     Input("confirm-save", "n_clicks"),
     Input("cancel-save", "n_clicks")],
    [State("modal-confirm-save", "is_open"),
     State('store-warehouses', 'data'),
     State('dropdown-base-warehouses', 'value')]
)
def toggle_save_modal(n_save, n_confirm, n_cancel, is_open, stored_data, dropdown_value):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == "btn-save-base":
        return True

    if trigger_id == "cancel-save":
        return False

    if trigger_id == "confirm-save":
        # Execute Save
        def get_current_base_path(dropdown_val):
            if dropdown_val == 'cadastrados':
                return BASE_ARMAZENS_CADASTRADOS_PATH, "Armazéns Cadastrados"
            elif dropdown_val == 'personalizada':
                return BASE_ARMAZENS_PERSONALIZADOS_PATH, "Base Personalizada"
            else:
                return BASE_ARMAZENS_CREDENCIADOS_PATH, "Armazéns Credenciados e Habilitados"

        current_path, current_title = get_current_base_path(dropdown_value)

        if stored_data:
            try:
                df = pd.read_json(io.StringIO(stored_data), orient='split')
                # Save as CSV with header
                with open(current_path, 'w', encoding='iso-8859-1') as f:
                    f.write(current_title + "\n")
                    df.to_csv(f, sep=';', index=False, lineterminator='\n')
            except Exception as e:
                print(f"Error saving: {e}")
        return False

    return is_open

# 7. Close Missing CDAs Modal
@app.callback(
    Output("modal-missing-cdas", "is_open", allow_duplicate=True),
    Input("close-missing-cdas", "n_clicks"),
    State("modal-missing-cdas", "is_open"),
    prevent_initial_call=True
)
def close_missing_cdas_modal(n_clicks, is_open):
    if n_clicks:
        return False
    return is_open


# 8. Tutorial Modal and Upload Visibility
@app.callback(
    Output("modal-tutorial", "is_open"),
    Output("manage-base-container", "style"),
    Output("upload-update-container", "style"),
    Output("fetch-registered-container", "style"),
    Output("download-example-container", "style"),
    Output("modal-tutorial-title", "children"),
    Output("modal-tutorial-body", "children"),
    Output("upload-update-base", "accept"),
    Output("upload-format-hint", "children"),
    [Input("btn-update-base", "n_clicks"),
     Input("close-modal-tutorial", "n_clicks"),
     Input("dropdown-base-warehouses", "value")],
    [State("modal-tutorial", "is_open"),
     State('store-lang', 'data')]
)
def toggle_tutorial_modal(n_update, n_close, dropdown_value, is_open, lang='pt'):
    ctx = dash.callback_context
    if not ctx.triggered:
        return is_open, {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "none"}, "", "", no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Hide everything if we just changed the dropdown
    if trigger_id == "dropdown-base-warehouses":
        return False, {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "none"}, no_update, no_update, no_update, no_update

    manage_style = {"display": "block"}
    upload_style = {"display": "block"} if dropdown_value in ['credenciados', 'personalizada'] else {"display": "none"}
    fetch_style = {"display": "block"} if dropdown_value == 'cadastrados' else {"display": "none"}
    download_example_style = {"display": "block"} if dropdown_value == 'personalizada' else {"display": "none"}

    upload_accept = ".csv, .xlsx" if dropdown_value == 'personalizada' else ".csv"
    upload_hint = "Formatos: .csv, .xlsx" if dropdown_value == 'personalizada' else "Formatos: .csv"

    # Set modal content based on selected base
    if dropdown_value == 'cadastrados':
        title = translate("Como Atualizar a Base (Armazéns Cadastrados)", lang)
        body = [
            html.P(translate("Para atualizar a base de Armazéns Cadastrados do SICARM, basta fechar este pop-up e clicar no botão 'Baixar Dados da Conab'.", lang)),
            html.P(translate("O sistema buscará automaticamente as informações mais recentes do site oficial da Conab e substituirá a base atual.", lang)),
            html.Ul([
                html.Li(html.B(translate("Atenção: Você precisará informar o estoque inicial manualmente para cada unidade armazenadora na tabela ao lado, pois a base utilizada não fornece essa informação.", lang))),
                html.Li(html.B(translate("Atenção: Para as unidades em que a base não fornecer o valor da capacidade de recepção, este será definido automaticamente como 0.", lang)))
            ])
        ]
    elif dropdown_value == 'personalizada':
        title = translate("Como Enviar uma Base Personalizada", lang)
        body = [
            html.P(translate("Você pode enviar a sua própria base de armazéns enviando um arquivo .csv ou .xlsx.", lang)),
            html.P(translate("Você também pode baixar um arquivo de exemplo com o formato esperado e editá-lo antes do envio.", lang)),
            html.P(translate("O arquivo deve conter as seguintes colunas (a ordem não importa e letras maiúsculas/minúsculas ou acentos são tolerados):", lang)),
            html.Ul([
                html.Li(translate("CDA", lang)),
                html.Li(translate("Armazenador", lang)),
                html.Li(translate("Endereço", lang)),
                html.Li(translate("Município", lang)),
                html.Li("UF"),
                html.Li(translate("Tipo", lang)),
                html.Li(translate("Email", lang)),
                html.Li(translate("Capacidade (t)", lang)),
                html.Li(translate("Latitude", lang)),
                html.Li(translate("Longitude", lang)),
                html.Li(translate("Estoque Inicial", lang)),
                html.Li(translate("Capacidade de Recepção", lang))
            ]),
            html.P(translate("Carregue o arquivo na área que aparecerá após fechar esta janela.", lang))
        ]
    else: # credenciados
        title = translate("Como Atualizar a Base (Armazéns Credenciados)", lang)
        body = [
            html.P(translate("Siga os passos abaixo para atualizar a base de armazéns:", lang)),
            html.Ol([
                html.Li([
                    translate("Acesse o link: ", lang),
                    html.A(translate("Consulta Conab", lang), href="https://consultaweb.conab.gov.br/consultas/consultaArmazem.do?method=acaoCarregarConsulta", target="_blank")
                ]),
                html.Li(translate("Marque apenas a opção 'Armazéns Credenciados'.", lang)),
                html.Li(translate("Deixe os outros campos em branco.", lang)),
                html.Li(translate("Preencha o código de segurança e clique em 'Consultar'.", lang)),
                html.Li(translate("No final da página de resultados, exporte ou salve a tabela como arquivo CSV.", lang)),
                html.Li(translate("Carregue o arquivo CSV na área que aparecerá após fechar esta janela.", lang)),
                html.Li(translate("O sistema consultará automaticamente a base do SICARM para preencher a coluna 'Capacidade de Recepção'.", lang)),
                html.Li(html.B(translate("Atenção: Você precisará informar o estoque inicial manualmente para cada unidade armazenadora na tabela ao lado, pois a base utilizada não fornece essa informação.", lang)))
            ]),
            html.Img(src="/assets/data/Tutorial_Atualizar_Armazens.png", style={"width": "100%", "marginTop": "10px", "borderRadius": "8px", "border": "1px solid #ddd"})
        ]

    if trigger_id == "btn-update-base":
        return True, manage_style, upload_style, fetch_style, download_example_style, title, body, upload_accept, upload_hint

    if trigger_id == "close-modal-tutorial":
        return False, manage_style, upload_style, fetch_style, download_example_style, title, body, upload_accept, upload_hint

    return is_open, {"display": "none"}, {"display": "none"}, {"display": "none"}, {"display": "none"}, title, body, upload_accept, upload_hint


@app.callback(
    Output("download-example-personalizada", "data"),
    Input("btn-download-example", "n_clicks"),
    State('store-lang', 'data'),
    prevent_initial_call=True
)
def download_example_file(n_clicks, lang='pt'):
    ctx = dash.callback_context
    if not n_clicks or not ctx.triggered or ctx.triggered[0]['prop_id'] != 'btn-download-example.n_clicks':
        return no_update

    # Create example dataframe
    data = {
        'CDA': ['EXEMPLO-123'],
        'Armazenador': ['Nome do Armazém Exemplo'],
        'Endereço': ['Rua Exemplo, 123'],
        'Município': ['Brasília'],
        'UF': ['DF'],
        'Tipo': ['Convencional'],
        'Email': ['contato@exemplo.com'],
        'Capacidade (t)': [10000],
        'Latitude': [-15.793889],
        'Longitude': [-47.882778],
        'Estoque Inicial': [500],
        'Capacidade de Recepção': [1000]
    }
    df = pd.DataFrame(data)

    return dcc.send_data_frame(df.to_excel, translate("Custom_Base_Example.xlsx", lang), index=False)

# 9. Validation for Tab Prod x Armazens
@app.callback(
    Output("modal-missing-data", "is_open"),
    Output("modal-missing-data-body", "children"),
    Input("main-tabs", "active_tab"),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data'),
     State('store-lang', 'data')]
)
def validate_tab_prod_warehouses(active_tab, stored_data, stored_warehouses, lang='pt'):
    if active_tab != 'tab-prod-warehouses':
        return False, no_update

    # Check Products
    has_prod = False
    if stored_data:
        try:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
            if not df.empty and "Produto" in df.columns:
                has_prod = True
        except:
            pass

    # Check Armazens
    has_warehouses = False
    if stored_warehouses:
        try:
            df = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            if not df.empty:
                has_warehouses = True
        except:
            pass

    if not has_prod and not has_warehouses:
        return True, translate("Você precisa adicionar produtos na aba 'Oferta' e carregar a base na aba 'Armazéns' antes de prosseguir.", lang)
    elif not has_prod:
        return True, translate("Você precisa adicionar pelo menos um produto na aba 'Oferta' antes de prosseguir.", lang)
    elif not has_warehouses:
        return True, translate("Você precisa carregar a base de dados na aba 'Armazéns' antes de prosseguir.", lang)

    return False, no_update

# 10. Redirection from Modal
@app.callback(
    Output("main-tabs", "active_tab"),
    Output("modal-missing-data", "is_open", allow_duplicate=True),
    Input("btn-confirm-missing-data", "n_clicks"),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data')],
    prevent_initial_call=True
)
def redirect_missing_data(n_clicks, stored_data, stored_warehouses):
    if not n_clicks:
        return no_update, no_update

    # Check Products
    has_prod = False
    if stored_data:
        try:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
            if not df.empty and "Produto" in df.columns:
                has_prod = True
        except:
            pass

    # Check Armazens
    has_warehouses = False
    if stored_warehouses:
        try:
            df = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            if not df.empty:
                has_warehouses = True
        except:
            pass

    if not has_prod:
        return 'tab-input', False
    elif not has_warehouses:
        return 'tab-warehouses', False

    return no_update, False


# 11. Populate Product x Armazens Table and Sync Store
@app.callback(
    Output('store-prod-warehouses', 'data'),
    Output('table-prod-armazens', 'data'),
    Output('table-prod-armazens', 'columns'),
    Input('main-tabs', 'active_tab'),
    Input('stored-data', 'data'),
    Input('store-warehouses', 'data'),
    Input('store-lang', 'data'),
    State('store-prod-warehouses', 'data')
)
def update_prod_warehouses_table(active_tab, stored_data, stored_warehouses, lang, stored_matrix):
    if active_tab != 'tab-prod-warehouses':
        return no_update, no_update, no_update

    # 1. Get Unique Products
    products = []
    if stored_data:
        try:
            df_prod = pd.read_json(io.StringIO(stored_data), orient='split')
            if not df_prod.empty and "Produto" in df_prod.columns:
                products = sorted(df_prod["Produto"].dropna().unique().astype(str).tolist())
        except Exception as e:
            print(f"Error reading products: {e}")

    # 2. Get Unique Warehouse Types
    types = []
    if stored_warehouses:
        try:
            df_arm = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            if not df_arm.empty and "Tipo" in df_arm.columns:
                types = sorted(df_arm["Tipo"].dropna().unique().astype(str).tolist())
        except Exception as e:
            print(f"Error reading types: {e}")

    if not products or not types:
        return no_update, [], []

    # 3. Load or Initialize Matrix
    try:
        if stored_matrix:
            df_matrix = pd.read_json(io.StringIO(stored_matrix), orient='split')
        else:
            df_matrix = pd.DataFrame(columns=['Produto'])
    except:
        df_matrix = pd.DataFrame(columns=['Produto'])

    # 4. Sync Logic
    # We want a DataFrame with rows = products, columns = ['Produto'] + types
    new_matrix = pd.DataFrame({'Produto': products})

    # For each type column, preserve existing values if possible
    for t in types:
        if t in df_matrix.columns:
            # Create lookup: Product -> Value for this type
            # We need to handle potential duplicates in df_matrix if something went wrong, but set_index should be fine if unique
            try:
                # Drop duplicates in old matrix just in case
                lookup = df_matrix.drop_duplicates(subset=['Produto']).set_index('Produto')[t].to_dict()
                new_matrix[t] = new_matrix['Produto'].map(lookup).fillna('☑')
            except:
                new_matrix[t] = '☑'
        else:
            new_matrix[t] = '☑'

    # 5. Prepare Output
    columns = [
        {'name': translate('Produto', lang), 'id': 'Produto', 'editable': False}
    ] + [
        {'name': t, 'id': t, 'editable': False} for t in types
    ]

    return new_matrix.to_json(date_format='iso', orient='split'), new_matrix.to_dict('records'), columns


# --- Costs Callbacks ---

@app.callback(
    Output('store-costs-storage', 'data'),
    Output('error-modal', 'is_open', allow_duplicate=True),
    Output('modal-body-content', 'children', allow_duplicate=True),
    Output('upload-storage-csv', 'contents'),
    [Input('main-tabs', 'active_tab'),
     Input('upload-storage-csv', 'contents'),
     Input('btn-add-storage-row', 'n_clicks'),
     Input('table-costs-storage', 'data_timestamp')],
    [State('store-costs-storage', 'data'),
     State('table-costs-storage', 'data'),
     State('upload-storage-csv', 'filename')],
    prevent_initial_call=True
)
def manage_storage_costs(active_tab, upload_contents, n_add, timestamp, stored_data, table_data, upload_filename):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Initial Load
    if trigger_id == 'main-tabs' and active_tab == 'tab-costs':
        if not stored_data:
            try:
                df = pd.read_csv(STORAGE_COSTS_PATH, sep=';', encoding='iso-8859-1')
                return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update
            except Exception as e:
                print(f"Error loading storage costs: {e}")
                return no_update, True, translate("Erro ao carregar a tabela de Tarifas de Armazenagem.", lang), no_update
        return no_update, no_update, no_update, no_update

    # Upload
    if trigger_id == 'upload-storage-csv' and upload_contents:
        content_type, content_string = upload_contents.split(',')
        decoded = base64.b64decode(content_string)
        try:
            if 'spreadsheetml' in content_type or (upload_filename and upload_filename.endswith('.xlsx')):
                df = pd.read_excel(io.BytesIO(decoded))
            else:
                file_bytes = io.BytesIO(decoded)
                df = flex_read_csv(file_bytes)

            # Normalize and clean columns to prevent trailing delimiter issues
            df = df.dropna(axis=1, how='all')
            if not df.empty and "Unnamed" in str(df.columns[-1]):
                 df = df.iloc[:, :-1]

            # Expected columns strictly required
            expected_cols = ['Produto', 'Armazenar_Publico', 'Armazenar_Privado']

            if not all(col in df.columns for col in expected_cols):
                return no_update, True, translate("O arquivo de Tarifas de Armazenagem deve ter exatamente as colunas:", lang) + f" {', '.join(expected_cols)}.", None

            # Enforce column order and remove extras
            df = df[expected_cols]

            # Function to normalize string
            import unicodedata
            def normalize_str(s):
                if pd.isna(s):
                    return ""
                s_str = str(s).strip()
                s_nfkd = unicodedata.normalize('NFKD', s_str)
                s_ascii = s_nfkd.encode('ASCII', 'ignore').decode('utf-8')
                return s_ascii.lower()

            # Ensure "Outros" exists
            df['Prod_Norm'] = df['Produto'].apply(normalize_str)
            if not (df['Prod_Norm'] == 'outros').any():
                # Append "Outros" row at the beginning
                new_row = pd.DataFrame([{'Produto': 'Outros', 'Armazenar_Publico': 50, 'Armazenar_Privado': 50}])
                dropped_df = df.drop(columns=['Prod_Norm'])
                if dropped_df.empty:
                    df = new_row
                else:
                    df = pd.concat([new_row, dropped_df], ignore_index=True)
            else:
                df = df.drop(columns=['Prod_Norm'])

            # Save to disk
            df.to_csv(STORAGE_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
            return df.to_json(date_format='iso', orient='split'), no_update, no_update, None
        except Exception as e:
            return no_update, True, translate("Erro ao processar o arquivo. Verifique se é um arquivo Excel válido (.xlsx) ou um CSV separado por ponto e vírgula (;).", lang), None

    # Add Row
    if trigger_id == 'btn-add-storage-row':
        if stored_data:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
        else:
            df = pd.DataFrame(columns=['Produto', 'Armazenar_Publico', 'Armazenar_Privado'])

        new_row = pd.DataFrame([{'Produto': '', 'Armazenar_Publico': 0, 'Armazenar_Privado': 0}])
        if df.empty:
            df = new_row
        else:
            df = pd.concat([df, new_row], ignore_index=True)
        # Save to disk
        df.to_csv(STORAGE_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
        return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

    # Edit Table
    if trigger_id == 'table-costs-storage':
        if table_data is not None:
            df = pd.DataFrame(table_data)
            # Save to disk
            df.to_csv(STORAGE_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
            return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

    return no_update, no_update, no_update, no_update

    # Add Row
    if trigger_id == 'btn-add-storage-row':
        if stored_data:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
        else:
            df = pd.DataFrame(columns=['Produto', 'Armazenar_Publico', 'Armazenar_Privado'])

        new_row = pd.DataFrame([{'Produto': '', 'Armazenar_Publico': 0, 'Armazenar_Privado': 0}])
        if df.empty:
            df = new_row
        else:
            df = pd.concat([df, new_row], ignore_index=True)
        # Save to disk
        df.to_csv(STORAGE_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
        return df.to_json(date_format='iso', orient='split'), no_update, no_update

    # Edit Table
    if trigger_id == 'table-costs-storage':
        if table_data is not None:
            df = pd.DataFrame(table_data)
            # Save to disk
            df.to_csv(STORAGE_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
            return df.to_json(date_format='iso', orient='split'), no_update, no_update

    return no_update, no_update, no_update

@app.callback(
    Output('table-costs-storage', 'data'),
    Output('table-costs-storage', 'columns'),
    Input('main-tabs', 'active_tab'),
    Input('store-costs-storage', 'data'),
    Input('store-lang', 'data')
)
def update_storage_table(active_tab, stored_data, lang='pt'):
    if active_tab != 'tab-costs':
        return no_update, no_update

    columns = [
        {'name': translate('Produto', lang), 'id': 'Produto'},
        {'name': translate('Armazenar Público', lang), 'id': 'Armazenar_Publico'},
        {'name': translate('Armazenar Privado', lang), 'id': 'Armazenar_Privado'}
    ]
    if not stored_data:
        return [], columns
    df = pd.read_json(io.StringIO(stored_data), orient='split')
    return df.to_dict('records'), columns

@app.callback(
    Output("download-storage-csv", "data"),
    Input("btn-download-storage", "n_clicks"),
    State('store-costs-storage', 'data'),
    State('store-lang', 'data'),
    prevent_initial_call=True,
)
def download_storage(n_clicks, stored_data, lang='pt'):
    if not n_clicks or not stored_data:
        return no_update
    df = pd.read_json(io.StringIO(stored_data), orient='split')
    return dcc.send_data_frame(df.to_excel, translate("Storage_Rate.xlsx", lang), index=False)


# Freight Cost Data Logic
@app.callback(
    Output('store-costs-freight', 'data'),
    Output('error-modal', 'is_open', allow_duplicate=True),
    Output('modal-body-content', 'children', allow_duplicate=True),
    Output('upload-freight-csv', 'contents'),
    [Input('main-tabs', 'active_tab'),
     Input('upload-freight-csv', 'contents'),
     Input('btn-add-freight-row', 'n_clicks'),
     Input('table-costs-freight', 'data_timestamp')],
    [State('store-costs-freight', 'data'),
     State('table-costs-freight', 'data'),
     State('upload-freight-csv', 'filename')],
    prevent_initial_call=True
)
def manage_freight_costs(active_tab, upload_contents, n_add, timestamp, stored_data, table_data, upload_filename):
    ctx = dash.callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Initial Load
    if trigger_id == 'main-tabs' and active_tab == 'tab-costs':
        if not stored_data:
            try:
                df = pd.read_csv(FREIGHT_COSTS_PATH, sep=';', encoding='iso-8859-1')
                return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update
            except Exception as e:
                print(f"Error loading freight costs: {e}")
                return no_update, True, translate("Erro ao carregar a tabela de Valor do Frete.", lang), no_update
        return no_update, no_update, no_update, no_update

    # Upload
    if trigger_id == 'upload-freight-csv' and upload_contents:
        content_type, content_string = upload_contents.split(',')
        decoded = base64.b64decode(content_string)
        try:
            if 'spreadsheetml' in content_type or (upload_filename and upload_filename.endswith('.xlsx')):
                df = pd.read_excel(io.BytesIO(decoded))
            else:
                file_bytes = io.BytesIO(decoded)
                df = flex_read_csv(file_bytes)

            # Normalize and clean columns to prevent trailing delimiter issues
            df = df.dropna(axis=1, how='all')
            if not df.empty and "Unnamed" in str(df.columns[-1]):
                 df = df.iloc[:, :-1]

            # Expected columns strictly required
            expected_cols = ['Estado', 'Frete Tonelada Km']

            if not all(col in df.columns for col in expected_cols):
                return no_update, True, translate("O arquivo de Valor do Frete deve ter exatamente as colunas:", lang) + f" {', '.join(expected_cols)}.", None

            # Enforce column order and remove extras
            df = df[expected_cols]

            # Save to disk
            df.to_csv(FREIGHT_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
            return df.to_json(date_format='iso', orient='split'), no_update, no_update, None
        except Exception as e:
            return no_update, True, translate("Erro ao processar o arquivo. Verifique se é um arquivo Excel válido (.xlsx) ou um CSV separado por ponto e vírgula (;).", lang), None

    # Add Row
    if trigger_id == 'btn-add-freight-row':
        if stored_data:
            df = pd.read_json(io.StringIO(stored_data), orient='split')
        else:
            df = pd.DataFrame(columns=['Estado', 'Frete Tonelada Km'])

        new_row = pd.DataFrame([{'Estado': '', 'Frete Tonelada Km': 0}])
        if df.empty:
            df = new_row
        else:
            df = pd.concat([df, new_row], ignore_index=True)
        # Save to disk
        df.to_csv(FREIGHT_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
        return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

    # Edit Table
    if trigger_id == 'table-costs-freight':
        if table_data is not None:
            df = pd.DataFrame(table_data)
            # Save to disk
            df.to_csv(FREIGHT_COSTS_PATH, sep=';', index=False, encoding='iso-8859-1')
            return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

    return no_update, no_update, no_update, no_update

@app.callback(
    Output('table-costs-freight', 'data'),
    Output('table-costs-freight', 'columns'),
    Input('main-tabs', 'active_tab'),
    Input('store-costs-freight', 'data'),
    Input('store-lang', 'data')
)
def update_freight_table(active_tab, stored_data, lang='pt'):
    if active_tab != 'tab-costs':
        return no_update, no_update

    columns = [
        {'name': translate('Estado', lang), 'id': 'Estado'},
        {'name': translate('Frete (R$/ton.km)', lang), 'id': 'Frete Tonelada Km'}
    ]
    if not stored_data:
        return [], columns
    df = pd.read_json(io.StringIO(stored_data), orient='split')
    return df.to_dict('records'), columns

@app.callback(
    Output("download-freight-csv", "data"),
    Input("btn-download-freight", "n_clicks"),
    State('store-costs-freight', 'data'),
    State('store-lang', 'data'),
    prevent_initial_call=True,
)
def download_freight(n_clicks, stored_data, lang='pt'):
    if not n_clicks or not stored_data:
        return no_update
    df = pd.read_json(io.StringIO(stored_data), orient='split')
    return dcc.send_data_frame(df.to_excel, translate("Freight_Cost_Ton_km.xlsx", lang), index=False)


# 12. Handle Checkbox Toggles
@app.callback(
    Output('store-prod-warehouses', 'data', allow_duplicate=True),
    Output('table-prod-armazens', 'data', allow_duplicate=True),
    Output('table-prod-armazens', 'active_cell'),
    Input('table-prod-armazens', 'active_cell'),
    State('table-prod-armazens', 'derived_viewport_data'),
    State('table-prod-armazens', 'data'),
    prevent_initial_call=True
)
def toggle_checkbox(active_cell, viewport_data, table_data):
    if not active_cell or not table_data or not viewport_data:
        return no_update, no_update, no_update

    row_idx = active_cell['row']
    col_id = active_cell['column_id']

    # Ignore clicks on "Produto" column
    if col_id == 'Produto':
        return no_update, no_update, None

    try:
        # Get the product name from the visible viewport using active_cell['row']
        product_name = viewport_data[row_idx]['Produto']

        df = pd.DataFrame(table_data)

        # Find the correct row index in the full dataframe
        actual_row_idx = df.index[df['Produto'] == product_name].tolist()[0]

        # Toggle Logic
        current_val = df.at[actual_row_idx, col_id]
        if current_val == '☐':
            new_val = '☑'
        else:
            new_val = '☐'

        df.at[actual_row_idx, col_id] = new_val

        return df.to_json(date_format='iso', orient='split'), df.to_dict('records'), None

    except Exception as e:
        print(f"Error toggling checkbox: {e}")
        return no_update, no_update, None


# 13. Distance Matrix Calculation
@app.callback(
    Output('store-distance-matrix', 'data'),
    Output('table-distance-matrix', 'data'),
    Output('table-distance-matrix', 'columns'),
    Output('calc-status-message', 'children'),
    Output('btn-download-matrix', 'disabled'),
    Input('btn-calc-matrix', 'n_clicks'),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data'),
     State('store-lang', 'data')],
    prevent_initial_call=True
)
def calculate_distance_matrix(n_clicks, stored_data, stored_warehouses, lang='pt'):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, True

    start_time = time.time()

    if not stored_data or not stored_warehouses:
        return no_update, [], [], translate("Dados de entrada ou armazéns não encontrados. Verifique as abas anteriores.", lang), True

    try:
        # Load Data
        df_input = pd.read_json(io.StringIO(stored_data), orient='split')
        df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')

        if df_input.empty or df_warehouses.empty:
            return no_update, [], [], translate("As tabelas de entrada ou armazéns estão vazias.", lang), True

        # Prepare Coordinates
        # Origins: Unique cities from input
        # Note: We need unique coordinate pairs. If multiple products come from same city, we only need one origin.
        if "Latitude" not in df_input.columns or "Longitude" not in df_input.columns:
             return no_update, [], [], translate("Colunas de Latitude/Longitude ausentes na entrada.", lang), True

        origins_df = df_input[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()

        # Add (Lat, Lon) to duplicate city names with different coordinates
        city_counts = origins_df['Cidade'].value_counts()
        duplicates = city_counts[city_counts > 1].index

        origins_df['Cidade_Display'] = origins_df.apply(
            lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
            if row['Cidade'] in duplicates else row['Cidade'],
            axis=1
        )

        origins = list(zip(origins_df['Latitude'], origins_df['Longitude']))
        origin_names = origins_df['Cidade_Display'].tolist()

        if not origins:
             return no_update, [], [], translate("Nenhuma origem válida (com coordenadas) encontrada.", lang), True

        # Destinations: Warehouses
        # We try to use 'Município' or similar if available for labeling, but use lat/lon for routing
        # Assuming warehouse table has Lat/Lon?
        # WAIT: The provided memory says "Lembre-se que todos tem latitude e longitude."
        # But the loaded CSV 'Armazens_Credenciados_Habilitados_Base.csv' might not have them explicitly if it's raw Conab data.
        # Let's check if we have Lat/Lon in armazens.

        # Checking columns...
        lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
        lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)

        # If no Lat/Lon in warehouses, we need to geocode them based on City/UF?
        # The user said "Lembre-se que todos tem latitude e longitude." so I assume they are in the data or derived.
        # If they are not in the CSV, I might need to merge with my city lookup.

        if not lat_col or not lon_col:
            # Attempt to look up by City - UF
            # Warehouse CSV usually has "Municipio" and "UF".
            mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
            uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)

            if mun_col and uf_col:
                # Create a temporary key
                df_warehouses['lookup_key'] = df_warehouses[mun_col].astype(str) + ' - ' + df_warehouses[uf_col].astype(str)

                # We need to map this key to our CITY_LOOKUP
                # CITY_LOOKUP keys are "City - UF"

                def get_coords(key):
                    if key in CITY_LOOKUP:
                        return CITY_LOOKUP[key]
                    return {'latitude': None, 'longitude': None}

                coords = df_warehouses['lookup_key'].apply(get_coords)
                df_warehouses['Latitude'] = coords.apply(lambda x: x['latitude'])
                df_warehouses['Longitude'] = coords.apply(lambda x: x['longitude'])

                # Filter out those without coords
                dests_df = df_warehouses.dropna(subset=['Latitude', 'Longitude'])
            else:
                return no_update, [], [], translate("Não foi possível identificar coordenadas ou colunas de Município/UF nos armazéns.", lang), True
        else:
            dests_df = df_warehouses.dropna(subset=[lat_col, lon_col])
            # Rename for consistency
            dests_df = dests_df.rename(columns={lat_col: 'Latitude', lon_col: 'Longitude'})

        if dests_df.empty:
             return no_update, [], [], translate("Nenhum armazém com coordenadas válidas encontrado.", lang), True

        destinations = list(zip(dests_df['Latitude'], dests_df['Longitude']))

        # Determine labels for destinations (e.g., Name of warehouse or City)
        # Prefer "CDA - Armazenador - Municipio"
        cda_col = next((c for c in dests_df.columns if 'cda' in str(c).lower()), None)
        name_col = next((c for c in dests_df.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
        mun_col_dest = next((c for c in dests_df.columns if 'munic' in str(c).lower()), None)

        dest_labels = []
        for idx, row in dests_df.iterrows():
            # Build the base label
            parts = []
            if cda_col and pd.notna(row[cda_col]):
                parts.append(str(row[cda_col]).strip())

            if name_col and pd.notna(row[name_col]):
                parts.append(str(row[name_col]).strip())

            if mun_col_dest and pd.notna(row[mun_col_dest]):
                parts.append(str(row[mun_col_dest]).strip())

            if parts:
                label = " - ".join(parts)
            else:
                label = translate("Dest", lang) + f" {idx}"

            dest_labels.append(label)


        # Call OSRM
        # Use service name 'osrm' if in docker, or 'localhost' if testing locally outside docker.
        # Since this code runs inside the container (production) or local (dev), we try both or env var.
        osrm_url = os.environ.get("OSRM_URL", "http://localhost:5000") # Default to localhost for dev
        # Inside docker-compose, the app container can reach osrm container via 'http://osrm:5000'
        # Check if we are in docker network?
        # Let's assume the user set OSRM_URL in docker-compose (I did: OSRM_URL=http://osrm:5000)

        client = OSRMClient(base_url=osrm_url)

        try:
            matrix = client.get_distance_matrix(origins, destinations)
        except Exception as e:
             return no_update, [], [], translate("Erro de conexão com OSRM:", lang) + f" {str(e)}", True

        # Format Result
        # Rows: Origins, Cols: Destinations
        # We want a table with "Origem" column + columns for each destination

        # Since matrix is [origins][destinations]

        final_data = []
        for i, row_vals in enumerate(matrix):
            row_dict = {'Origem': origin_names[i]}
            for j, val in enumerate(row_vals):
                col_name = dest_labels[j]
                # Convert meters to km
                if val is not None:
                    row_dict[col_name] = round(val / 1000, 2)
                else:
                    row_dict[col_name] = "N/A"
            final_data.append(row_dict)

        final_df = pd.DataFrame(final_data)

        columns = [{"name": translate(i, lang) if i == "Origem" else i, "id": i} for i in final_df.columns]

        return final_df.to_json(date_format='iso', orient='split'), final_df.to_dict('records'), columns, translate("Cálculo concluído com sucesso! (Tempo de execução:", lang) + f" {time.time() - start_time:.2f} " + translate("segundos)", lang), False

    except Exception as e:
        print(f"Calculation error: {e}")
        import traceback
        traceback.print_exc()
        return no_update, [], [], translate("Erro inesperado:", lang) + f" {str(e)}", True

# 14. Download Matrix
@app.callback(
    Output("download-matrix-xlsx", "data"),
    Input("btn-download-matrix", "n_clicks"),
    State('store-distance-matrix', 'data'),
    State('store-lang', 'data'),
    prevent_initial_call=True,
)
def download_matrix(n_clicks, stored_matrix, lang='pt'):
    if not n_clicks or not stored_matrix:
        return no_update

    df = pd.read_json(io.StringIO(stored_matrix), orient='split')
    return dcc.send_data_frame(df.to_excel, translate("Distance_Matrix.xlsx", lang), index=False)

# 15. Route Visualization
@app.callback(
    Output("graph-route-map", "figure"),
    Input("table-distance-matrix", "active_cell"),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data'),
     State('table-distance-matrix', 'derived_viewport_data'),
     State('store-lang', 'data')],
    prevent_initial_call=True
)
def update_route_map(active_cell, stored_data, stored_warehouses, table_data, lang='pt'):
    # Default map centered on Brazil
    default_fig = go.Figure(go.Scattermapbox())
    default_fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=3,
        mapbox_center={"lat": -14.2350, "lon": -51.9253},
        margin={"r": 0, "t": 0, "l": 0, "b": 0}
    )

    if not active_cell or not stored_data or not stored_warehouses or not table_data:
        return default_fig

    try:
        # Get Origin and Destination from active cell
        # Table data has 'Origem' column and destination columns
        row_idx = active_cell['row']
        col_id = active_cell['column_id']

        # If clicked on 'Origem' column, maybe show all routes? Or just ignore.
        # Let's ignore for now or pick the first destination?
        if col_id == 'Origem':
            return default_fig

        row_data = table_data[row_idx]
        origin_name = row_data['Origem']
        dest_label = col_id

        # Retrieve Coordinates
        df_input = pd.read_json(io.StringIO(stored_data), orient='split')
        df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')

        # Origin Coords
        # We need to find the lat/lon for the origin_name (City)
        # Assuming unique city names for simplicity or taking first match
        # Apply the same deduplication logic to find the exact match
        origins_df_map = df_input[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
        city_counts_map = origins_df_map['Cidade'].value_counts()
        duplicates_map = city_counts_map[city_counts_map > 1].index

        origins_df_map['Cidade_Display'] = origins_df_map.apply(
            lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
            if row['Cidade'] in duplicates_map else row['Cidade'],
            axis=1
        )

        origin_row = origins_df_map[origins_df_map['Cidade_Display'] == origin_name]
        if origin_row.empty:
            # Fallback to just Cidade if not found
            origin_row = df_input[df_input['Cidade'] == origin_name].iloc[0]
        else:
            origin_row = origin_row.iloc[0]

        origin_coords = (origin_row['Latitude'], origin_row['Longitude'])

        # Destination Coords
        # This is trickier because dest_label is a formatted string "Name (City)" or similar
        # We need to reconstruct the logic from calculation callback or store dest coords
        # Re-running logic for now (could be optimized by storing mapping)

        # Re-resolve warehouses logic
        lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
        lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)

        if not lat_col or not lon_col:
             # Using lookup logic
             mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
             uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)
             df_warehouses['lookup_key'] = df_warehouses[mun_col].astype(str) + ' - ' + df_warehouses[uf_col].astype(str)
             def get_coords(key):
                 if key in CITY_LOOKUP: return CITY_LOOKUP[key]
                 return {'latitude': None, 'longitude': None}
             coords = df_warehouses['lookup_key'].apply(get_coords)
             df_warehouses['Latitude'] = coords.apply(lambda x: x['latitude'])
             df_warehouses['Longitude'] = coords.apply(lambda x: x['longitude'])
             dests_df = df_warehouses.dropna(subset=['Latitude', 'Longitude'])
        else:
            dests_df = df_warehouses.dropna(subset=[lat_col, lon_col])
            dests_df = dests_df.rename(columns={lat_col: 'Latitude', lon_col: 'Longitude'})

        # Match label
        cda_col = next((c for c in dests_df.columns if 'cda' in str(c).lower()), None)
        name_col = next((c for c in dests_df.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
        mun_col_dest = next((c for c in dests_df.columns if 'munic' in str(c).lower()), None)

        dest_coords = None
        for idx, row in dests_df.iterrows():
            parts = []
            if cda_col and pd.notna(row[cda_col]):
                parts.append(str(row[cda_col]).strip())

            if name_col and pd.notna(row[name_col]):
                parts.append(str(row[name_col]).strip())

            if mun_col_dest and pd.notna(row[mun_col_dest]):
                parts.append(str(row[mun_col_dest]).strip())

            if parts:
                label = " - ".join(parts)
            else:
                label = translate("Dest", lang) + f" {idx}"

            if label == dest_label:
                dest_coords = (row['Latitude'], row['Longitude'])
                break

        if not dest_coords:
            return default_fig

        # Call OSRM for Route
        osrm_url = os.environ.get("OSRM_URL", "http://localhost:5000")
        client = OSRMClient(base_url=osrm_url)
        route_data = client.get_route(origin_coords, dest_coords)

        if not route_data:
             return default_fig

        # Process Geometry (GeoJSON LineString)
        geometry = route_data['geometry']
        lats = [p[1] for p in geometry['coordinates']]
        lons = [p[0] for p in geometry['coordinates']]

        is_fallback = route_data.get('type') == 'fallback'

        # Line Style based on type
        # Note: Scattermapbox does NOT support 'dash' property for lines.
        # We use distinct colors instead.
        line_color = UNB_THEME['UNB_BLUE']
        line_width = 4
        line_name = translate("Rota (OSRM)", lang)

        if is_fallback:
            line_color = '#FF4500' # OrangeRed for visibility
            line_width = 3
            line_name = translate("Rota Estimada (Linha Reta x 1.3)", lang)

        # Create Figure
        fig = go.Figure(go.Scattermapbox(
            mode="lines",
            lon=lons,
            lat=lats,
            line={'width': line_width, 'color': line_color},
            name=line_name
        ))

        # Add Origin Marker
        fig.add_trace(go.Scattermapbox(
            mode="markers",
            lon=[origin_coords[1]],
            lat=[origin_coords[0]],
            marker={'size': 12, 'color': UNB_THEME['UNB_GREEN']},
            name=f"{translate('Origem', lang)}: {origin_name}"
        ))

        # Add Destination Marker
        fig.add_trace(go.Scattermapbox(
            mode="markers",
            lon=[dest_coords[1]],
            lat=[dest_coords[0]],
            marker={'size': 12, 'color': 'red'},
            name=f"{translate('Destino', lang)}: {dest_label}"
        ))

        # Center map on route
        center_lat = np.mean(lats)
        center_lon = np.mean(lons)

        # Simple zoom estimation (could be better)
        # distance in degrees
        lat_diff = max(lats) - min(lats)
        lon_diff = max(lons) - min(lons)
        max_diff = max(lat_diff, lon_diff)

        zoom = 5
        if max_diff < 0.1: zoom = 11
        elif max_diff < 0.5: zoom = 9
        elif max_diff < 2: zoom = 7
        elif max_diff < 5: zoom = 6
        elif max_diff < 10: zoom = 5
        else: zoom = 4

        fig.update_layout(
            mapbox_style="open-street-map",
            mapbox_zoom=zoom,
            mapbox_center={"lat": center_lat, "lon": center_lon},
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            showlegend=True,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )

        return fig

    except Exception as e:
        print(f"Error plotting route: {e}")
        return default_fig



# --- Model Config Callbacks ---

@app.callback(
    Output("container-min-max-options", "style"),
    Input("toggle-min-max-capacity", "value")
)
def toggle_min_max_container(is_active):
    if is_active:
        return {"display": "block"}
    return {"display": "none"}

@app.callback(
    Output("input-max-load", "disabled"),
    Input("toggle-use-reception", "value")
)
def toggle_carga_max_input(use_reception):
    return use_reception

# 16. Run Optimization Model (Background Callback)
@app.callback(
    output=(
        Output("model-output-text", "children"),
        Output("model-output-text", "className"),
        Output("store-model-results", "data"),
        Output("store-model-log", "data"),
        Output("main-tabs", "active_tab", allow_duplicate=True)
    ),
    inputs=[
        Input("btn-run-model", "n_clicks"),
        State('stored-data', 'data'),
        State('store-warehouses', 'data'),
        State('store-prod-warehouses', 'data'),
        State('store-distance-matrix', 'data'),
        State('toggle-detailed-log', 'value'),
        State('toggle-pareto-routes', 'value'),
        State('toggle-min-max-capacity', 'value'),
        State('input-min-load', 'value'),
        State('input-max-load', 'value'),
        State('toggle-use-reception', 'value'),
        State('input-allocation-days', 'value'),
        State('input-min-freight', 'value'),
        State('input-max-freight', 'value'),
        State('store-lang', 'data')
    ],
    background=True,
    running=[
        (Output("btn-run-model", "disabled"), True, False),
        (Output("btn-cancel-model", "disabled"), False, True),
    ],
    cancel=[Input("btn-cancel-model", "n_clicks")],
    prevent_initial_call=True
)
def execute_model(n_clicks, stored_data, stored_warehouses, stored_prod_warehouses, stored_matrix, detailed_log,
                  toggle_pareto, toggle_min_max_capacity, input_min_load, input_max_load, toggle_use_reception, input_allocation_days, input_min_freight, input_max_freight, lang='pt'):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    if not stored_data or not stored_warehouses or not stored_prod_warehouses or not stored_matrix:
        return translate("Erro: Faltam dados. Certifique-se de preencher todas as abas anteriores (Oferta, Armazéns, Relação Produto x Armazém, Matriz de Distâncias) antes de rodar o modelo.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

    try:
        # Load DataFrames
        df_supply = pd.read_json(io.StringIO(stored_data), orient='split')
        df_demand = pd.read_json(io.StringIO(stored_warehouses), orient='split')
        df_compat = pd.read_json(io.StringIO(stored_prod_warehouses), orient='split')
        df_dist = pd.read_json(io.StringIO(stored_matrix), orient='split')

        # Load local CSVs for Freight and Storage
        import os
        data_dir = os.path.join(os.path.dirname(__file__), 'assets', 'data')

        try:
            df_freight = pd.read_csv(os.path.join(data_dir, 'Valor_Tonelada_km.csv'), sep=';', encoding='iso-8859-1')
        except Exception as e:
            print(f"Warning: Could not load Freight CSV: {e}")
            df_freight = pd.DataFrame()

        try:
            df_storage = pd.read_csv(os.path.join(data_dir, 'Tarifa_de_Armazenagem.csv'), sep=';', encoding='iso-8859-1')
        except Exception as e:
            print(f"Warning: Could not load Storage CSV: {e}")
            df_storage = pd.DataFrame()

        # Run model
        log_filename, results_dict = run_optimization_model(
            df_supply=df_supply,
            df_demand=df_demand,
            df_compat=df_compat,
            df_dist=df_dist,
            df_freight=df_freight,
            df_storage=df_storage,
            detailed_log=detailed_log,
            toggle_pareto=toggle_pareto,
            toggle_min_max_capacity=toggle_min_max_capacity,
            input_min_load=input_min_load,
            input_max_load=input_max_load,
            toggle_use_reception=toggle_use_reception,
            input_allocation_days=input_allocation_days,
            input_min_freight=input_min_freight,
            input_max_freight=input_max_freight,
            solver_gap=0.01,
            lang=lang
        )

        # Get execution time
        exec_time = results_dict.get('kpis', {}).get('execution_time', 0.0)
        time_str = translate(" (Tempo de execução:", lang) + f" {exec_time:.2f} " + translate("segundos)", lang) if exec_time else ""

        status_msg = translate("Modelo executado com sucesso!", lang) + time_str if results_dict.get("status") == "optimal" else translate("Falha ao encontrar solução ótima.", lang) + time_str
        status_class = "text-success mt-3 fw-bold" if results_dict.get("status") == "optimal" else "text-warning mt-3 fw-bold"

        # Redirect to results tab on success
        next_tab = "tab-results" if results_dict.get("status") == "optimal" else dash.no_update

        # The log_filename is just a string (filename) and will be stored in store-model-log
        return status_msg, status_class, results_dict, log_filename, next_tab

    except Exception as e:
        import traceback
        err_msg = f"Erro fatal ao executar o modelo:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return err_msg, "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update


# --- Results Callbacks ---

@app.callback(
    [Output("res-kpi-objective", "children"),
     Output("res-kpi-tons", "children"),
     Output("res-kpi-km", "children"),
     Output("res-kpi-freight", "children"),
     Output("res-kpi-storage", "children"),
     Output("table-results-routes", "data"),
     Output("table-results-routes", "columns"),
     Output("results-warnings-container", "children")],
    Input("store-model-results", "data"),
    State("store-lang", "data"),
    prevent_initial_call=True
)
def update_results_kpis_and_table(results_data, lang='pt'):
    if not results_data or results_data.get("status") != "optimal":
        return "R$ 0,00", "0.00", "0.00", "R$ 0,00", "R$ 0,00", [], dash.no_update, dash.no_update

    kpis = results_data.get("kpis", {})
    routes = results_data.get("routes", [])
    warnings = results_data.get("warnings", {})
    objective = results_data.get("objective", 0.0)

    obj_str = f"R$ {objective:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    tons = f"{kpis.get('total_tons', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    kms = f"{kpis.get('total_km', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    freight = f"R$ {kpis.get('total_freight_cost', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    storage = f"R$ {kpis.get('total_storage_cost', 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    has_viagens = False
    table_data = []
    for r in routes:
        row_data = {
            "Origem": r["Origem"],
            "Destino": r["Destino"],
            "Produto": r["Produto"],
            "Quantidade (ton)": round(r["Quantidade (ton)"], 2)
        }

        if "Qtd. de Viagens" in r and r["Qtd. de Viagens"] is not None:
            has_viagens = True
            row_data["Qtd. de Viagens"] = r["Qtd. de Viagens"]

        table_data.append(row_data)

    columns = [
        {'name': translate('Origem', lang), 'id': 'Origem'},
        {'name': translate('Destino', lang), 'id': 'Destino'},
        {'name': translate('Produto', lang), 'id': 'Produto'},
        {'name': translate('Qtd (ton)', lang), 'id': 'Quantidade (ton)'}
    ]

    if has_viagens:
        columns.append({'name': translate('Qtd. de Viagens', lang), 'id': 'Qtd. de Viagens'})

    # Render warnings
    warnings_html = []

    # Legacy fallback for old data
    if isinstance(warnings, list):
        if warnings:
            warnings_list = [html.Li(w) for w in warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-exclamation-triangle-fill me-2"), translate("Atenção: Uso de Capacidade Artificial Detectado!", lang)], className="alert-heading"),
                html.P(translate("O modelo matemático identificou restrições na sua infraestrutura real. Para evitar que o modelo ficasse 'sem solução' e para indicar onde estão os gargalos logísticos, as seguintes capacidades artificiais foram utilizadas (Elas carregam um custo exorbitante no modelo):", lang)),
                html.Hr(),
                html.Ul(warnings_list, className="mb-0")
            ], className="alert-danger-custom shadow-sm mb-3"))
    else:
        # 1. Capacity warnings
        capacity_warnings = warnings.get("capacity", [])
        if capacity_warnings:
            warnings_list = [html.Li(w) for w in capacity_warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-exclamation-triangle-fill me-2"), translate("Armazenamento Insuficiente", lang)], className="alert-heading"),
                html.P(translate("A oferta excedeu a capacidade de armazenamento dos armazéns. Não há um erro no cálculo, mas sim uma limitação física na infraestrutura de armazenamento disponível para os armazéns utilizados.", lang), className="mb-2"),
                html.P(translate("Capacidade Local vs. Global: Somar a capacidade total de todos os armazéns não garante a viabilidade. Se um armazém tiver espaço vazio, mas possuir restrições de recepção diária ou de frete que forcem envios incompatíveis, o modelo pode ser obrigado a estourar a capacidade física de outro armazém para escoar a carga.", lang), className="mb-2"),
                html.P([html.I(className="bi bi-info-circle-fill me-1"), html.B(translate("Suposições do Modelo e Atenção aos Resultados:", lang))], className="fw-bold mb-1"),
                html.P(translate("Estes avisos refletem escolhas matemáticas que o modelo precisou fazer para contornar gargalos logísticos. Para evitar que o sistema ficasse 'sem solução' e mostrar onde a operação trava, o modelo utilizou uma capacidade artificial com um custo (multa) exorbitantemente alto. Portanto, os valores de custo total exibidos nesta página devem ser desconsiderados até que a questão seja resolvida.", lang), className="mb-2"),
                html.Hr(),
                html.Ul(warnings_list, className="mb-3"),
                html.P(html.B(translate("Possíveis Soluções:", lang))),
                html.Ul([
                    html.Li(translate("Aumente a capacidade estática dos armazéns utilizados na aba 'Armazéns'.", lang)),
                    html.Li(translate("Habilite novos armazéns na aba 'Produto e Armazéns' para distribuir melhor a carga.", lang)),
                    html.Li(translate("Reduza a quantidade ofertada na aba 'Oferta'.", lang)),
                    html.Li(translate("Verifique se as restrições de 'Carga mínima de frete' não estão forçando o envio de cargas maiores do que o armazém suporta receber.", lang))
                ], className="mb-0")
            ], className="alert-warning-custom shadow-sm mb-3"))

        # 2. Reception warnings (MILP)
        reception_warnings = warnings.get("reception", [])
        if reception_warnings:
            warnings_list = [html.Li(w) for w in reception_warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-calendar2-x-fill me-2"), translate("Capacidade de Recepção Diária Insuficiente", lang)], className="alert-heading"),
                html.P(translate("O volume alocado superou a capacidade diária de recepção (em toneladas por dia) de um ou mais armazéns dentro do tempo estipulado.", lang), className="mb-2"),
                html.P(translate("Interações de regras: Mesmo que haja muito espaço interno (capacidade estática) sobrando, se a taxa diária de recepção for insuficiente, ocorrerá um gargalo. Além disso, se houver regras rígidas de 'Frete Mínimo', o modelo pode preferir estourar essa recepção diária para garantir que os caminhões não viagem vazios.", lang), className="mb-2"),
                html.P([html.I(className="bi bi-info-circle-fill me-1"), html.B(translate("Suposições do Modelo e Atenção aos Resultados:", lang))], className="fw-bold mb-1"),
                html.P(translate("Estes avisos refletem escolhas matemáticas que o modelo precisou fazer para contornar gargalos logísticos. Para evitar que o sistema ficasse 'sem solução' e mostrar onde a operação trava, o modelo utilizou uma capacidade artificial com um custo (multa) exorbitantemente alto. Portanto, os valores de custo total exibidos nesta página devem ser desconsiderados até que a questão seja resolvida.", lang), className="mb-2"),
                html.Hr(),
                html.Ul(warnings_list, className="mb-3"),
                html.P(html.B(translate("Possíveis Soluções:", lang))),
                html.Ul([
                    html.Li(translate("Aumente a carga máxima de recepção diária ou o número de dias úteis na configuração do modelo.", lang)),
                    html.Li(translate("Se estiver usando a capacidade do banco de dados, certifique-se de que os armazéns escolhidos possuem valores suficientes de recepção na base.", lang)),
                    html.Li(translate("Distribua melhor a oferta entre outros armazéns habilitados.", lang)),
                    html.Li(translate("Verifique se as restrições de 'Carga mínima de frete' não estão obrigando o envio de volumes muito grandes de uma só vez.", lang))
                ], className="mb-0")
            ], className="alert-warning-custom shadow-sm mb-3"))

        # 3. Freight warnings (MILP)
        freight_warnings = warnings.get("freight", [])
        if freight_warnings:
            warnings_list = [html.Li(w) for w in freight_warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-truck-flatbed me-2"), translate("Conflito nas Regras de Frete Mínimo/Máximo", lang)], className="alert-heading"),
                html.P(translate("Existem ofertas não alocadas porque as restrições de frete (carga mínima ou máxima por viagem) inviabilizaram o escoamento total dessa carga para qualquer destino válido.", lang), className="mb-2"),
                html.P(translate("Interações de regras: Isso ocorre quando os dados entram em conflito. Por exemplo, se a sobra de oferta for de 10t, mas a exigência de Frete Mínimo for de 30t, as 10t não podem ser enviadas. O mesmo acontece se um armazém só puder receber 15t diárias, mas o caminhão mínimo carrega 30t: o modelo não tem como fazer a entrega sem quebrar alguma restrição.", lang), className="mb-2"),
                html.P([html.I(className="bi bi-info-circle-fill me-1"), html.B(translate("Suposições do Modelo e Atenção aos Resultados:", lang))], className="fw-bold mb-1"),
                html.P(translate("Estes avisos refletem escolhas matemáticas que o modelo precisou fazer para contornar gargalos logísticos. Para evitar que o sistema ficasse 'sem solução' e mostrar onde a operação trava, o modelo utilizou uma capacidade artificial com um custo (multa) exorbitantemente alto. Portanto, os valores de custo total exibidos nesta página devem ser desconsiderados até que a questão seja resolvida.", lang), className="mb-2"),
                html.Hr(),
                html.Ul(warnings_list, className="mb-3"),
                html.P(html.B(translate("Possíveis Soluções:", lang))),
                html.Ul([
                    html.Li(translate("Reduza a exigência de 'Carga mínima de frete' na configuração do modelo para permitir que as sobras sejam transportadas.", lang)),
                    html.Li(translate("Certifique-se de que as quantidades ofertadas totais são compatíveis com os limites de carga estabelecidos.", lang)),
                    html.Li(translate("Verifique se os armazéns de destino possuem 'Capacidade de Recepção Diária' suficiente para receber ao menos um caminhão do tamanho mínimo exigido.", lang))
                ], className="mb-0")
            ], className="alert-danger-custom shadow-sm mb-3"))

        # 4. Unallocated warnings
        unallocated_warnings = warnings.get("unallocated", [])
        if unallocated_warnings:
            warnings_list = [html.Li(w) for w in unallocated_warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-exclamation-octagon-fill me-2"), translate("Oferta Não Alocada (Sem Rotas)", lang)], className="alert-heading"),
                html.P(translate("Alguns pontos de oferta não possuem rotas válidas para nenhum armazém. Isso geralmente acontece quando uma nova cidade é adicionada na aba de Oferta, mas a matriz de distâncias não foi recalculada.", lang), className="mb-2"),
                html.P([html.I(className="bi bi-info-circle-fill me-1"), html.B(translate("Atenção aos Resultados:", lang))], className="fw-bold mb-1"),
                html.P(translate("Os valores de custo total exibidos nesta página devem ser desconsiderados. Para impedir que o sistema falhasse completamente, foi criada uma rota artificial de escoamento ('não alocada') com um custo unitário (multa) exorbitantemente alto para essas cidades isoladas. Resolva a falta de rotas abaixo e rode o modelo novamente para obter os custos reais.", lang), className="mb-2"),
                html.Hr(),
                html.Ul(warnings_list, className="mb-3"),
                html.P(html.B(translate("Possíveis Soluções:", lang))),
                html.Ul([
                    html.Li(translate("Recalcule a matriz de distâncias para garantir que todas as origens tenham rotas mapeadas.", lang))
                ], className="mb-3"),
                dbc.Button(translate("Ir para a aba Matriz de Distâncias", lang), id="btn-go-to-distance-matrix", color="none", className="btn-primary-custom", size="sm")
            ], className="alert-danger-custom shadow-sm mb-3"))

        # 3. General warnings
        general_warnings = warnings.get("general", [])
        if general_warnings:
            warnings_list = [html.Li(w) for w in general_warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-exclamation-circle-fill me-2"), translate("Aviso Geral", lang)], className="alert-heading"),
                html.Hr(),
                html.Ul(warnings_list, className="mb-0")
            ], className="alert-info-custom shadow-sm mb-3"))

    return obj_str, tons, kms, freight, storage, table_data, columns, warnings_html

@app.callback(
    Output("main-tabs", "active_tab", allow_duplicate=True),
    Input("btn-go-to-distance-matrix", "n_clicks"),
    prevent_initial_call=True
)
def navigate_to_distance_matrix(n_clicks):
    if n_clicks:
        return "tab-distance-matrix"
    return dash.no_update

@app.callback(
    Output("download-results-xlsx", "data"),
    Input("btn-download-results", "n_clicks"),
    State("store-model-results", "data"),
    State('store-lang', 'data'),
    prevent_initial_call=True
)
def download_results(n_clicks, results_data, lang='pt'):
    if not n_clicks or not results_data or results_data.get("status") != "optimal":
        return dash.no_update

    routes = results_data.get("routes", [])
    if not routes:
        return dash.no_update

    df = pd.DataFrame(routes)

    # Remove Qtd. de Viagens if all values are None or missing
    if "Qtd. de Viagens" in df.columns and df["Qtd. de Viagens"].isnull().all():
        df = df.drop(columns=["Qtd. de Viagens"])

    return dcc.send_data_frame(df.to_excel, translate("Optimization_Results.xlsx", lang), index=False)

@app.callback(
    Output("modal-confirm-all-routes", "is_open"),
    [Input("btn-show-all-routes", "n_clicks"),
     Input("btn-cancel-all-routes", "n_clicks"),
     Input("btn-confirm-all-routes", "n_clicks")],
    [State("store-model-results", "data"),
     State("modal-confirm-all-routes", "is_open")],
    prevent_initial_call=True
)
def manage_all_routes_modal(n_show, n_cancel, n_confirm, results_data, is_open):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    if trigger_id == "btn-show-all-routes":
        routes = results_data.get("routes", []) if results_data else []
        if len(routes) > 150:
            return True
        return False

    if trigger_id == "btn-cancel-all-routes":
        return False

    if trigger_id == "btn-confirm-all-routes":
        return False

    return is_open

@app.callback(
    [Output("graph-results-map", "figure"),
     Output("route-details-container", "children")],
    [Input("table-results-routes", "active_cell"),
     Input("btn-show-all-routes", "n_clicks"),
     Input("btn-confirm-all-routes", "n_clicks")],
    [State("table-results-routes", "derived_viewport_data"),
     State("store-model-results", "data"),
     State("stored-data", "data"),
     State("store-warehouses", "data"),
     State("store-lang", "data")],
    prevent_initial_call=True
)
def update_results_map(active_cell, btn_all_routes, btn_confirm_all, table_data, results_data, stored_data, stored_warehouses, lang='pt'):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    # Handle the "Show All" logic depending on route length
    if trigger_id == "btn-show-all-routes":
        routes = results_data.get("routes", []) if results_data else []
        if len(routes) > 150:
            # We must wait for the modal confirmation to actually render
            return dash.no_update, dash.no_update

    # Default map
    default_fig = go.Figure(go.Scattermapbox())
    default_fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=3,
        mapbox_center={"lat": -14.2350, "lon": -51.9253},
        margin={"r": 0, "t": 0, "l": 0, "b": 0}
    )

    if not results_data or results_data.get("status") != "optimal":
        return default_fig, html.P(translate("Resultados indisponíveis.", lang), className="text-muted small")

    if not stored_data or not stored_warehouses:
        return default_fig, html.P(translate("Faltam dados base para renderizar o mapa.", lang), className="text-muted small")

    df_input = pd.read_json(io.StringIO(stored_data), orient='split')
    df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')

    # Pre-calculate coordinate mappings for performance
    # 1. Origin Mappings
    origins_df_map = df_input[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
    city_counts_map = origins_df_map['Cidade'].value_counts()
    duplicates_map = city_counts_map[city_counts_map > 1].index

    origins_df_map['Cidade_Display'] = origins_df_map.apply(
        lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
        if row['Cidade'] in duplicates_map else row['Cidade'],
        axis=1
    )
    origin_mapping = origins_df_map.set_index('Cidade_Display')[['Latitude', 'Longitude']].to_dict('index')

    # 2. Destination Mappings
    lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
    lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)

    if not lat_col or not lon_col:
        mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
        uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)
        if mun_col and uf_col:
            df_warehouses_map = df_warehouses.copy()
            df_warehouses_map['lookup_key'] = df_warehouses_map[mun_col].astype(str) + ' - ' + df_warehouses_map[uf_col].astype(str)
            def get_c(key):
                if key in CITY_LOOKUP: return CITY_LOOKUP[key]
                return {'latitude': None, 'longitude': None}
            coords = df_warehouses_map['lookup_key'].apply(get_c)
            df_warehouses_map['Latitude'] = coords.apply(lambda x: x['latitude'])
            df_warehouses_map['Longitude'] = coords.apply(lambda x: x['longitude'])
            dests_df = df_warehouses_map.dropna(subset=['Latitude', 'Longitude'])
        else:
            dests_df = pd.DataFrame()
    else:
        dests_df = df_warehouses.dropna(subset=[lat_col, lon_col]).copy()
        dests_df = dests_df.rename(columns={lat_col: 'Latitude', lon_col: 'Longitude'})

    dest_mapping = {}
    if not dests_df.empty:
        cda_col = next((c for c in dests_df.columns if 'cda' in str(c).lower()), None)
        name_col = next((c for c in dests_df.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
        mun_col_dest = next((c for c in dests_df.columns if 'munic' in str(c).lower()), None)

        labels = pd.Series("", index=dests_df.index)
        first = True
        for col in [cda_col, name_col, mun_col_dest]:
            if col:
                val = dests_df[col].astype(str).str.strip()
                mask = dests_df[col].notna()
                if first:
                    labels = labels.mask(mask, val)
                    first = False
                else:
                    # For non-empty current labels, append " - " and the new value.
                    # For empty current labels, just set the new value.
                    labels = labels.mask(mask, labels.where(~mask | (labels == ""), labels + " - " + val).where(labels != "", val))

        empty_mask = labels == ""
        if empty_mask.any():
            labels.loc[empty_mask] = [f"Dest {i}" for i in dests_df.index[empty_mask]]

        dests_df['__label'] = labels
        # Handle duplicate labels by keeping the first occurrence
        dests_df = dests_df.drop_duplicates(subset=['__label'])
        dest_mapping = dests_df.set_index('__label')[['Latitude', 'Longitude']].to_dict('index')

    def get_coords_optimized(orig_name, dest_name):
        origin_coords = None
        if orig_name in origin_mapping:
            o = origin_mapping[orig_name]
            origin_coords = (o['Latitude'], o['Longitude'])
        else:
            # Fallback for origin
            fallback_row = df_input[df_input['Cidade'] == orig_name]
            if not fallback_row.empty:
                origin_coords = (fallback_row.iloc[0]['Latitude'], fallback_row.iloc[0]['Longitude'])

        dest_coords = None
        if dest_name in dest_mapping:
            d = dest_mapping[dest_name]
            dest_coords = (d['Latitude'], d['Longitude'])

        return origin_coords, dest_coords

    osrm_url = os.environ.get("OSRM_URL", "http://localhost:5000")
    client = OSRMClient(base_url=osrm_url)

    # Show single route
    if trigger_id == "table-results-routes" and active_cell and table_data:
        row_idx = active_cell['row']
        row_info = table_data[row_idx]
        orig_name = row_info['Origem']
        dest_name = row_info['Destino']
        prod_name = row_info['Produto']

        # Find exact route in results
        route_detail = None
        for r in results_data.get("routes", []):
            if r["Origem"] == orig_name and r["Destino"] == dest_name and r["Produto"] == prod_name:
                route_detail = r
                break

        if not route_detail:
            return default_fig, html.P(translate("Detalhes não encontrados.", lang), className="text-muted small")

        orig_coords, dest_coords = get_coords_optimized(orig_name, dest_name)
        if not orig_coords or not dest_coords:
            return default_fig, html.P(translate("Coordenadas não encontradas para desenhar a rota.", lang), className="text-muted small")

        route_data_osrm = client.get_route(orig_coords, dest_coords)
        if not route_data_osrm:
             return default_fig, html.P(translate("Falha ao calcular a rota no OSRM.", lang), className="text-muted small")

        geometry = route_data_osrm['geometry']
        lats = [p[1] for p in geometry['coordinates']]
        lons = [p[0] for p in geometry['coordinates']]

        fig = go.Figure(go.Scattermapbox(
            mode="lines", lon=lons, lat=lats,
            line={'width': 4, 'color': UNB_THEME['UNB_BLUE']},
            name="Rota"
        ))
        fig.add_trace(go.Scattermapbox(
            mode="markers", lon=[orig_coords[1]], lat=[orig_coords[0]],
            marker={'size': 12, 'color': UNB_THEME['UNB_GREEN']}, name=f"Origem"
        ))
        fig.add_trace(go.Scattermapbox(
            mode="markers", lon=[dest_coords[1]], lat=[dest_coords[0]],
            marker={'size': 12, 'color': 'red'}, name=f"Destino"
        ))

        lat_diff = max(lats) - min(lats)
        lon_diff = max(lons) - min(lons)
        max_diff = max(lat_diff, lon_diff)
        zoom = 5
        if max_diff < 0.1: zoom = 11
        elif max_diff < 0.5: zoom = 9
        elif max_diff < 2: zoom = 7
        elif max_diff < 5: zoom = 6
        elif max_diff < 10: zoom = 5
        else: zoom = 4

        fig.update_layout(
            mapbox_style="open-street-map",
            mapbox_zoom=zoom,
            mapbox_center={"lat": np.mean(lats), "lon": np.mean(lons)},
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            showlegend=False
        )

        # Formatted currency/numbers
        fmt_freight = f"R$ {route_detail['Custo Frete (R$)']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_storage = f"R$ {route_detail['Custo Armazenagem (R$)']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_total = f"R$ {route_detail['Custo Total (R$)']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_qtd = f"{route_detail['Quantidade (ton)']:,.2f} ton".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_dist = f"{route_detail['Distancia (km)']:,.2f} km".replace(",", "X").replace(".", ",").replace("X", ".")

        details_html = dbc.Card([
            dbc.CardHeader(html.H6([html.I(className="bi bi-info-circle-fill me-2"), translate("Detalhes da Rota Selecionada", lang)], className="mb-0 text-white"), className="bg-primary-custom"),
            dbc.ListGroup([
                dbc.ListGroupItem([
                    html.Div([html.I(className="bi bi-geo-alt-fill text-success-custom me-2"), html.Strong(translate("Origem: ", lang))]),
                    html.Span(orig_name, className="text-muted d-block ms-4")
                ], className="py-2"),
                dbc.ListGroupItem([
                    html.Div([html.I(className="bi bi-geo-alt-fill text-danger-custom me-2"), html.Strong(translate("Destino: ", lang))]),
                    html.Span(dest_name, className="text-muted d-block ms-4")
                ], className="py-2"),
                dbc.ListGroupItem([
                    html.Div([html.I(className="bi bi-box-seam-fill text-primary-custom me-2"), html.Strong(translate("Produto: ", lang))]),
                    html.Span(prod_name, className="text-muted d-block ms-4")
                ], className="py-2"),
                dbc.ListGroupItem([
                    html.Div([html.I(className="bi bi-truck text-secondary-custom me-2"), html.Strong(translate("Distância: ", lang))]),
                    html.Span(fmt_dist, className="text-muted d-block ms-4")
                ], className="py-2"),
                dbc.ListGroupItem([
                    html.Div([html.I(className="bi bi-boxes text-info-custom me-2"), html.Strong(translate("Movimentado: ", lang))]),
                    html.Span(fmt_qtd, className="fw-bold text-info-custom d-block ms-4")
                ], className="py-2"),
            ], flush=True),
            dbc.CardFooter([
                html.Div([
                    html.Span(translate("Custo de Frete: ", lang), className="text-muted small"),
                    html.Span(fmt_freight, className="float-end fw-bold text-danger-custom")
                ], className="mb-1"),
                html.Div([
                    html.Span(translate("Custo de Armaz.: ", lang), className="text-muted small"),
                    html.Span(fmt_storage, className="float-end fw-bold text-warning-custom")
                ], className="mb-2"),
                html.Div([
                    html.Span(translate("Custo da Rota:", lang), className="fw-bold"),
                    html.H5(fmt_total, className="float-end fw-bold mb-0 text-success-custom")
                ], className="mt-2 border-top pt-2")
            ], className="bg-light")
        ], className="shadow-sm border-0 h-100")

        return fig, details_html

    # Show all routes
    if trigger_id == "btn-confirm-all-routes" or trigger_id == "btn-show-all-routes" or (trigger_id is None and results_data.get("routes")):
        routes = results_data.get("routes", [])
        if not routes:
            return default_fig, html.P(translate("Nenhuma rota encontrada.", lang), className="text-muted small")

        fig = go.Figure()
        all_lats, all_lons = [], []

        for r in routes:
            orig_coords, dest_coords = get_coords_optimized(r["Origem"], r["Destino"])
            if orig_coords and dest_coords:
                route_data_osrm = client.get_route(orig_coords, dest_coords)
                if route_data_osrm:
                    geometry = route_data_osrm['geometry']
                    lats = [p[1] for p in geometry['coordinates']]
                    lons = [p[0] for p in geometry['coordinates']]
                    all_lats.extend(lats)
                    all_lons.extend(lons)

                    fig.add_trace(go.Scattermapbox(
                        mode="lines", lon=lons, lat=lats,
                        line={'width': 2, 'color': UNB_THEME['UNB_BLUE']},
                        opacity=0.6,
                        hoverinfo='skip'
                    ))
                    # Mark origin
                    fig.add_trace(go.Scattermapbox(
                        mode="markers", lon=[orig_coords[1]], lat=[orig_coords[0]],
                        marker={'size': 8, 'color': UNB_THEME['UNB_GREEN']}, hoverinfo='skip'
                    ))
                    # Mark destination
                    fig.add_trace(go.Scattermapbox(
                        mode="markers", lon=[dest_coords[1]], lat=[dest_coords[0]],
                        marker={'size': 8, 'color': 'red'}, hoverinfo='skip'
                    ))

        if all_lats and all_lons:
            fig.update_layout(
                mapbox_style="open-street-map",
                mapbox_zoom=4,
                mapbox_center={"lat": np.mean(all_lats), "lon": np.mean(all_lons)},
                margin={"r": 0, "t": 0, "l": 0, "b": 0},
                showlegend=False
            )
        else:
            fig = default_fig

        details_html = html.Div([
            html.P(translate("Exibindo malha logística com", lang) + f" {len(routes)} " + translate("rotas realizadas.", lang), className="text-muted mb-2"),
            html.P(translate("Selecione uma rota na tabela para ver os detalhes individuais.", lang), className="text-muted small")
        ])

        return fig, details_html

    return default_fig, html.P(translate("Selecione uma rota na tabela para ver os detalhes.", lang), className="text-muted small")

@app.callback(
    Output("btn-download-log", "disabled"),
    Output("btn-download-log", "className"),
    Input("store-model-log", "data"),
    prevent_initial_call=False
)
def update_download_button_state(log_data):
    if log_data:
        return False, "btn-secondary-custom w-100 mb-3"
    return True, "btn-outline-secondary-custom w-100 mb-3"

import flask
import os
import tempfile

@app.server.route('/download_log/<string:filename>')
def download_log_route(filename):
    # Security: Ensure filename is just a basename, no directory traversal
    filename = os.path.basename(filename)
    log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
    # Get lang from query params
    lang = flask.request.args.get('lang', 'pt')
    download_name = translate('Model_Execution_Log.txt', lang)
    # Use standard flask send_from_directory for secure file serving
    return flask.send_from_directory(log_dir, filename, as_attachment=True, download_name=download_name)

app.clientside_callback(
    """
    function(n_clicks, log_filename, lang) {
        if (n_clicks && log_filename) {
            let userLang = lang || 'pt';
            window.location.href = '/download_log/' + log_filename + '?lang=' + userLang;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("download-model-log", "data"),
    Input("btn-download-log", "n_clicks"),
    State("store-model-log", "data"),
    State("store-lang", "data"),
    prevent_initial_call=True
)

app.clientside_callback(
    """
    function(n_clicks, d1, d2, d3, d4) {
        if (n_clicks && d1 && d2 && d3 && d4) {
            return true;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("modal-model-running", "is_open", allow_duplicate=True),
    Input("btn-run-model", "n_clicks"),
    [State("stored-data", "data"),
     State("store-warehouses", "data"),
     State("store-prod-warehouses", "data"),
     State("store-distance-matrix", "data")],
    prevent_initial_call=True
)

@app.callback(
    Output("modal-model-running", "is_open", allow_duplicate=True),
    [Input("store-model-results", "data"),
     Input("btn-cancel-model", "n_clicks"),
     Input("model-output-text", "children")],
    prevent_initial_call=True
)
def close_model_modal(results_data, cancel_clicks, error_text):
    return False


# --- Demand Callbacks ---

@app.callback(
  Output("demand-input-city", "options"),
  Input("demand-input-city", "search_value"),
  State("demand-input-city", "value")
)
def update_demand_city_options(search_value, value):
  if not search_value:
    if value:
      return [{'label': value, 'value': value}]
    return []

  filtered = [
    {'label': c, 'value': c}
    for c in CITY_OPTIONS
    if search_value.lower() in c.lower()
  ]
  filtered = filtered[:50]

  if value:
    if not any(f['value'] == value for f in filtered):
      filtered.insert(0, {'label': value, 'value': value})

  return filtered


@app.callback(
  [Output('demand-input-lat', 'value'),
   Output('demand-input-lon', 'value')],
  Input('demand-input-city', 'value'),
  prevent_initial_call=True
)
def update_demand_lat_lon(city_value):
  if not city_value or city_value not in CITY_LOOKUP:
    return no_update, no_update

  data = CITY_LOOKUP[city_value]
  return data['latitude'], data['longitude']


@app.callback(
  [Output('demand-input-lat', 'disabled'),
   Output('demand-input-lon', 'disabled'),
   Output('btn-demand-manual-edit', 'children')],
  Input('btn-demand-manual-edit', 'n_clicks'),
  prevent_initial_call=True
)
def toggle_demand_manual_edit(n_clicks):
  if n_clicks % 2 == 1:
    return False, False, "🔓"
  return True, True, "🔒"


@app.callback(
  [Output('demand-input-weight', 'disabled'),
   Output('demand-input-weight', 'value'),
   Output('demand-input-pattern', 'disabled'),
   Output('demand-input-pattern', 'value'),
   Output('demand-input-growth-rate', 'disabled'),
   Output('demand-input-growth-rate', 'value'),
   Output('demand-label-growth-rate', 'style')],
  [Input('demand-toggle-infinite', 'value'),
   Input('demand-input-pattern', 'value')]
)
def handle_demand_input_states(infinite_val, pattern_val):
  # Defaults
  weight_disabled = False
  weight_value = no_update
  pattern_disabled = False
  pattern_value = no_update
  growth_disabled = False
  growth_value = no_update
  growth_style = {'color': UNB_THEME['UNB_GRAY_DARK']}

  if infinite_val:
    weight_disabled = True
    weight_value = None
    pattern_disabled = True
    pattern_value = 'constant'
    growth_disabled = True
    growth_value = None
    growth_style = {'color': '#9ca3af'}
  else:
    if pattern_val == 'linear':
      growth_disabled = False
      growth_style = {'color': UNB_THEME['UNB_GRAY_DARK']}
    else:
      growth_disabled = True
      growth_value = None
      growth_style = {'color': '#9ca3af'}

  return weight_disabled, weight_value, pattern_disabled, pattern_value, growth_disabled, growth_value, growth_style


@app.callback(
  [Output('demand-input-start-year', 'value'),
   Output('demand-input-end-year', 'value')],
  Input('stored-data', 'data')
)
def sync_demand_timespan_values(stored_supply_data):
  if stored_supply_data is None:
    return 2026, 2035
  try:
    df = pd.read_json(io.StringIO(stored_supply_data), orient='split')
    if df.empty:
      return 2026, 2035
    dates = pd.to_datetime(df['Data'], errors='coerce').dropna()
    if not dates.empty:
      return dates.min().year, dates.max().year
    return 2026, 2035
  except Exception as e:
    print(f"Error in sync_demand_timespan_values: {e}")
    return 2026, 2035


@app.callback(
  Output('confirm-clear-demand-modal', 'is_open'),
  [Input('btn-clear-demand-dataset', 'n_clicks'),
   Input('btn-cancel-clear-demand', 'n_clicks'),
   Input('btn-confirm-clear-demand', 'n_clicks')],
  State('confirm-clear-demand-modal', 'is_open'),
  prevent_initial_call=True
)
def toggle_confirm_clear_demand_modal(n_open, n_cancel, n_confirm, is_open):
  ctx = dash.callback_context
  if not ctx.triggered:
    return is_open
  trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
  if trigger_id == 'btn-clear-demand-dataset':
    return True
  return False


@app.callback(
  Output('modal-missing-demand-data', 'is_open'),
  Input('main-tabs', 'active_tab'),
  State('stored-data', 'data')
)
def validate_demand_tab_access(active_tab, stored_supply_data):
  if active_tab != 'tab-demand':
    return False
  if stored_supply_data is None:
    return True
  try:
    df = pd.read_json(io.StringIO(stored_supply_data), orient='split')
    if df.empty:
      return True
    return False
  except:
    return True


@app.callback(
  Output('main-tabs', 'active_tab', allow_duplicate=True),
  Input('btn-confirm-missing-demand', 'n_clicks'),
  prevent_initial_call=True
)
def redirect_to_supply_tab(n_clicks):
  if n_clicks:
    return 'tab-input'
  return no_update


@app.callback(
  Output('demand-input-product', 'options'),
  Input('stored-data', 'data')
)
def populate_demand_product_dropdown(stored_supply_data):
  if stored_supply_data is None:
    return []
  try:
    df = pd.read_json(io.StringIO(stored_supply_data), orient='split')
    if df.empty:
      return []
    products = sorted(df['Produto'].dropna().unique())
    return [{'label': p, 'value': p} for p in products]
  except Exception as e:
    print(f"Error populating product dropdown: {e}")
    return []


@app.callback(
  [Output('stored-demand-data', 'data'),
   Output('error-modal', 'is_open', allow_duplicate=True),
   Output('modal-body-content', 'children', allow_duplicate=True),
   Output('upload-demand-data', 'contents')],
  [Input('upload-demand-data', 'contents'),
   Input('btn-demand-add-row', 'n_clicks'),
   Input('demand-editable-table', 'data_timestamp'),
   Input('btn-confirm-clear-demand', 'n_clicks')],
  [State('upload-demand-data', 'filename'),
   State('stored-demand-data', 'data'),
   State('demand-input-product', 'value'),
   State('demand-input-weight', 'value'),
   State('demand-toggle-infinite', 'value'),
   State('demand-input-city', 'value'),
   State('demand-input-lat', 'value'),
   State('demand-input-lon', 'value'),
   State('demand-editable-table', 'data'),
   State('store-lang', 'data'),
   State('demand-input-pattern', 'value'),
   State('demand-input-growth-rate', 'value'),
   State('demand-filter-product', 'value'),
   State('demand-filter-city', 'value'),
   State('stored-data', 'data')],
  prevent_initial_call=True
)
def update_demand_store(contents, n_add, timestamp, n_confirm_clear, filename, stored_demand_data,
                        prod_val, weight_val, infinite_val, city_val, lat_val, lon_val,
                        table_data, lang, pattern_val, growth_val, filter_prod, filter_city, stored_supply_data):
  ctx = dash.callback_context
  if not ctx.triggered:
    return no_update, no_update, no_update, no_update

  trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

  if trigger_id == 'btn-confirm-clear-demand':
    empty_df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])
    return empty_df.to_json(date_format='iso', orient='split'), False, no_update, None

  if trigger_id == 'upload-demand-data':
    if contents is None:
      return no_update, no_update, no_update, no_update

    try:
      start_yr, end_yr, valid_products = validate_and_parse_supply_data(stored_supply_data, lang)
    except ValueError as ve:
      return no_update, True, str(ve), no_update

    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
      if filename.endswith('.xlsx'):
        df = pd.read_excel(io.BytesIO(decoded))
      elif filename.endswith('.csv'):
        file_bytes = io.BytesIO(decoded)
        df = flex_read_csv(file_bytes)
      else:
        return no_update, True, translate("O arquivo deve ser Excel (.xlsx) ou CSV (.csv).", lang), None

      expected_cols = ["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"]
      if not all(col in df.columns for col in expected_cols):
        return no_update, True, translate("Aviso: O arquivo carregado deve conter exatamente as colunas:", lang) + f" {', '.join(expected_cols)}.", None

      df = df[expected_cols]
      df["Produto"] = df["Produto"].fillna('').astype(str).str.title()

      invalid_prods = set(df["Produto"].dropna().unique()) - valid_products
      if invalid_prods:
        return no_update, True, translate("O arquivo contém produtos não cadastrados na aba Oferta:", lang) + f" {', '.join(invalid_prods)}.", None

      df["Data"] = pd.to_datetime(df["Data"], errors='coerce').dt.strftime('%Y-%m')
      df["Data"] = df["Data"].fillna(f"{start_yr}-01")

      def parse_demand_weight(val):
        if pd.isna(val) or val is None or str(val).strip() == '∞' or str(val).strip() == '':
          return None
        return parse_brazilian_number(val)

      df["Peso (ton)"] = df["Peso (ton)"].apply(parse_demand_weight)

      expected_dates = pd.date_range(
        start=f"{start_yr}-01-01", 
        end=f"{end_yr}-12-01", 
        freq='MS'
      ).strftime('%Y-%m').tolist()

      uploaded_dates = sorted(df["Data"].dropna().unique().tolist())
      if uploaded_dates != expected_dates:
        error_msg = translate("Aviso: O arquivo carregado não condiz com o horizonte temporal travado para esta sessão ({start} a {end}).", lang).format(start=start_yr, end=end_yr)
        return no_update, True, error_msg, None

      return df.to_json(date_format='iso', orient='split'), False, no_update, None
    except Exception as e:
      print(f"Error processing file: {e}")
      return no_update, True, translate("Erro ao processar o arquivo. Verifique se é um arquivo válido.", lang), None

  if trigger_id == 'btn-demand-add-row':
    if not n_add:
      return no_update, no_update, no_update, no_update

    try:
      start_yr, end_yr, valid_products = validate_and_parse_supply_data(stored_supply_data, lang)
    except ValueError as ve:
      return no_update, True, str(ve), no_update

    if stored_demand_data:
      df = pd.read_json(io.StringIO(stored_demand_data), orient='split')
      df = df.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
      })
    else:
      df = pd.DataFrame(columns=["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"])
      df = df.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
      })

    if not prod_val or not city_val:
      return no_update, True, translate("Preencha Produto e Cidade para adicionar.", lang), no_update

    prod_val_normalized = str(prod_val).title()
    if prod_val_normalized not in valid_products:
      return no_update, True, translate("Produto não encontrado na aba de Oferta.", lang), no_update

    if not infinite_val:
      if weight_val is None or str(weight_val).strip() == '':
        return no_update, True, translate("Preencha o peso ou marque demanda infinita.", lang), no_update
      try:
        base_weight = float(weight_val)
      except ValueError:
        return no_update, True, translate("O peso deve ser um valor numérico.", lang), no_update
    else:
      base_weight = None

    try:
      dates_list = pd.date_range(
        start=f"{start_yr}-01-01", 
        end=f"{end_yr}-12-01", 
        freq='MS'
      ).strftime('%Y-%m').tolist()

      growth_rate = 0.0
      if pattern_val == 'linear' and growth_val is not None:
        try:
          growth_rate = float(growth_val) / 100.0
        except ValueError:
          pass

      new_rows = []
      for t, dt_str in enumerate(dates_list):
        if base_weight is None:
          val = None
        elif pattern_val == 'linear':
          val = base_weight * ((1 + growth_rate) ** t)
          val = round(val, 2)
        else:
          val = round(base_weight, 2)

        new_rows.append({
          'Produto': prod_val_normalized,
          'Cidade': city_val,
          'Latitude': lat_val,
          'Longitude': lon_val,
          'Data': dt_str,
          'Peso (ton)': val
        })

      new_rows_df = pd.DataFrame(new_rows)
      new_rows_df = new_rows_df.astype({
        'Produto': 'object',
        'Cidade': 'object',
        'Latitude': 'float64',
        'Longitude': 'float64',
        'Data': 'object',
        'Peso (ton)': 'float64'
      })
      if df.empty:
        df = new_rows_df
      else:
        df = pd.concat([df, new_rows_df], ignore_index=True)
      return df.to_json(date_format='iso', orient='split'), False, no_update, no_update
    except Exception as e:
      print(f"Error adding row: {e}")
      return no_update, True, translate("Erro ao adicionar linha:", lang) + f" {str(e)}", no_update

  if trigger_id == 'demand-editable-table':
    try:
      if table_data is None or not stored_demand_data:
        return no_update, no_update, no_update, no_update

      full_df = pd.read_json(io.StringIO(stored_demand_data), orient='split')

      filtered_indices = full_df.index
      if filter_prod:
        filtered_indices = filtered_indices[full_df.loc[filtered_indices, 'Produto'] == filter_prod]
      if filter_city:
        filtered_indices = filtered_indices[full_df.loc[filtered_indices, 'Cidade'] == filter_city]

      indices_in_table = set()
      for row in table_data:
        idx = row.get('_index')
        if idx is not None:
          indices_in_table.add(idx)
          if idx in full_df.index:
            full_df.at[idx, 'Produto'] = str(row.get('Produto', '')).title()
            full_df.at[idx, 'Cidade'] = row.get('Cidade')
            full_df.at[idx, 'Latitude'] = row.get('Latitude')
            full_df.at[idx, 'Longitude'] = row.get('Longitude')
            full_df.at[idx, 'Data'] = row.get('Data')
            
            w_raw = row.get('Peso (ton)')
            if w_raw == '∞' or pd.isna(w_raw) or w_raw is None or str(w_raw).strip() == '':
              full_df.at[idx, 'Peso (ton)'] = None
            else:
              full_df.at[idx, 'Peso (ton)'] = parse_brazilian_number(w_raw)

      deleted_indices = set(filtered_indices) - indices_in_table
      if deleted_indices:
        full_df = full_df.drop(index=list(deleted_indices))

      return full_df.to_json(date_format='iso', orient='split'), False, no_update, no_update
    except Exception as e:
      print(f"Error updating store from table edit: {e}")
      return no_update, no_update, no_update, no_update

  return no_update, no_update, no_update, no_update


@app.callback(
  [Output('demand-editable-table', 'data'),
   Output('demand-editable-table', 'columns')],
  [Input('stored-demand-data', 'data'),
   Input('main-tabs', 'active_tab'),
   Input('demand-filter-product', 'value'),
   Input('demand-filter-city', 'value')],
  State('store-lang', 'data')
)
def update_demand_table_view(stored_demand_data, active_tab, filter_prod, filter_city, lang='pt'):
  if active_tab != 'tab-demand':
    return no_update, no_update

  if stored_demand_data is None:
    return no_update, no_update

  try:
    df = pd.read_json(io.StringIO(stored_demand_data), orient='split')
    
    df_filtered = df.copy()
    if filter_prod:
      df_filtered = df_filtered[df_filtered['Produto'] == filter_prod]
    if filter_city:
      df_filtered = df_filtered[df_filtered['Cidade'] == filter_city]

    df_filtered['_index'] = df_filtered.index

    records = df_filtered.to_dict('records')
    for row in records:
      w = row.get('Peso (ton)')
      if pd.isna(w) or w is None or w == '':
        row['Peso (ton)'] = '∞'
      else:
        row['Peso (ton)'] = round(float(w), 2)

    expected_cols = ["Produto", "Cidade", "Latitude", "Longitude", "Data", "Peso (ton)"]
    columns = [{'name': translate(col, lang), 'id': col, 'deletable': False, 'renamable': False} for col in expected_cols]
    
    return records, columns
  except Exception as e:
    print(f"Error rendering table: {e}")
    return no_update, no_update


@app.callback(
  [Output('demand-filter-product', 'options'),
   Output('demand-filter-city', 'options'),
   Output('demand-filter-product', 'value'),
   Output('demand-filter-city', 'value')],
  [Input('stored-demand-data', 'data'),
   Input('demand-filter-product', 'value'),
   Input('demand-filter-city', 'value')]
)
def update_demand_filter_options_and_resolve_conflicts(stored_demand_data, selected_prod, selected_city):
  if stored_demand_data is None:
    return [], [], None, None
  try:
    df = pd.read_json(io.StringIO(stored_demand_data), orient='split')
    if df.empty:
      return [], [], None, None

    products = sorted(df['Produto'].dropna().unique().tolist())
    cities = sorted(df['Cidade'].dropna().unique().tolist())

    prod_val = selected_prod
    city_val = selected_city

    if selected_city:
      available_prods = df[df['Cidade'] == selected_city]['Produto'].dropna().unique().tolist()
      prod_options = [{'label': p, 'value': p} for p in sorted(available_prods)]
      if selected_prod and selected_prod not in available_prods:
        prod_val = None
    else:
      prod_options = [{'label': p, 'value': p} for p in products]

    if selected_prod:
      available_cities = df[df['Produto'] == selected_prod]['Cidade'].dropna().unique().tolist()
      city_options = [{'label': c, 'value': c} for c in sorted(available_cities)]
      if selected_city and selected_city not in available_cities:
        city_val = None
    else:
      city_options = [{'label': c, 'value': c} for c in cities]

    return prod_options, city_options, prod_val, city_val
  except Exception as e:
    print(f"Error in demand cross-filtering: {e}")
    return [], [], None, None


@app.callback(
  Output('demand-chart', 'figure'),
  [Input('stored-demand-data', 'data'),
   Input('demand-filter-product', 'value'),
   Input('demand-filter-city', 'value')],
  State('store-lang', 'data')
)
def update_demand_chart(stored_demand_data, filter_prod, filter_city, lang='pt'):
  if stored_demand_data is None:
    return go.Figure()

  try:
    df = pd.read_json(io.StringIO(stored_demand_data), orient='split')
    if df.empty:
      return go.Figure()

    df['dt_parsed'] = pd.to_datetime(df['Data'], errors='coerce')
    df = df.dropna(subset=['dt_parsed'])

    title_suffix = ""
    traces_data = []

    # Get overall unique dates sorted chronologically
    all_dates = sorted(df['Data'].unique())
    if not all_dates:
      return go.Figure()

    if filter_prod and filter_city:
      df_trace = df[(df['Produto'] == filter_prod) & (df['Cidade'] == filter_city)]
      if not df_trace.empty:
        df_grp = df_trace.groupby('Data')['Peso (ton)'].first().reindex(all_dates).reset_index()
        traces_data.append({
          'name': f"{filter_prod} ({filter_city})",
          'x': df_grp['Data'].tolist(),
          'y_raw': df_grp['Peso (ton)'].tolist()
        })
      title_suffix = f" - {filter_prod} ({filter_city})"

    elif filter_prod:
      # Split by City
      df_prod = df[df['Produto'] == filter_prod]
      unique_cities = sorted(df_prod['Cidade'].dropna().unique())
      for city in unique_cities:
        df_trace = df_prod[df_prod['Cidade'] == city]
        df_grp = df_trace.groupby('Data')['Peso (ton)'].first().reindex(all_dates).reset_index()
        traces_data.append({
          'name': city,
          'x': df_grp['Data'].tolist(),
          'y_raw': df_grp['Peso (ton)'].tolist()
        })
      title_suffix = f" - {filter_prod}"

    elif filter_city:
      # Split by Product
      df_city = df[df['Cidade'] == filter_city]
      unique_prods = sorted(df_city['Produto'].dropna().unique())
      for prod in unique_prods:
        df_trace = df_city[df_city['Produto'] == prod]
        df_grp = df_trace.groupby('Data')['Peso (ton)'].first().reindex(all_dates).reset_index()
        traces_data.append({
          'name': prod,
          'x': df_grp['Data'].tolist(),
          'y_raw': df_grp['Peso (ton)'].tolist()
        })
      title_suffix = f" - {filter_city}"

    else:
      # Total Geral: Split by Product, summing only finite values
      unique_prods = sorted(df['Produto'].dropna().unique())
      for prod in unique_prods:
        df_trace = df[df['Produto'] == prod]

        # For "Total Geral", we exclude infinite (None/NaN) nodes from the sum.
        # If all cities have infinite demand for a date, the sum will be None.
        def sum_excluding_infinite(series):
          finite_vals = series.dropna()
          if finite_vals.empty:
            return None
          return finite_vals.sum()

        df_grp = df_trace.groupby('Data')['Peso (ton)'].agg(sum_excluding_infinite).reindex(all_dates).reset_index()
        traces_data.append({
          'name': prod,
          'x': df_grp['Data'].tolist(),
          'y_raw': df_grp['Peso (ton)'].tolist()
        })
      title_suffix = f" - {translate('Total Geral', lang)}"

    if not traces_data:
      return go.Figure()

    # Find the maximum Y value among all finite points in all traces to set threshold height
    all_finite_vals = []
    for td in traces_data:
      for val in td['y_raw']:
        if val is not None and not pd.isna(val):
          all_finite_vals.append(val)

    if all_finite_vals:
      max_y = max(all_finite_vals)
      if max_y <= 0:
        max_y = 100.0
    else:
      max_y = 100.0

    fig = go.Figure()

    # Premium color palette using UNB theme colors and complementary hues
    colors = [
      UNB_THEME['UNB_BLUE'],
      UNB_THEME['UNB_GREEN'],
      '#dc3545', # Red
      '#17a2b8', # Cyan
      '#6f42c1', # Purple
      '#fd7e14', # Orange
      '#20c997', # Teal
      '#e83e8c', # Pink
      '#6c757d'  # Gray
    ]

    has_any_infinite = False
    infinite_traces = []
    max_infinite_y = -1

    for idx, td in enumerate(traces_data):
      trace_color = colors[idx % len(colors)]
      plot_y = []
      hover_text = []
      is_inf_list = []

      # Unique jittered height for this trace's infinite values
      jittered_inf_y = max_y * (1.2 + idx * 0.08)
      has_inf_in_trace = any(val is None or pd.isna(val) for val in td['y_raw'])

      if has_inf_in_trace:
        has_any_infinite = True
        infinite_traces.append((jittered_inf_y, trace_color))
        if jittered_inf_y > max_infinite_y:
          max_infinite_y = jittered_inf_y

      for val in td['y_raw']:
        if val is None or pd.isna(val):
          plot_y.append(jittered_inf_y)
          hover_text.append("∞")
          is_inf_list.append(True)
        else:
          plot_y.append(val)
          hover_text.append(f"{val:,.2f}")
          is_inf_list.append(False)

      marker_colors = [UNB_THEME['UNB_YELLOW_DARK'] if is_inf else trace_color for is_inf in is_inf_list]
      marker_symbols = ['star' if is_inf else 'circle' for is_inf in is_inf_list]
      marker_sizes = [10 if is_inf else 6 for is_inf in is_inf_list]

      fig.add_trace(go.Scatter(
        x=td['x'],
        y=plot_y,
        name=td['name'],
        mode='lines+markers',
        line=dict(color=trace_color, width=3),
        marker=dict(size=marker_sizes, color=marker_colors, symbol=marker_symbols),
        hovertemplate="%{text}<extra></extra>",
        text=hover_text
      ))

    if has_any_infinite:
      for jittered_inf_y, trace_color in infinite_traces:
        if jittered_inf_y == max_infinite_y:
          fig.add_hline(
            y=jittered_inf_y,
            line_dash="dash",
            line_color=trace_color,
            annotation_text="∞ " + translate("Demanda Infinita", lang),
            annotation_position="top right",
            annotation_yshift=10
          )
        else:
          fig.add_hline(
            y=jittered_inf_y,
            line_dash="dash",
            line_color=trace_color
          )

    fig.update_layout(
      title=dict(
        text=translate("Evolução Mensal da Demanda", lang) + title_suffix,
        font=dict(size=14, color=UNB_THEME['UNB_BLUE'], family="'Roboto', sans-serif"),
        x=0.02
      ),
      xaxis=dict(
        title=translate("Mês/Ano", lang),
        gridcolor='#F0F2F5',
        tickangle=-45,
        type='category'
      ),
      yaxis=dict(
        title=translate("Peso (ton)", lang),
        gridcolor='#F0F2F5',
        zeroline=False
      ),
      margin=dict(l=50, r=20, t=50, b=40),
      plot_bgcolor='rgba(0,0,0,0)',
      paper_bgcolor='rgba(0,0,0,0)',
      height=350,
      hovermode='x unified',
      legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1
      )
    )

    return fig
  except Exception as e:
    print(f"Error rendering demand chart: {e}")
    return go.Figure()


@app.callback(
  Output('demand-metrics-store', 'data'),
  Input('stored-demand-data', 'data'),
  State('store-lang', 'data')
)
def update_demand_metrics(stored_demand_data, lang='pt'):
  if stored_demand_data is None:
    return {'weight': 0, 'count': 0}

  try:
    df = pd.read_json(io.StringIO(stored_demand_data), orient='split')

    total_weight = 0
    unique_products = 0

    if not df.empty:
      if "Peso (ton)" in df.columns:
        try:
          total_weight = df["Peso (ton)"].dropna().sum()
        except Exception as e:
          print(f"Error calculating demand weight: {e}")
          total_weight = 0

      if "Produto" in df.columns:
        unique_products = df["Produto"].dropna().nunique()

    return {'weight': float(total_weight), 'count': int(unique_products)}
  except Exception as e:
    print(f"Error calculating demand metrics: {e}")
    return {'weight': 0, 'count': 0}


app.clientside_callback(
  """
  function(data, lang) {
      if (!data) return window.dash_clientside.no_update;

      const locale = lang === 'pt' ? 'pt-BR' : 'en-US';

      const animate = (id, endValue, isFloat) => {
          const el = document.getElementById(id);
          if (!el) return;

          let startValue = parseFloat(el.dataset.rawValue) || 0;
          const duration = 1000;
          const startTime = performance.now();

          const step = (currentTime) => {
              const elapsed = currentTime - startTime;
              const progress = Math.min(elapsed / duration, 1);

              const ease = 1 - Math.pow(1 - progress, 3);

              const current = startValue + (endValue - startValue) * ease;

              if (isFloat) {
                  el.innerText = current.toLocaleString(locale, {minimumFractionDigits: 2, maximumFractionDigits: 2});
              } else {
                  el.innerText = Math.round(current).toLocaleString(locale);
              }

              if (progress < 1) {
                  requestAnimationFrame(step);
              } else {
                  if (isFloat) {
                      el.innerText = endValue.toLocaleString(locale, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                  } else {
                      el.innerText = endValue.toLocaleString(locale);
                  }
                  el.dataset.rawValue = endValue;
              }
          };

          requestAnimationFrame(step);
      };

      animate('demand-metric-total-weight', data.weight, true);
      animate('demand-metric-unique-products', data.count, false);

      return window.dash_clientside.no_update;
  }
  """,
  Output('demand-metric-total-weight', 'id'),
  Input('demand-metrics-store', 'data'),
  State('store-lang', 'data')
)


@app.callback(
  Output("download-demand-xlsx", "data"),
  Input("btn-demand-download", "n_clicks"),
  State('stored-demand-data', 'data'),
  State('store-lang', 'data'),
  prevent_initial_call=True,
)
def download_demand_data(n_clicks, stored_demand_data, lang='pt'):
  if not n_clicks:
    return no_update

  if not stored_demand_data:
    return no_update

  df = pd.read_json(io.StringIO(stored_demand_data), orient='split')
  
  df_export = df.copy()
  if "Peso (ton)" in df_export.columns:
    df_export["Peso (ton)"] = df_export["Peso (ton)"].fillna('∞')
      
  return dcc.send_data_frame(df_export.to_excel, translate("Edited_Demand.xlsx", lang), index=False)


def view():
    # Use environment variable to determine if we are in Docker or dev
    # '0.0.0.0' allows external access (from host to docker container)
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host=host, port=port)
