import base64
import io
import os
import sys
import tempfile
import time
import traceback
import unicodedata
import uuid
import pandas as pd
from dash import Dash, dcc, html, Input, Output, State, dash_table, no_update
import dash
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME
from src.view.pages.distance_matrix import get_tab_distance_matrix_layout
from src.view.pages.model_config import get_tab_model_config_layout
from src.view.pages.costs import get_tab_costs_layout
from src.view.pages.results import get_tab_results_layout, get_tab_stochastic_results_layout
from src.view.pages.warehouses import get_tab_warehouses_layout
from src.view.pages.prediction import get_tab_prediction_layout
from src.logic.prediction import (
    prepare_time_series,
    calculate_metrics,
    get_quality_badge,
    forecast_sarima,
    forecast_prophet,
    forecast_xgboost,
    forecast_lstm
)
from src.logic.osrm import OSRMClient
from src.logic.optimization import run_deterministic_model, run_stochastic_model, compute_evpi_vss
from src.logic.i18n import translate
from src.logic.utils import validate_and_parse_supply_data, safe_parse_numeric
import dash
import time
from dash import DiskcacheManager
import diskcache
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import requests
import json

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

def strip_accents(text):
    if not isinstance(text, str):
        return text
    return "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

# --- Data Loading ---
try:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'data')
    MUNICIPIOS_PATH = os.path.join(DATA_DIR, 'municipios.csv')
    ESTADOS_PATH = os.path.join(DATA_DIR, 'estados.csv')
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

def serve_layout(lang="pt"):
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
                                    html.Small(translate("Otimização de Localização de Instalações", lang), className="navbar-subtext", style={"whiteSpace": "nowrap"}),
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
                    html.P(translate("Bem-vindo ao SiloDSS! Este aplicativo foi desenvolvido para otimizar a alocação de produtos em armazéns, minimizando os custos de frete e armazenagem. Siga o fluxo de 1 a 10 nas abas para obter os resultados da operação:", lang), className="mb-4 text-muted"),

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
                            html.H5([html.Span("3.", className="badge bg-info-custom rounded-pill me-2"), translate("Previsão", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Utilize modelos de inteligência artificial ou séries temporais estatísticas (como Prophet, SARIMA, XGBoost e LSTM) para prever a oferta e a demanda futura com base nos dados históricos fornecidos, gerando um panorama preditivo completo.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("4.", className="badge bg-info-custom rounded-pill me-2"), translate("Armazéns", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Gerencie os armazéns que receberão os produtos. Defina-os como existentes (informando capacidade, tipo, etc.) ou possíveis candidatos de abertura. Carregue uma planilha ou adicione os dados manualmente e confira a localização no mapa interativo.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("5.", className="badge bg-info-custom rounded-pill me-2"), translate("Produto e Armazéns", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Defina a compatibilidade. Indique quais tipos de armazéns podem estocar cada tipo de produto marcando ou desmarcando as caixas na tabela.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("6.", className="badge bg-info-custom rounded-pill me-2"), translate("Custos", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Configure as tarifas de armazenamento (público e privado) para cada produto e o valor do frete (tonelada/km) para cada estado. Você pode usar os valores padrão ou inserir novos, e as alterações nas tabelas são salvas automaticamente.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("7.", className="badge bg-info-custom rounded-pill me-2"), translate("Matriz de Distâncias", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("O sistema calcula todas as rotas possíveis entre as cidades de origem e os armazéns disponíveis. Clique em 'Calcular Matriz de Distâncias' para iniciar e aguarde a conclusão. Em seguida, você também pode visualizar qualquer rota diretamente no mapa interativo abaixo da tabela.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("8.", className="badge bg-info-custom rounded-pill me-2"), translate("Configuração do Modelo", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Configure as restrições da operação (como limites de recepção, regras de frete e uso do Princípio de Pareto) e rode o modelo de otimização matemática.", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("9.", className="badge bg-info-custom rounded-pill me-2"), translate("Resultados", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Visualize as métricas globais da operação, explore as rotas sugeridas no mapa interativo e baixe o relatório final completo (Excel).", lang), className="mb-0 text-muted")
                        ], className="border-0 border-bottom py-3"),

                        dbc.ListGroupItem([
                            html.H5([html.Span("10.", className="badge bg-info-custom rounded-pill me-2"), translate("Comparação de Cenários", lang)], className="mb-1 fw-bold d-flex align-items-center"),
                            html.P(translate("Compare o desempenho físico e financeiro da rede sob diferentes cenários de incerteza (otimista, esperado, pessimista) e avalie a viabilidade de decisões robustas (como EVPI e VSS) geradas pelo modelo estocástico.", lang), className="mb-0 text-muted")
                        ], className="border-0 py-3"),
                    ], flush=True),
                ]
            ),
            dbc.ModalFooter(
                dbc.Button(translate("Entendi, vamos começar!", lang), id="close-help-modal", color="none", className="btn-info-custom", n_clicks=0)
            ),
        ],
        id="modal-help",
        size="xl",
        is_open=False,
        centered=True,
        scrollable=True
    )

    # 2. Tabs
    tabs = dbc.Tabs(
        [
            dbc.Tab(label=translate("Oferta", lang), tab_id="tab-input", label_class_name="px-4"),
            dbc.Tab(label=translate("Demanda", lang), tab_id="tab-demand", label_class_name="px-4"),
            dbc.Tab(label=translate("Previsão", lang), tab_id="tab-prediction", label_class_name="px-4"),
            dbc.Tab(label=translate("Armazéns", lang), tab_id="tab-warehouses", label_class_name="px-4"),
            dbc.Tab(label=translate("Produto e Armazéns", lang), tab_id="tab-prod-warehouses", label_class_name="px-4"),
            dbc.Tab(label=translate("Custos", lang), tab_id="tab-costs", label_class_name="px-4"),
            dbc.Tab(label=translate("Matriz de Distâncias", lang), tab_id="tab-distance-matrix", label_class_name="px-4"),
            dbc.Tab(label=translate("Configuração do Modelo", lang), tab_id="tab-config", label_class_name="px-4"),
            dbc.Tab(label=translate("Resultados", lang), tab_id="tab-results", label_class_name="px-4"),
            dbc.Tab(label=translate("Comparação de Cenários", lang), tab_id="tab-stochastic-results", label_class_name="px-4"),
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
                                html.Span(translate('Arraste e solte ou', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}, className="me-1"),
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
                                html.Span(translate('Arraste e solte ou', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}, className="me-1"),
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
    # (Removed inline get_tab_warehouses_layout; now imported from src.view.pages.warehouses)

    # 5. Tab Product and Warehouses Content
    def get_tab_prod_warehouses_layout():
        # Upload Card
        upload_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Carregar Estoque Inicial", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-init-inv-upload", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Carregue uma planilha (.xlsx ou .csv) contendo as colunas CDA, Produto e Estoque Inicial (t).", lang),
                            target="help-init-inv-upload",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dcc.Upload(
                            id="upload-initial-inventory-data",
                            children=html.Div([
                                html.Div([
                                    html.Span("📂 ", style={"fontSize": "1.2rem", "marginRight": "4px"}),
                                    html.Span(translate("Arraste e solte ou", lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}, className="me-1"),
                                    html.A(translate("Selecione", lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                ], className="d-flex align-items-center justify-content-center"),
                                html.Div(translate("Formatos: .xlsx, .csv", lang), className="text-muted small mt-1")
                            ]),
                            className="upload-box",
                            style={"height": "70px", "padding": "6px"},
                            multiple=False,
                            accept=".xlsx, .csv"
                        )
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom mb-16"
        )

        # Add Initial Inventory Card
        add_init_inv_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Configurar Estoque Inicial", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-init-inv-add", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Escolha o produto e o armazém para adicionar ou modificar o estoque inicial.", lang),
                            target="help-init-inv-add",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    dbc.Label(translate("Produto", lang), className="fw-bold small mb-1 me-2"),
                                ], className="d-flex align-items-center"),
                                dcc.Dropdown(
                                    id="input-init-inv-product",
                                    options=[],
                                    placeholder=translate("Selecione o produto...", lang),
                                    className="mb-16"
                                )
                            ], width=12),
                            dbc.Col([
                                html.Div([
                                    dbc.Label(translate("Armazém", lang), className="fw-bold small mb-1 me-2"),
                                ], className="d-flex align-items-center"),
                                dcc.Dropdown(
                                    id="input-init-inv-warehouse",
                                    options=[],
                                    placeholder=translate("Selecione o armazém...", lang),
                                    className="mb-16"
                                )
                            ], width=12),
                            dbc.Col([
                                html.Div([
                                    dbc.Label(translate("Estoque Inicial (t)", lang), className="fw-bold small mb-1 me-2"),
                                ], className="d-flex align-items-center"),
                                dbc.Input(
                                    id="input-init-inv-amount",
                                    type="number",
                                    min=0,
                                    placeholder=translate("Ex: 100", lang),
                                    className="mb-16"
                                )
                            ], width=12),
                            dbc.Col([
                                dbc.Button(
                                    translate("Adicionar Estoque Inicial", lang),
                                    id="btn-add-initial-inventory",
                                    color="none",
                                    className="btn-primary-custom w-100 mt-8"
                                )
                            ], width=12)
                        ])
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom mb-16"
        )

        # Export Card
        export_card = dbc.Card(
            [
                dbc.CardHeader(
                    html.Div([
                        html.Span(translate("Exportar Estoque Inicial", lang), className="me-2"),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-init-inv-export", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Exporta os dados de estoque inicial configurados em formato Excel.", lang),
                            target="help-init-inv-export",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center"),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Button(
                            translate("Baixar Planilha (.xlsx)", lang),
                            id="btn-export-initial-inventory-xlsx",
                            color="none",
                            className="btn-success-custom w-100"
                        )
                    ],
                    className="card-body-custom"
                ),
            ],
            className="card-custom"
        )

        # Table Card (Initial Inventory)
        initial_inventory_table_card = dbc.Card(
            [
                dbc.CardHeader(
                    translate("Tabela de Estoque Inicial", lang),
                    className="card-header-custom"
                ),
                dbc.CardBody(
                    [
                        dbc.Spinner(
                            html.Div(id="table-initial-inventory-container", children=[
                                dash_table.DataTable(
                                    id="table-initial-inventory",
                                    data=[],
                                    columns=[
                                        {
                                            'name': translate(col, lang), 
                                            'id': col, 
                                            'deletable': False, 
                                            'renamable': False,
                                            'editable': col == 'Estoque Inicial (t)'
                                        } for col in ['CDA', 'Armazenador', 'Município', 'Cap. Estática (t)', 'Produto', 'Estoque Inicial (t)']
                                    ],
                                    editable=True,
                                    row_deletable=True,
                                    page_size=12,
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
                            ], className="h-100 d-flex flex-column"),
                            spinner_class_name="text-primary-custom"
                        )
                    ],
                    className="card-body-custom d-flex flex-column flex-grow-1"
                ),
            ],
            className="card-custom h-100 d-flex flex-column"
        )

        # Existing Product vs Warehouse Type Table Card
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
            style={"minHeight": "400px"}
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
                    # Top section: Initial Inventory
                    dbc.Col([
                        upload_card,
                        add_init_inv_card,
                        export_card
                    ], width=12, lg=3, className="d-flex flex-column mb-24"),
                    dbc.Col([
                        initial_inventory_table_card
                    ], width=12, lg=9, className="d-flex flex-column mb-24"),
                ],
                className="align-items-stretch"
            ),
            dbc.Row(
                [
                    # Bottom section: Product x Warehouse Type
                    dbc.Col(table_card, width=12, className="mb-24")
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

    # Pre-render all tab layouts to ensure IDs exist for callbacks
    tab1_layout = get_tab1_layout()
    tab_demand_layout = get_tab_demand_layout()
    tab_prediction_layout = get_tab_prediction_layout(lang)
    tab2_layout = get_tab_warehouses_layout(lang, city_options=CITY_OPTIONS)
    tab_prod_warehouses_layout = get_tab_prod_warehouses_layout()
    tab_costs_layout = get_tab_costs_layout(lang)
    tab_distance_matrix_layout = get_tab_distance_matrix_layout(lang)
    tab_config_layout = get_tab_model_config_layout(lang)
    tab_results_layout = get_tab_results_layout(lang)
    tab_stochastic_results_layout = get_tab_stochastic_results_layout(lang)

    content_container = html.Div(
        [
            html.Div(id="tab-input-container", children=tab1_layout, style={"display": "block"}),
            html.Div(id="tab-demand-container", children=tab_demand_layout, style={"display": "none"}),
            html.Div(id="tab-prediction-container", children=tab_prediction_layout, style={"display": "none"}),
            html.Div(id="tab-warehouses-container", children=tab2_layout, style={"display": "none"}),
            html.Div(id="tab-prod-warehouses-container", children=tab_prod_warehouses_layout, style={"display": "none"}),
            html.Div(id="tab-costs-container", children=tab_costs_layout, style={"display": "none"}),
            html.Div(id="tab-distance-matrix-container", children=tab_distance_matrix_layout, style={"display": "none"}),
            html.Div(id="tab-config-container", children=tab_config_layout, style={"display": "none"}),
            html.Div(id="tab-results-container", children=tab_results_layout, style={"display": "none"}),
            html.Div(id="tab-stochastic-results-container", children=tab_stochastic_results_layout, style={"display": "none"}),
        ],
        id="tabs-content"
    )

    initial_store_df = pd.DataFrame(columns=['Produto', 'Cidade', 'Latitude', 'Longitude', 'Data', 'Peso (ton)'])
    initial_init_inv_df = pd.DataFrame(columns=['CDA', 'Armazenador', 'Município', 'Produto', 'Estoque Inicial (t)'])

    return html.Div(
        [
            dcc.Store(id='stored-data', data=initial_store_df.to_json(date_format='iso', orient='split')),
            dcc.Store(id='stored-demand-data', data=initial_store_df.to_json(date_format='iso', orient='split')),
            dcc.Store(id='store-initial-inventory', data=initial_init_inv_df.to_json(date_format='iso', orient='split')),
            dcc.Store(id='metrics-store', data={'weight': 0, 'count': 0}),
            dcc.Store(id='demand-metrics-store', data={'weight': 0, 'count': 0}),
            dcc.Store(id='store-warehouses'),
            dcc.Store(id='store-prod-warehouses'),
            dcc.Store(id='store-costs-storage'),
            dcc.Store(id='store-costs-freight'),
            dcc.Store(id='store-distance-matrix'),
            dcc.Store(id='store-model-results'),
            dcc.Store(id='store-model-log'),
            dcc.Store(id='store-active-log-filename'),
            dcc.Store(id='store-prediction-results'),
            dcc.Store(id='store-forecast-residuals'),
            dcc.Store(id='store-historical-max-dates'),
            dcc.Store(id='store-gurobi-lic', storage_type='session'),
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
    dcc.Location(id='url', refresh=True),
    dcc.Store(id='store-lang', storage_type='local', data='pt'),
    dcc.Store(id='store-pending-lang', storage_type='memory', data=None),

    dcc.Download(id='download-warehouses-xlsx'),
    dcc.Download(id='download-warehouses-template'),
    dcc.Download(id='download-dataframe-xlsx'),
    dcc.Download(id='download-demand-xlsx'),
    dcc.Download(id='download-prediction-xlsx'),
    dcc.Download(id='download-storage-csv'),
    dcc.Download(id='download-freight-csv'),
    dcc.Download(id='download-matrix-xlsx'),
    dcc.Download(id='download-model-log'),
    dcc.Download(id='download-results-xlsx'),
    dcc.Download(id='download-initial-inventory'),

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
     Output('store-pending-lang', 'data'),
     Output('url', 'href')],
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
        return no_update, False, no_update, no_update, no_update, no_update, no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Handle language selector click
    if trigger_id in ('lang-pt', 'lang-en'):
        clicks = pt_clicks if trigger_id == 'lang-pt' else en_clicks
        if not clicks:
            return no_update, False, no_update, no_update, no_update, no_update, no_update, no_update
            
        target_lang = 'pt' if trigger_id == 'lang-pt' else 'en'
        
        # If the clicked language is the same as the current language, do nothing
        if target_lang == current_lang:
            return no_update, False, no_update, no_update, no_update, no_update, None, no_update

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

            return no_update, True, title, body, cancel_label, confirm_label, target_lang, no_update
        else:
            # Switch language immediately since there is no data to lose
            return target_lang, False, no_update, no_update, no_update, no_update, None, '/'

    # Handle modal confirmation
    if trigger_id == 'btn-confirm-lang-switch':
        if not confirm_clicks:
            return no_update, False, no_update, no_update, no_update, no_update, no_update, no_update
        if pending_lang:
            return pending_lang, False, no_update, no_update, no_update, no_update, None, '/'
        return no_update, False, no_update, no_update, no_update, no_update, None, no_update

    # Handle modal cancellation or closing
    if trigger_id == 'btn-cancel-lang-switch':
        if not cancel_clicks:
            return no_update, False, no_update, no_update, no_update, no_update, no_update, no_update
        return no_update, False, no_update, no_update, no_update, no_update, None, no_update

    return no_update, False, no_update, no_update, no_update, no_update, no_update, no_update

@app.callback(
    Output('page-content', 'children'),
    [Input('store-lang', 'data')],
    prevent_initial_call=True
)
def render_page(lang):
    if not lang:
        lang = 'pt'
    return serve_layout(lang)




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
     Output("tab-prediction-container", "style"),
     Output("tab-warehouses-container", "style"),
     Output("tab-prod-warehouses-container", "style"),
     Output("tab-costs-container", "style"),
     Output("tab-distance-matrix-container", "style"),
     Output("tab-config-container", "style"),
     Output("tab-results-container", "style"),
     Output("tab-stochastic-results-container", "style")],
    Input("main-tabs", "active_tab")
)
def render_content(active_tab):
    base_styles = [{"display": "none"}] * 10

    if active_tab == 'tab-input':
        base_styles[0] = {"display": "block"}
    elif active_tab == 'tab-demand':
        base_styles[1] = {"display": "block"}
    elif active_tab == 'tab-prediction':
        base_styles[2] = {"display": "block"}
    elif active_tab == 'tab-warehouses':
        base_styles[3] = {"display": "block"}
    elif active_tab == 'tab-prod-warehouses':
        base_styles[4] = {"display": "block"}
    elif active_tab == 'tab-costs':
        base_styles[5] = {"display": "block"}
    elif active_tab == 'tab-distance-matrix':
        base_styles[6] = {"display": "block"}
    elif active_tab == 'tab-config':
        base_styles[7] = {"display": "block"}
    elif active_tab == 'tab-results':
        base_styles[8] = {"display": "block"}
    elif active_tab == 'tab-stochastic-results':
        base_styles[9] = {"display": "block"}

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

def process_uploaded_warehouses(contents, filename, lang='pt'):
  content_type, content_string = contents.split(',')
  decoded = base64.b64decode(content_string)
  file_bytes = io.BytesIO(decoded)
  try:
    if filename.endswith('.csv'):
      df = flex_read_csv(file_bytes)
    else:
      df = pd.read_excel(file_bytes)
  except Exception as e:
    raise ValueError(f"Error reading file: {e}")

  cols_map = {}
  for col in df.columns:
    col_lower = strip_accents(str(col).lower().strip())
    if 'status' in col_lower or 'classif' in col_lower:
      cols_map['Status'] = col
    elif 'cda' in col_lower:
      cols_map['CDA'] = col
    elif 'munic' in col_lower or 'cidade' in col_lower or 'city' in col_lower:
      cols_map['Município'] = col
    elif 'uf' in col_lower or 'estado' in col_lower or 'state' in col_lower:
      cols_map['UF'] = col
    elif 'lat' in col_lower:
      cols_map['Latitude'] = col
    elif 'lon' in col_lower:
      cols_map['Longitude'] = col
    elif 'armazenador' in col_lower or 'owner' in col_lower or 'provedor' in col_lower or 'provider' in col_lower:
      cols_map['Armazenador'] = col
    elif 'tipo' in col_lower or 'type' in col_lower:
      cols_map['Tipo'] = col
    elif 'cap' in col_lower and 'max' in col_lower:
      cols_map['Cap. Estática Máxima (t)'] = col
    elif 'cap' in col_lower and ('est' in col_lower or 'capacidade' in col_lower or 'total' in col_lower or 'static' in col_lower):
      cols_map['Cap. Estática (t)'] = col
    elif 'recep' in col_lower or 'receb' in col_lower:
      cols_map['Cap. Recepção (t)'] = col
    elif 'exped' in col_lower or 'envio' in col_lower:
      cols_map['Cap. Expedição (t)'] = col
    elif ('custo' in col_lower and ('abert' in col_lower or 'open' in col_lower)) or 'opening' in col_lower:
      cols_map['Custo de Abertura ($)'] = col
    elif 'transb' in col_lower or 'transship' in col_lower:
      cols_map['Custo de Transbordo ($/t)'] = col

  new_df = pd.DataFrame()
  
  if 'Status' in cols_map:
    new_df['Status'] = df[cols_map['Status']].astype(str).str.strip().apply(
      lambda x: 'Candidato' if 'candidato' in x.lower() or 'candidate' in x.lower() else 'Existente'
    )
  else:
    new_df['Status'] = 'Existente'

  if 'Município' in cols_map:
    new_df['Município'] = df[cols_map['Município']].fillna('').astype(str).str.strip()
  else:
    new_df['Município'] = ''

  if 'UF' in cols_map:
    new_df['UF'] = df[cols_map['UF']].fillna('').astype(str).str.strip().str.upper()
  else:
    new_df['UF'] = ''

  if 'Latitude' in cols_map:
    new_df['Latitude'] = pd.to_numeric(df[cols_map['Latitude']], errors='coerce')
  else:
    new_df['Latitude'] = np.nan

  if 'Longitude' in cols_map:
    new_df['Longitude'] = pd.to_numeric(df[cols_map['Longitude']], errors='coerce')
  else:
    new_df['Longitude'] = np.nan

  if 'Armazenador' in cols_map:
    new_df['Armazenador'] = df[cols_map['Armazenador']].fillna('').astype(str).str.strip()
  else:
    new_df['Armazenador'] = ''

  if 'Tipo' in cols_map:
    new_df['Tipo'] = df[cols_map['Tipo']].fillna('').astype(str).str.strip()
  else:
    new_df['Tipo'] = ''

  for col_key, col_target in [('Cap. Estática (t)', 'Cap. Estática (t)'),
                              ('Cap. Estática Máxima (t)', 'Cap. Estática Máxima (t)'),
                              ('Cap. Recepção (t)', 'Cap. Recepção (t)'),
                              ('Cap. Expedição (t)', 'Cap. Expedição (t)'),
                              ('Custo de Abertura ($)', 'Custo de Abertura ($)'),
                              ('Custo de Transbordo ($/t)', 'Custo de Transbordo ($/t)')]:
    if col_key in cols_map:
      new_df[col_target] = df[cols_map[col_key]].apply(parse_brazilian_number)
    else:
      if col_target == 'Cap. Estática Máxima (t)' and 'Cap. Estática (t)' in new_df.columns:
        new_df[col_target] = new_df['Cap. Estática (t)']
      else:
        new_df[col_target] = 0.0

  if 'CDA' in cols_map:
    new_df['CDA'] = df[cols_map['CDA']].fillna('').astype(str).str.strip()
    for idx, val in enumerate(new_df['CDA']):
      if not val:
        new_df.at[idx, 'CDA'] = f"WH-{idx+1:03d}"
  else:
    new_df['CDA'] = [f"WH-{i+1:03d}" for i in range(len(df))]

  col_names = list(new_df.columns)
  mun_idx = col_names.index('Município')
  uf_idx = col_names.index('UF')
  lat_idx = col_names.index('Latitude')
  lon_idx = col_names.index('Longitude')
  
  lats = []
  lons = []
  
  try:
    for row in new_df.itertuples(index=False):
      lat = row[lat_idx]
      lon = row[lon_idx]
      mun = row[mun_idx]
      uf = row[uf_idx]
      
      if pd.isna(lat) or pd.isna(lon):
        key = f"{mun} - {uf}"
        if key in CITY_LOOKUP:
          lat = CITY_LOOKUP[key]['latitude']
          lon = CITY_LOOKUP[key]['longitude']
      
      lats.append(lat)
      lons.append(lon)
  except (ValueError, IndexError):
    lats = []
    lons = []
    for idx, row in new_df.iterrows():
      lat = row['Latitude']
      lon = row['Longitude']
      mun = row['Município']
      uf = row['UF']
      
      if pd.isna(lat) or pd.isna(lon):
        key = f"{mun} - {uf}"
        if key in CITY_LOOKUP:
          lat = CITY_LOOKUP[key]['latitude']
          lon = CITY_LOOKUP[key]['longitude']
      
      lats.append(lat)
      lons.append(lon)

  new_df['Latitude'] = lats
  new_df['Longitude'] = lons

  cands_mask = new_df['Status'] == 'Candidato'
  new_df.loc[cands_mask, ['Armazenador', 'Tipo']] = ''
  new_df.loc[cands_mask, ['Cap. Estática (t)', 'Cap. Recepção (t)', 'Cap. Expedição (t)']] = 0.0

  exist_mask = new_df['Status'] == 'Existente'
  if 'Custo de Abertura ($)' in new_df.columns:
    new_df.loc[exist_mask, 'Custo de Abertura ($)'] = 0.0
  if 'Cap. Estática Máxima (t)' in new_df.columns:
    new_df.loc[exist_mask, 'Cap. Estática Máxima (t)'] = 0.0

  # Verification for all warehouses in the uploaded file
  for idx, row in new_df.iterrows():
    st = str(row['Status']).strip().lower()
    is_existing = ('existente' in st or 'existing' in st)
    
    mun = str(row['Município']).strip()
    if not mun:
      raise ValueError(translate("Erro no arquivo: Município não pode ser vazio.", lang))

    if is_existing:
      prov = str(row['Armazenador']).strip()
      if not prov:
        raise ValueError(translate("Erro no arquivo: Para armazéns Existentes, o campo 'Armazenador' deve ser preenchido.", lang))
      
      t_val = str(row['Tipo']).strip()
      if not t_val:
        raise ValueError(translate("Erro no arquivo: Para armazéns Existentes, o campo 'Tipo' deve ser preenchido.", lang))
      
      # capacities
      for cap_col_name, cap_label in [
          ('Cap. Estática (t)', translate("Capacidade Estática", lang)),
          ('Cap. Recepção (t)', translate("Capacidade de Recepção", lang)),
          ('Cap. Expedição (t)', translate("Capacidade de Expedição", lang))
      ]:
        val = row[cap_col_name]
        if pd.isna(val) or val is None or str(val).strip() == '':
          raise ValueError(translate("Erro no arquivo: Para armazéns Existentes, o campo '{campo}' deve ser preenchido.", lang).format(campo=cap_label))
        try:
          num = float(val)
          if num < 0:
            raise ValueError()
        except ValueError:
          raise ValueError(translate("Erro no arquivo: Para armazéns Existentes, as capacidades devem ser números maiores ou iguais a 0.", lang))

    else:
      # Candidate validation
      val_max = row.get('Cap. Estática Máxima (t)')
      if pd.isna(val_max) or val_max is None or str(val_max).strip() == '':
        raise ValueError(translate("Erro no arquivo: Para armazéns Candidatos, o campo 'Capacidade Estática Máxima' deve ser preenchido.", lang))
      try:
        num_max = float(val_max)
        if num_max < 0:
          raise ValueError()
      except ValueError:
        raise ValueError(translate("Erro no arquivo: Para armazéns Candidatos, a Capacidade Estática Máxima deve ser um número maior ou igual a 0.", lang))

      val_cost = row.get('Custo de Abertura ($)')
      if pd.isna(val_cost) or val_cost is None or str(val_cost).strip() == '':
        raise ValueError(translate("Erro no arquivo: Para armazéns Candidatos, o campo 'Custo de Abertura' deve ser preenchido.", lang))
      try:
        num_cost = float(val_cost)
        if num_cost < 0:
          raise ValueError()
      except ValueError:
        raise ValueError(translate("Erro no arquivo: Para armazéns Candidatos, o Custo de Abertura deve ser um número maior ou igual a 0.", lang))

    # Transshipment cost validation (for both existing and candidate)
    val_transb = row.get('Custo de Transbordo ($/t)')
    if pd.isna(val_transb) or val_transb is None or str(val_transb).strip() == '':
      num_transb = 0.0
    else:
      try:
        num_transb = float(val_transb)
        if num_transb < 0:
          raise ValueError()
      except ValueError:
        raise ValueError(translate("Erro no arquivo: O Custo de Transbordo deve ser um número maior ou igual a 0.", lang))
    new_df.at[idx, 'Custo de Transbordo ($/t)'] = num_transb

  # Reorder columns to ensure CDA is always first, matching the strict pattern
  cols_order = [
    'CDA', 'Status', 'Município', 'UF', 'Latitude', 'Longitude',
    'Armazenador', 'Tipo', 'Cap. Estática (t)', 'Cap. Recepção (t)', 'Cap. Expedição (t)',
    'Cap. Estática Máxima (t)', 'Custo de Abertura ($)', 'Custo de Transbordo ($/t)'
  ]
  for col in cols_order:
    if col not in new_df.columns:
      new_df[col] = ''
  new_df = new_df[cols_order]

  return new_df


@app.callback(
  Output('store-warehouses', 'data'),
  Output('upload-warehouses-data', 'contents'),
  Output('error-modal', 'is_open', allow_duplicate=True),
  Output('modal-body-content', 'children', allow_duplicate=True),
  [Input('upload-warehouses-data', 'contents'),
   Input('btn-wh-add-row', 'n_clicks'),
   Input('table-warehouses', 'data_timestamp'),
   Input('btn-confirm-clear-warehouses', 'n_clicks')],
  [State('store-warehouses', 'data'),
   State('table-warehouses', 'data'),
   State('upload-warehouses-data', 'filename'),
   State('wh-status-radio', 'value'),
   State('wh-input-city', 'value'),
   State('wh-input-lat', 'value'),
   State('wh-input-lon', 'value'),
   State('wh-input-provider', 'value'),
   State('wh-input-type', 'value'),
   State('wh-input-static-cap', 'value'),
   State('wh-input-max-static-cap', 'value'),
   State('wh-input-reception-cap', 'value'),
   State('wh-input-expedition-cap', 'value'),
   State('wh-input-opening-cost', 'value'),
   State('wh-input-transshipment-cost', 'value'),
   State('store-lang', 'data')],
  prevent_initial_call=True
)
def update_warehouses_store(upload_contents, btn_add_clicks, data_timestamp, btn_clear_clicks,
                            store_data, table_data, upload_filename, status_val, city_val,
                            lat_val, lon_val, provider_val, type_val, static_cap_val,
                            max_static_cap_val, reception_cap_val,
                            expedition_cap_val, opening_cost_val, transshipment_cost_val, lang):
  ctx = dash.callback_context
  if not ctx.triggered:
    return no_update, no_update, no_update, no_update

  trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

  if store_data:
    try:
      df = pd.read_json(io.StringIO(store_data), orient='split')
    except:
      df = pd.DataFrame()
  else:
    df = pd.DataFrame()

  if trigger_id == 'btn-confirm-clear-warehouses':
    empty_df = pd.DataFrame(columns=[
      'CDA', 'Status', 'Município', 'UF', 'Latitude', 'Longitude',
      'Armazenador', 'Tipo', 'Cap. Estática (t)', 'Cap. Recepção (t)', 'Cap. Expedição (t)',
      'Cap. Estática Máxima (t)', 'Custo de Abertura ($)', 'Custo de Transbordo ($/t)'
    ])
    return empty_df.to_json(date_format='iso', orient='split'), None, no_update, no_update

  elif trigger_id == 'upload-warehouses-data':
    if not upload_contents:
      return no_update, no_update, no_update, no_update
    try:
      new_df = process_uploaded_warehouses(upload_contents, upload_filename, lang)
      return new_df.to_json(date_format='iso', orient='split'), None, no_update, no_update
    except Exception as e:
      print(f"Error uploading warehouses: {e}")
      return no_update, None, True, str(e)

  elif trigger_id == 'btn-wh-add-row':
    if not city_val:
      return no_update, no_update, True, translate("Por favor, selecione a Cidade.", lang)

    if ' - ' in city_val:
      municipio, uf = city_val.split(' - ', 1)
    else:
      municipio = city_val
      uf = ''

    try:
      lat = float(lat_val) if lat_val is not None else np.nan
    except:
      lat = np.nan

    try:
      lon = float(lon_val) if lon_val is not None else np.nan
    except:
      lon = np.nan

    if not df.empty and 'CDA' in df.columns:
      cdas = df['CDA'].astype(str).tolist()
      nums = []
      for cda in cdas:
        if cda.startswith('WH-'):
          try:
            nums.append(int(cda.split('-')[1]))
          except:
            pass
      next_num = max(nums) + 1 if nums else 1
    else:
      next_num = 1
    new_cda = f"WH-{next_num:03d}"

    if status_val == 'Candidato':
      provider = ''
      wh_type = ''
      static_cap = 0.0
      reception_cap = 0.0
      expedition_cap = 0.0

      if max_static_cap_val is None or str(max_static_cap_val).strip() == '':
        return no_update, no_update, True, translate("Para armazéns Candidatos, o campo 'Capacidade Estática Máxima' deve ser preenchido.", lang)
      try:
        max_static_cap = float(max_static_cap_val)
        if max_static_cap < 0:
          raise ValueError()
      except ValueError:
        return no_update, no_update, True, translate("Para armazéns Candidatos, a Capacidade Estática Máxima deve ser um número maior ou igual a 0.", lang)

      if opening_cost_val is None or str(opening_cost_val).strip() == '':
        return no_update, no_update, True, translate("Para armazéns Candidatos, o campo 'Custo de Abertura' deve ser preenchido.", lang)
      try:
        opening_cost = float(opening_cost_val)
        if opening_cost < 0:
          raise ValueError()
      except ValueError:
        return no_update, no_update, True, translate("Para armazéns Candidatos, o Custo de Abertura deve ser um número maior ou igual a 0.", lang)
    else:
      provider = str(provider_val).strip() if provider_val else ''
      if not provider:
        return no_update, no_update, True, translate("Para armazéns Existentes, o campo 'Armazenador' deve ser preenchido.", lang)
      
      wh_type = str(type_val).strip() if type_val else ''
      if not wh_type:
        return no_update, no_update, True, translate("Para armazéns Existentes, o campo 'Tipo' deve ser preenchido.", lang)
      
      # capacities validation
      for cap_val, cap_label in [
          (static_cap_val, translate("Capacidade Estática", lang)),
          (reception_cap_val, translate("Capacidade de Recepção", lang)),
          (expedition_cap_val, translate("Capacidade de Expedição", lang))
      ]:
        if cap_val is None or str(cap_val).strip() == '':
          return no_update, no_update, True, translate("Para armazéns Existentes, o campo '{campo}' deve ser preenchido.", lang).format(campo=cap_label)
        try:
          c_num = float(cap_val)
          if c_num < 0:
            raise ValueError()
        except ValueError:
          return no_update, no_update, True, translate("Para armazéns Existentes, as capacidades devem ser números maiores ou iguais a 0.", lang)

      static_cap = float(static_cap_val)
      reception_cap = float(reception_cap_val)
      expedition_cap = float(expedition_cap_val)

      max_static_cap = 0.0
      opening_cost = 0.0

    if transshipment_cost_val is None or str(transshipment_cost_val).strip() == '':
      transshipment_cost = 0.0
    else:
      try:
        transshipment_cost = float(transshipment_cost_val)
        if transshipment_cost < 0:
          raise ValueError()
      except ValueError:
        return no_update, no_update, True, translate("O Custo de Transbordo deve ser um número maior ou igual a 0.", lang)

    new_row = {
      'CDA': new_cda,
      'Status': status_val,
      'Município': municipio,
      'UF': uf,
      'Latitude': lat,
      'Longitude': lon,
      'Armazenador': provider,
      'Tipo': wh_type,
      'Cap. Estática (t)': static_cap,
      'Cap. Estática Máxima (t)': max_static_cap,
      'Cap. Recepção (t)': reception_cap,
      'Cap. Expedição (t)': expedition_cap,
      'Custo de Abertura ($)': opening_cost,
      'Custo de Transbordo ($/t)': transshipment_cost
    }

    if df.empty:
      df = pd.DataFrame([new_row])
    else:
      df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

  elif trigger_id == 'table-warehouses':
    if table_data is None:
      return no_update, no_update, no_update, no_update
    
    table_df = pd.DataFrame(table_data)
    
    # Normalize Status column back to internal PT values
    if 'Status' in table_df.columns:
      table_df['Status'] = table_df['Status'].fillna('Existente').astype(str).str.strip().apply(
        lambda x: 'Candidato' if 'candidato' in x.lower() or 'candidate' in x.lower() else 'Existente'
      )

    # Clear fields for Candidates
    cands_mask = table_df['Status'] == 'Candidato'
    table_df.loc[cands_mask, ['Armazenador', 'Tipo']] = ''
    table_df.loc[cands_mask, ['Cap. Estática (t)', 'Cap. Recepção (t)', 'Cap. Expedição (t)']] = 0.0

    # Clear opening cost and max static cap for Existente
    exist_mask = table_df['Status'] == 'Existente'
    if 'Custo de Abertura ($)' in table_df.columns:
      table_df.loc[exist_mask, 'Custo de Abertura ($)'] = 0.0
    if 'Cap. Estática Máxima (t)' in table_df.columns:
      table_df.loc[exist_mask, 'Cap. Estática Máxima (t)'] = 0.0

    # Validate each row in table_df
    for idx, row in table_df.iterrows():
      st = str(row.get('Status', '')).strip().lower()
      is_existing = ('existente' in st or 'existing' in st)
      
      mun = str(row.get('Município', '')).strip()
      if not mun:
        return no_update, no_update, True, translate("Por favor, selecione a Cidade.", lang)

      if is_existing:
        prov = str(row.get('Armazenador', '')).strip()
        if not prov:
          return no_update, no_update, True, translate("Para armazéns Existentes, o campo 'Armazenador' deve ser preenchido.", lang)
        
        t_val = str(row.get('Tipo', '')).strip()
        if not t_val:
          return no_update, no_update, True, translate("Para armazéns Existentes, o campo 'Tipo' deve ser preenchido.", lang)
        
        for cap_col_name, cap_label in [
            ('Cap. Estática (t)', translate("Capacidade Estática", lang)),
            ('Cap. Recepção (t)', translate("Capacidade de Recepção", lang)),
            ('Cap. Expedição (t)', translate("Capacidade de Expedição", lang))
        ]:
          val = row.get(cap_col_name)
          if pd.isna(val) or val is None or str(val).strip() == '':
            return no_update, no_update, True, translate("Para armazéns Existentes, o campo '{campo}' deve ser preenchido.", lang).format(campo=cap_label)
          try:
            num = float(val)
            if num < 0:
              raise ValueError()
          except ValueError:
            return no_update, no_update, True, translate("Para armazéns Existentes, as capacidades devem ser números maiores ou iguais a 0.", lang)

      else:
        # Candidate validation
        max_static_cap_val = row.get('Cap. Estática Máxima (t)')
        if pd.isna(max_static_cap_val) or max_static_cap_val is None or str(max_static_cap_val).strip() == '':
          return no_update, no_update, True, translate("Para armazéns Candidatos, o campo 'Capacidade Estática Máxima' deve ser preenchido.", lang)
        try:
          max_static_cap = float(max_static_cap_val)
          if max_static_cap < 0:
            raise ValueError()
        except ValueError:
          return no_update, no_update, True, translate("Para armazéns Candidatos, a Capacidade Estática Máxima deve ser um número maior ou igual a 0.", lang)

        opening_cost_val = row.get('Custo de Abertura ($)')
        if pd.isna(opening_cost_val) or opening_cost_val is None or str(opening_cost_val).strip() == '':
          return no_update, no_update, True, translate("Para armazéns Candidatos, o campo 'Custo de Abertura' deve ser preenchido.", lang)
        try:
          opening_cost = float(opening_cost_val)
          if opening_cost < 0:
            raise ValueError()
        except ValueError:
          return no_update, no_update, True, translate("Para armazéns Candidatos, o Custo de Abertura deve ser um número maior ou igual a 0.", lang)

      # Transshipment cost validation
      val_transb = row.get('Custo de Transbordo ($/t)')
      if pd.isna(val_transb) or val_transb is None or str(val_transb).strip() == '':
        num_transb = 0.0
      else:
        try:
          num_transb = float(val_transb)
          if num_transb < 0:
            raise ValueError()
        except ValueError:
          return no_update, no_update, True, translate("O Custo de Transbordo deve ser um número maior ou igual a 0.", lang)
      table_df.at[idx, 'Custo de Transbordo ($/t)'] = num_transb
    
    if 'CDA' not in table_df.columns:
      table_df['CDA'] = [f"WH-{i+1:03d}" for i in range(len(table_df))]
    else:
      table_df['CDA'] = table_df['CDA'].fillna('')
      for idx, row in table_df.iterrows():
        if not row['CDA']:
          table_df.at[idx, 'CDA'] = f"WH-{idx+1:03d}"
    
    cols = [
      'CDA', 'Status', 'Município', 'UF', 'Latitude', 'Longitude',
      'Armazenador', 'Tipo', 'Cap. Estática (t)', 'Cap. Recepção (t)', 'Cap. Expedição (t)',
      'Cap. Estática Máxima (t)', 'Custo de Abertura ($)', 'Custo de Transbordo ($/t)'
    ]
    for col in cols:
      if col not in table_df.columns:
        table_df[col] = ''
    table_df = table_df[cols]
    
    return table_df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

  return no_update, no_update, no_update, no_update


@app.callback(
  [Output('table-warehouses', 'data'),
   Output('wh-metric-total-count', 'children'),
   Output('wh-metric-existing-count', 'children'),
   Output('wh-metric-candidate-count', 'children'),
   Output('wh-metric-total-capacity', 'children'),
   Output('graph-warehouses-map', 'figure')],
  [Input('store-warehouses', 'data'),
   Input('main-tabs', 'active_tab'),
   Input('store-lang', 'data')]
)
def update_warehouses_table_and_map(store_data, active_tab, lang):
  if active_tab != 'tab-warehouses':
    empty_fig = go.Figure()
    empty_fig.update_layout(mapbox_style="open-street-map")
    return [], "0", "0", "0", "0.00", empty_fig

  if store_data:
    try:
      df = pd.read_json(io.StringIO(store_data), orient='split')
    except:
      df = pd.DataFrame()
  else:
    df = pd.DataFrame()

  if df.empty:
    empty_fig = go.Figure()
    empty_fig.update_layout(
      mapbox=dict(
        style="open-street-map",
        center=dict(lat=-15.793889, lon=-47.882778),
        zoom=3
      ),
      margin={"r":0,"t":0,"l":0,"b":0},
      height=500
    )
    return [], "0", "0", "0", "0.00", empty_fig

  total_count = len(df)
  existing_count = len(df[df['Status'] == 'Existente'])
  candidate_count = len(df[df['Status'] == 'Candidato'])
  
  if 'Cap. Estática (t)' in df.columns:
    total_capacity = pd.to_numeric(df['Cap. Estática (t)'], errors='coerce').sum()
  else:
    total_capacity = 0.0

  total_capacity_str = f"{total_capacity:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

  df_table = df.copy()
  if 'Status' in df_table.columns:
    df_table['Status'] = df_table['Status'].apply(lambda x: translate(x, lang) if x in ['Existente', 'Candidato'] else x)
  table_records = df_table.to_dict('records')

  fig = go.Figure()

  df_existing = df[df['Status'] == 'Existente']
  df_candidates = df[df['Status'] == 'Candidato']

  df_existing = df_existing.dropna(subset=['Latitude', 'Longitude'])
  df_candidates = df_candidates.dropna(subset=['Latitude', 'Longitude'])

  if not df_existing.empty:
    hover_texts = []
    col_names = list(df_existing.columns)
    prov_idx = col_names.index('Armazenador')
    mun_idx = col_names.index('Município')
    uf_idx = col_names.index('UF')
    cap_idx = col_names.index('Cap. Estática (t)')
    type_idx = col_names.index('Tipo')
    
    try:
      for row in df_existing.itertuples(index=False):
        hover_texts.append(
          f"<b>{translate('Armazém Existente', lang)}</b><br>"
          f"<b>{row[prov_idx]}</b><br>"
          f"{row[mun_idx]} - {row[uf_idx]}<br>"
          f"{translate('Tipo', lang)}: {row[type_idx]}<br>"
          f"{translate('Capacidade Estática (t)', lang)}: {row[cap_idx]:,.1f}"
        )
    except (ValueError, IndexError):
      for _, row in df_existing.iterrows():
        hover_texts.append(
          f"<b>{translate('Armazém Existente', lang)}</b><br>"
          f"<b>{row['Armazenador']}</b><br>"
          f"{row['Município']} - {row['UF']}<br>"
          f"{translate('Tipo', lang)}: {row['Tipo']}<br>"
          f"{translate('Capacidade Estática (t)', lang)}: {row['Cap. Estática (t)']:,.1f}"
        )

    fig.add_trace(go.Scattermapbox(
      lat=df_existing['Latitude'],
      lon=df_existing['Longitude'],
      mode='markers',
      marker=go.scattermapbox.Marker(
        size=12,
        color='#003366',
        opacity=0.85
      ),
      text=hover_texts,
      hoverinfo='text',
      name=translate('Existente', lang)
    ))

  if not df_candidates.empty:
    hover_texts_cand = []
    col_names_cand = list(df_candidates.columns)
    mun_cand_idx = col_names_cand.index('Município')
    uf_cand_idx = col_names_cand.index('UF')
    max_cap_cand_idx = col_names_cand.index('Cap. Estática Máxima (t)')
    cost_cand_idx = col_names_cand.index('Custo de Abertura ($)')
    
    try:
      for row in df_candidates.itertuples(index=False):
        hover_texts_cand.append(
          f"<b>{translate('Candidato de Abertura', lang)}</b><br>"
          f"{row[mun_cand_idx]} - {row[uf_cand_idx]}<br>"
          f"{translate('Capacidade Estática Máxima (t)', lang)}: {row[max_cap_cand_idx]:,.1f}<br>"
          f"{translate('Custo de Abertura ($)', lang)}: {row[cost_cand_idx]:,.2f}"
        )
    except (ValueError, IndexError):
      for _, row in df_candidates.iterrows():
        hover_texts_cand.append(
          f"<b>{translate('Candidato de Abertura', lang)}</b><br>"
          f"{row['Município']} - {row['UF']}<br>"
          f"{translate('Capacidade Estática Máxima (t)', lang)}: {row['Cap. Estática Máxima (t)']:,.1f}<br>"
          f"{translate('Custo de Abertura ($)', lang)}: {row['Custo de Abertura ($)']:,.2f}"
        )

    fig.add_trace(go.Scattermapbox(
      lat=df_candidates['Latitude'],
      lon=df_candidates['Longitude'],
      mode='markers',
      marker=go.scattermapbox.Marker(
        size=12,
        color='#997A00',
        opacity=0.85
      ),
      text=hover_texts_cand,
      hoverinfo='text',
      name=translate('Candidato', lang)
    ))

  all_lats = df.dropna(subset=['Latitude', 'Longitude'])['Latitude']
  all_lons = df.dropna(subset=['Latitude', 'Longitude'])['Longitude']
  
  if not all_lats.empty and not all_lons.empty:
    center_lat = all_lats.mean()
    center_lon = all_lons.mean()
    zoom = 4
  else:
    center_lat = -15.793889
    center_lon = -47.882778
    zoom = 3

  fig.update_layout(
    mapbox=dict(
      style="open-street-map",
      center=dict(lat=center_lat, lon=center_lon),
      zoom=zoom
    ),
    margin={"r":0,"t":0,"l":0,"b":0},
    showlegend=True,
    legend=dict(
      yanchor="top",
      y=0.98,
      xanchor="left",
      x=0.02,
      bgcolor="rgba(255, 255, 255, 0.8)"
    ),
    height=500
  )

  return table_records, str(total_count), str(existing_count), str(candidate_count), total_capacity_str, fig


@app.callback(
  Output('wh-existing-fields-container', 'style'),
  Output('wh-candidate-fields-container', 'style'),
  Input('wh-status-radio', 'value')
)
def toggle_wh_conditional_fields(status):
  if status == 'Candidato':
    return {"display": "none"}, {"display": "block"}
  return {"display": "block"}, {"display": "none"}


@app.callback(
  Output("wh-input-city", "options"),
  Input("wh-input-city", "search_value"),
  State("wh-input-city", "value")
)
def update_wh_city_options(search_value, value):
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
  [Output('wh-input-lat', 'value'),
   Output('wh-input-lon', 'value')],
  Input('wh-input-city', 'value')
)
def update_wh_city_coords(city_value):
  if not city_value or city_value not in CITY_LOOKUP:
    return None, None
  coords = CITY_LOOKUP[city_value]
  return coords['latitude'], coords['longitude']


@app.callback(
  [Output('wh-input-lat', 'disabled'),
   Output('wh-input-lon', 'disabled'),
   Output('btn-wh-manual-edit', 'children')],
  [Input('btn-wh-manual-edit', 'n_clicks')],
  [State('wh-input-lat', 'disabled')],
  prevent_initial_call=True
)
def toggle_wh_manual_edit(n_clicks, is_disabled):
  if not n_clicks:
    return is_disabled, is_disabled, "🔒"
  if is_disabled:
    return False, False, "🔓"
  else:
    return True, True, "🔒"


@app.callback(
  Output('confirm-clear-warehouses-modal', 'is_open'),
  [Input('btn-clear-warehouses', 'n_clicks'),
   Input('btn-cancel-clear-warehouses', 'n_clicks'),
   Input('btn-confirm-clear-warehouses', 'n_clicks')],
  [State('confirm-clear-warehouses-modal', 'is_open')],
  prevent_initial_call=True
)
def toggle_clear_warehouses_modal(n_open, n_cancel, n_confirm, is_open):
  return not is_open


@app.callback(
  Output('download-warehouses-xlsx', 'data'),
  Input('btn-wh-export-xlsx', 'n_clicks'),
  [State('store-warehouses', 'data'),
   State('store-lang', 'data')],
  prevent_initial_call=True
)
def download_warehouses_xlsx(n_clicks, store_data, lang):
  if not n_clicks or not store_data:
    return no_update

  df = pd.read_json(io.StringIO(store_data), orient='split')
  if df.empty:
    return no_update

  # Translate columns and Status values
  translated_cols = {col: translate(col, lang) for col in df.columns}
  df = df.rename(columns=translated_cols)
  
  status_col = translate('Status', lang)
  if status_col in df.columns:
    df[status_col] = df[status_col].apply(lambda x: translate(x, lang) if x in ['Existente', 'Candidato'] else x)

  return dcc.send_data_frame(df.to_excel, translate("Warehouses.xlsx", lang), index=False)


@app.callback(
  Output('download-warehouses-template', 'data'),
  Input('btn-wh-download-template', 'n_clicks'),
  State('store-lang', 'data'),
  prevent_initial_call=True
)
def download_warehouses_template(n_clicks, lang):
  if not n_clicks:
    return no_update

  pt_data = {
    'CDA': ['WH-001', 'WH-002'],
    'Status': ['Existente', 'Candidato'],
    'Município': ['Brasília', 'Goiânia'],
    'UF': ['DF', 'GO'],
    'Latitude': [-15.793889, -16.686891],
    'Longitude': [-47.882778, -49.264789],
    'Armazenador': ['CONAB Exemplo', ''],
    'Tipo': ['Convencional', ''],
    'Cap. Estática (t)': [10000.0, 0.0],
    'Cap. Recepção (t)': [1000.0, 0.0],
    'Cap. Expedição (t)': [800.0, 0.0],
    'Cap. Estática Máxima (t)': [0.0, 20000.0],
    'Custo de Abertura ($)': [0.0, 50000.0],
    'Custo de Transbordo ($/t)': [5.0, 10.0]
  }

  translated_data = {}
  for key, val in pt_data.items():
    translated_key = translate(key, lang)
    if key == 'Status':
      translated_val = [translate(v, lang) for v in val]
    else:
      translated_val = val
    translated_data[translated_key] = translated_val

  df = pd.DataFrame(translated_data)
  
  return dcc.send_data_frame(df.to_excel, translate("Warehouses_Template.xlsx", lang), index=False)

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
                raw_types = df_arm["Tipo"].dropna().astype(str).str.strip()
                types = sorted(raw_types[raw_types != ''].unique().tolist())
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
            expected_cols = ['Produto', 'Armazenar']

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
                new_row = pd.DataFrame([{'Produto': 'Outros', 'Armazenar': 50}])
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
            df = pd.DataFrame(columns=['Produto', 'Armazenar'])

        new_row = pd.DataFrame([{'Produto': '', 'Armazenar': 0}])
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
        {'name': translate('Armazenar', lang), 'id': 'Armazenar'}
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


def _get_warehouse_coordinates_and_labels(df_warehouses, lang='pt'):
    # Checking columns...
    lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
    lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)

    if not lat_col or not lon_col:
        # Attempt to look up by City - UF
        mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
        uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)

        if mun_col and uf_col:
            df_warehouses = df_warehouses.copy()
            df_warehouses['lookup_key'] = df_warehouses[mun_col].astype(str) + ' - ' + df_warehouses[uf_col].astype(str)

            def get_coords(key):
                if key in CITY_LOOKUP:
                    return CITY_LOOKUP[key]
                return {'latitude': None, 'longitude': None}

            coords = df_warehouses['lookup_key'].apply(get_coords)
            df_warehouses['Latitude'] = coords.apply(lambda x: x['latitude'])
            df_warehouses['Longitude'] = coords.apply(lambda x: x['longitude'])
            dests_df = df_warehouses.dropna(subset=['Latitude', 'Longitude'])
        else:
            return [], []
    else:
        dests_df = df_warehouses.dropna(subset=[lat_col, lon_col])
        dests_df = dests_df.rename(columns={lat_col: 'Latitude', lon_col: 'Longitude'})

    if dests_df.empty:
        return [], []

    coords_list = list(zip(dests_df['Latitude'], dests_df['Longitude']))

    # Determine labels for destinations (e.g., Name of warehouse or City)
    cda_col = next((c for c in dests_df.columns if 'cda' in str(c).lower()), None)
    name_col = next((c for c in dests_df.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)
    mun_col_dest = next((c for c in dests_df.columns if 'munic' in str(c).lower()), None)

    dest_labels = []

    # Pre-calculate column indices for performance as per global rules
    cda_idx = dests_df.columns.get_loc(cda_col) if cda_col else -1
    name_idx = dests_df.columns.get_loc(name_col) if name_col else -1
    mun_idx = dests_df.columns.get_loc(mun_col_dest) if mun_col_dest else -1

    try:
        # Fast namedtuple iteration
        for row in dests_df.itertuples(index=False):
            parts = []
            if cda_idx != -1:
                cda_val = row[cda_idx]
                if pd.notna(cda_val):
                    parts.append(str(cda_val).strip())
            if name_idx != -1:
                name_val = row[name_idx]
                if pd.notna(name_val):
                    parts.append(str(name_val).strip())
            if mun_idx != -1:
                mun_val = row[mun_idx]
                if pd.notna(mun_val):
                    parts.append(str(mun_val).strip())

            if parts:
                label = " - ".join(parts)
            else:
                label = translate("Dest", lang) + f" {len(dest_labels)}"
            dest_labels.append(label)
    except (ValueError, IndexError):
        # Fallback to iterrows for robustness as per global rules
        dest_labels = []
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
            dest_labels.append(label)

    return coords_list, dest_labels


def _find_warehouse_coords_by_label(df_warehouses, target_label, lang='pt'):
    coords_list, labels_list = _get_warehouse_coordinates_and_labels(df_warehouses, lang)
    for coords, label in zip(coords_list, labels_list):
        if label == target_label:
            return coords
    return None


# 13. Distance Matrix Calculation
@app.callback(
    Output('store-distance-matrix', 'data'),
    Output('calc-status-message', 'children'),
    Output('btn-download-matrix', 'disabled'),
    Input('btn-calc-matrix', 'n_clicks'),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data'),
     State('stored-demand-data', 'data'),
     State('toggle-direct-arcs', 'value'),
     State('store-lang', 'data')],
    prevent_initial_call=True
)
def calculate_distance_matrix(n_clicks, stored_data, stored_warehouses, stored_demand_data, toggle_direct_arcs, lang='pt'):
    if not n_clicks:
        return no_update, no_update, True

    start_time = time.time()

    if not stored_data or not stored_warehouses or not stored_demand_data:
        return no_update, translate("Dados de entrada (Oferta), Armazéns ou Demanda não encontrados. Verifique as abas anteriores.", lang), True

    try:
        # Load Data
        df_input = pd.read_json(io.StringIO(stored_data), orient='split')
        df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
        df_demand = pd.read_json(io.StringIO(stored_demand_data), orient='split')

        if df_input.empty or df_warehouses.empty or df_demand.empty:
            return no_update, translate("As tabelas de entrada (Oferta), Armazéns ou Demanda estão vazias.", lang), True

        # 1. Prepare coordinates and labels for Supply (origins of leg 1)
        if "Latitude" not in df_input.columns or "Longitude" not in df_input.columns:
            return no_update, translate("Colunas de Latitude/Longitude ausentes na entrada da Oferta.", lang), True

        origins_df = df_input[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
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
            return no_update, translate("Nenhuma origem válida (com coordenadas) encontrada na Oferta.", lang), True

        # 2. Prepare coordinates and labels for Warehouses (destinations of leg 1, origins of leg 2)
        destinations, dest_labels = _get_warehouse_coordinates_and_labels(df_warehouses, lang)
        if not destinations:
            return no_update, translate("Não foi possível identificar coordenadas ou colunas de Município/UF nos armazéns.", lang), True

        # 3. Prepare coordinates and labels for Demand (destinations of leg 2)
        if "Latitude" not in df_demand.columns or "Longitude" not in df_demand.columns:
            return no_update, translate("Colunas de Latitude/Longitude ausentes na entrada da Demanda.", lang), True

        demand_df = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
        demand_city_counts = demand_df['Cidade'].value_counts()
        demand_duplicates = demand_city_counts[demand_city_counts > 1].index

        demand_df['Cidade_Display'] = demand_df.apply(
            lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
            if row['Cidade'] in demand_duplicates else row['Cidade'],
            axis=1
        )
        demand_coords = list(zip(demand_df['Latitude'], demand_df['Longitude']))
        demand_names = demand_df['Cidade_Display'].tolist()

        if not demand_coords:
            return no_update, translate("Nenhum destino de demanda válido (com coordenadas) encontrado.", lang), True

        # Call OSRM
        osrm_url = os.environ.get("OSRM_URL", "http://localhost:5000")
        client = OSRMClient(base_url=osrm_url)

        # Segment 1: Supply -> Warehouses
        try:
            matrix_1 = client.get_distance_matrix(origins, destinations)
        except Exception as e:
            return no_update, translate("Erro de conexão com OSRM (Trecho Oferta -> Armazéns):", lang) + f" {str(e)}", True

        # Segment 2: Warehouses -> Demand
        try:
            matrix_2 = client.get_distance_matrix(destinations, demand_coords)
        except Exception as e:
            return no_update, translate("Erro de conexão com OSRM (Trecho Armazéns -> Demanda):", lang) + f" {str(e)}", True

        # Segment 3: Warehouses -> Warehouses
        try:
            matrix_3 = client.get_distance_matrix(destinations, destinations)
        except Exception as e:
            return no_update, translate("Erro de conexão com OSRM (Trecho Armazéns -> Armazéns):", lang) + f" {str(e)}", True

        # Segment 4: Supply -> Demand (Direct)
        final_df_4 = None
        if toggle_direct_arcs:
            try:
                matrix_4 = client.get_distance_matrix(origins, demand_coords)
            except Exception as e:
                return no_update, translate("Erro de conexão com OSRM (Trecho Oferta -> Demanda):", lang) + f" {str(e)}", True

            # Format Result 4
            final_data_4 = []
            for i, row_vals in enumerate(matrix_4):
                row_dict = {'Origem': origin_names[i]}
                for j, val in enumerate(row_vals):
                    col_name = demand_names[j]
                    if val is not None:
                        row_dict[col_name] = round(val / 1000, 2)
                    else:
                        row_dict[col_name] = "N/A"
                final_data_4.append(row_dict)
            final_df_4 = pd.DataFrame(final_data_4)

        # Format Result 1
        final_data_1 = []
        for i, row_vals in enumerate(matrix_1):
            row_dict = {'Origem': origin_names[i]}
            for j, val in enumerate(row_vals):
                col_name = dest_labels[j]
                if val is not None:
                    row_dict[col_name] = round(val / 1000, 2)
                else:
                    row_dict[col_name] = "N/A"
            final_data_1.append(row_dict)
        final_df_1 = pd.DataFrame(final_data_1)

        # Format Result 2
        final_data_2 = []
        for i, row_vals in enumerate(matrix_2):
            row_dict = {'Origem': dest_labels[i]}
            for j, val in enumerate(row_vals):
                col_name = demand_names[j]
                if val is not None:
                    row_dict[col_name] = round(val / 1000, 2)
                else:
                    row_dict[col_name] = "N/A"
            final_data_2.append(row_dict)
        final_df_2 = pd.DataFrame(final_data_2)

        # Format Result 3
        final_data_3 = []
        for i, row_vals in enumerate(matrix_3):
            row_dict = {'Origem': dest_labels[i]}
            for j, val in enumerate(row_vals):
                col_name = dest_labels[j]
                if i == j:
                    row_dict[col_name] = 0.0
                elif val is not None:
                    row_dict[col_name] = round(val / 1000, 2)
                else:
                    row_dict[col_name] = "N/A"
            final_data_3.append(row_dict)
        final_df_3 = pd.DataFrame(final_data_3)

        # Save to store as a dict of JSONs
        stored_dict = {
            'supply_to_warehouses': final_df_1.to_json(date_format='iso', orient='split'),
            'warehouses_to_demand': final_df_2.to_json(date_format='iso', orient='split'),
            'warehouses_to_warehouses': final_df_3.to_json(date_format='iso', orient='split')
        }
        if final_df_4 is not None:
            stored_dict['supply_to_demand'] = final_df_4.to_json(date_format='iso', orient='split')

        msg = translate("Cálculo concluído com sucesso! (Tempo de execução:", lang) + f" {time.time() - start_time:.2f} " + translate("segundos)", lang)
        return json.dumps(stored_dict), msg, False

    except Exception as e:
        print(f"Calculation error: {e}")
        import traceback
        traceback.print_exc()
        return no_update, translate("Erro inesperado:", lang) + f" {str(e)}", True


@app.callback(
    [Output('table-distance-matrix', 'data'),
     Output('table-distance-matrix', 'columns'),
     Output('table-distance-matrix', 'active_cell')],
    [Input('distance-matrix-segment-selector', 'value'),
     Input('store-distance-matrix', 'data')],
    State('store-lang', 'data')
)
def update_distance_table(segment, stored_matrix_json, lang='pt'):
    if not stored_matrix_json:
        return [], [], None

    try:
        stored_dict = json.loads(stored_matrix_json)
        if not isinstance(stored_dict, dict) or segment not in stored_dict:
            return [], [], None
        
        df = pd.read_json(io.StringIO(stored_dict[segment]), orient='split')
        
        records = df.to_dict('records')
        columns = [{"name": translate(i, lang) if i == "Origem" else i, "id": i} for i in df.columns]
        
        return records, columns, None
    except Exception as e:
        print(f"Error updating distance table: {e}")
        return [], [], None


# 14. Download Matrix
@app.callback(
    Output("download-matrix-xlsx", "data"),
    Input("btn-download-matrix", "n_clicks"),
    State('store-distance-matrix', 'data'),
    State('store-lang', 'data'),
    prevent_initial_call=True,
)
def download_matrix(n_clicks, stored_matrix_json, lang='pt'):
    if not n_clicks or not stored_matrix_json:
        return no_update

    try:
        stored_dict = json.loads(stored_matrix_json)
        if not isinstance(stored_dict, dict) or 'supply_to_warehouses' not in stored_dict:
            return no_update

        df_supply_to_wh = pd.read_json(io.StringIO(stored_dict['supply_to_warehouses']), orient='split')
        df_wh_to_demand = pd.read_json(io.StringIO(stored_dict['warehouses_to_demand']), orient='split')
        df_wh_to_wh = None
        if 'warehouses_to_warehouses' in stored_dict:
            df_wh_to_wh = pd.read_json(io.StringIO(stored_dict['warehouses_to_warehouses']), orient='split')
        df_supply_to_demand = None
        if 'supply_to_demand' in stored_dict:
            df_supply_to_demand = pd.read_json(io.StringIO(stored_dict['supply_to_demand']), orient='split')
    except Exception as e:
        print(f"Error loading matrix for download: {e}")
        return no_update

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_supply_to_wh.to_excel(writer, sheet_name=translate("Oferta para Armazéns", lang), index=False)
        df_wh_to_demand.to_excel(writer, sheet_name=translate("Armazéns para Demanda", lang), index=False)
        if df_wh_to_wh is not None:
            df_wh_to_wh.to_excel(writer, sheet_name=translate("Armazéns para Armazéns", lang), index=False)
        if df_supply_to_demand is not None:
            df_supply_to_demand.to_excel(writer, sheet_name=translate("Oferta para Demanda", lang), index=False)
    
    return dcc.send_bytes(buffer.getvalue(), translate("Matriz_Distancias.xlsx", lang))

# 15. Route Visualization
@app.callback(
    Output("graph-route-map", "figure"),
    Input("table-distance-matrix", "active_cell"),
    [State('stored-data', 'data'),
     State('store-warehouses', 'data'),
     State('stored-demand-data', 'data'),
     State('table-distance-matrix', 'derived_viewport_data'),
     State('distance-matrix-segment-selector', 'value'),
     State('store-lang', 'data')],
    prevent_initial_call=True
)
def update_route_map(active_cell, stored_data, stored_warehouses, stored_demand_data, table_data, segment, lang='pt'):
    # Default map centered on Brazil
    default_fig = go.Figure(go.Scattermapbox())
    default_fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=3,
        mapbox_center={"lat": -14.2350, "lon": -51.9253},
        margin={"r": 0, "t": 0, "l": 0, "b": 0}
    )

    if not active_cell or not table_data or not segment:
        return default_fig

    try:
        # Get Origin and Destination from active cell
        # Table data has 'Origem' column and destination columns
        row_idx = active_cell['row']
        col_id = active_cell['column_id']

        # If clicked on 'Origem' column, ignore
        if col_id == 'Origem':
            return default_fig

        row_data = table_data[row_idx]
        origin_name = row_data['Origem']
        dest_label = col_id

        origin_coords = None
        dest_coords = None

        if segment == 'supply_to_warehouses':
            # Origin: Supply
            if not stored_data:
                return default_fig
            df_input = pd.read_json(io.StringIO(stored_data), orient='split')
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
                origin_row = df_input[df_input['Cidade'] == origin_name].iloc[0]
            else:
                origin_row = origin_row.iloc[0]

            origin_coords = (origin_row['Latitude'], origin_row['Longitude'])

            # Destination: Warehouse
            if not stored_warehouses:
                return default_fig
            df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            dest_coords = _find_warehouse_coords_by_label(df_warehouses, dest_label, lang)

        elif segment == 'warehouses_to_demand':
            # Origin: Warehouse
            if not stored_warehouses:
                return default_fig
            df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            origin_coords = _find_warehouse_coords_by_label(df_warehouses, origin_name, lang)

            # Destination: Demand
            if not stored_demand_data:
                return default_fig
            df_demand = pd.read_json(io.StringIO(stored_demand_data), orient='split')
            demand_df_map = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
            demand_city_counts_map = demand_df_map['Cidade'].value_counts()
            demand_duplicates_map = demand_city_counts_map[demand_city_counts_map > 1].index

            demand_df_map['Cidade_Display'] = demand_df_map.apply(
                lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
                if row['Cidade'] in demand_duplicates_map else row['Cidade'],
                axis=1
            )

            dest_row = demand_df_map[demand_df_map['Cidade_Display'] == dest_label]
            if dest_row.empty:
                dest_row = df_demand[df_demand['Cidade'] == dest_label].iloc[0]
            else:
                dest_row = dest_row.iloc[0]

            dest_coords = (dest_row['Latitude'], dest_row['Longitude'])

        elif segment == 'warehouses_to_warehouses':
            # Origin: Warehouse
            if not stored_warehouses:
                return default_fig
            df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
            origin_coords = _find_warehouse_coords_by_label(df_warehouses, origin_name, lang)

            # Destination: Warehouse
            dest_coords = _find_warehouse_coords_by_label(df_warehouses, dest_label, lang)

        elif segment == 'supply_to_demand':
            # Origin: Supply
            if not stored_data:
                return default_fig
            df_input = pd.read_json(io.StringIO(stored_data), orient='split')
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
                origin_row = df_input[df_input['Cidade'] == origin_name].iloc[0]
            else:
                origin_row = origin_row.iloc[0]

            origin_coords = (origin_row['Latitude'], origin_row['Longitude'])

            # Destination: Demand
            if not stored_demand_data:
                return default_fig
            df_demand = pd.read_json(io.StringIO(stored_demand_data), orient='split')
            demand_df_map = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
            demand_city_counts_map = demand_df_map['Cidade'].value_counts()
            demand_duplicates_map = demand_city_counts_map[demand_city_counts_map > 1].index

            demand_df_map['Cidade_Display'] = demand_df_map.apply(
                lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
                if row['Cidade'] in demand_duplicates_map else row['Cidade'],
                axis=1
            )

            dest_row = demand_df_map[demand_df_map['Cidade_Display'] == dest_label]
            if dest_row.empty:
                dest_row = df_demand[df_demand['Cidade'] == dest_label].iloc[0]
            else:
                dest_row = dest_row.iloc[0]

            dest_coords = (dest_row['Latitude'], dest_row['Longitude'])

        if not origin_coords or not dest_coords:
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

        # Simple zoom estimation
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
    Output('input-bulk-eligible-types', 'options'),
    Input('store-prod-warehouses', 'data')
)
def update_bulk_eligible_options(stored_prod_warehouses):
    if not stored_prod_warehouses:
        return []
    try:
        df = pd.read_json(io.StringIO(stored_prod_warehouses), orient='split')
        types = [col for col in df.columns if col != 'Produto']
        return [{'label': t, 'value': t} for t in types]
    except Exception:
        return []

@app.callback(
    Output("collapse-expansion-fields", "is_open"),
    Input("toggle-expansion-enabled", "value")
)
def toggle_expansion_collapse(is_enabled):
    return bool(is_enabled)

@app.callback(
    Output("collapse-bulk-fields", "is_open"),
    Input("toggle-bulk-enabled", "value")
)
def toggle_bulk_collapse(is_enabled):
    return bool(is_enabled)

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
        State('store-initial-inventory', 'data'),
        State('store-prod-warehouses', 'data'),
        State('store-distance-matrix', 'data'),
        State('stored-demand-data', 'data'),
        State('toggle-detailed-log', 'value'),
        State('toggle-pareto-routes', 'value'),
        State('toggle-direct-arcs', 'value'),
        State('input-allocation-days', 'value'),
        State('input-interhub-factor', 'value'),
        State('input-solver-gap', 'value'),
        State('input-solver-time-limit', 'value'),
        State('dropdown-solver-name', 'value'),
        State('toggle-expansion-enabled', 'value'),
        State('toggle-bulk-enabled', 'value'),
        State('input-ratio-expand-rec', 'value'),
        State('input-ratio-expand-ship', 'value'),
        State('input-max-expand-capacity', 'value'),
        State('input-expand-fixed-cost', 'value'),
        State('input-expand-var-cost', 'value'),
        State('input-max-bulk-capacity', 'value'),
        State('input-bulk-fixed-cost', 'value'),
        State('input-bulk-var-cost', 'value'),
        State('input-bulk-eligible-types', 'value'),
        State('radio-model-type', 'value'),
        State('input-prob-pessimista', 'value'),
        State('input-prob-esperado', 'value'),
        State('input-prob-otimista', 'value'),
        State('radio-error-source', 'value'),
        State('input-supply-error-pct', 'value'),
        State('input-demand-error-pct', 'value'),
        State('store-prediction-results', 'data'),
        State('store-gurobi-lic', 'data'),
        State('store-lang', 'data')
    ],
    background=True,
    progress=[
        Output("store-active-log-filename", "data"),
    ],
    running=[
        (Output("btn-run-model", "disabled"), True, False),
        (Output("btn-cancel-model", "disabled"), False, True),
        (Output("interval-model-log", "disabled"), False, True),
        (Output("model-running-log-container", "style"), {"display": "block"}, {"display": "none"}),
    ],
    cancel=[Input("btn-cancel-model", "n_clicks")],
    prevent_initial_call=True
)
def execute_model(set_progress, n_clicks, stored_data, stored_warehouses, stored_initial_inventory, stored_prod_warehouses, stored_matrix, stored_demand, detailed_log,
                  toggle_pareto, toggle_direct_arcs, input_allocation_days, interhub_factor, solver_gap, solver_time_limit, solver_name,
                  expansion_enabled, bulk_enabled,
                  ratio_expand_rec, ratio_expand_ship, max_expand_capacity, expand_fixed_cost, expand_var_cost,
                  max_bulk_capacity, bulk_fixed_cost, bulk_var_cost, bulk_eligible_types,
                  model_type, prob_pessimista, prob_esperado, prob_otimista, error_source,
                  supply_error_pct, demand_error_pct, prediction_results_json, gurobi_lic_data, lang='pt'):
    if not n_clicks:
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
    os.makedirs(log_dir, exist_ok=True)
    prefix = 'stochastic_log_' if model_type == "stochastic" else 'optimization_log_'
    log_filename = f"{prefix}{uuid.uuid4().hex}.txt"
    log_path = os.path.join(log_dir, log_filename)

    # Write initial header
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(translate("Carregando e preparando dados para o modelo...\n", lang))

    # Send log filename to the store so the interval can poll it
    set_progress((log_filename,))

    if not stored_data or not stored_warehouses or not stored_prod_warehouses or not stored_matrix or not stored_demand:
        return translate("Erro: Faltam dados. Certifique-se de preencher todas as abas anteriores (Oferta, Armazéns, Relação Produto x Armazém, Demanda, Matriz de Distâncias) antes de rodar o modelo.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

    # Parameters required verification (no defaults allowed, must highlight missing fields)
    required_params = {
        translate("Dias operacionais por período", lang): input_allocation_days,
        translate("Fator interhub (α)", lang): interhub_factor,
        translate("Gap do solver (%)", lang): solver_gap,
        translate("Tempo limite do solver (s)", lang): solver_time_limit,
        translate("Razão de Capacidade de Recepção", lang): ratio_expand_rec,
        translate("Razão de Capacidade de Expedição", lang): ratio_expand_ship,
    }

    if expansion_enabled:
        required_params.update({
            translate("Expansão máxima (t)", lang): max_expand_capacity,
            translate("Custo fixo de expansão ($)", lang): expand_fixed_cost,
            translate("Custo variável de expansão ($/t)", lang): expand_var_cost,
        })

    if bulk_enabled:
        required_params.update({
            translate("Granelização máxima (t/dia)", lang): max_bulk_capacity,
            translate("Custo fixo de granelização ($)", lang): bulk_fixed_cost,
            translate("Custo var. de granelização ($/(t · dia))", lang): bulk_var_cost,
            translate("Tipos elegíveis para granelização", lang): bulk_eligible_types,
        })

    missing = [name for name, val in required_params.items() if val is None or str(val).strip() == "" or (isinstance(val, list) and not val)]
    if missing:
        msg = translate("Erro: Os seguintes parâmetros de configuração são obrigatórios e não foram preenchidos: ", lang) + ", ".join(missing)
        return msg, "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

    try:
        # Load distance matrices
        try:
            import json
            stored_dict = json.loads(stored_matrix)
            if isinstance(stored_dict, dict) and 'supply_to_warehouses' in stored_dict:
                df_dist_supply_wh = pd.read_json(io.StringIO(stored_dict['supply_to_warehouses']), orient='split')
                df_dist_wh_demand = pd.read_json(io.StringIO(stored_dict['warehouses_to_demand']), orient='split')
                df_dist_wh_wh = pd.read_json(io.StringIO(stored_dict['warehouses_to_warehouses']), orient='split')
                
                if toggle_direct_arcs:
                    if 'supply_to_demand' in stored_dict:
                        df_dist_supply_demand = pd.read_json(io.StringIO(stored_dict['supply_to_demand']), orient='split')
                    else:
                        return translate("Erro: A opção de arcos diretos (Origem -> Destino) está ativa, mas a matriz correspondente não foi calculada. Por favor, calcule a matriz na aba 'Matriz de Distâncias' primeiro.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update
                else:
                    df_dist_supply_demand = pd.DataFrame()
            else:
                df_dist_supply_wh = pd.DataFrame()
                df_dist_wh_demand = pd.DataFrame()
                df_dist_wh_wh = pd.DataFrame()
                df_dist_supply_demand = pd.DataFrame()
        except Exception:
            df_dist_supply_wh = pd.DataFrame()
            df_dist_wh_demand = pd.DataFrame()
            df_dist_wh_wh = pd.DataFrame()
            df_dist_supply_demand = pd.DataFrame()

        if df_dist_supply_wh.empty or df_dist_wh_demand.empty or df_dist_wh_wh.empty or (toggle_direct_arcs and df_dist_supply_demand.empty):
            return translate("Erro: Matrizes de distância incompletas. Certifique-se de calcular a Matriz de Distâncias na aba anterior antes de rodar o modelo.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

        # Load input DataFrames
        df_supply = pd.read_json(io.StringIO(stored_data), orient='split')
        df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
        df_compat = pd.read_json(io.StringIO(stored_prod_warehouses), orient='split')
        df_demand = pd.read_json(io.StringIO(stored_demand), orient='split')

        df_initial_inventory = None
        if stored_initial_inventory:
            try:
                df_initial_inventory = pd.read_json(io.StringIO(stored_initial_inventory), orient='split')
            except Exception as e:
                print(f"Error loading initial inventory in execute_model: {e}")

        # Normalize historical dates to string YYYY-MM
        if not df_supply.empty:
            df_supply["Data"] = pd.to_datetime(df_supply["Data"], errors='coerce').dt.strftime('%Y-%m')
        if not df_demand.empty:
            df_demand["Data"] = pd.to_datetime(df_demand["Data"], errors='coerce').dt.strftime('%Y-%m')

        # Merge prediction data if available
        if prediction_results_json:
            try:
                preds = json.loads(prediction_results_json)
                if preds:
                    supply_forecast_rows = []
                    demand_forecast_rows = []
                    
                    coords_supply = df_supply.groupby(['Produto', 'Cidade'])[['Latitude', 'Longitude']].first().to_dict('index') if not df_supply.empty else {}
                    coords_demand = df_demand.groupby(['Produto', 'Cidade'])[['Latitude', 'Longitude']].first().to_dict('index') if not df_demand.empty else {}
                    
                    for combo_key, combo_val in preds.items():
                        if not isinstance(combo_val, dict) or combo_val.get('status') != 'success':
                            continue
                        
                        s_type = combo_val.get('series_type')
                        prod = combo_val.get('product')
                        city = combo_val.get('city')
                        future_dates = combo_val.get('future_dates', [])
                        future_preds = combo_val.get('future_preds', [])
                        is_infinite_demand = combo_val.get('is_infinite_demand', False)
                        
                        if s_type == 'supply':
                            coords = coords_supply.get((prod, city), {'Latitude': 0.0, 'Longitude': 0.0})
                            for d, val in zip(future_dates, future_preds):
                                supply_forecast_rows.append({
                                    "Produto": prod,
                                    "Cidade": city,
                                    "Latitude": coords.get('Latitude', 0.0),
                                    "Longitude": coords.get('Longitude', 0.0),
                                    "Data": d,
                                    "Peso (ton)": float(val) if val is not None else None
                                })
                        elif s_type == 'demand':
                            coords = coords_demand.get((prod, city), {'Latitude': 0.0, 'Longitude': 0.0})
                            for d, val in zip(future_dates, future_preds):
                                demand_forecast_rows.append({
                                    "Produto": prod,
                                    "Cidade": city,
                                    "Latitude": coords.get('Latitude', 0.0),
                                    "Longitude": coords.get('Longitude', 0.0),
                                    "Data": d,
                                    "Peso (ton)": float(val) if (val is not None and not is_infinite_demand) else None
                                })
                    
                    if supply_forecast_rows:
                        df_supply_forecast = pd.DataFrame(supply_forecast_rows)
                        df_supply = pd.concat([df_supply, df_supply_forecast], ignore_index=True)
                        df_supply = df_supply.sort_values(by=["Produto", "Cidade", "Data"])
                        
                    if demand_forecast_rows:
                        df_demand_forecast = pd.DataFrame(demand_forecast_rows)
                        df_demand = pd.concat([df_demand, df_demand_forecast], ignore_index=True)
                        df_demand = df_demand.sort_values(by=["Produto", "Cidade", "Data"])
            except Exception as e:
                print(f"Error merging prediction results in execute_model: {e}")

        # Load local CSVs for Freight and Storage
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

        temp_lic_path = None
        if solver_name == 'gurobi':
            if not gurobi_lic_data:
                return translate("Licença do Gurobi não encontrada na sessão. Por favor, envie o arquivo de licença nas configurações do modelo.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update
            
            try:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.lic', encoding='utf-8') as temp_lic:
                    temp_lic.write(gurobi_lic_data)
                    temp_lic_path = temp_lic.name
                os.environ["GRB_LICENSE_FILE"] = temp_lic_path
            except Exception as e:
                return translate("Erro ao processar licença.", lang) + f" {str(e)}", "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

        try:
            # Run appropriate model
            if model_type == "stochastic":
                # Validate predictions
                try:
                    if not prediction_results_json:
                        raise ValueError()
                    preds = json.loads(prediction_results_json)
                    if not preds:
                        raise ValueError()
                except Exception:
                    return translate("Erro: O modelo estocástico requer que as previsões na aba 'Previsão' tenham sido executadas primeiro.", lang), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

                # Validate scenario probabilities
                p_pess = 0.33 if prob_pessimista is None else float(prob_pessimista)
                p_esp = 0.34 if prob_esperado is None else float(prob_esperado)
                p_otim = 0.33 if prob_otimista is None else float(prob_otimista)
                tot_prob = p_pess + p_esp + p_otim
                if abs(tot_prob - 1.0) > 1e-4:
                    return translate("Erro: A soma das probabilidades dos cenários deve ser igual a 1.0 (atual: {val:.2f})", lang).format(val=tot_prob), "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update

                scenario_probabilities = {
                    "pessimista": p_pess,
                    "esperado": p_esp,
                    "otimista": p_otim
                }

                log_filename, results_dict = run_stochastic_model(
                    df_supply=df_supply,
                    df_warehouses=df_warehouses,
                    df_compat=df_compat,
                    df_dist_supply_wh=df_dist_supply_wh,
                    df_dist_wh_demand=df_dist_wh_demand,
                    df_dist_wh_wh=df_dist_wh_wh,
                    df_demand=df_demand,
                    df_freight=df_freight,
                    df_storage=df_storage,
                    scenario_probabilities=scenario_probabilities,
                    error_source=error_source or "prediction",
                    supply_error_pct=float(supply_error_pct) if supply_error_pct is not None else 15.0,
                    demand_error_pct=float(demand_error_pct) if demand_error_pct is not None else 15.0,
                    prediction_results=preds,
                    df_initial_inventory=df_initial_inventory,
                    df_dist_supply_demand=df_dist_supply_demand,
                    detailed_log=detailed_log,
                    toggle_pareto=toggle_pareto,
                    input_allocation_days=input_allocation_days,
                    interhub_factor=interhub_factor,
                    solver_gap=solver_gap,
                    solver_time_limit=solver_time_limit,
                    ratio_expand_rec=ratio_expand_rec,
                    ratio_expand_ship=ratio_expand_ship,
                    max_expand_capacity=max_expand_capacity if expansion_enabled else None,
                    expand_fixed_cost=expand_fixed_cost if expansion_enabled else None,
                    expand_var_cost=expand_var_cost if expansion_enabled else None,
                    max_bulk_capacity=max_bulk_capacity if bulk_enabled else None,
                    bulk_fixed_cost=bulk_fixed_cost if bulk_enabled else None,
                    bulk_var_cost=bulk_var_cost if bulk_enabled else None,
                    bulk_eligible_types=bulk_eligible_types if bulk_enabled else None,
                    lang=lang,
                    log_path=log_path,
                    solver_name=solver_name
                )
                if results_dict.get("status") == "optimal":
                    try:
                        stochastic_obj = results_dict.get("objective", 0.0)
                        stochastic_kpis = results_dict.get("kpis", {})
                        stochastic_scenario_kpis = results_dict.get("scenario_kpis", {})
                        old_stdout = sys.stdout
                        with open(log_path, 'a', encoding='utf-8', buffering=1) as f_log:
                            sys.stdout = f_log
                            try:
                                evpi_vss_res = compute_evpi_vss(
                                    df_supply=df_supply,
                                    df_warehouses=df_warehouses,
                                    df_compat=df_compat,
                                    df_dist_supply_wh=df_dist_supply_wh,
                                    df_dist_wh_demand=df_dist_wh_demand,
                                    df_dist_wh_wh=df_dist_wh_wh,
                                    df_demand=df_demand,
                                    df_freight=df_freight,
                                    df_storage=df_storage,
                                    scenario_probabilities=scenario_probabilities,
                                    error_source=error_source or "prediction",
                                    supply_error_pct=float(supply_error_pct) if supply_error_pct is not None else 15.0,
                                    demand_error_pct=float(demand_error_pct) if demand_error_pct is not None else 15.0,
                                    prediction_results=preds,
                                    stochastic_objective=stochastic_obj,
                                    df_initial_inventory=df_initial_inventory,
                                    df_dist_supply_demand=df_dist_supply_demand,
                                    detailed_log=detailed_log,
                                    toggle_pareto=toggle_pareto,
                                    input_allocation_days=input_allocation_days,
                                    interhub_factor=interhub_factor,
                                    solver_gap=solver_gap,
                                    solver_time_limit=solver_time_limit,
                                    ratio_expand_rec=ratio_expand_rec,
                                    ratio_expand_ship=ratio_expand_ship,
                                    max_expand_capacity=max_expand_capacity if expansion_enabled else None,
                                    expand_fixed_cost=expand_fixed_cost if expansion_enabled else None,
                                    expand_var_cost=expand_var_cost if expansion_enabled else None,
                                    max_bulk_capacity=max_bulk_capacity if bulk_enabled else None,
                                    bulk_fixed_cost=bulk_fixed_cost if bulk_enabled else None,
                                    bulk_var_cost=bulk_var_cost if bulk_enabled else None,
                                    bulk_eligible_types=bulk_eligible_types if bulk_enabled else None,
                                    lang=lang,
                                    solver_name=solver_name,
                                    stochastic_kpis=stochastic_kpis,
                                    stochastic_scenario_kpis=stochastic_scenario_kpis
                                )
                                results_dict["evpi_vss"] = evpi_vss_res
                            finally:
                                sys.stdout = old_stdout
                    except Exception as e_evpi:
                        print(f"Error computing EVPI/VSS during execution: {e_evpi}", flush=True)
            else:
                log_filename, results_dict = run_deterministic_model(
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
                    df_dist_supply_demand=df_dist_supply_demand,
                    detailed_log=detailed_log,
                    toggle_pareto=toggle_pareto,
                    input_allocation_days=input_allocation_days,
                    interhub_factor=interhub_factor,
                    solver_gap=solver_gap,
                    solver_time_limit=solver_time_limit,
                    ratio_expand_rec=ratio_expand_rec,
                    ratio_expand_ship=ratio_expand_ship,
                    max_expand_capacity=max_expand_capacity if expansion_enabled else None,
                    expand_fixed_cost=expand_fixed_cost if expansion_enabled else None,
                    expand_var_cost=expand_var_cost if expansion_enabled else None,
                    max_bulk_capacity=max_bulk_capacity if bulk_enabled else None,
                    bulk_fixed_cost=bulk_fixed_cost if bulk_enabled else None,
                    bulk_var_cost=bulk_var_cost if bulk_enabled else None,
                    bulk_eligible_types=bulk_eligible_types if bulk_enabled else None,
                    lang=lang,
                    log_path=log_path,
                    solver_name=solver_name
                )
        finally:
            if temp_lic_path:
                try:
                    if os.path.exists(temp_lic_path):
                        os.remove(temp_lic_path)
                except Exception:
                    pass
                os.environ.pop("GRB_LICENSE_FILE", None)

        # Store configuration options used to generate these results
        pred_model_name = "N/A"
        pred_test_size = "N/A"
        pred_horizon = "N/A"
        if prediction_results_json:
            try:
                preds_meta = json.loads(prediction_results_json)
                if preds_meta:
                    for combo_key, combo_val in preds_meta.items():
                        if isinstance(combo_val, dict) and 'model' in combo_val:
                            pred_model_name = combo_val.get('model', "N/A")
                            pred_test_size = combo_val.get('test_size', "N/A")
                            pred_horizon = combo_val.get('horizon', "N/A")
                            break
            except Exception:
                pass

        results_dict["configs"] = {
            "model_type": model_type,
            "input_allocation_days": input_allocation_days,
            "interhub_factor": interhub_factor,
            "solver_gap": solver_gap,
            "solver_time_limit": solver_time_limit,
            "solver_name": solver_name,
            "expansion_enabled": expansion_enabled,
            "bulk_enabled": bulk_enabled,
            "ratio_expand_rec": ratio_expand_rec,
            "ratio_expand_ship": ratio_expand_ship,
            "max_expand_capacity": max_expand_capacity,
            "expand_fixed_cost": expand_fixed_cost,
            "expand_var_cost": expand_var_cost,
            "max_bulk_capacity": max_bulk_capacity,
            "bulk_fixed_cost": bulk_fixed_cost,
            "bulk_var_cost": bulk_var_cost,
            "bulk_eligible_types": bulk_eligible_types,
            "detailed_log": detailed_log,
            "toggle_pareto": toggle_pareto,
            "toggle_direct_arcs": toggle_direct_arcs,
            "prediction_model": pred_model_name,
            "prediction_test_size": pred_test_size,
            "prediction_horizon": pred_horizon
        }
        if model_type == "stochastic":
            results_dict["configs"].update({
                "prob_pessimista": prob_pessimista,
                "prob_esperado": prob_esperado,
                "prob_otimista": prob_otimista,
                "error_source": error_source,
                "supply_error_pct": supply_error_pct,
                "demand_error_pct": demand_error_pct,
            })

        # Get execution time
        exec_time = results_dict.get('kpis', {}).get('execution_time', 0.0)
        time_str = translate(" (Tempo de execução:", lang) + f" {exec_time:.2f} " + translate("segundos)", lang) if exec_time else ""

        status_msg = translate("Modelo executado com sucesso!", lang) + time_str if results_dict.get("status") == "optimal" else translate("Falha ao encontrar solução ótima.", lang) + time_str
        status_class = "text-success mt-3 fw-bold" if results_dict.get("status") == "optimal" else "text-warning mt-3 fw-bold"

        # Redirect to results tab on success
        next_tab = "tab-results" if results_dict.get("status") == "optimal" else dash.no_update

        return status_msg, status_class, results_dict, log_filename, next_tab

    except Exception as e:
        err_msg = translate("Erro fatal ao executar o modelo:", lang) + f"\n{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return err_msg, "text-danger mt-3", dash.no_update, dash.no_update, dash.no_update


# --- Results Callbacks ---

def make_warehouse_row(w, lang):
    def fmt_num(v):
        if v is None:
            v = 0.0
        if abs(v) >= 1e9:
            s = f"{v:.2e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return s
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    is_cand = w.get("IsCandidate", False)
    type_str = translate("Candidato", lang) if is_cand else translate("Existente", lang)
    
    is_open = w.get("IsOpen", False)
    status_str = translate("Aberto", lang) if is_open else translate("Fechado", lang)
    
    is_exp = w.get("IsExpanded", False)
    exp_str = translate("Sim", lang) if is_exp else translate("Não", lang)
    
    is_bulk = w.get("IsBulkified", False)
    bulk_str = translate("Sim", lang) if is_bulk else translate("Não", lang)
    
    dec_static = w.get("DecidedStaticCapacity", 0.0)
    static_cap_str = fmt_num(dec_static)
    
    eff_static = w.get("EffectiveStaticCapacity", 0.0)
    eff_static_str = fmt_num(eff_static)
    
    exp_vol = w.get("ExpandedVolume", 0.0)
    exp_vol_str = fmt_num(exp_vol) if is_exp else "0,00"
    
    bulk_cap = w.get("BulkCapacityAdded", 0.0)
    bulk_cap_str = fmt_num(bulk_cap) if is_bulk else "0,00"
    
    outflow = w.get("TotalOutflow", 0.0)
    outflow_str = fmt_num(outflow)
    
    final_stock = w.get("FinalStock", 0.0)
    final_stock_str = fmt_num(final_stock)
    
    dyn_cap = w.get("DynamicCapacity", 0.0)
    dyn_cap_str = fmt_num(dyn_cap)
    
    turnover = w.get("TurnoverRatio", 0.0)
    if turnover is None:
        turnover = 0.0
    turnover_str = f"{turnover:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    return {
        "Name": w.get("Name", ""),
        "Type": type_str,
        "Status": status_str,
        "StaticCap": static_cap_str,
        "IsExpanded": exp_str,
        "ExpandedVol": exp_vol_str,
        "IsBulkified": bulk_str,
        "BulkCap": bulk_cap_str,
        "EffStaticCap": eff_static_str,
        "TotalOutflow": outflow_str,
        "FinalStock": final_stock_str,
        "DynCap": dyn_cap_str,
        "TurnoverRatio": turnover_str,
    }

@app.callback(
    [Output("res-kpi-objective", "children"),
     Output("res-kpi-tons", "children"),
     Output("res-kpi-km", "children"),
     Output("res-kpi-freight", "children"),
     Output("res-kpi-storage", "children"),
     Output("res-kpi-transshipment", "children"),
     Output("res-kpi-opening", "children"),
     Output("res-kpi-expand", "children"),
     Output("res-kpi-bulk", "children"),
     Output("res-wh-opened-count", "children"),
     Output("res-wh-expanded-count", "children"),
     Output("res-wh-bulkified-count", "children"),
     Output("res-wh-investment", "children"),
     Output("table-results-warehouses", "data"),
     Output("table-results-warehouses", "columns"),
     Output("table-results-routes", "data"),
     Output("table-results-routes", "columns"),
     Output("results-warnings-container", "children"),
     Output("results-scenario-selector-container", "style")],
    [Input("store-model-results", "data"),
     Input("switch-show-all-warehouses", "value"),
     Input("radio-results-scenario-select", "value")],
    [State("store-lang", "data")],
    prevent_initial_call=False
)
def update_results_kpis_and_table(results_data, show_all_warehouses, selected_scenario, lang='pt'):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    # BR format helpers
    def fmt_curr(val):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.2e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return f"R$ {s}"
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def fmt_num(val):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.2e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return s
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    show_all_warehouses_bool = bool(show_all_warehouses)

    # Determine visibility style of the selector
    selector_style = {"display": "none"}
    is_stochastic = False
    if results_data and results_data.get("status") == "optimal":
        if results_data.get("model_type") == "stochastic":
            selector_style = {"display": "block"}
            is_stochastic = True

    if trigger_id == "switch-show-all-warehouses":
        if not results_data or results_data.get("status") != "optimal":
            wh_table_data = []
        else:
            if is_stochastic:
                scen = selected_scenario or "esperado"
                wh_decisions = results_data.get("scenario_warehouse_metrics", {}).get(scen, [])
            else:
                wh_decisions = results_data.get("warehouse_decisions", [])
                
            if not show_all_warehouses_bool:
                wh_decisions = [
                    w for w in wh_decisions
                    if w.get("TotalOutflow", 0) > 1e-4 or w.get("FinalStock", 0) > 1e-4 or (w.get("IsCandidate") and w.get("IsOpen"))
                ]
            wh_table_data = [make_warehouse_row(w, lang) for w in wh_decisions]
            
        return (dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update, wh_table_data, dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, selector_style)

    if not results_data or results_data.get("status") != "optimal":
        return ("R$ 0,00", "0,00", "0,00", "R$ 0,00", "R$ 0,00", "R$ 0,00", "R$ 0,00", "R$ 0,00", "R$ 0,00",
                "0", "0", "0", "R$ 0,00", [], dash.no_update, [], dash.no_update, [], selector_style)

    # Fetch data depending on stochastic vs deterministic
    if is_stochastic:
        scen = selected_scenario or "esperado"
        kpis = results_data.get("scenario_kpis", {}).get(scen, {})
        routes = results_data.get("scenario_routes", {}).get(scen, [])
        wh_decisions = results_data.get("scenario_warehouse_metrics", {}).get(scen, [])
        objective = kpis.get("total_cost", 0.0)
        recourse_used = results_data.get("scenario_recourse_used", {}).get(scen, results_data.get("scenario_slack_used", {}).get(scen, {}))
    else:
        kpis = results_data.get("kpis", {})
        routes = results_data.get("routes", [])
        wh_decisions = results_data.get("warehouse_decisions", [])
        objective = results_data.get("objective", 0.0)
        recourse_used = results_data.get("recourse_used", results_data.get("slack_used", {}))

    warnings = results_data.get("warnings", {})

    obj_str = fmt_curr(objective)
    tons = fmt_num(kpis.get('total_tons', 0))
    kms = fmt_num(kpis.get('total_km', 0))
    freight = fmt_curr(kpis.get('total_freight_cost', 0))
    storage = fmt_curr(kpis.get('total_storage_cost', 0))
    transshipment = fmt_curr(kpis.get('total_transshipment_cost', 0))
    opening = fmt_curr(kpis.get('total_opening_cost', 0))
    expand = fmt_curr(kpis.get('total_expand_cost', 0))
    bulk = fmt_curr(kpis.get('total_bulk_cost', 0))

    # Warehouse decisions metrics
    opened_count = str(sum(1 for w in wh_decisions if w.get("IsCandidate") and w.get("IsOpen")))
    expanded_count = str(sum(1 for w in wh_decisions if w.get("IsExpanded")))
    bulkified_count = str(sum(1 for w in wh_decisions if w.get("IsBulkified")))
    
    total_inv = (kpis.get('total_opening_cost', 0.0) or 0.0) + (kpis.get('total_expand_cost', 0.0) or 0.0) + (kpis.get('total_bulk_cost', 0.0) or 0.0)
    investment_str = fmt_curr(total_inv)

    # Warehouse table data
    if not show_all_warehouses_bool:
        filtered_decisions = [
            w for w in wh_decisions
            if w.get("TotalOutflow", 0) > 1e-4 or w.get("FinalStock", 0) > 1e-4 or (w.get("IsCandidate") and w.get("IsOpen"))
        ]
    else:
        filtered_decisions = wh_decisions
        
    wh_table_data = [make_warehouse_row(w, lang) for w in filtered_decisions]

    wh_columns = [
        {'name': translate('Nome', lang), 'id': 'Name'},
        {'name': translate('Tipo', lang), 'id': 'Type'},
        {'name': translate('Status', lang), 'id': 'Status'},
        {'name': translate('Cap. Estática (ton)', lang), 'id': 'StaticCap'},
        {'name': translate('Expandido?', lang), 'id': 'IsExpanded'},
        {'name': translate('Expansão (ton)', lang), 'id': 'ExpandedVol'},
        {'name': translate('Granelizado?', lang), 'id': 'IsBulkified'},
        {'name': translate('Granelização (ton/dia)', lang), 'id': 'BulkCap'},
        {'name': translate('Cap. Efetiva (ton)', lang), 'id': 'EffStaticCap'},
        {'name': translate('Saída Total (ton)', lang), 'id': 'TotalOutflow'},
        {'name': translate('Estoque Final (ton)', lang), 'id': 'FinalStock'},
        {'name': translate('Cap. Dinâmica Anual (ton/ano)', lang), 'id': 'DynCap'},
        {'name': translate('Giro Anual', lang), 'id': 'TurnoverRatio'}
    ]

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

        if "Período" in r:
            row_data["Período"] = r["Período"]

        if "Tipo de Rota" in r:
            row_data["Tipo de Rota"] = translate(r["Tipo de Rota"], lang)

        table_data.append(row_data)

    columns = [
        {'name': translate('Origem', lang), 'id': 'Origem'},
        {'name': translate('Destino', lang), 'id': 'Destino'},
        {'name': translate('Produto', lang), 'id': 'Produto'},
        {'name': translate('Qtd (ton)', lang), 'id': 'Quantidade (ton)'}
    ]

    if has_viagens:
        columns.append({'name': translate('Qtd. de Viagens', lang), 'id': 'Qtd. de Viagens'})

    if any("Período" in r for r in routes):
        columns.append({'name': translate('Período', lang), 'id': 'Período'})

    if any("Tipo de Rota" in r for r in routes):
        columns.append({'name': translate('Tipo de Rota', lang), 'id': 'Tipo de Rota'})

    # Render warnings
    warnings_html = []

    # Emergency capacity and unmet demand recourse warnings red container
    if recourse_used and recourse_used.get("has_slack", False):
        emerg_static_items = recourse_used.get("emerg_static", recourse_used.get("slack_static", {})).get("items", [])
        unmet_demand_items = recourse_used.get("unmet_demand", recourse_used.get("slack_demand", {})).get("items", [])
        
        static_li = []
        for item in emerg_static_items:
            dest_name = item.get("destination_name", item.get("destination"))
            period = item.get("period")
            tons = item.get("tons")
            penalty_rate = item.get("penalty_rate")
            cost = item.get("cost")
            
            tons_str = fmt_num(tons)
            rate_str = fmt_curr(penalty_rate)
            cost_str = fmt_curr(cost)
            
            msg = translate("Armazém {name} (Período {period}): {tons} ton de capacidade temporária de emergência utilizada (Tarifa de Penalidade: {rate}/ton, Custo Adicional: {cost})", lang).format(
                name=dest_name, period=period, tons=tons_str, rate=rate_str, cost=cost_str
            )
            static_li.append(html.Li(msg))
            
        demand_li = []
        for item in unmet_demand_items:
            customer = item.get("customer")
            product = item.get("product")
            period = item.get("period")
            tons = item.get("tons")
            penalty_rate = item.get("penalty_rate")
            cost = item.get("cost")
            
            tons_str = fmt_num(tons)
            rate_str = fmt_curr(penalty_rate)
            cost_str = fmt_curr(cost)
            
            msg = translate("Cliente {customer} - Produto {product} (Período {period}): {tons} ton de demanda interna não atendida (Tarifa de Penalidade: {rate}/ton, Custo Adicional: {cost})", lang).format(
                customer=customer, product=product, period=period, tons=tons_str, rate=rate_str, cost=cost_str
            )
            demand_li.append(html.Li(msg))
            
        recourse_total_cost = recourse_used.get("total_recourse_cost", recourse_used.get("total_slack_cost", 0.0))
        
        warnings_html.append(dbc.Alert([
            html.H5([html.I(className="bi bi-exclamation-octagon-fill me-2"), translate("Aviso: Uso de Capacidade Temporária de Emergência e Demanda Não Atendida Detectado!", lang)], className="alert-heading"),
            html.P(translate("Para manter a viabilidade matemática sob cenários severos, o modelo precisou recorrer a capacidades temporárias de emergência ou não atender integralmente contratos de demanda. Estas ações possuem um custo penalizado significativo no objetivo total.", lang)),
            html.Hr(),
            html.Ul(static_li + demand_li, className="mb-3"),
            html.P([
                html.B(translate("Impacto Financeiro Adicional no Custo Total:", lang) + " "),
                html.Span(fmt_curr(recourse_total_cost), className="fw-bold text-danger")
            ], className="mb-0")
        ], className="alert-danger-custom shadow-sm mb-3"))

    if isinstance(warnings, list):
        if warnings:
            title = translate("Aviso de Viabilidade do Modelo", lang) if is_stochastic else translate("Atenção: Uso de Capacidade Artificial Detectado!", lang)
            desc = translate("O modelo identificou possíveis restrições de viabilidade ou oferta menor que a demanda nos cenários:", lang) if is_stochastic else translate("O modelo matemático identificou restrições na sua infraestrutura real. Para evitar que o modelo ficasse 'sem solução' e para indicar onde estão os gargalos logísticos, as seguintes capacidades artificiais foram utilizadas (Elas carregam um custo exorbitante no modelo):", lang)
            alert_class = "alert-warning-custom shadow-sm mb-3" if is_stochastic else "alert-danger-custom shadow-sm mb-3"
            
            warnings_list = [html.Li(w) for w in warnings]
            warnings_html.append(dbc.Alert([
                html.H5([html.I(className="bi bi-exclamation-triangle-fill me-2"), title], className="alert-heading"),
                html.P(desc),
                html.Hr(),
                html.Ul(warnings_list, className="mb-0")
            ], className=alert_class))
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
                    html.Li(translate("Considere utilizar o modelo com prazos mais flexíveis ou revisar as rotas de menor custo.", lang))
                ], className="mb-0")
            ], className="alert-warning-custom shadow-sm mb-3"))

        # 3. Freight warnings (MILP)
        freight_warnings = warnings.get("freight", [])
        if freight_warnings:
            warnings_list = [html.Li(w) for w in freight_warnings]
            warnings_html.append(dbc.Alert([
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

    return (
        obj_str, tons, kms, freight, storage, transshipment,
        opening, expand, bulk, opened_count, expanded_count,
        bulkified_count, investment_str, wh_table_data, wh_columns,
        table_data, columns, warnings_html, selector_style
    )

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

    model_stats = results_data.get("model_stats", {})
    configs = results_data.get("configs", {})
    
    config_rows = []
    
    # 1. General Settings
    model_type_val = configs.get("model_type", results_data.get("model_type", "deterministic"))
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Tipo de Modelo", lang),
        translate("Valor", lang): translate("Estocástico", lang) if model_type_val == "stochastic" else translate("Determinístico", lang)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Solver", lang),
        translate("Valor", lang): str(configs.get("solver_name", "cbc")).upper()
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Gap do solver (%)", lang),
        translate("Valor", lang): configs.get("solver_gap", 0.0)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Tempo limite do solver (s)", lang),
        translate("Valor", lang): configs.get("solver_time_limit", 0)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Dias operacionais por período", lang),
        translate("Valor", lang): configs.get("input_allocation_days", 0)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Fator interhub (α)", lang),
        translate("Valor", lang): configs.get("interhub_factor", 0.0)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Ativar Arcos Diretos (Origem -> Cliente)", lang),
        translate("Valor", lang): translate("Sim", lang) if configs.get("toggle_direct_arcs") else translate("Não", lang)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Geral", lang),
        translate("Parâmetro", lang): translate("Filtrar rotas pelo Pareto de distância", lang),
        translate("Valor", lang): translate("Sim", lang) if configs.get("toggle_pareto") else translate("Não", lang)
    })
    
    # 2. Expansion Settings
    exp_enabled = configs.get("expansion_enabled", False)
    config_rows.append({
        translate("Categoria", lang): translate("Expansão Física", lang),
        translate("Parâmetro", lang): translate("Habilitar Expansão", lang),
        translate("Valor", lang): translate("Sim", lang) if exp_enabled else translate("Não", lang)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Expansão Física", lang),
        translate("Parâmetro", lang): translate("Razão de Capacidade de Recepção", lang),
        translate("Valor", lang): configs.get("ratio_expand_rec", 0.0)
    })
    config_rows.append({
        translate("Categoria", lang): translate("Expansão Física", lang),
        translate("Parâmetro", lang): translate("Razão de Capacidade de Expedição", lang),
        translate("Valor", lang): configs.get("ratio_expand_ship", 0.0)
    })
    if exp_enabled:
        config_rows.append({
            translate("Categoria", lang): translate("Expansão Física", lang),
            translate("Parâmetro", lang): translate("Expansão máxima (t)", lang),
            translate("Valor", lang): configs.get("max_expand_capacity", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Expansão Física", lang),
            translate("Parâmetro", lang): translate("Custo fixo de expansão ($)", lang),
            translate("Valor", lang): configs.get("expand_fixed_cost", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Expansão Física", lang),
            translate("Parâmetro", lang): translate("Custo variável de expansão ($/t)", lang),
            translate("Valor", lang): configs.get("expand_var_cost", 0.0)
        })
        
    # 3. Bulkification Settings
    bulk_enabled = configs.get("bulk_enabled", False)
    config_rows.append({
        translate("Categoria", lang): translate("Granelização", lang),
        translate("Parâmetro", lang): translate("Habilitar Granelização", lang),
        translate("Valor", lang): translate("Sim", lang) if bulk_enabled else translate("Não", lang)
    })
    if bulk_enabled:
        config_rows.append({
            translate("Categoria", lang): translate("Granelização", lang),
            translate("Parâmetro", lang): translate("Granelização máxima (t/dia)", lang),
            translate("Valor", lang): configs.get("max_bulk_capacity", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Granelização", lang),
            translate("Parâmetro", lang): translate("Custo fixo de granelização ($)", lang),
            translate("Valor", lang): configs.get("bulk_fixed_cost", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Granelização", lang),
            translate("Parâmetro", lang): translate("Custo var. de granelização ($/(t · dia))", lang),
            translate("Valor", lang): configs.get("bulk_var_cost", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Granelização", lang),
            translate("Parâmetro", lang): translate("Tipos elegíveis para granelização", lang),
            translate("Valor", lang): ", ".join(configs.get("bulk_eligible_types", []) or [])
        })

    # 4. Stochastic Settings (if stochastic)
    if model_type_val == "stochastic":
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Probabilidade Cenário Pessimista", lang),
            translate("Valor", lang): configs.get("prob_pessimista", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Probabilidade Cenário Esperado", lang),
            translate("Valor", lang): configs.get("prob_esperado", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Probabilidade Cenário Otimista", lang),
            translate("Valor", lang): configs.get("prob_otimista", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Origem da incerteza", lang),
            translate("Valor", lang): translate("Previsão de Demanda/Oferta", lang) if configs.get("error_source") == "prediction" else translate("Variação Percentual", lang)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Incerteza da Oferta (%)", lang),
            translate("Valor", lang): configs.get("supply_error_pct", 0.0)
        })
        config_rows.append({
            translate("Categoria", lang): translate("Modelo Estocástico", lang),
            translate("Parâmetro", lang): translate("Incerteza da Demanda (%)", lang),
            translate("Valor", lang): configs.get("demand_error_pct", 0.0)
        })
        
    # 5. Prediction Settings (if predictions used)
    pred_model = configs.get("prediction_model", "N/A")
    pred_test_size = configs.get("prediction_test_size", "N/A")
    pred_horizon = configs.get("prediction_horizon", "N/A")
    
    config_rows.append({
        translate("Categoria", lang): translate("Previsão", lang),
        translate("Parâmetro", lang): translate("Modelo de Previsão", lang),
        translate("Valor", lang): pred_model
    })
    config_rows.append({
        translate("Categoria", lang): translate("Previsão", lang),
        translate("Parâmetro", lang): translate("Período de Teste (meses)", lang),
        translate("Valor", lang): pred_test_size
    })
    config_rows.append({
        translate("Categoria", lang): translate("Previsão", lang),
        translate("Parâmetro", lang): translate("Horizonte de Previsão (meses)", lang),
        translate("Valor", lang): pred_horizon
    })
    
    df_config = pd.DataFrame(config_rows)

    if results_data.get("model_type") == "stochastic":
        scenarios = ["pessimista", "esperado", "otimista"]
        scenario_names_map = {
            "pessimista": translate("Pessimista", lang),
            "esperado": translate("Esperado", lang),
            "otimista": translate("Otimista", lang)
        }
        
        # 1. Resumo por Cenário
        comparison_rows = []
        metrics_def = [
            ("total_cost", translate("Custo Total Ótimo (R$)", lang)),
            ("total_tons", translate("Volume Total Movimentado (ton)", lang)),
            ("total_km", translate("Distância Total Percorrida (km)", lang)),
            ("total_freight_cost", translate("Custo Total de Frete (R$)", lang)),
            ("total_storage_cost", translate("Custo Total de Armazenagem (R$)", lang)),
            ("total_transshipment_cost", translate("Custo Total de Transbordo (R$)", lang)),
            ("total_opening_cost", translate("Custo Total de Abertura (R$)", lang)),
            ("total_expand_cost", translate("Custo Total de Expansão (R$)", lang)),
            ("total_bulk_cost", translate("Custo Total de Granelização (R$)", lang)),
            ("emerg_static_cost", translate("Custo Total de Capacidade de Emergência (R$)", lang)),
            ("unmet_demand_cost", translate("Custo Total de Demanda Não Atendida (R$)", lang)),
            ("total_recourse_cost", translate("Custo Total de Penalidades (R$)", lang))
        ]
        
        for key, label in metrics_def:
            row = {"Métrica" if lang == "pt" else "Metric": label}
            for s in scenarios:
                s_kpi = results_data.get("scenario_kpis", {}).get(s, {})
                recourse_s = results_data.get("scenario_recourse_used", {}).get(s, results_data.get("scenario_slack_used", {}).get(s, {}))
                if key == "emerg_static_cost":
                    val = recourse_s.get("emerg_static", recourse_s.get("slack_static", {})).get("total_cost", 0.0)
                elif key == "unmet_demand_cost":
                    val = recourse_s.get("unmet_demand", recourse_s.get("slack_demand", {})).get("total_cost", 0.0)
                elif key == "total_recourse_cost":
                    val = recourse_s.get("total_recourse_cost", recourse_s.get("total_slack_cost", 0.0))
                else:
                    val = s_kpi.get(key, 0.0)
                row[scenario_names_map[s]] = val
            comparison_rows.append(row)
        df_comparison = pd.DataFrame(comparison_rows)

        df_routes_by_scen = {}
        for s in scenarios:
            s_routes = results_data.get("scenario_routes", {}).get(s, [])
            route_rows = []
            for r in s_routes:
                row = {
                    translate("Origem", lang): r.get("Origem", ""),
                    translate("Destino", lang): r.get("Destino", ""),
                    translate("Produto", lang): r.get("Produto", ""),
                    translate("Quantidade (ton)", lang): r.get("Quantidade (ton)", 0.0),
                    translate("Período", lang): r.get("Período", ""),
                    translate("Tipo de Rota", lang): translate(r.get("Tipo de Rota", ""), lang),
                    translate("Distancia (km)", lang): r.get("Distancia (km)", 0.0),
                    translate("Custo Frete (R$)", lang): r.get("Custo Frete (R$)", 0.0)
                }
                if "Qtd. de Viagens" in r and r["Qtd. de Viagens"] is not None:
                    row[translate("Qtd. de Viagens", lang)] = r["Qtd. de Viagens"]
                route_rows.append(row)
            df_routes_by_scen[s] = pd.DataFrame(route_rows)
            
        df_wh_by_scen = {}
        for s in scenarios:
            s_wh = results_data.get("scenario_warehouse_metrics", {}).get(s, [])
            wh_rows = []
            for w in s_wh:
                is_cand = w.get("IsCandidate", False)
                type_str = translate("Candidato", lang) if is_cand else translate("Existente", lang)
                
                is_open = w.get("IsOpen", False)
                status_str = translate("Aberto", lang) if is_open else translate("Fechado", lang)
                
                is_exp = w.get("IsExpanded", False)
                exp_str = translate("Sim", lang) if is_exp else translate("Não", lang)
                
                is_bulk = w.get("IsBulkified", False)
                bulk_str = translate("Sim", lang) if is_bulk else translate("Não", lang)
                
                wh_rows.append({
                    "CDA": w.get("CDA", ""),
                    translate("Nome", lang): w.get("Name", ""),
                    translate("Tipo", lang): type_str,
                    translate("Status", lang): status_str,
                    translate("Cap. Estática (ton)", lang): w.get("DecidedStaticCapacity", 0.0),
                    translate("Expandido?", lang): exp_str,
                    translate("Expansão (ton)", lang): w.get("ExpandedVolume", 0.0),
                    translate("Granelizado?", lang): bulk_str,
                    translate("Granelização (ton/dia)", lang): w.get("BulkCapacityAdded", 0.0),
                    translate("Cap. Efetiva (ton)", lang): w.get("EffectiveStaticCapacity", 0.0),
                    translate("Saída Total (ton)", lang): w.get("TotalOutflow", 0.0),
                    translate("Estoque Final (ton)", lang): w.get("FinalStock", 0.0),
                    translate("Cap. Dinâmica Anual (ton/ano)", lang): w.get("DynamicCapacity", 0.0),
                    translate("Giro Anual", lang): w.get("TurnoverRatio", 0.0),
                    translate("Custo Abertura (R$)", lang): w.get("OpeningCost", 0.0),
                    translate("Custo Expansão (R$)", lang): w.get("ExpandCost", 0.0),
                    translate("Custo Granelização (R$)", lang): w.get("BulkCost", 0.0),
                    translate("Custo Armazenagem (R$)", lang): w.get("StorageCost", 0.0),
                    translate("Custo Transbordo (R$)", lang): w.get("TransshipmentCost", 0.0),
                    translate("Custo Total (R$)", lang): w.get("TotalCost", 0.0)
                })
            df_wh_by_scen[s] = pd.DataFrame(wh_rows)

        df_inv_by_scen = {}
        for s in scenarios:
            s_inv = results_data.get("scenario_inventory", {}).get(s, [])
            inv_rows = []
            for i in s_inv:
                inv_rows.append({
                    "CDA": i.get("CDA", ""),
                    translate("Nome", lang): i.get("Name", ""),
                    translate("Produto", lang): i.get("Produto", ""),
                    translate("Período", lang): i.get("Período", ""),
                    translate("Estoque (ton)", lang): i.get("Quantidade (ton)", 0.0),
                    translate("Tarifa Armazenagem (R$/ton)", lang): i.get("StorageTariff", 0.0),
                    translate("Custo Armazenagem (R$)", lang): i.get("StorageCost", 0.0)
                })
            df_inv_by_scen[s] = pd.DataFrame(inv_rows)

        df_recourse_by_scen = {}
        for s in scenarios:
            recourse_s = results_data.get("scenario_recourse_used", {}).get(s, results_data.get("scenario_slack_used", {}).get(s, {}))
            recourse_rows = []
            for item in recourse_s.get("emerg_static", recourse_s.get("slack_static", {})).get("items", []):
                recourse_rows.append({
                    translate("Categoria", lang): translate("Capacidade de Emergência", lang),
                    translate("Local / Entidade", lang): item.get("destination_name", item.get("destination")),
                    translate("Produto", lang): "-",
                    translate("Período", lang): item.get("period", ""),
                    translate("Quantidade (ton)", lang): item.get("tons", 0.0),
                    translate("Tarifa de Penalidade (R$/ton)", lang): item.get("penalty_rate", 0.0),
                    translate("Custo Penalizado (R$)", lang): item.get("cost", 0.0)
                })
            for item in recourse_s.get("unmet_demand", recourse_s.get("slack_demand", {})).get("items", []):
                recourse_rows.append({
                    translate("Categoria", lang): translate("Demanda Não Atendida", lang),
                    translate("Local / Entidade", lang): item.get("customer", ""),
                    translate("Produto", lang): item.get("product", ""),
                    translate("Período", lang): item.get("period", ""),
                    translate("Quantidade (ton)", lang): item.get("tons", 0.0),
                    translate("Tarifa de Penalidade (R$/ton)", lang): item.get("penalty_rate", 0.0),
                    translate("Custo Penalizado (R$)", lang): item.get("cost", 0.0)
                })
            df_recourse_by_scen[s] = pd.DataFrame(recourse_rows)

        stats_rows = [
            {"Métrica" if lang == "pt" else "Metric": translate("Status da Solução", lang), "Valor" if lang == "pt" else "Value": translate(results_data.get("status", ""), lang)},
            {"Métrica" if lang == "pt" else "Metric": translate("Tempo de Execução (segundos)", lang), "Valor" if lang == "pt" else "Value": results_data.get("scenario_kpis", {}).get("esperado", {}).get("execution_time", 0.0)},
            {"Métrica" if lang == "pt" else "Metric": translate("Total de Variáveis", lang), "Valor" if lang == "pt" else "Value": model_stats.get("total_variables", 0)},
            {"Métrica" if lang == "pt" else "Metric": translate("Total de Restrições", lang), "Valor" if lang == "pt" else "Value": model_stats.get("total_constraints", 0)},
            {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Binárias", lang), "Valor" if lang == "pt" else "Value": model_stats.get("binary_variables", 0)},
            {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Inteiras", lang), "Valor" if lang == "pt" else "Value": model_stats.get("integer_variables", 0)},
            {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Contínuas", lang), "Valor" if lang == "pt" else "Value": model_stats.get("continuous_variables", 0)},
        ]
        df_stats = pd.DataFrame(stats_rows)

        def to_xlsx_stochastic(bytes_io):
            with pd.ExcelWriter(bytes_io, engine='openpyxl') as writer:
                df_comparison.to_excel(writer, sheet_name=translate("Resumo por Cenário", lang), index=False)
                for s in scenarios:
                    s_label = scenario_names_map[s]
                    df_wh_by_scen[s].to_excel(writer, sheet_name=f"{translate('Armazéns', lang)} ({s_label})", index=False)
                    df_routes_by_scen[s].to_excel(writer, sheet_name=f"{translate('Rotas', lang)} ({s_label})", index=False)
                    df_inv_by_scen[s].to_excel(writer, sheet_name=f"{translate('Estoque', lang)} ({s_label})", index=False)
                    if not df_recourse_by_scen[s].empty:
                        df_recourse_by_scen[s].to_excel(writer, sheet_name=f"{translate('Penalidades', lang)} ({s_label})", index=False)
                df_config.to_excel(writer, sheet_name=translate("Configurações", lang), index=False)
                df_stats.to_excel(writer, sheet_name=translate("Estatísticas do Modelo", lang), index=False)

        filename = translate("Optimization_Results.xlsx", lang)
        return dcc.send_bytes(to_xlsx_stochastic, filename)

    # Deterministic flow
    kpis = results_data.get("kpis", {})
    routes = results_data.get("routes", [])
    wh_decisions = results_data.get("warehouse_decisions", [])
    inventory = results_data.get("inventory", [])
    objective = results_data.get("objective", 0.0)
    recourse_used = results_data.get("recourse_used", results_data.get("slack_used", {}))
    emerg_static_cost = recourse_used.get("emerg_static", recourse_used.get("slack_static", {})).get("total_cost", 0.0)
    unmet_demand_cost = recourse_used.get("unmet_demand", recourse_used.get("slack_demand", {})).get("total_cost", 0.0)
    recourse_total_cost = recourse_used.get("total_recourse_cost", recourse_used.get("total_slack_cost", 0.0))

    # 1. Sheet 1: KPIs
    kpi_rows = [
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total Ótimo (R$)", lang), "Valor" if lang == "pt" else "Value": objective},
        {"Métrica" if lang == "pt" else "Metric": translate("Volume Total Movimentado (ton)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_tons", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Distância Total Percorrida (km)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_km", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Frete (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_freight_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Armazenagem (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_storage_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Transbordo (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_transshipment_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Abertura (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_opening_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Expansão (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_expand_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Granelização (R$)", lang), "Valor" if lang == "pt" else "Value": kpis.get("total_bulk_cost", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Capacidade de Emergência (R$)", lang), "Valor" if lang == "pt" else "Value": emerg_static_cost},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Demanda Não Atendida (R$)", lang), "Valor" if lang == "pt" else "Value": unmet_demand_cost},
        {"Métrica" if lang == "pt" else "Metric": translate("Custo Total de Penalidades (R$)", lang), "Valor" if lang == "pt" else "Value": recourse_total_cost},
    ]
    df_kpi = pd.DataFrame(kpi_rows)

    # 2. Sheet 2: Decisões Armazéns
    wh_rows = []
    for w in wh_decisions:
        is_cand = w.get("IsCandidate", False)
        type_str = translate("Candidato", lang) if is_cand else translate("Existente", lang)
        
        is_open = w.get("IsOpen", False)
        status_str = translate("Aberto", lang) if is_open else translate("Fechado", lang)
        
        is_exp = w.get("IsExpanded", False)
        exp_str = translate("Sim", lang) if is_exp else translate("Não", lang)
        
        is_bulk = w.get("IsBulkified", False)
        bulk_str = translate("Sim", lang) if is_bulk else translate("Não", lang)
        
        wh_rows.append({
            "CDA": w.get("CDA", ""),
            translate("Nome", lang): w.get("Name", ""),
            translate("Tipo", lang): type_str,
            translate("Status", lang): status_str,
            translate("Cap. Estática (ton)", lang): w.get("DecidedStaticCapacity", 0.0),
            translate("Expandido?", lang): exp_str,
            translate("Expansão (ton)", lang): w.get("ExpandedVolume", 0.0),
            translate("Granelizado?", lang): bulk_str,
            translate("Granelização (ton/dia)", lang): w.get("BulkCapacityAdded", 0.0),
            translate("Cap. Efetiva (ton)", lang): w.get("EffectiveStaticCapacity", 0.0),
            translate("Saída Total (ton)", lang): w.get("TotalOutflow", 0.0),
            translate("Estoque Final (ton)", lang): w.get("FinalStock", 0.0),
            translate("Cap. Dinâmica Anual (ton/ano)", lang): w.get("DynamicCapacity", 0.0),
            translate("Giro Anual", lang): w.get("TurnoverRatio", 0.0),
            translate("Custo Abertura (R$)", lang): w.get("OpeningCost", 0.0),
            translate("Custo Expansão (R$)", lang): w.get("ExpandCost", 0.0),
            translate("Custo Granelização (R$)", lang): w.get("BulkCost", 0.0),
            translate("Custo Armazenagem (R$)", lang): w.get("StorageCost", 0.0),
            translate("Custo Transbordo (R$)", lang): w.get("TransshipmentCost", 0.0),
            translate("Custo Total (R$)", lang): w.get("TotalCost", 0.0)
        })
    df_wh = pd.DataFrame(wh_rows)

    # 3. Sheet 3: Rotas
    route_rows = []
    for r in routes:
        row = {
            translate("Origem", lang): r.get("Origem", ""),
            translate("Destino", lang): r.get("Destino", ""),
            translate("Produto", lang): r.get("Produto", ""),
            translate("Quantidade (ton)", lang): r.get("Quantidade (ton)", 0.0),
            translate("Período", lang): r.get("Período", ""),
            translate("Tipo de Rota", lang): translate(r.get("Tipo de Rota", ""), lang),
            translate("Distancia (km)", lang): r.get("Distancia (km)", 0.0),
            translate("Custo Frete (R$)", lang): r.get("Custo Frete (R$)", 0.0)
        }
        if "Qtd. de Viagens" in r and r["Qtd. de Viagens"] is not None:
            row[translate("Qtd. de Viagens", lang)] = r["Qtd. de Viagens"]
        route_rows.append(row)
    df_routes = pd.DataFrame(route_rows)

    # 4. Sheet 4: Estoque por Período
    inv_rows = []
    for i in inventory:
        inv_rows.append({
            "CDA": i.get("CDA", ""),
            translate("Nome", lang): i.get("Name", ""),
            translate("Produto", lang): i.get("Produto", ""),
            translate("Período", lang): i.get("Período", ""),
            translate("Estoque (ton)", lang): i.get("Quantidade (ton)", 0.0),
            translate("Tarifa Armazenagem (R$/ton)", lang): i.get("StorageTariff", 0.0),
            translate("Custo Armazenagem (R$)", lang): i.get("StorageCost", 0.0)
        })
    df_inv = pd.DataFrame(inv_rows)

    # 5. Sheet 5: Penalidades
    recourse_rows = []
    emerg_items = recourse_used.get("emerg_static", recourse_used.get("slack_static", {})).get("items", [])
    for item in emerg_items:
        recourse_rows.append({
            translate("Categoria", lang): translate("Capacidade de Emergência", lang),
            translate("Local / Entidade", lang): item.get("destination_name", item.get("destination")),
            translate("Produto", lang): "-",
            translate("Período", lang): item.get("period", ""),
            translate("Quantidade (ton)", lang): item.get("tons", 0.0),
            translate("Tarifa de Penalidade (R$/ton)", lang): item.get("penalty_rate", 0.0),
            translate("Custo Penalizado (R$)", lang): item.get("cost", 0.0)
        })
    unmet_items = recourse_used.get("unmet_demand", recourse_used.get("slack_demand", {})).get("items", [])
    for item in unmet_items:
        recourse_rows.append({
            translate("Categoria", lang): translate("Demanda Não Atendida", lang),
            translate("Local / Entidade", lang): item.get("customer", ""),
            translate("Produto", lang): item.get("product", ""),
            translate("Período", lang): item.get("period", ""),
            translate("Quantidade (ton)", lang): item.get("tons", 0.0),
            translate("Tarifa de Penalidade (R$/ton)", lang): item.get("penalty_rate", 0.0),
            translate("Custo Penalizado (R$)", lang): item.get("cost", 0.0)
        })
    df_recourse = pd.DataFrame(recourse_rows)

    # 6. Sheet 6: Estatísticas do Modelo
    stats_rows = [
        {"Métrica" if lang == "pt" else "Metric": translate("Status da Solução", lang), "Valor" if lang == "pt" else "Value": translate(results_data.get("status", ""), lang)},
        {"Métrica" if lang == "pt" else "Metric": translate("Tempo de Execução (segundos)", lang), "Valor" if lang == "pt" else "Value": kpis.get("execution_time", 0.0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Total de Variáveis", lang), "Valor" if lang == "pt" else "Value": model_stats.get("total_variables", 0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Total de Restrições", lang), "Valor" if lang == "pt" else "Value": model_stats.get("total_constraints", 0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Binárias", lang), "Valor" if lang == "pt" else "Value": model_stats.get("binary_variables", 0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Inteiras", lang), "Valor" if lang == "pt" else "Value": model_stats.get("integer_variables", 0)},
        {"Métrica" if lang == "pt" else "Metric": translate("Variáveis Contínuas", lang), "Valor" if lang == "pt" else "Value": model_stats.get("continuous_variables", 0)},
    ]
    df_stats = pd.DataFrame(stats_rows)

    def to_xlsx(bytes_io):
        with pd.ExcelWriter(bytes_io, engine='openpyxl') as writer:
            df_kpi.to_excel(writer, sheet_name=translate("Resumo", lang), index=False)
            df_wh.to_excel(writer, sheet_name=translate("Decisões Armazéns", lang), index=False)
            df_routes.to_excel(writer, sheet_name=translate("Rotas", lang), index=False)
            df_inv.to_excel(writer, sheet_name=translate("Estoque por Período", lang), index=False)
            if not df_recourse.empty:
                df_recourse.to_excel(writer, sheet_name=translate("Penalidades", lang), index=False)
            df_config.to_excel(writer, sheet_name=translate("Configurações", lang), index=False)
            df_stats.to_excel(writer, sheet_name=translate("Estatísticas do Modelo", lang), index=False)

    filename = translate("Optimization_Results.xlsx", lang)
    return dcc.send_bytes(to_xlsx, filename)



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
    [State("radio-results-scenario-select", "value"),
     State("table-results-routes", "derived_viewport_data"),
     State("store-model-results", "data"),
     State("stored-data", "data"),
     State("store-warehouses", "data"),
     State("stored-demand-data", "data"),
     State("store-lang", "data")],
    prevent_initial_call=True
)
def update_results_map(active_cell, btn_all_routes, btn_confirm_all, scenario_map_select, table_data, results_data, stored_data, stored_warehouses, stored_demand_data, lang='pt'):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    if trigger_id == "table-results-routes" and not active_cell:
        return dash.no_update, dash.no_update

    # Resolve active routes list based on selected scenario if stochastic
    selected_scenario = scenario_map_select or "esperado"
    if results_data and results_data.get("model_type") == "stochastic":
        routes = results_data.get("scenario_routes", {}).get(selected_scenario, [])
    else:
        routes = results_data.get("routes", []) if results_data else []

    # Handle the "Show All" logic depending on route length
    if trigger_id == "btn-show-all-routes":
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
    mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
    uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)
    armaz_col = next((c for c in df_warehouses.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)

    dest_mapping = {}
    for _, row in df_warehouses.iterrows():
        cda = str(row['CDA']).strip()
        parts = []
        if pd.notna(row['CDA']):
            parts.append(str(row['CDA']).strip())
        if armaz_col and pd.notna(row[armaz_col]):
            parts.append(str(row[armaz_col]).strip())
        if mun_col and pd.notna(row[mun_col]):
            parts.append(str(row[mun_col]).strip())
        
        name = " - ".join(parts) if parts else cda
        
        # Resolve coords
        lat_val = float(row[lat_col]) if lat_col and pd.notna(row[lat_col]) else None
        lon_val = float(row[lon_col]) if lon_col and pd.notna(row[lon_col]) else None
        if lat_val is None or lon_val is None:
            if mun_col and uf_col and pd.notna(row[mun_col]) and pd.notna(row[uf_col]):
                key = f"{str(row[mun_col]).strip()} - {str(row[uf_col]).strip()}"
                if key in CITY_LOOKUP:
                    lat_val = CITY_LOOKUP[key]['latitude']
                    lon_val = CITY_LOOKUP[key]['longitude']
        if lat_val is not None and lon_val is not None:
            dest_mapping[name] = {"Latitude": lat_val, "Longitude": lon_val}
            dest_mapping[cda] = {"Latitude": lat_val, "Longitude": lon_val}

    # 3. Customer Mappings
    customer_mapping = {}
    if stored_demand_data:
        try:
            df_demand = pd.read_json(io.StringIO(stored_demand_data), orient='split')
            demand_df_map = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
            demand_city_counts_map = demand_df_map['Cidade'].value_counts()
            demand_duplicates_map = demand_city_counts_map[demand_city_counts_map > 1].index

            demand_df_map['Cidade_Display'] = demand_df_map.apply(
                lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
                if row['Cidade'] in demand_duplicates_map else row['Cidade'],
                axis=1
            )
            customer_mapping = demand_df_map.set_index('Cidade_Display')[['Latitude', 'Longitude']].to_dict('index')
        except Exception as e:
            print(f"Error building customer mapping: {e}")

    def get_coords_optimized(orig_name, dest_name):
        origin_coords = None
        orig_cda = orig_name.split(" - ")[0].strip() if orig_name else ""
        if orig_name in origin_mapping:
            o = origin_mapping[orig_name]
            origin_coords = (o['Latitude'], o['Longitude'])
        elif orig_name in dest_mapping:
            o = dest_mapping[orig_name]
            origin_coords = (o['Latitude'], o['Longitude'])
        elif orig_cda in dest_mapping:
            o = dest_mapping[orig_cda]
            origin_coords = (o['Latitude'], o['Longitude'])

        dest_coords = None
        dest_cda = dest_name.split(" - ")[0].strip() if dest_name else ""
        if dest_name in dest_mapping:
            d = dest_mapping[dest_name]
            dest_coords = (d['Latitude'], d['Longitude'])
        elif dest_cda in dest_mapping:
            d = dest_mapping[dest_cda]
            dest_coords = (d['Latitude'], d['Longitude'])
        elif dest_name in customer_mapping:
            d = customer_mapping[dest_name]
            dest_coords = (d['Latitude'], d['Longitude'])
        else:
            # Fallback for customer/origin
            fallback_row = df_input[df_input['Cidade'] == dest_name]
            if not fallback_row.empty:
                dest_coords = (fallback_row.iloc[0]['Latitude'], fallback_row.iloc[0]['Longitude'])

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

        # Find exact route in current active routes
        route_detail = None
        for r in routes:
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
        total_val = route_detail.get('Custo Total (R$)', route_detail.get('Custo Frete (R$)', 0.0))
        fmt_total = f"R$ {total_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_qtd = f"{route_detail['Quantidade (ton)']:,.2f} ton".replace(",", "X").replace(".", ",").replace("X", ".")
        fmt_dist = f"{route_detail['Distancia (km)']:,.2f} km".replace(",", "X").replace(".", ",").replace("X", ".")

        r_type = route_detail.get("Tipo de Rota", "")
        if r_type == "Origem -> Armazém":
            type_color_class = "text-success-custom"
        elif r_type == "Armazém -> Cliente":
            type_color_class = "text-danger-custom"
        elif r_type == "Origem -> Cliente":
            type_color_class = "text-info-custom"
        else:
            type_color_class = "text-warning-custom"

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
                    html.Div([html.I(className=f"bi bi-signpost-split-fill {type_color_class} me-2"), html.Strong(translate("Tipo de Rota", lang) + ": ")]),
                    html.Span(translate(r_type, lang), className=f"fw-bold {type_color_class} d-block ms-4")
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
            ], flush=True, className="flex-grow-1"),
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
        ], className="shadow-sm border-0 h-100 d-flex flex-column")

        return fig, details_html

    # Show all routes
    if trigger_id == "btn-confirm-all-routes" or trigger_id == "btn-show-all-routes" or (trigger_id is None and routes):
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


# --- Scenario Comparison Map Callbacks ---

# --- Scenario Comparison Map Callbacks ---

@app.callback(
    [Output("graph-scenario-minimap-pessimista", "figure"),
     Output("graph-scenario-minimap-esperado", "figure"),
     Output("graph-scenario-minimap-otimista", "figure")],
    [Input("store-model-results", "data"),
     Input("graph-scenario-minimap-pessimista", "relayoutData"),
     Input("graph-scenario-minimap-esperado", "relayoutData"),
     Input("graph-scenario-minimap-otimista", "relayoutData"),
     Input("radio-scenario-comparison-variable", "value"),
     Input("main-tabs", "active_tab"),
     Input("stochastic-results-actual-card", "style")],
    [State("graph-scenario-minimap-pessimista", "figure"),
     State("graph-scenario-minimap-esperado", "figure"),
     State("graph-scenario-minimap-otimista", "figure"),
     State("stored-data", "data"),
     State("store-warehouses", "data"),
     State("stored-demand-data", "data"),
     State("store-lang", "data")]
)
def update_scenario_network_map(results_data, pess_relayout, esp_relayout, otim_relayout, selected_var, active_tab, card_style,
                                pess_fig, esp_fig, otim_fig,
                                stored_data, stored_warehouses, stored_demand_data, lang='pt'):
    # Default map centered on Brazil
    def make_default_map():
        fig = go.Figure(go.Scattermapbox())
        fig.update_layout(
            mapbox_style="open-street-map",
            mapbox_zoom=3,
            mapbox_center={"lat": -14.2350, "lon": -51.9253},
            margin={"r": 0, "t": 0, "l": 0, "b": 0},
            showlegend=False
        )
        return fig

    default_fig = make_default_map()

    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    # Handle map zoom/pan synchronization
    if trigger_id in ["graph-scenario-minimap-pessimista", "graph-scenario-minimap-esperado", "graph-scenario-minimap-otimista"]:
        relayout_data = None
        trigger_fig = None
        if trigger_id == "graph-scenario-minimap-pessimista":
            relayout_data = pess_relayout
            trigger_fig = pess_fig
        elif trigger_id == "graph-scenario-minimap-esperado":
            relayout_data = esp_relayout
            trigger_fig = esp_fig
        elif trigger_id == "graph-scenario-minimap-otimista":
            relayout_data = otim_relayout
            trigger_fig = otim_fig

        if relayout_data:
            center = None
            zoom = None
            
            # Extract zoom
            zoom = relayout_data.get("mapbox.zoom")
            
            # Extract center (handle flat keys as well as dictionary representation)
            current_center = None
            if trigger_fig and isinstance(trigger_fig, dict) and "layout" in trigger_fig and "mapbox" in trigger_fig["layout"]:
                current_center = trigger_fig["layout"]["mapbox"].get("center")
                
            mapbox_center = relayout_data.get("mapbox.center")
            if isinstance(mapbox_center, dict):
                center = mapbox_center.copy()
            else:
                lat = relayout_data.get("mapbox.center.lat")
                lon = relayout_data.get("mapbox.center.lon")
                if lat is not None or lon is not None:
                    curr_lat = current_center.get("lat", -14.2350) if isinstance(current_center, dict) else -14.2350
                    curr_lon = current_center.get("lon", -51.9253) if isinstance(current_center, dict) else -51.9253
                    center = {
                        "lat": lat if lat is not None else curr_lat,
                        "lon": lon if lon is not None else curr_lon
                    }

            if center is not None or zoom is not None:
                # Compare to current state to prevent circular/feedback callbacks
                any_change = False
                for fig in [pess_fig, esp_fig, otim_fig]:
                    if fig and isinstance(fig, dict) and "layout" in fig and "mapbox" in fig["layout"]:
                        current_mapbox = fig["layout"]["mapbox"]
                        if center is not None and current_mapbox.get("center") != center:
                            any_change = True
                        if zoom is not None and current_mapbox.get("zoom") != zoom:
                            any_change = True
                
                if not any_change:
                    return dash.no_update, dash.no_update, dash.no_update

                # Update maps layout in-place and return them
                for fig in [pess_fig, esp_fig, otim_fig]:
                    if fig and isinstance(fig, dict) and "layout" in fig and "mapbox" in fig["layout"]:
                        if center is not None:
                            fig["layout"]["mapbox"]["center"] = center
                        if zoom is not None:
                            fig["layout"]["mapbox"]["zoom"] = zoom
                return pess_fig, esp_fig, otim_fig

    if active_tab != 'tab-stochastic-results':
        return default_fig, default_fig, default_fig

    if not results_data or results_data.get("model_type") != "stochastic" or results_data.get("status") != "optimal":
        return default_fig, default_fig, default_fig

    if not stored_data or not stored_warehouses:
        return default_fig, default_fig, default_fig

    try:
        df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')

        # Destination Mappings
        lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
        lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)
        mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
        uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)
        armaz_col = next((c for c in df_warehouses.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)

        dest_mapping = {}
        for _, row in df_warehouses.iterrows():
            cda = str(row['CDA']).strip()
            parts = []
            if pd.notna(row['CDA']):
                parts.append(str(row['CDA']).strip())
            if armaz_col and pd.notna(row[armaz_col]):
                parts.append(str(row[armaz_col]).strip())
            if mun_col and pd.notna(row[mun_col]):
                parts.append(str(row[mun_col]).strip())
            
            name = " - ".join(parts) if parts else cda
            
            lat_val = float(row[lat_col]) if lat_col and pd.notna(row[lat_col]) else None
            lon_val = float(row[lon_col]) if lon_col and pd.notna(row[lon_col]) else None
            if lat_val is None or lon_val is None:
                if mun_col and uf_col and pd.notna(row[mun_col]) and pd.notna(row[uf_col]):
                    key = f"{str(row[mun_col]).strip()} - {str(row[uf_col]).strip()}"
                    if key in CITY_LOOKUP:
                        lat_val = CITY_LOOKUP[key]['latitude']
                        lon_val = CITY_LOOKUP[key]['longitude']
            if lat_val is not None and lon_val is not None:
                dest_mapping[name] = {"Latitude": lat_val, "Longitude": lon_val}
                dest_mapping[cda] = {"Latitude": lat_val, "Longitude": lon_val}

        wh_metrics_scen = results_data.get("scenario_warehouse_metrics", {})

        # Resolve selected variable
        var_key = selected_var or "utilization"

        # Pre-calculate max values for scaling across all scenarios
        max_vals = {
            "outflow": 1.0,
            "final_stock": 1.0,
            "storage_cost": 1.0,
            "dynamic_capacity": 1.0,
            "turnover": 1.0
        }
        for s in ["pessimista", "esperado", "otimista"]:
            for w in wh_metrics_scen.get(s, []):
                for k in max_vals.keys():
                    val = 0.0
                    if k == "outflow":
                        val = w.get("TotalOutflow", 0.0)
                    elif k == "final_stock":
                        val = w.get("FinalStock", 0.0)
                    elif k == "storage_cost":
                        val = w.get("StorageCost", 0.0)
                    elif k == "dynamic_capacity":
                        val = w.get("DynamicCapacity", 0.0)
                    elif k == "turnover":
                        val = w.get("TurnoverRatio", 0.0)
                    if val > max_vals[k]:
                        max_vals[k] = val

        # Compute a common center and zoom for all three maps to align them
        all_wh_lats = []
        all_wh_lons = []
        for w in wh_metrics_scen.get("esperado", []):
            cda = w["CDA"]
            name = w["Name"]
            coords = dest_mapping.get(cda) or dest_mapping.get(name)
            if coords:
                all_wh_lats.append(coords["Latitude"])
                all_wh_lons.append(coords["Longitude"])

        # Retrieve current zoom and center from existing figures to preserve user state
        current_center = None
        current_zoom = None
        for fig in [pess_fig, esp_fig, otim_fig]:
            if fig and isinstance(fig, dict) and "layout" in fig and "mapbox" in fig["layout"]:
                current_center = fig["layout"]["mapbox"].get("center")
                current_zoom = fig["layout"]["mapbox"].get("zoom")
                break

        if current_center is not None and current_zoom is not None:
            map_center = current_center
            map_zoom = current_zoom
        elif all_wh_lats and all_wh_lons:
            map_center = {"lat": np.mean(all_wh_lats), "lon": np.mean(all_wh_lons)}
            map_zoom = 3.8
        else:
            map_center = {"lat": -14.2350, "lon": -51.9253}
            map_zoom = 3.5

        # format helpers
        def fmt_curr(val):
            if val is None:
                val = 0.0
            if abs(val) >= 1e9:
                s = f"{val:.2e}"
                if lang != 'en':
                    s = s.replace(".", ",")
                return f"R$ {s}"
            return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def fmt_num(val):
            if val is None:
                val = 0.0
            if abs(val) >= 1e9:
                s = f"{val:.2e}"
                if lang != 'en':
                    s = s.replace(".", ",")
                return s
            return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
        def fmt_num_integer(val):
            if val is None:
                val = 0.0
            if abs(val) >= 1e9:
                s = f"{val:.2e}"
                if lang != 'en':
                    s = s.replace(".", ",")
                return s
            return f"{val:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # Get translation of selected metric
        metric_labels = {
            "utilization": translate("Utilização de Capacidade", lang),
            "outflow": translate("Saída Total", lang),
            "final_stock": translate("Estoque Final", lang),
            "storage_cost": translate("Custo de Armazenagem", lang),
            "dynamic_capacity": translate("Capacidade Dinâmica Anual", lang),
            "turnover": translate("Giro Anual (Turnover)", lang)
        }
        metric_name = metric_labels.get(var_key, "")

        # Determine legend values
        if var_key == "utilization":
            val_min = "0,0%"
            val_mid = "50,0%"
            val_max = "100,0%"
        elif var_key in ["outflow", "final_stock", "dynamic_capacity"]:
            max_val = max_vals.get(var_key, 0.0)
            val_min = "0 t"
            val_mid = f"{fmt_num_integer(max_val * 0.5)} t"
            val_max = f"{fmt_num_integer(max_val)} t"
        elif var_key == "storage_cost":
            max_val = max_vals.get(var_key, 0.0)
            val_min = "R$ 0,00"
            val_mid = fmt_curr(max_val * 0.5)
            val_max = fmt_curr(max_val)
        elif var_key == "turnover":
            max_val = max_vals.get(var_key, 0.0)
            val_min = "0,00"
            val_mid = fmt_num(max_val * 0.5)
            val_max = fmt_num(max_val)

        def make_scenario_wh_map(scen_name):
            fig = go.Figure()
            s_whs = wh_metrics_scen.get(scen_name, [])
            
            open_lats = []
            open_lons = []
            open_ratios = []
            open_sizes = []
            open_texts = []
            
            closed_lats = []
            closed_lons = []
            closed_sizes = []
            closed_texts = []
            
            for w in s_whs:
                cda = w["CDA"]
                name = w["Name"]
                coords = dest_mapping.get(cda) or dest_mapping.get(name)
                if coords:
                    is_open = w.get("IsOpen", False)
                    status_str = translate("Aberto", lang) if is_open else translate("Fechado", lang)
                    wh_type = translate("Candidato", lang) if w.get("IsCandidate") else translate("Existente", lang)
                    
                    # Formatting values
                    fmt_static = f"{w.get('EffectiveStaticCapacity', 0.0):,.0f} t".replace(",", "X").replace(".", ",").replace("X", ".")
                    fmt_outflow = f"{w.get('TotalOutflow', 0.0):,.0f} t".replace(",", "X").replace(".", ",").replace("X", ".")
                    fmt_final = f"{w.get('FinalStock', 0.0):,.0f} t".replace(",", "X").replace(".", ",").replace("X", ".")
                    fmt_storage = f"R$ {w.get('StorageCost', 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    fmt_dyn = f"{w.get('DynamicCapacity', 0.0):,.0f} t".replace(",", "X").replace(".", ",").replace("X", ".")
                    fmt_turnover = f"{w.get('TurnoverRatio', 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    
                    eff_static = w.get("EffectiveStaticCapacity", 0.0)
                    dyn_cap_raw = w.get("DynamicCapacityRaw", 0.0)
                    util_val = (dyn_cap_raw / eff_static) if eff_static > 0.0 else 0.0
                    fmt_util = f"{util_val * 100:,.1f}%".replace(",", "X").replace(".", ",").replace("X", ".")

                    # Highlight selected variable in hover tooltip
                    hover_lines = [
                        f"<b>{name}</b> (CDA: {cda})",
                        f"{translate('Tipo', lang)}: {wh_type}",
                        f"{translate('Status', lang)}: {status_str}",
                    ]
                    
                    def wrap_selected(label, val_str, is_sel):
                        if is_sel:
                            return f"⭐ <b>{label}: {val_str}</b>"
                        return f"{label}: {val_str}"

                    hover_lines.append(wrap_selected(translate('Capacidade Estática Eficiente', lang), fmt_static, False))
                    hover_lines.append(wrap_selected(translate('Saída Total', lang), fmt_outflow, var_key == "outflow"))
                    hover_lines.append(wrap_selected(translate('Estoque Final', lang), fmt_final, var_key == "final_stock"))
                    hover_lines.append(wrap_selected(translate('Custo de Armazenagem', lang), fmt_storage, var_key == "storage_cost"))
                    hover_lines.append(wrap_selected(translate('Capacidade Dinâmica Anual', lang), fmt_dyn, var_key == "dynamic_capacity"))
                    hover_lines.append(wrap_selected(translate('Giro Anual (Turnover)', lang), fmt_turnover, var_key == "turnover"))
                    
                    if is_open:
                        hover_lines.append(wrap_selected(translate('Utilização de Capacidade', lang), fmt_util, var_key == "utilization"))
                    
                    tooltip_text = "<br>".join(hover_lines)

                    if is_open:
                        open_lats.append(coords["Latitude"])
                        open_lons.append(coords["Longitude"])
                        open_texts.append(tooltip_text)
                        
                        # Extract ratio for dynamic color and size scaling
                        ratio = 0.0
                        if var_key == "utilization":
                            ratio = min(util_val, 1.0)
                        elif var_key == "outflow":
                            ratio = w.get("TotalOutflow", 0.0) / max_vals["outflow"] if max_vals["outflow"] > 0.0 else 0.0
                        elif var_key == "final_stock":
                            ratio = w.get("FinalStock", 0.0) / max_vals["final_stock"] if max_vals["final_stock"] > 0.0 else 0.0
                        elif var_key == "storage_cost":
                            ratio = w.get("StorageCost", 0.0) / max_vals["storage_cost"] if max_vals["storage_cost"] > 0.0 else 0.0
                        elif var_key == "dynamic_capacity":
                            ratio = w.get("DynamicCapacity", 0.0) / max_vals["dynamic_capacity"] if max_vals["dynamic_capacity"] > 0.0 else 0.0
                        elif var_key == "turnover":
                            ratio = w.get("TurnoverRatio", 0.0) / max_vals["turnover"] if max_vals["turnover"] > 0.0 else 0.0
                        
                        ratio = min(max(ratio, 0.0), 1.0)
                        open_ratios.append(ratio)
                        open_sizes.append(8 + 16 * np.sqrt(ratio))
                    else:
                        closed_lats.append(coords["Latitude"])
                        closed_lons.append(coords["Longitude"])
                        closed_texts.append(tooltip_text)
                        closed_sizes.append(6)

            if closed_lats:
                fig.add_trace(go.Scattermapbox(
                    mode="markers",
                    lon=closed_lons,
                    lat=closed_lats,
                    marker=dict(
                        size=closed_sizes,
                        color="#6C757D",
                        opacity=0.9
                    ),
                    text=closed_texts,
                    hoverinfo="text",
                    showlegend=False
                ))

            if open_lats:
                if scen_name == "otimista":
                    colorbar_config = dict(
                        thickness=15,
                        len=0.9,
                        x=1.02,
                        y=0.5,
                        yanchor="middle",
                        tickvals=[0.0, 0.5, 1.0],
                        ticktext=[val_min, val_mid, val_max],
                        tickfont=dict(size=10, family="Roboto, sans-serif"),
                        title=dict(
                            text=metric_name,
                            font=dict(size=11, family="Roboto, sans-serif", weight="bold"),
                            side="top"
                        )
                    )
                else:
                    colorbar_config = None

                fig.add_trace(go.Scattermapbox(
                    mode="markers",
                    lon=open_lons,
                    lat=open_lats,
                    marker=dict(
                        size=open_sizes,
                        color=open_ratios,
                        colorscale=[
                            [0.0, "rgb(0,102,51)"],
                            [0.5, "rgb(153,122,0)"],
                            [1.0, "rgb(200,16,46)"]
                        ],
                        cmin=0.0,
                        cmax=1.0,
                        showscale=True if (scen_name == "otimista") else False,
                        colorbar=colorbar_config,
                        opacity=0.9
                    ),
                    text=open_texts,
                    hoverinfo="text",
                    showlegend=False
                ))

            fig.update_layout(
                mapbox_style="open-street-map",
                mapbox_zoom=map_zoom,
                mapbox_center=map_center,
                margin={"r": 0, "t": 0, "l": 0, "b": 0},
                showlegend=False
            )
            return fig

        fig_pess = make_scenario_wh_map("pessimista")
        fig_esp = make_scenario_wh_map("esperado")
        fig_otim = make_scenario_wh_map("otimista")

        return fig_pess, fig_esp, fig_otim

    except Exception as e:
        print(f"Error drawing scenario maps: {e}")
        return default_fig, default_fig, default_fig


@app.callback(
    [Output("wh-route-type-filter", "options"),
     Output("wh-route-type-filter", "value")],
    [Input("store-model-results", "data"),
     Input("toggle-direct-arcs", "value"),
     Input("radio-results-scenario-select", "value"),
     Input("table-results-warehouses", "active_cell"),
     Input("store-lang", "data")],
    [State("wh-route-type-filter", "value")],
    prevent_initial_call=False
)
def update_wh_route_filter_options(results_data, toggle_direct_arcs, scenario_select, active_cell, lang, current_value):
    lang = lang or 'pt'
    
    default_options = [
        {"label": translate("Ver todas as rotas", lang), "value": "all"},
        {"label": translate("Origem -> Armazém", lang), "value": "inflow"},
        {"label": translate("Interhub", lang), "value": "interhub"},
        {"label": translate("Armazém -> Cliente Doméstico", lang), "value": "outflow_domestic"},
        {"label": translate("Armazém -> Cliente Exportação", lang), "value": "outflow_export"},
        {"label": translate("Origem -> Cliente", lang), "value": "direct_only"},
    ]
    
    if not results_data or results_data.get("status") != "optimal":
        return default_options, "all"
        
    selected_scenario = scenario_select or "esperado"
    if results_data.get("model_type") == "stochastic":
        routes = results_data.get("scenario_routes", {}).get(selected_scenario, [])
    else:
        routes = results_data.get("routes", [])
        
    has_inflow = any(r.get("Tipo de Rota") == "Origem -> Armazém" for r in routes)
    has_outflow_dom = any(r.get("Tipo de Rota") in ["Armazém -> Cliente Doméstico", "Armazém -> Cliente"] for r in routes)
    has_outflow_exp = any(r.get("Tipo de Rota") == "Armazém -> Cliente Exportação" for r in routes)
    has_transbordo = any(r.get("Tipo de Rota") == "Interhub" for r in routes)
    has_direct = any(r.get("Tipo de Rota") in ["Origem -> Cliente Doméstico", "Origem -> Cliente Exportação", "Origem -> Cliente"] for r in routes) and (toggle_direct_arcs is True or toggle_direct_arcs is None or toggle_direct_arcs == [1])
    
    allow_direct = (active_cell is None) and has_direct
    
    options = [
        {"label": translate("Ver todas as rotas", lang), "value": "all"},
        {"label": translate("Origem -> Armazém", lang), "value": "inflow", "disabled": not has_inflow},
        {"label": translate("Interhub", lang), "value": "interhub", "disabled": not has_transbordo},
        {"label": translate("Armazém -> Cliente Doméstico", lang), "value": "outflow_domestic", "disabled": not has_outflow_dom},
        {"label": translate("Armazém -> Cliente Exportação", lang), "value": "outflow_export", "disabled": not has_outflow_exp},
        {"label": translate("Origem -> Cliente", lang), "value": "direct_only", "disabled": not allow_direct},
    ]
    
    valid_values = {opt["value"] for opt in options if not opt.get("disabled", False)}
    new_value = current_value if current_value in valid_values else "all"
    
    return options, new_value


@app.callback(
    Output("wh-global-view-filter", "options"),
    [Input("store-lang", "data")]
)
def update_global_filter_options(lang):
    lang = lang or 'pt'
    return [
        {"label": translate("Mostrar todos os armazéns", lang), "value": "show_all"},
    ]


@app.callback(
    [Output("table-results-warehouses", "active_cell"),
     Output("wh-global-view-filter", "value"),
     Output("wh-route-type-filter-container", "style")],
    [Input("table-results-warehouses", "active_cell"),
     Input("wh-global-view-filter", "value"),
     Input("wh-route-type-filter", "value")],
    prevent_initial_call=False
)
def sync_results_wh_selection(active_cell, global_filter, route_type_filter):
    ctx = dash.callback_context
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None
    
    if trigger_id == "wh-route-type-filter":
        if route_type_filter == "direct_only" and active_cell is not None:
            return None, "show_all", {"display": "flex"}
        return no_update, no_update, {"display": "flex"}

    if trigger_id == "table-results-warehouses":
        if active_cell is not None:
            return no_update, None, {"display": "flex"}
        else:
            return no_update, None, {"display": "flex"}
            
    elif trigger_id == "wh-global-view-filter":
        if global_filter == "show_all":
            return None, no_update, {"display": "flex"}
        else:
            return no_update, None, {"display": "flex"}
            
    # Initial load:
    if active_cell is None:
        return no_update, None, {"display": "flex"}
    else:
        return no_update, None, {"display": "flex"}


@app.callback(
    [Output("graph-results-wh-map", "figure"),
     Output("warehouse-details-container", "children"),
     Output("graph-results-wh-inventory", "figure"),
     Output("warehouse-inventory-chart-row", "style")],
    [Input("table-results-warehouses", "active_cell"),
     Input("wh-route-type-filter", "value"),
     Input("store-model-results", "data"),
     Input("main-tabs", "active_tab"),
     Input("radio-results-scenario-select", "value"),
     Input("wh-global-view-filter", "value")],
    [State("table-results-warehouses", "derived_viewport_data"),
     State("stored-data", "data"),
     State("store-warehouses", "data"),
     State("stored-demand-data", "data"),
     State("store-lang", "data")],
    prevent_initial_call=False
)
def update_warehouse_results_map(active_cell, filter_value, results_data, active_tab, scenario_map_select, global_filter, table_data, stored_data, stored_warehouses, stored_demand_data, lang='pt'):
    # Default map centered on Brazil
    default_fig = go.Figure(go.Scattermapbox())
    default_fig.update_layout(
        mapbox_style="open-street-map",
        mapbox_zoom=3.5,
        mapbox_center={"lat": -14.2350, "lon": -51.9253},
        margin={"r": 0, "t": 0, "l": 0, "b": 0}
    )

    if active_tab != 'tab-results':
        return default_fig, html.P(translate("Resultados indisponíveis.", lang), className="text-muted small"), go.Figure(), {"display": "none"}

    if not results_data or results_data.get("status") != "optimal":
        return default_fig, html.P(translate("Resultados indisponíveis.", lang), className="text-muted small"), go.Figure(), {"display": "none"}

    if not stored_data or not stored_warehouses:
        return default_fig, html.P(translate("Faltam dados base para renderizar o mapa.", lang), className="text-muted small"), go.Figure(), {"display": "none"}

    # Define Formatting Helpers early to be available everywhere in the function
    def fmt_num_only(val, decimal_places=2):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.{decimal_places}e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return s
        fmt = f"{{:,.{decimal_places}f}}"
        s = fmt.format(val)
        if lang != 'en':
            s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return s

    def fmt_n(val, unit='ton'):
        return f"{fmt_num_only(val)} {translate(unit, lang)}"

    def fmt_c(val):
        return f"R$ {fmt_num_only(val)}"

    # Resolve active routes list and warehouse decisions based on selected scenario if stochastic
    selected_scenario = scenario_map_select or "esperado"
    if results_data and results_data.get("model_type") == "stochastic":
        wh_decisions = results_data.get("scenario_warehouse_metrics", {}).get(selected_scenario, [])
        routes = results_data.get("scenario_routes", {}).get(selected_scenario, [])
    else:
        wh_decisions = results_data.get("warehouse_decisions", []) if results_data else []
        routes = results_data.get("routes", []) if results_data else []

    # Load dataframes
    df_input = pd.read_json(io.StringIO(stored_data), orient='split')
    df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')

    # Pre-calculate coordinate mappings
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

    # 2. Warehouse Mappings
    lat_col = next((c for c in df_warehouses.columns if 'lat' in str(c).lower()), None)
    lon_col = next((c for c in df_warehouses.columns if 'lon' in str(c).lower()), None)
    mun_col = next((c for c in df_warehouses.columns if 'munic' in str(c).lower()), None)
    uf_col = next((c for c in df_warehouses.columns if 'uf' in str(c).lower()), None)
    armaz_col = next((c for c in df_warehouses.columns if 'armaz' in str(c).lower() or 'nome' in str(c).lower()), None)

    dest_mapping = {}
    for _, row in df_warehouses.iterrows():
        cda = str(row['CDA']).strip()
        parts = []
        if pd.notna(row['CDA']):
            parts.append(str(row['CDA']).strip())
        if armaz_col and pd.notna(row[armaz_col]):
            parts.append(str(row[armaz_col]).strip())
        if mun_col and pd.notna(row[mun_col]):
            parts.append(str(row[mun_col]).strip())
        
        name = " - ".join(parts) if parts else cda
        
        # Resolve coords
        lat_val = float(row[lat_col]) if lat_col and pd.notna(row[lat_col]) else None
        lon_val = float(row[lon_col]) if lon_col and pd.notna(row[lon_col]) else None
        if lat_val is None or lon_val is None:
            if mun_col and uf_col and pd.notna(row[mun_col]) and pd.notna(row[uf_col]):
                key = f"{str(row[mun_col]).strip()} - {str(row[uf_col]).strip()}"
                if key in CITY_LOOKUP:
                    lat_val = CITY_LOOKUP[key]['latitude']
                    lon_val = CITY_LOOKUP[key]['longitude']
        if lat_val is not None and lon_val is not None:
            dest_mapping[name] = {"Latitude": lat_val, "Longitude": lon_val}
            dest_mapping[cda] = {"Latitude": lat_val, "Longitude": lon_val}

    # 3. Customer Mappings
    customer_mapping = {}
    if stored_demand_data:
        try:
            df_demand = pd.read_json(io.StringIO(stored_demand_data), orient='split')
            demand_df_map = df_demand[['Cidade', 'Latitude', 'Longitude']].drop_duplicates().dropna()
            demand_city_counts_map = demand_df_map['Cidade'].value_counts()
            demand_duplicates_map = demand_city_counts_map[demand_city_counts_map > 1].index

            demand_df_map['Cidade_Display'] = demand_df_map.apply(
                lambda row: f"{row['Cidade']} ({row['Latitude']:.4f}, {row['Longitude']:.4f})"
                if row['Cidade'] in demand_duplicates_map else row['Cidade'],
                axis=1
            )
            customer_mapping = demand_df_map.set_index('Cidade_Display')[['Latitude', 'Longitude']].to_dict('index')
        except Exception as e:
            print(f"Error building customer mapping: {e}")

    def get_coords_optimized(orig_name, dest_name):
        origin_coords = None
        orig_cda = orig_name.split(" - ")[0].strip() if orig_name else ""
        if orig_name in origin_mapping:
            o = origin_mapping[orig_name]
            origin_coords = (o['Latitude'], o['Longitude'])
        elif orig_name in dest_mapping:
            o = dest_mapping[orig_name]
            origin_coords = (o['Latitude'], o['Longitude'])
        elif orig_cda in dest_mapping:
            o = dest_mapping[orig_cda]
            origin_coords = (o['Latitude'], o['Longitude'])

        dest_coords = None
        dest_cda = dest_name.split(" - ")[0].strip() if dest_name else ""
        if dest_name in dest_mapping:
            d = dest_mapping[dest_name]
            dest_coords = (d['Latitude'], d['Longitude'])
        elif dest_cda in dest_mapping:
            d = dest_mapping[dest_cda]
            dest_coords = (d['Latitude'], d['Longitude'])
        elif dest_name in customer_mapping:
            d = customer_mapping[dest_name]
            dest_coords = (d['Latitude'], d['Longitude'])
        else:
            fallback_row = df_input[df_input['Cidade'] == dest_name]
            if not fallback_row.empty:
                dest_coords = (fallback_row.iloc[0]['Latitude'], fallback_row.iloc[0]['Longitude'])

        return origin_coords, dest_coords

    osrm_url = os.environ.get("OSRM_URL", "http://localhost:5000")
    client = OSRMClient(base_url=osrm_url)

    # Initial state or Global View: no warehouse selected
    if not active_cell or not table_data:
        if global_filter in ["show_all", "direct_only"]:
            # Gather routes for global view
            wh_routes = []
            for r in routes:
                r_type = r.get("Tipo de Rota", "")
                if r_type == "Armazém -> Cliente":
                    r_type = "Armazém -> Cliente Doméstico"
                elif r_type == "Origem -> Cliente":
                    r_type = "Origem -> Cliente Doméstico"
                
                is_direct_dom = r_type == "Origem -> Cliente Doméstico"
                is_direct_exp = r_type == "Origem -> Cliente Exportação"
                is_direct = is_direct_dom or is_direct_exp
                
                if global_filter == "show_all":
                    if filter_value == "all":
                        wh_routes.append(r)
                    elif filter_value == "direct_only" and is_direct:
                        wh_routes.append(r)
                    elif filter_value == "inflow" and r_type == "Origem -> Armazém":
                        wh_routes.append(r)
                    elif filter_value == "outflow_domestic" and r_type == "Armazém -> Cliente Doméstico":
                        wh_routes.append(r)
                    elif filter_value == "outflow_export" and r_type == "Armazém -> Cliente Exportação":
                        wh_routes.append(r)
                    elif filter_value == "interhub" and r_type == "Interhub":
                        wh_routes.append(r)

            grouped_flows = {}
            for r in wh_routes:
                k = (r["Origem"], r["Destino"], r["Tipo de Rota"])
                grouped_flows[k] = grouped_flows.get(k, 0.0) + r["Quantidade (ton)"]

            fig = go.Figure()
            all_lats, all_lons = [], []

            nodes_to_draw = {}
            for w in wh_decisions:
                w_name = w.get("Name", "")
                w_cda = w.get("CDA", "")
                coords = dest_mapping.get(w_name, dest_mapping.get(w_cda))
                if coords:
                    is_cand = w.get("IsCandidate", False)
                    is_open = w.get("IsOpen", False)
                    if is_cand:
                        n_type = "candidate_open" if is_open else "candidate_closed"
                    else:
                        n_type = "existing"
                    nodes_to_draw[w_name] = {
                        "coords": (coords['Latitude'], coords['Longitude']),
                        "type": n_type,
                        "name": w_name
                    }
                    all_lats.append(coords['Latitude'])
                    all_lons.append(coords['Longitude'])

            for (orig, dest, route_type), qty in grouped_flows.items():
                if qty < 1e-4:
                    continue
                orig_coords, dest_coords = get_coords_optimized(orig, dest)
                if orig_coords and dest_coords:
                    all_lats.extend([orig_coords[0], dest_coords[0]])
                    all_lons.extend([orig_coords[1], dest_coords[1]])

                    orig_cda = orig.split(" - ")[0].strip() if orig else ""
                    if orig not in nodes_to_draw and orig_cda not in nodes_to_draw:
                        nodes_to_draw[orig] = {"coords": orig_coords, "type": "origin", "name": orig}

                    dest_cda = dest.split(" - ")[0].strip() if dest else ""
                    if dest not in nodes_to_draw and dest_cda not in nodes_to_draw:
                        n_type = "customer_export" if dest in results_data.get("Customers_exp", []) else "customer_domestic"
                        nodes_to_draw[dest] = {"coords": dest_coords, "type": n_type, "name": dest}

                    route_type_lookup = route_type
                    if route_type_lookup == "Armazém -> Cliente":
                        route_type_lookup = "Armazém -> Cliente Doméstico"
                    elif route_type_lookup == "Origem -> Cliente":
                        route_type_lookup = "Origem -> Cliente Doméstico"
                        
                    if route_type_lookup == "Origem -> Armazém":
                        line_color = UNB_THEME['UNB_GREEN']
                        line_name = translate("Origem -> Armazém", lang)
                    elif route_type_lookup == "Armazém -> Cliente Doméstico":
                        line_color = '#D9534F'
                        line_name = translate(route_type_lookup, lang)
                    elif route_type_lookup == "Armazém -> Cliente Exportação":
                        line_color = '#C0392B'
                        line_name = translate(route_type_lookup, lang)
                    elif route_type_lookup in ["Origem -> Cliente Doméstico", "Origem -> Cliente Exportação"]:
                        line_color = UNB_THEME['UNB_BLUE_GREEN']
                        line_name = translate(route_type_lookup, lang)
                    else:
                        line_color = UNB_THEME['UNB_YELLOW_DARK']
                        line_name = translate("Interhub", lang)

                    route_data = client.get_route(orig_coords, dest_coords)
                    if route_data:
                        geom = route_data['geometry']
                        lats = [p[1] for p in geom['coordinates']]
                        lons = [p[0] for p in geom['coordinates']]
                        fig.add_trace(go.Scattermapbox(
                            mode="lines", lon=lons, lat=lats,
                            line={'width': 3, 'color': line_color},
                            opacity=0.8,
                            name=line_name,
                            text=f"{qty:,.2f} {translate('ton', lang)}",
                            hoverinfo='text+name'
                        ))

            for name, nd in nodes_to_draw.items():
                n_type = nd["type"]
                n_coords = nd["coords"]
                
                if n_type == "candidate_open":
                    color = UNB_THEME['UNB_BLUE']
                    size = 12
                    lbl = translate("Candidato - Aberto", lang)
                elif n_type == "candidate_closed":
                    color = '#888888'
                    size = 10
                    lbl = translate("Candidato - Fechado", lang)
                elif n_type == "existing":
                    color = UNB_THEME['UNB_GREEN']
                    size = 12
                    lbl = translate("Existente - Aberto", lang)
                elif n_type == "origin":
                    color = '#2ECC71'
                    size = 10
                    lbl = translate("Origem / Produtor", lang)
                elif n_type == "customer_domestic":
                    color = '#D9534F'
                    size = 10
                    lbl = translate("Cliente Doméstico", lang)
                elif n_type == "customer_export":
                    color = '#C0392B'
                    size = 10
                    lbl = translate("Cliente Exportação", lang)
                else:
                    color = UNB_THEME['UNB_YELLOW_DARK']
                    size = 12
                    lbl = translate("Armazém Interhub", lang)

                fig.add_trace(go.Scattermapbox(
                    mode="markers",
                    lon=[n_coords[1]],
                    lat=[n_coords[0]],
                    marker={'size': size, 'color': color},
                    text=f"{name}<br>({lbl})",
                    hoverinfo='text',
                    showlegend=False
                ))

            if all_lats:
                lat_diff = max(all_lats) - min(all_lats)
                lon_diff = max(all_lons) - min(all_lons)
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
                    mapbox_center={"lat": np.mean(all_lats), "lon": np.mean(all_lons)},
                    margin={"r": 0, "t": 0, "l": 0, "b": 0},
                    showlegend=False
                )
            else:
                fig = default_fig

            # Details card for global view
            total_vol = sum(r["Quantidade (ton)"] for r in wh_routes)
            num_routes = len(wh_routes)
            origins_set = set(r["Origem"] for r in wh_routes)
            dests_set = set(r["Destino"] for r in wh_routes)
            num_origins = len(origins_set)
            num_dests = len(dests_set)

            if global_filter == "show_all":
                title_text = translate("Rede Completa de Fluxos", lang)
                subtitle_text = translate("Visão Geral do Escopo Logístico", lang)
                icon_class = "bi bi-globe-americas me-2"
            else:
                title_text = translate("Rotas Diretas", lang)
                subtitle_text = translate("Origem -> Cliente (Bypass)", lang)
                icon_class = "bi bi-arrow-right-circle-fill me-2"

            details_html = dbc.Card([
                dbc.CardHeader(
                    html.Div([
                        html.I(className=icon_class),
                        html.Span(title_text, className="fw-bold")
                    ], className="d-flex align-items-center text-white"),
                    className="bg-primary-custom"
                ),
                dbc.ListGroup([
                    dbc.ListGroupItem([
                        html.Div([
                            html.Strong(subtitle_text),
                        ], className="py-1")
                    ], className="py-2"),
                    dbc.ListGroupItem([
                        html.H6([html.I(className="bi bi-box-seam text-info-custom me-2"), translate("Fluxo Total", lang)], className="mb-2 fw-bold small text-uppercase d-flex align-items-center"),
                        html.Div([
                            html.Span([html.I(className="bi bi-truck me-2 text-muted"), translate("Volume Movimentado:", lang)], className="text-muted small"),
                            html.Span(fmt_n(total_vol), className="float-end fw-bold")
                        ], className="mb-1 d-flex justify-content-between align-items-center"),
                    ], className="py-2"),
                    dbc.ListGroupItem([
                        html.H6([html.I(className="bi bi-signpost-split text-primary-custom me-2"), translate("Estrutura da Rede", lang)], className="mb-2 fw-bold small text-uppercase d-flex align-items-center"),
                        html.Div([
                            html.Span([html.I(className="bi bi-shuffle me-2 text-muted"), translate("Número de Rotas Ativas:", lang)], className="text-muted small"),
                            html.Span(str(num_routes), className="float-end fw-bold")
                        ], className="mb-1 d-flex justify-content-between align-items-center"),
                        html.Div([
                            html.Span([html.I(className="bi bi-geo-alt me-2 text-muted"), translate("Origens Ativas:", lang)], className="text-muted small"),
                            html.Span(str(num_origins), className="float-end")
                        ], className="mb-1 d-flex justify-content-between align-items-center"),
                        html.Div([
                            html.Span([html.I(className="bi bi-people me-2 text-muted"), translate("Destinos Ativos:", lang)], className="text-muted small"),
                            html.Span(str(num_dests), className="float-end")
                        ], className="mb-1 d-flex justify-content-between align-items-center"),
                    ], className="py-2"),
                ], flush=True, className="flex-grow-1"),
            ], className="shadow-sm border-0 h-100 d-flex flex-column")

            # Inventory chart for global view (summed aggregate inventory)
            fig_inv = go.Figure()
            fig_inv.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)'
            )
            chart_style = {"display": "none"}
            try:
                model_type = results_data.get("model_type", "deterministic")
                selected_scenario = scenario_map_select or "esperado"
                if model_type == "stochastic":
                    inv_data = results_data.get("scenario_inventory", {}).get(selected_scenario, [])
                else:
                    inv_data = results_data.get("inventory", [])
                
                if inv_data:
                    df_inv = pd.DataFrame(inv_data)
                    if not df_inv.empty:
                        df_grouped = df_inv.groupby("Período")["Quantidade (ton)"].sum().reset_index()
                        fig_inv.add_trace(go.Bar(
                            x=df_grouped["Período"],
                            y=df_grouped["Quantidade (ton)"],
                            marker=dict(color="#003366"),
                            showlegend=False,
                            hovertemplate=f"<b>{translate('Estoque Total', lang)}</b><br>{translate('Período', lang)}: %{{x}}<br>{translate('Quantidade', lang)}: %{{y:,.2f}} t<extra></extra>"
                        ))
                        fig_inv.update_layout(
                            barmode='stack',
                            height=350,
                            margin=dict(l=40, r=40, t=40, b=40),
                            font=dict(family="Roboto, sans-serif", size=14),
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)'
                        )
                        fig_inv.update_xaxes(tickfont=dict(size=14))
                        fig_inv.update_yaxes(gridcolor='#E5E7EB', zeroline=False, tickfont=dict(size=14))
                        chart_style = {"display": "block"}
            except Exception as chart_err:
                print(f"Error drawing aggregate inventory chart: {chart_err}")

            return fig, details_html, fig_inv, chart_style

        # Default fallback view: no filter and no selected warehouse
        placeholder = html.Div([
            html.P(translate("Selecione um armazém na tabela acima para ver os detalhes, indicadores e custos aqui.", lang), className="text-muted small mt-2")
        ])
        return default_fig, placeholder, go.Figure(), {"display": "none"}

    row_idx = active_cell['row']
    if row_idx >= len(table_data):
        return default_fig, html.P(translate("Erro: Linha selecionada inválida.", lang), className="text-muted small"), go.Figure(), {"display": "none"}
        
    selected_wh_info = table_data[row_idx]
    selected_wh_name = selected_wh_info.get('Name', '')
    selected_wh_cda = selected_wh_info.get('CDA', '')

    selected_wh_dec = None
    for w in wh_decisions:
        if (selected_wh_cda and w.get("CDA") == selected_wh_cda) or (w.get("Name") == selected_wh_name):
            selected_wh_dec = w
            break

    if not selected_wh_dec:
        return default_fig, html.P(translate("Detalhes do armazém não encontrados.", lang), className="text-muted small"), go.Figure(), {"display": "none"}

    coords_key = None
    if selected_wh_name in dest_mapping:
        coords_key = selected_wh_name
    elif selected_wh_cda in dest_mapping:
        coords_key = selected_wh_cda
    elif selected_wh_name.split(" - ")[0].strip() in dest_mapping:
        coords_key = selected_wh_name.split(" - ")[0].strip()

    if not coords_key:
        return default_fig, html.P(translate("Coordenadas do armazém não encontradas.", lang), className="text-muted small"), go.Figure(), {"display": "none"}

    wh_coords = dest_mapping[coords_key]
    wh_lat, wh_lon = wh_coords['Latitude'], wh_coords['Longitude']

    # Gather routes and apply type filter
    wh_routes = []
    for r in routes:
        orig = r.get("Origem", "")
        dest = r.get("Destino", "")
        orig_cda = orig.split(" - ")[0].strip() if orig else ""
        dest_cda = dest.split(" - ")[0].strip() if dest else ""
        
        match_orig = (orig == selected_wh_name) or (selected_wh_cda and orig_cda == selected_wh_cda)
        match_dest = (dest == selected_wh_name) or (selected_wh_cda and dest_cda == selected_wh_cda)
        
        r_type = r.get("Tipo de Rota", "")
        if r_type == "Armazém -> Cliente":
            r_type = "Armazém -> Cliente Doméstico"
        elif r_type == "Origem -> Cliente":
            r_type = "Origem -> Cliente Doméstico"
            
        is_direct_dom = r_type == "Origem -> Cliente Doméstico"
        is_direct_exp = r_type == "Origem -> Cliente Exportação"
        is_direct = is_direct_dom or is_direct_exp
        
        if not is_direct and (match_orig or match_dest):
            if filter_value == "all":
                wh_routes.append(r)
            elif filter_value == "inflow" and r_type == "Origem -> Armazém":
                wh_routes.append(r)
            elif filter_value == "outflow_domestic" and r_type == "Armazém -> Cliente Doméstico":
                wh_routes.append(r)
            elif filter_value == "outflow_export" and r_type == "Armazém -> Cliente Exportação":
                wh_routes.append(r)
            elif filter_value == "interhub" and r_type == "Interhub":
                wh_routes.append(r)

    grouped_flows = {}
    for r in wh_routes:
        k = (r["Origem"], r["Destino"], r["Tipo de Rota"])
        grouped_flows[k] = grouped_flows.get(k, 0.0) + r["Quantidade (ton)"]

    fig = go.Figure()
    all_lats, all_lons = [wh_lat], [wh_lon]

    nodes_to_draw = {
        selected_wh_name: {
            "coords": (wh_lat, wh_lon),
            "type": "selected_wh",
            "name": selected_wh_name
        }
    }

    for (orig, dest, route_type), qty in grouped_flows.items():
        if qty < 1e-4:
            continue
        orig_coords, dest_coords = get_coords_optimized(orig, dest)
        if orig_coords and dest_coords:
            all_lats.extend([orig_coords[0], dest_coords[0]])
            all_lons.extend([orig_coords[1], dest_coords[1]])

            if orig == selected_wh_name:
                if route_type == "Interhub":
                    nodes_to_draw[dest] = {"coords": dest_coords, "type": "transshipment_wh", "name": dest}
                else:
                    n_type = "customer_export" if dest in results_data.get("Customers_exp", []) else "customer_domestic"
                    nodes_to_draw[dest] = {"coords": dest_coords, "type": n_type, "name": dest}
            elif dest == selected_wh_name:
                if route_type == "Interhub":
                    nodes_to_draw[orig] = {"coords": orig_coords, "type": "transshipment_wh", "name": orig}
                else:
                    nodes_to_draw[orig] = {"coords": orig_coords, "type": "origin", "name": orig}
            else:
                nodes_to_draw[orig] = {"coords": orig_coords, "type": "origin", "name": orig}
                n_type = "customer_export" if dest in results_data.get("Customers_exp", []) else "customer_domestic"
                nodes_to_draw[dest] = {"coords": dest_coords, "type": n_type, "name": dest}

            route_type_lookup = route_type
            if route_type_lookup == "Armazém -> Cliente":
                route_type_lookup = "Armazém -> Cliente Doméstico"
            elif route_type_lookup == "Origem -> Cliente":
                route_type_lookup = "Origem -> Cliente Doméstico"
                
            if route_type_lookup == "Origem -> Armazém":
                line_color = UNB_THEME['UNB_GREEN']
                line_name = translate("Origem -> Armazém", lang)
            elif route_type_lookup == "Armazém -> Cliente Doméstico":
                line_color = '#D9534F'
                line_name = translate(route_type_lookup, lang)
            elif route_type_lookup == "Armazém -> Cliente Exportação":
                line_color = '#C0392B'
                line_name = translate(route_type_lookup, lang)
            elif route_type_lookup in ["Origem -> Cliente Doméstico", "Origem -> Cliente Exportação"]:
                line_color = UNB_THEME['UNB_BLUE_GREEN']
                line_name = translate(route_type_lookup, lang)
            else:
                line_color = UNB_THEME['UNB_YELLOW_DARK']
                line_name = translate("Interhub", lang)

            route_data = client.get_route(orig_coords, dest_coords)
            if route_data:
                geom = route_data['geometry']
                lats = [p[1] for p in geom['coordinates']]
                lons = [p[0] for p in geom['coordinates']]
                fig.add_trace(go.Scattermapbox(
                    mode="lines", lon=lons, lat=lats,
                    line={'width': 3, 'color': line_color},
                    opacity=0.8,
                    name=line_name,
                    text=f"{qty:,.2f} {translate('ton', lang)}",
                    hoverinfo='text+name'
                ))

    for name, nd in nodes_to_draw.items():
        n_type = nd["type"]
        n_coords = nd["coords"]
        
        if n_type == "selected_wh":
            color = UNB_THEME['UNB_BLUE']
            size = 15
            lbl = translate("Armazém Selecionado", lang)
        elif n_type == "origin":
            color = UNB_THEME['UNB_GREEN']
            size = 10
            lbl = translate("Origem / Produtor", lang)
        elif n_type == "customer_domestic":
            color = '#D9534F'
            size = 10
            lbl = translate("Cliente Doméstico", lang)
        elif n_type == "customer_export":
            color = '#C0392B'
            size = 10
            lbl = translate("Cliente Exportação", lang)
        else:
            color = UNB_THEME['UNB_YELLOW_DARK']
            size = 12
            lbl = translate("Armazém Interhub", lang)

        fig.add_trace(go.Scattermapbox(
            mode="markers",
            lon=[n_coords[1]],
            lat=[n_coords[0]],
            marker={'size': size, 'color': color},
            text=f"{name}<br>({lbl})",
            hoverinfo='text',
            showlegend=False
        ))

    lat_diff = max(all_lats) - min(all_lats)
    lon_diff = max(all_lons) - min(all_lons)
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
        mapbox_center={"lat": np.mean(all_lats), "lon": np.mean(all_lons)},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        showlegend=False
    )

    # Calculate aggregate inflows/outflows for the selected warehouse
    # Note: we calculate this based on all routes involving this warehouse, regardless of the map filter
    total_inflow = sum(r["Quantidade (ton)"] for r in routes if r["Destino"] == selected_wh_name)
    total_outflow = sum(r["Quantidade (ton)"] for r in routes if r["Origem"] == selected_wh_name)

    opening_cost = selected_wh_dec.get("OpeningCost", 0.0) or 0.0
    expand_cost = selected_wh_dec.get("ExpandCost", 0.0) or 0.0
    bulk_cost = selected_wh_dec.get("BulkCost", 0.0) or 0.0
    storage_cost = selected_wh_dec.get("StorageCost", 0.0) or 0.0
    total_cost = selected_wh_dec.get("TotalCost", opening_cost + expand_cost + bulk_cost + storage_cost) or 0.0

    def fmt_num_only(val, decimal_places=2):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.{decimal_places}e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return s
        fmt = f"{{:,.{decimal_places}f}}"
        s = fmt.format(val)
        if lang != 'en':
            s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return s

    def fmt_n(val, unit='ton'):
        return f"{fmt_num_only(val)} {translate(unit, lang)}"

    def fmt_c(val):
        return f"R$ {fmt_num_only(val)}"

    is_cand = selected_wh_dec.get("IsCandidate", False)
    is_open = selected_wh_dec.get("IsOpen", False)
    is_exp = selected_wh_dec.get("IsExpanded", False)
    is_bulk = selected_wh_dec.get("IsBulkified", False)

    type_lbl = translate("Candidato", lang) if is_cand else translate("Existente", lang)
    status_lbl = translate("Aberto", lang) if is_open else translate("Fechado", lang)
    
    status_badge_color = "success" if is_open else "danger"
    type_badge_color = "primary" if not is_cand else "warning"

    dyn_cap = selected_wh_dec.get("DynamicCapacity", 0.0)
    turnover = selected_wh_dec.get("TurnoverRatio", 0.0)

    details_html = dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.I(className="bi bi-house-door-fill me-2"),
                html.Span(translate("Detalhes do Armazém Selecionado", lang), className="fw-bold")
            ], className="d-flex align-items-center text-white"),
            className="bg-primary-custom"
        ),
        dbc.ListGroup([
            dbc.ListGroupItem([
                html.Div([
                    html.I(className="bi bi-info-circle-fill text-primary-custom me-2"),
                    html.Strong(selected_wh_name),
                    html.Span(type_lbl, className=f"badge bg-{type_badge_color} ms-2"),
                    html.Span(status_lbl, className=f"badge bg-{status_badge_color} ms-1")
                ], className="d-flex align-items-center flex-wrap gap-1")
            ], className="py-2"),
            dbc.ListGroupItem([
                html.H6([html.I(className="bi bi-database-fill text-info-custom me-2"), translate("Capacidades", lang)], className="mb-2 fw-bold small text-uppercase d-flex align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-border-style me-2 text-muted"), translate("Capacidade Estática Efetiva:", lang)], className="text-muted small"),
                    html.Span(fmt_n(selected_wh_dec.get("EffectiveStaticCapacity", 0.0)), className="float-end fw-bold")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-arrows-angle-expand me-2 text-muted"), translate("Expansão:", lang)], className="text-muted small"),
                    html.Span(fmt_n(selected_wh_dec.get("ExpandedVolume", 0.0)) if is_exp else fmt_n(0.0), className="float-end")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-box-seam me-2 text-muted"), translate("Granelização:", lang)], className="text-muted small"),
                    html.Span(fmt_n(selected_wh_dec.get('BulkCapacityAdded', 0.0), 'ton/dia') if is_bulk else fmt_n(0.0, 'ton/dia'), className="float-end")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
            ], className="py-2"),
            dbc.ListGroupItem([
                html.H6([html.I(className="bi bi-arrow-down-up text-primary-custom me-2"), translate("Movimentação de Cargas", lang)], className="mb-2 fw-bold small text-uppercase d-flex align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-box-arrow-in-right me-2 text-success-custom"), translate("Entrada Total (Inflow):", lang)], className="text-muted small"),
                    html.Span(fmt_n(total_inflow), className="float-end fw-bold text-success-custom")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-box-arrow-up-right me-2 text-primary-custom"), translate("Saída Total (Outflow):", lang)], className="text-muted small"),
                    html.Span(fmt_n(total_outflow), className="float-end fw-bold text-primary-custom")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-archive me-2 text-secondary-custom"), translate("Estoque Final:", lang)], className="text-muted small"),
                    html.Span(fmt_n(selected_wh_dec.get("FinalStock", 0.0)), className="float-end text-secondary-custom")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
            ], className="py-2"),
            dbc.ListGroupItem([
                html.H6([html.I(className="bi bi-arrow-repeat text-info-custom me-2"), translate("Giro e Capacidade Dinâmica", lang)], className="mb-2 fw-bold small text-uppercase d-flex align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-activity me-2 text-muted"), translate("Capacidade Dinâmica Anual:", lang)], className="text-muted small"),
                    html.Span(fmt_n(dyn_cap, 'ton/ano'), className="float-end")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
                html.Div([
                    html.Span([html.I(className="bi bi-arrow-clockwise me-2 text-info-custom"), translate("Giro Anual:", lang)], className="text-muted small"),
                    html.Span(fmt_num_only(turnover, 4), className="float-end fw-bold text-info-custom")
                ], className="mb-1 d-flex justify-content-between align-items-center"),
            ], className="py-2"),
        ], flush=True, className="flex-grow-1"),
        dbc.CardFooter([
            html.H6([html.I(className="bi bi-cash-stack text-danger-custom me-2"), translate("Detalhamento de Custos", lang)], className="text-dark mb-2 fw-bold small text-uppercase d-flex align-items-center"),
            html.Div([
                html.Span([html.I(className="bi bi-door-open me-2 text-muted"), translate("Custo de Abertura:", lang)], className="text-muted small"),
                html.Span(fmt_c(opening_cost), className="float-end text-info-custom")
            ], className="mb-1 d-flex justify-content-between align-items-center"),
            html.Div([
                html.Span([html.I(className="bi bi-arrows-angle-expand me-2 text-muted"), translate("Custo de Expansão:", lang)], className="text-muted small"),
                html.Span(fmt_c(expand_cost), className="float-end text-secondary-custom")
            ], className="mb-1 d-flex justify-content-between align-items-center"),
            html.Div([
                html.Span([html.I(className="bi bi-box-seam me-2 text-muted"), translate("Custo de Granelização:", lang)], className="text-muted small"),
                html.Span(fmt_c(bulk_cost), className="float-end text-primary-custom")
            ], className="mb-1 d-flex justify-content-between align-items-center"),
            html.Div([
                html.Span([html.I(className="bi bi-archive me-2 text-muted"), translate("Custo de Armazenagem:", lang)], className="text-muted small"),
                html.Span(fmt_c(storage_cost), className="float-end text-warning-custom")
            ], className="mb-2"),
            html.Div([
                html.Span(translate("Custo Total do Armazém:", lang), className="fw-bold"),
                html.H6(fmt_c(total_cost), className="float-end fw-bold mb-0 text-danger-custom")
            ], className="mt-2 border-top pt-2")
        ], className="bg-light")
    ], className="shadow-sm border-0 h-100 d-flex flex-column")

    # Generate selected warehouse inventory chart
    fig_inv = go.Figure()
    fig_inv.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    chart_style = {"display": "none"}
    
    try:
        model_type = results_data.get("model_type", "deterministic")
        selected_scenario = scenario_map_select or "esperado"
        
        if model_type == "stochastic":
            inv_data = results_data.get("scenario_inventory", {}).get(selected_scenario, [])
        else:
            inv_data = results_data.get("inventory", [])
        
        bar_color = "#003366"
            
        wh_inv = [
            r for r in inv_data
            if (selected_wh_cda and r.get("CDA") == selected_wh_cda) or (r.get("Name") == selected_wh_name)
        ]
        
        if wh_inv:
            df_inv = pd.DataFrame(wh_inv)
            if not df_inv.empty:
                df_grouped = df_inv.groupby("Período")["Quantidade (ton)"].sum().reset_index()
                
                fig_inv.add_trace(go.Bar(
                    x=df_grouped["Período"],
                    y=df_grouped["Quantidade (ton)"],
                    marker=dict(color=bar_color),
                    showlegend=False,
                    hovertemplate=f"<b>{selected_wh_name}</b><br>{translate('Período', lang)}: %{{x}}<br>{translate('Quantidade', lang)}: %{{y:,.2f}} t<extra></extra>"
                ))
                
                fig_inv.update_layout(
                    barmode='stack',
                    height=350,
                    margin=dict(l=40, r=40, t=40, b=40),
                    font=dict(family="Roboto, sans-serif", size=14),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)'
                )
                fig_inv.update_xaxes(tickfont=dict(size=14))
                fig_inv.update_yaxes(gridcolor='#E5E7EB', zeroline=False, tickfont=dict(size=14))
                chart_style = {"display": "block"}
    except Exception as chart_err:
        print(f"Error drawing selected warehouse inventory chart: {chart_err}")

    return fig, details_html, fig_inv, chart_style

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


@app.callback(
    Output("model-running-log-text", "children"),
    Input("interval-model-log", "n_intervals"),
    State("store-active-log-filename", "data"),
    State("store-lang", "data"),
    prevent_initial_call=True
)
def update_running_log(n_intervals, log_filename, lang):
    if not log_filename:
        return ""
    
    import tempfile
    log_dir = os.path.join(tempfile.gettempdir(), 'silodss_logs')
    log_path = os.path.join(log_dir, log_filename)
    
    if not os.path.exists(log_path):
        return translate("Iniciando solver...", lang)
        
    try:
        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        tail_lines = lines[-40:]
        return "".join(tail_lines)
    except Exception as e:
        return f"Error reading log: {str(e)}"


app.clientside_callback(
    """
    function(children) {
        var el = document.getElementById("model-running-log-text");
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("model-running-log-text", "id"),
    Input("model-running-log-text", "children"),
    prevent_initial_call=True
)


@app.callback(
    Output("error-modal", "is_open", allow_duplicate=True),
    Output("modal-body-content", "children", allow_duplicate=True),
    Input("model-output-text", "children"),
    [State("radio-model-type", "value"),
     State("store-lang", "data")],
    prevent_initial_call=True
)
def trigger_error_popup_on_model_error(output_text, model_type, lang):
    if not output_text:
        return dash.no_update, dash.no_update
    
    text_str = str(output_text)
    
    is_error = (
        "Erro" in text_str or 
        "Error" in text_str or 
        "Falha ao encontrar" in text_str or 
        "Failed to find" in text_str or 
        "infeasible" in text_str.lower()
    )
    
    if is_error:
        body_elements = []
        
        if "Falha ao encontrar" in text_str or "Failed to find" in text_str:
            title_msg = translate("Aviso: Solução Não Encontrada", lang)
            desc_msg = translate(
                "O solver não conseguiu encontrar uma solução ótima. "
                "Isso geralmente ocorre se o modelo for inviável (infeasible), ou seja, as restrições impostas não podem ser satisfeitas simultaneamente (ex: demanda maior que a capacidade total de expedição/recepção, falta de conexões permitidas entre produtos e armazéns, etc).", 
                lang
            )
            body_elements.append(html.H5(title_msg, className="text-warning mb-2"))
            body_elements.append(html.P(desc_msg))
            body_elements.append(html.Hr())
            body_elements.append(html.P(f"{translate('Detalhes:', lang)} {text_str}"))
        else:
            title_msg = translate("Erro na Execução do Modelo", lang)
            body_elements.append(html.H5(title_msg, className="text-danger mb-2"))
            body_elements.append(html.P(text_str, style={"whiteSpace": "pre-wrap", "wordBreak": "break-word"}))
            
        return True, html.Div(body_elements)
        
    return dash.no_update, dash.no_update


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
    [Output('modal-missing-prediction-data', 'is_open'),
     Output('modal-missing-prediction-data-body', 'children')],
    Input('main-tabs', 'active_tab'),
    [State('stored-data', 'data'),
     State('stored-demand-data', 'data'),
     State('store-lang', 'data')]
)
def validate_prediction_tab_access(active_tab, stored_supply_data, stored_demand_data, lang='pt'):
    if active_tab != 'tab-prediction':
        return False, dash.no_update

    # Check supply
    has_supply = False
    if stored_supply_data:
        try:
            df_sup = pd.read_json(io.StringIO(stored_supply_data), orient='split')
            if not df_sup.empty:
                has_supply = True
        except:
            pass

    # Check demand
    has_demand = False
    if stored_demand_data:
        try:
            df_dem = pd.read_json(io.StringIO(stored_demand_data), orient='split')
            if not df_dem.empty:
                has_demand = True
        except:
            pass

    if not has_supply and not has_demand:
        msg = translate("Você precisa preencher as abas 'Oferta' e 'Demanda' antes de acessar a aba 'Previsão'.", lang)
        return True, msg
    elif not has_supply:
        msg = translate("Você precisa preencher a aba 'Oferta' antes de acessar a aba 'Previsão'.", lang)
        return True, msg
    elif not has_demand:
        msg = translate("Você precisa preencher a aba 'Demanda' antes de acessar a aba 'Previsão'.", lang)
        return True, msg

    return False, dash.no_update


@app.callback(
    Output('main-tabs', 'active_tab', allow_duplicate=True),
    Input('btn-confirm-missing-prediction', 'n_clicks'),
    [State('stored-data', 'data'),
     State('stored-demand-data', 'data')],
    prevent_initial_call=True
)
def redirect_from_prediction_tab(n_clicks, stored_supply_data, stored_demand_data):
    if not n_clicks:
        return dash.no_update

    has_supply = False
    if stored_supply_data:
        try:
            df_sup = pd.read_json(io.StringIO(stored_supply_data), orient='split')
            if not df_sup.empty:
                has_supply = True
        except:
            pass

    if not has_supply:
        return 'tab-input'
    
    return 'tab-demand'


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


@app.callback(
  [Output('store-historical-max-dates', 'data', allow_duplicate=True),
   Output('store-prediction-results', 'data', allow_duplicate=True),
   Output('store-forecast-residuals', 'data', allow_duplicate=True)],
  [Input('upload-data', 'contents'),
   Input('btn-add-row', 'n_clicks'),
   Input('editable-table', 'data_timestamp'),
   Input('btn-confirm-clear', 'n_clicks'),
   Input('upload-demand-data', 'contents'),
   Input('btn-demand-add-row', 'n_clicks'),
   Input('demand-editable-table', 'data_timestamp'),
   Input('btn-confirm-clear-demand', 'n_clicks')],
  prevent_initial_call=True
)
def clear_prediction_cache(*args):
  return {}, None, {}


# --- Prediction Tab Callbacks ---

@app.callback(
  [Output("prediction-series-type", "options"),
   Output("prediction-series-type", "disabled"),
   Output("prediction-series-type", "value"),
   Output("prediction-product-dropdown", "options"),
   Output("prediction-product-dropdown", "disabled"),
   Output("prediction-product-dropdown", "value"),
   Output("prediction-city-dropdown", "options"),
   Output("prediction-city-dropdown", "disabled"),
   Output("prediction-city-dropdown", "value")],
  [Input("store-prediction-results", "data"),
   Input("prediction-series-type", "value"),
   Input("prediction-product-dropdown", "value")],
  [State("prediction-city-dropdown", "value"),
   State("store-lang", "data")]
)
def sync_prediction_dropdowns(prediction_results, selected_series, selected_product, current_city, lang='pt'):
  series_options = [
    {"label": translate("Oferta", lang), "value": "supply"},
    {"label": translate("Demanda", lang), "value": "demand"}
  ]
  if not prediction_results:
    return series_options, True, None, [], True, None, [], True, None

  try:
    results = json.loads(prediction_results)
    if not results:
      return series_options, True, None, [], True, None, [], True, None

    combos = []
    for k, v in results.items():
      s_type = v.get("series_type")
      prod = v.get("product")
      city = v.get("city")
      if not s_type or not prod or not city:
        parts = k.split("_", 2)
        if len(parts) == 3:
          s_type, prod, city = parts
        else:
          continue
      combos.append({"series_type": s_type, "product": prod, "city": city})

    if not combos:
      return series_options, True, None, [], True, None, [], True, None

    # 1. Determine Series Type
    available_series = sorted(list(set([c["series_type"] for c in combos])))
    if selected_series not in available_series:
      if "supply" in available_series:
        selected_series = "supply"
      else:
        selected_series = available_series[0] if available_series else None

    # 2. Determine Product Dropdown options and value
    products_for_series = sorted(list(set([c["product"] for c in combos if c["series_type"] == selected_series])))
    product_options = [{"label": p, "value": p} for p in products_for_series]
    
    if selected_product not in products_for_series:
      selected_product = products_for_series[0] if products_for_series else None

    # 3. Determine City Dropdown options and value
    cities_for_prod = sorted(list(set([c["city"] for c in combos if c["series_type"] == selected_series and c["product"] == selected_product])))
    city_options = [{"label": c, "value": c} for c in cities_for_prod]

    if current_city not in cities_for_prod:
      current_city = cities_for_prod[0] if cities_for_prod else None

    return (
      series_options, False, selected_series,
      product_options, False, selected_product,
      city_options, False, current_city
    )

  except Exception as e:
    print(f"Error in sync_prediction_dropdowns: {e}")
    return series_options, True, None, [], True, None, [], True, None




@app.callback(
    [Output('store-prediction-results', 'data'),
     Output('store-forecast-residuals', 'data'),
     Output('store-historical-max-dates', 'data', allow_duplicate=True),
     Output('stored-data', 'data', allow_duplicate=True),
     Output('stored-demand-data', 'data', allow_duplicate=True),
     Output('prediction-output-text', 'children'),
     Output('prediction-output-text', 'className')],
    [Input('btn-run-forecast', 'n_clicks')],
    [State('prediction-model-select', 'value'),
     State('prediction-test-size', 'value'),
     State('prediction-horizon', 'value'),
     State('stored-data', 'data'),
     State('stored-demand-data', 'data'),
     State('store-forecast-residuals', 'data'),
     State('store-historical-max-dates', 'data'),
     State('store-lang', 'data')],
    background=True,
    running=[
        (Output("btn-run-forecast", "disabled"), True, False),
        (Output("btn-cancel-forecast", "disabled"), False, True),
    ],
    cancel=[Input("btn-cancel-forecast", "n_clicks")],
    prevent_initial_call=True
)
def execute_prediction(n_clicks, model_name, test_size, horizon,
                       stored_supply, stored_demand, current_residuals, historical_max_dates, lang='pt'):
    if not n_clicks:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update

    try:
        if not stored_supply and not stored_demand:
            return no_update, no_update, no_update, no_update, no_update, translate("Nenhum dado encontrado para Oferta ou Demanda.", lang), "text-danger mt-3"

        results_dict = {}
        updated_residuals = current_residuals or {}
        historical_max_dates = historical_max_dates or {}

        test_size = int(test_size) if test_size is not None else 12
        horizon = int(horizon) if horizon is not None else 12

        success_count = 0
        fail_count = 0

        stored_supply_out = no_update
        stored_demand_out = no_update

        # Loop through both Supply and Demand datasets
        for s_type, active_store in [('supply', stored_supply), ('demand', stored_demand)]:
            if not active_store:
                continue

            df = pd.read_json(io.StringIO(active_store), orient='split')
            if df.empty:
                continue

            df = df.copy()
            df["Data"] = pd.to_datetime(df["Data"], errors="coerce")
            df = df.dropna(subset=["Data"])
            if df.empty:
                continue

            # Find all unique combinations in the active dataframe
            unique_combos = df[["Produto", "Cidade"]].drop_duplicates().values.tolist()
            cleaned_rows = []

            for prod, city in unique_combos:
                combo_key = f"{s_type}_{prod}_{city}"
                df_combo = df[(df["Produto"] == prod) & (df["Cidade"] == city)]

                if combo_key in historical_max_dates:
                    max_hist_date = pd.to_datetime(historical_max_dates[combo_key])
                    df_combo_hist = df_combo[df_combo["Data"] <= max_hist_date]
                else:
                    if df_combo.empty:
                        continue
                    max_hist_date = df_combo["Data"].max()
                    historical_max_dates[combo_key] = max_hist_date.strftime('%Y-%m')
                    df_combo_hist = df_combo

                cleaned_rows.append(df_combo_hist)

            if not cleaned_rows:
                continue

            df_historical = pd.concat(cleaned_rows, ignore_index=True)
            forecasted_rows = []

            for prod, city in unique_combos:
                combo_key = f"{s_type}_{prod}_{city}"
                df_combo = df_historical[(df_historical["Produto"] == prod) & (df_historical["Cidade"] == city)]

                # Check for infinite demand
                is_infinite_demand = (s_type == 'demand') and (df_combo["Peso (ton)"].isna().all())

                if is_infinite_demand:
                    test_len = test_size if test_size > 0 else 0
                    test_preds = [None] * test_len
                    future_preds = [None] * horizon
                    summary = translate("Demanda Infinita (Porto) - Assumida infinita para sempre.", lang)
                    
                    mae, rmse, mape, wmape = 0.0, 0.0, 0.0, 0.0
                    residuals = [0.0] * test_len
                    
                    res_list = []
                    sorted_dates = sorted(df_combo["Data"].dt.strftime('%Y-%m').tolist())
                    if test_len > 0:
                        train_dates = sorted_dates[:-test_len]
                        test_dates = sorted_dates[-test_len:]
                    else:
                        train_dates = sorted_dates
                        test_dates = []
                        
                    for d in test_dates:
                        res_list.append({
                            "date": d,
                            "actual": None,
                            "predicted": None,
                            "residual": 0.0
                        })
                    updated_residuals[combo_key] = res_list

                    history_dates = train_dates
                    history_values = [None] * len(history_dates)
                    test_values = [None] * len(test_dates)

                    last_date_str = sorted_dates[-1]
                    last_date = pd.to_datetime(last_date_str)
                    future_dates = [str((last_date + pd.DateOffset(months=i)).strftime('%Y-%m')) for i in range(1, horizon + 1)]

                    results_dict[combo_key] = {
                        "status": "success",
                        "is_infinite_demand": True,
                        "series_type": s_type,
                        "product": prod,
                        "city": city,
                        "model": model_name,
                        "test_size": test_size,
                        "horizon": horizon,
                        "history_dates": history_dates,
                        "history_values": history_values,
                        "test_dates": test_dates,
                        "test_values": test_values,
                        "test_preds": test_preds,
                        "future_dates": future_dates,
                        "future_preds": future_preds,
                        "mae": mae,
                        "rmse": rmse,
                        "mape": mape,
                        "wmape": wmape,
                        "params": summary,
                        "residuals": residuals,
                        "residuals_dates": test_dates
                    }

                    lat = df_combo.iloc[0]["Latitude"] if "Latitude" in df_combo.columns and not pd.isna(df_combo.iloc[0]["Latitude"]) else 0.0
                    lon = df_combo.iloc[0]["Longitude"] if "Longitude" in df_combo.columns and not pd.isna(df_combo.iloc[0]["Longitude"]) else 0.0
                    for d in future_dates:
                        forecasted_rows.append({
                            "Produto": prod,
                            "Cidade": city,
                            "Latitude": lat,
                            "Longitude": lon,
                            "Data": d,
                            "Peso (ton)": None
                        })

                    success_count += 1
                    continue

                # Prepare series
                series = prepare_time_series(df_combo, prod, city)
                if series.empty or len(series) < 6 or len(series) <= test_size:
                    results_dict[combo_key] = {"status": "error", "message": "insufficient_data"}
                    fail_count += 1
                    continue

                # Run model
                n_samples = len(series)
                if test_size > 0:
                    train_series = series.iloc[:-test_size]
                    test_series = series.iloc[-test_size:]
                else:
                    train_series = series
                    test_series = pd.Series(dtype=float)

                test_len = len(test_series)

                try:
                    if model_name == 'sarima':
                        test_preds, future_preds, summary = forecast_sarima(series, test_len, horizon)
                    elif model_name == 'prophet':
                        test_preds, future_preds, summary = forecast_prophet(series, test_len, horizon)
                    elif model_name == 'xgboost':
                        test_preds, future_preds, summary = forecast_xgboost(series, test_len, horizon)
                    elif model_name == 'lstm':
                        test_preds, future_preds, summary = forecast_lstm(series, test_len, horizon)
                    else:
                        raise ValueError(f"Unknown model: {model_name}")

                    # Compute metrics
                    mae, rmse, mape, wmape = 0.0, 0.0, 0.0, 0.0
                    residuals = []
                    if test_len > 0:
                        mae, rmse, mape, wmape = calculate_metrics(test_series.values, test_preds)
                        residuals = list(test_series.values - test_preds)

                    # Save residuals for optimization
                    res_list = []
                    test_dates_str = test_series.index.strftime('%Y-%m').tolist() if test_len > 0 else []
                    for d, act, prd, res in zip(test_dates_str, test_series.values, test_preds, residuals):
                        res_list.append({
                            "date": d,
                            "actual": float(act),
                            "predicted": float(prd),
                            "residual": float(res)
                        })
                    updated_residuals[combo_key] = res_list

                    # Save predictions
                    history_dates = train_series.index.strftime('%Y-%m').tolist()
                    history_values = list(train_series.values)
                    test_dates = test_series.index.strftime('%Y-%m').tolist() if test_len > 0 else []
                    test_values = list(test_series.values) if test_len > 0 else []

                    last_date = series.index[-1]
                    future_dates = [str((last_date + pd.DateOffset(months=i)).strftime('%Y-%m')) for i in range(1, horizon + 1)]

                    # Store in results_dict
                    results_dict[combo_key] = {
                        "status": "success",
                        "series_type": s_type,
                        "product": prod,
                        "city": city,
                        "model": model_name,
                        "test_size": test_size,
                        "horizon": horizon,
                        "history_dates": history_dates,
                        "history_values": history_values,
                        "test_dates": test_dates,
                        "test_values": test_values,
                        "test_preds": test_preds,
                        "future_dates": future_dates,
                        "future_preds": [float(v) for v in future_preds],
                        "mae": mae,
                        "rmse": rmse,
                        "mape": mape,
                        "wmape": wmape,
                        "params": summary,
                        "residuals": residuals,
                        "residuals_dates": test_dates
                    }

                    # Prepare rows to append to the database
                    lat = df_combo.iloc[0]["Latitude"] if "Latitude" in df_combo.columns and not pd.isna(df_combo.iloc[0]["Latitude"]) else 0.0
                    lon = df_combo.iloc[0]["Longitude"] if "Longitude" in df_combo.columns and not pd.isna(df_combo.iloc[0]["Longitude"]) else 0.0
                    for d, val in zip(future_dates, future_preds):
                        forecasted_rows.append({
                            "Produto": prod,
                            "Cidade": city,
                            "Latitude": lat,
                            "Longitude": lon,
                            "Data": d,
                            "Peso (ton)": float(val)
                        })

                    success_count += 1

                except Exception as e:
                    print(f"Error forecasting {combo_key}: {e}")
                    results_dict[combo_key] = {"status": "error", "message": str(e)}
                    fail_count += 1

            # We no longer modify the original stores.
            # Merging will happen on the fly when executing the optimization model.
            pass

        status_msg = translate("Previsão concluída com sucesso!", lang)
        status_msg += f" (Success: {success_count}, Failed/Insufficient Data: {fail_count})"

        return (
            json.dumps(results_dict),
            updated_residuals,
            historical_max_dates,
            stored_supply_out,
            stored_demand_out,
            status_msg,
            "text-success mt-3 fw-bold"
        )

    except Exception as e:
        import traceback
        print(f"Error in execute_prediction: {e}")
        traceback.print_exc()
        return no_update, no_update, no_update, no_update, no_update, f"{translate('Erro ao executar a previsão:', lang)} {str(e)}", "text-danger mt-3"



@app.callback(
  [Output("prediction-kpi-mape", "children"),
   Output("prediction-kpi-rmse", "children"),
   Output("prediction-kpi-mae", "children"),
   Output("prediction-kpi-quality-container", "children"),
   Output("prediction-kpi-badge-icon", "style"),
   Output("prediction-graph-forecast", "figure"),
   Output("prediction-graph-residuals-time", "figure"),
   Output("prediction-graph-residuals-hist", "figure"),
   Output("prediction-model-parameters", "children"),
   Output("btn-download-forecast", "disabled")],
  [Input("store-prediction-results", "data"),
   Input("prediction-series-type", "value"),
   Input("prediction-product-dropdown", "value"),
   Input("prediction-city-dropdown", "value"),
   Input("store-lang", "data")]
)
def render_prediction_results(prediction_results, series_type, product, city, lang='pt'):
  if not prediction_results or not series_type or not product or not city:
    empty_fig = go.Figure()
    empty_fig.update_layout(
      xaxis={"visible": False},
      yaxis={"visible": False},
      annotations=[{
        "text": translate("Execute a previsão para visualizar o gráfico", lang),
        "xref": "paper",
        "yref": "paper",
        "showarrow": False,
        "font": {"size": 16}
      }]
    )
    return "-", "-", "-", "-", {"color": UNB_THEME['UNB_GRAY_DARK']}, empty_fig, empty_fig, empty_fig, "", True

  try:
    results = json.loads(prediction_results)
    key = f"{series_type}_{product}_{city}"
    combo_res = results.get(key)
    
    if not combo_res or combo_res.get("status") != "success":
      empty_fig = go.Figure()
      empty_fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
          "text": translate("Não há dados suficientes para realizar o treinamento e teste.", lang) if combo_res and combo_res.get("message") == "insufficient_data" else translate("Sem previsão", lang),
          "xref": "paper",
          "yref": "paper",
          "showarrow": False,
          "font": {"size": 16}
        }]
      )
      return "-", "-", "-", "-", {"color": UNB_THEME['UNB_GRAY_DARK']}, empty_fig, empty_fig, empty_fig, "", True

    is_infinite = combo_res.get("is_infinite_demand", False)
    if is_infinite:
      fig = go.Figure()
      plot_height = 100.0
      
      history_dates = combo_res.get("history_dates", [])
      future_dates = combo_res.get("future_dates", [])
      
      fig.add_trace(go.Scatter(
        x=history_dates, y=[plot_height] * len(history_dates),
        name=translate("Histórico (Treino)", lang),
        mode='lines+markers',
        line=dict(color=UNB_THEME['UNB_BLUE'], width=3),
        marker=dict(size=10, color=UNB_THEME['UNB_YELLOW_DARK'], symbol='star'),
        hovertemplate="∞<extra></extra>"
      ))
      
      fig.add_trace(go.Scatter(
        x=future_dates, y=[plot_height] * len(future_dates),
        name=translate("Previsão Futura", lang),
        mode='lines+markers',
        line=dict(color=UNB_THEME['UNB_GREEN'], width=3),
        marker=dict(size=10, color=UNB_THEME['UNB_YELLOW_DARK'], symbol='star'),
        hovertemplate="∞<extra></extra>"
      ))
      
      fig.add_hline(
        y=plot_height,
        line_dash="dash",
        line_color=UNB_THEME['UNB_YELLOW_DARK'],
        annotation_text=translate("Demanda Infinita (∞)", lang),
        annotation_position="bottom right"
      )
      
      fig.update_layout(
        title=translate("Série Histórica e Previsão Futura", lang),
        xaxis_title=translate("Data", lang),
        yaxis_title=translate("Peso (ton)", lang),
        hovermode="x unified",
        template="plotly_white",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=80, b=40)
      )
      
      fig_res_time = go.Figure()
      fig_res_time.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
          "text": translate("Resíduos não aplicáveis para demanda infinita", lang),
          "xref": "paper",
          "yref": "paper",
          "showarrow": False,
          "font": {"size": 14}
        }]
      )
      
      fig_res_hist = go.Figure()
      fig_res_hist.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
          "text": translate("Resíduos não aplicáveis para demanda infinita", lang),
          "xref": "paper",
          "yref": "paper",
          "showarrow": False,
          "font": {"size": 14}
        }]
      )
      
      params = combo_res.get("params", "")
      quality_badge = html.Span(translate("Demanda Infinita", lang), style={"color": UNB_THEME['UNB_YELLOW_DARK']})
      return "-", "-", "-", quality_badge, {"color": UNB_THEME['UNB_YELLOW_DARK']}, fig, fig_res_time, fig_res_hist, params, False

    wmape = combo_res.get("wmape", combo_res.get("mape", 0.0))
    rmse = combo_res.get("rmse", 0.0)
    mae = combo_res.get("mae", 0.0)
    
    mape_str = f"{wmape:.2f}%" if wmape > 0 else "-"
    rmse_str = f"{rmse:.2f}" if rmse > 0 else "-"
    mae_str = f"{mae:.2f}" if mae > 0 else "-"
    
    quality_text, badge_color = get_quality_badge(wmape, lang)
    color_map = {
      "success": UNB_THEME['UNB_GREEN'],
      "warning": UNB_THEME['UNB_YELLOW_DARK'],
      "danger": UNB_THEME['DANGER']
    }
    badge_style = {"color": color_map.get(badge_color, UNB_THEME['UNB_GRAY_DARK'])}
    quality_badge = html.Span(quality_text, style={"color": color_map.get(badge_color, UNB_THEME['UNB_GRAY_DARK'])})

    fig = go.Figure()
    
    history_dates = combo_res.get("history_dates", [])
    history_values = combo_res.get("history_values", [])
    test_dates = combo_res.get("test_dates", [])
    test_values = combo_res.get("test_values", [])
    test_preds = combo_res.get("test_preds", [])
    future_dates = combo_res.get("future_dates", [])
    future_preds = combo_res.get("future_preds", [])
    
    fig.add_trace(go.Scatter(
      x=history_dates, y=history_values,
      name=translate("Histórico (Treino)", lang),
      line=dict(color=UNB_THEME['UNB_BLUE'], width=2)
    ))
    
    if test_dates:
      fig.add_trace(go.Scatter(
        x=test_dates, y=test_values,
        name=translate("Teste (Real)", lang),
        mode='lines+markers',
        line=dict(color=UNB_THEME['UNB_GRAY_DARK'], width=1.5, dash='dash')
      ))
      fig.add_trace(go.Scatter(
        x=test_dates, y=test_preds,
        name=translate("Teste (Previsão)", lang),
        mode='lines+markers',
        line=dict(color=UNB_THEME['UNB_YELLOW_DARK'], width=1.5)
      ))
      
    fig.add_trace(go.Scatter(
      x=future_dates, y=future_preds,
      name=translate("Previsão Futura", lang),
      line=dict(color=UNB_THEME['UNB_GREEN'], width=2.5)
    ))
    
    fig.update_layout(
      title=translate("Série Histórica e Previsão Futura", lang),
      xaxis_title=translate("Data", lang),
      yaxis_title=translate("Peso (ton)", lang),
      hovermode="x unified",
      template="plotly_white",
      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
      margin=dict(l=40, r=40, t=80, b=40)
    )

    fig_res_time = go.Figure()
    residuals = combo_res.get("residuals", [])
    residuals_dates = combo_res.get("residuals_dates", [])
    
    if residuals:
      fig_res_time.add_trace(go.Scatter(
        x=residuals_dates, y=residuals,
        name=translate("Resíduos", lang),
        line=dict(color=UNB_THEME['DANGER'], width=2)
      ))
      fig_res_time.add_trace(go.Scatter(
        x=residuals_dates, y=[0]*len(residuals),
        showlegend=False,
        line=dict(color='gray', dash='dash')
      ))
      
    fig_res_time.update_layout(
      title=translate("Resíduos do Teste ao Longo do Tempo", lang),
      xaxis_title=translate("Data", lang),
      yaxis_title=translate("Resíduo (Real - Previsto)", lang),
      template="plotly_white",
      margin=dict(l=40, r=40, t=50, b=40)
    )

    fig_res_hist = go.Figure()
    if residuals:
      fig_res_hist.add_trace(go.Histogram(
        x=residuals,
        name=translate("Resíduos", lang),
        marker_color=UNB_THEME['UNB_BLUE_MED']
      ))
      
    fig_res_hist.update_layout(
      title=translate("Distribuição de Frequência dos Resíduos", lang),
      xaxis_title=translate("Valor do Resíduo", lang),
      yaxis_title=translate("Frequência", lang),
      template="plotly_white",
      margin=dict(l=40, r=40, t=50, b=40)
    )

    params = combo_res.get("params", "")

    return mape_str, rmse_str, mae_str, quality_badge, badge_style, fig, fig_res_time, fig_res_hist, params, False

  except Exception as e:
    print(f"Error rendering prediction results: {e}")
    empty_fig = go.Figure()
    return "-", "-", "-", "-", {"color": UNB_THEME['UNB_GRAY_DARK']}, empty_fig, empty_fig, empty_fig, "", True


@app.callback(
  Output("download-prediction-xlsx", "data"),
  [Input("btn-download-forecast", "n_clicks")],
  [State("store-prediction-results", "data"),
   State("store-lang", "data")],
  prevent_initial_call=True
)
def download_prediction_report(n_clicks, prediction_results, lang='pt'):
  if not n_clicks or not prediction_results:
    return no_update

  try:
    results = json.loads(prediction_results)
    if not results:
      return no_update

    forecast_rows = []
    metrics_rows = []
    residuals_rows = []

    for key, combo_res in results.items():
      if not combo_res or combo_res.get("status") != "success":
        continue

      s_type = combo_res.get("series_type")
      s_label = translate("Oferta", lang) if s_type == "supply" else translate("Demanda", lang)
      prod = combo_res.get("product")
      city = combo_res.get("city")

      history_dates = combo_res.get("history_dates", [])
      history_values = combo_res.get("history_values", [])
      test_dates = combo_res.get("test_dates", [])
      test_values = combo_res.get("test_values", [])
      test_preds = combo_res.get("test_preds", [])
      future_dates = combo_res.get("future_dates", [])
      future_preds = combo_res.get("future_preds", [])

      for d, val in zip(history_dates, history_values):
        forecast_rows.append({
          "Série": s_label,
          "Produto": prod,
          "Cidade": city,
          "Data": d,
          "Tipo": translate("Histórico (Treino)", lang),
          "Real": val,
          "Previsão": None
        })
      for d, val, pred in zip(test_dates, test_values, test_preds):
        forecast_rows.append({
          "Série": s_label,
          "Produto": prod,
          "Cidade": city,
          "Data": d,
          "Tipo": translate("Teste (Avaliação)", lang),
          "Real": val,
          "Previsão": pred
        })
      for d, pred in zip(future_dates, future_preds):
        forecast_rows.append({
          "Série": s_label,
          "Produto": prod,
          "Cidade": city,
          "Data": d,
          "Tipo": translate("Previsão Futura", lang),
          "Real": None,
          "Previsão": pred
        })

      if combo_res.get("is_infinite_demand"):
        mae = "N/A"
        rmse = "N/A"
        mape = "N/A"
        wmape = "N/A"
      else:
        mae = combo_res.get("mae", 0.0)
        rmse = combo_res.get("rmse", 0.0)
        mape = combo_res.get("mape", 0.0)
        wmape = combo_res.get("wmape", mape)
        
      metrics_rows.append({
        "Série": s_label,
        "Produto": prod,
        "Cidade": city,
        "MAE": mae,
        "RMSE": rmse,
        "MAPE (%)": mape,
        "WMAPE (%)": wmape
      })

      residuals = combo_res.get("residuals", [])
      residuals_dates = combo_res.get("residuals_dates", [])
      for d, res in zip(residuals_dates, residuals):
        residuals_rows.append({
          "Série": s_label,
          "Produto": prod,
          "Cidade": city,
          "Data": d,
          "Resíduo": res
        })

    if not forecast_rows:
      return no_update

    df_forecast = pd.DataFrame(forecast_rows)
    df_metrics = pd.DataFrame(metrics_rows)
    df_residuals = pd.DataFrame(residuals_rows)

    df_forecast = df_forecast[["Série", "Produto", "Cidade", "Data", "Tipo", "Real", "Previsão"]]
    df_metrics = df_metrics[["Série", "Produto", "Cidade", "MAE", "RMSE", "MAPE (%)", "WMAPE (%)"]]
    df_residuals = df_residuals[["Série", "Produto", "Cidade", "Data", "Resíduo"]]

    def to_xlsx(bytes_io):
      with pd.ExcelWriter(bytes_io, engine='openpyxl') as writer:
        df_forecast.to_excel(writer, sheet_name=translate("Previsões", lang), index=False)
        df_metrics.to_excel(writer, sheet_name=translate("Métricas", lang), index=False)
        df_residuals.to_excel(writer, sheet_name=translate("Resíduos", lang), index=False)

    return dcc.send_bytes(to_xlsx, translate("SiloDSS_Previsoes_Consolidadas.xlsx", lang))

  except Exception as e:
    print(f"Error in download_prediction_report: {e}")
    return no_update




# --- Stochastic Model Config Callbacks ---

@app.callback(
    Output("collapse-stochastic-fields", "is_open"),
    Input("radio-model-type", "value")
)
def toggle_stochastic_collapse(model_type):
    return model_type == "stochastic"


@app.callback(
    Output("collapse-manual-error", "is_open"),
    Input("radio-error-source", "value")
)
def toggle_manual_error_collapse(error_source):
    return error_source == "manual"


@app.callback(
    Output("prob-validation-text", "children"),
    [Input("input-prob-pessimista", "value"),
     Input("input-prob-esperado", "value"),
     Input("input-prob-otimista", "value")],
    [State("store-lang", "data")]
)
def validate_scenario_probabilities(p_pess, p_esp, p_otim, lang="pt"):
    p_pess = 0.33 if p_pess is None else float(p_pess)
    p_esp = 0.34 if p_esp is None else float(p_esp)
    p_otim = 0.33 if p_otim is None else float(p_otim)
    
    total = p_pess + p_esp + p_otim
    if abs(total - 1.0) < 1e-4:
        return html.Span(translate("Probabilidades válidas (soma = 1.0)", lang), className="text-success")
    else:
        return html.Span(translate("A soma das probabilidades deve ser exatamente 1.0 (atual: {val:.2f})", lang).format(val=total), className="text-danger")


@app.callback(
    Output("prediction-status-container", "children"),
    Input("store-prediction-results", "data"),
    State("store-lang", "data")
)
def update_prediction_status_badge(prediction_results, lang="pt"):
    import json
    has_preds = False
    if prediction_results:
        try:
            preds = json.loads(prediction_results)
            if preds:
                has_preds = True
        except Exception:
            pass

    if has_preds:
        return dbc.Badge(translate("Previsões carregadas.", lang), color="success", className="p-2")
    else:
        return dbc.Badge(translate("Aviso: Previsões ausentes na aba 'Previsão'. O modelo estocástico requer previsões.", lang), color="danger", className="p-2")


# --- Stochastic Results Callbacks ---

@app.callback(
    [Output("stochastic-results-placeholder", "style"),
     Output("stochastic-results-actual-card", "style")],
    Input("store-model-results", "data")
)
def toggle_stochastic_results_container(results_data):
    if results_data and results_data.get("model_type") == "stochastic" and results_data.get("status") == "optimal":
        return {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}


@app.callback(
    [Output("scenario-kpi-cards-container", "children"),
     Output("graph-scenario-costs", "figure"),
     Output("dropdown-scenario-inventory-warehouses", "options"),
     Output("dropdown-warehouse-utilization-warehouses", "options"),
     Output("dropdown-scenario-inventory-warehouses", "value"),
     Output("dropdown-warehouse-utilization-warehouses", "value"),
     Output("stochastic-warnings-container", "children")],
    [Input("store-model-results", "data")],
    [State("store-lang", "data")]
)
def populate_stochastic_results(results_data, lang="pt"):
    if not results_data or results_data.get("model_type") != "stochastic" or results_data.get("status") != "optimal":
        return [], go.Figure(), [], [], None, None, ""

    # BR format helpers
    def fmt_curr(val):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.2e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return f"R$ {s}"
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def fmt_num(val):
        if val is None:
            val = 0.0
        if abs(val) >= 1e9:
            s = f"{val:.2e}"
            if lang != 'en':
                s = s.replace(".", ",")
            return s
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # 1. Scenario KPI Side-by-Side Cards
    scenario_kpis = results_data.get("scenario_kpis", {})
    esp_kpis = scenario_kpis.get("esperado", {})

    kpis_def = [
        {"key": "total_cost", "label": "Custo Total", "is_curr": True, "is_cost": True},
        {"key": "total_tons", "label": "Total Movimentado", "is_curr": False, "is_cost": False},
        {"key": "total_km", "label": "Distância Total", "is_curr": False, "is_cost": True},
        {"key": "total_freight_cost", "label": "Custo Frete", "is_curr": True, "is_cost": True},
        {"key": "total_storage_cost", "label": "Custo Armazenagem", "is_curr": True, "is_cost": True},
        {"key": "total_transshipment_cost", "label": "Custo Transbordo", "is_curr": True, "is_cost": True},
        {"key": "total_opening_cost", "label": "Custo Abertura", "is_curr": True, "is_cost": True},
        {"key": "total_expand_cost", "label": "Custo Expansão", "is_curr": True, "is_cost": True},
        {"key": "total_bulk_cost", "label": "Custo Granelização", "is_curr": True, "is_cost": True},
    ]

    def make_delta_badge(val, baseline_val, is_cost_or_dist=True):
        if baseline_val == 0:
            return html.Span("-", className="delta-badge-neutral ms-2")
        delta_pct = (val - baseline_val) / baseline_val * 100
        if abs(delta_pct) < 1e-4:
            return html.Span("0,00%", className="delta-badge-neutral ms-2")
        
        sign = "+" if delta_pct > 0 else ""
        val_str = f"{sign}{delta_pct:,.2f}%".replace(",", "X").replace(".", ",").replace("X", ".")
        
        if is_cost_or_dist:
            if delta_pct < 0:
                return html.Span(val_str, className="delta-badge-positive ms-2")
            else:
                return html.Span(val_str, className="delta-badge-negative ms-2")
        else:
            if delta_pct > 0:
                return html.Span(val_str, className="delta-badge-positive ms-2")
            else:
                return html.Span(val_str, className="delta-badge-negative ms-2")

    card_cols = []
    for s_name in ["pessimista", "esperado", "otimista"]:
        sk = scenario_kpis.get(s_name, {})
        kpi_rows = []
        for kpi in kpis_def:
            val = sk.get(kpi["key"], 0.0)
            base_val = esp_kpis.get(kpi["key"], 0.0)
            
            val_formatted = fmt_curr(val) if kpi["is_curr"] else fmt_num(val)
            if kpi["key"] == "total_km":
                val_formatted = f"{val_formatted} km"
            elif kpi["key"] == "total_tons":
                val_formatted = f"{val_formatted} t"
                
            if s_name == "esperado":
                badge = html.Span(translate("Referência", lang), className="delta-badge-neutral ms-2")
            else:
                badge = make_delta_badge(val, base_val, is_cost_or_dist=kpi["is_cost"])
                
            kpi_rows.append(html.Div([
                html.Div([
                    html.Span(translate(kpi["label"], lang), className="text-muted fw-bold"),
                ], className="d-flex justify-content-between align-items-center mb-1"),
                html.Div([
                    html.Span(val_formatted, className="fw-bold text-dark fs-5"),
                    badge
                ], className="d-flex align-items-center justify-content-between mb-4 border-bottom pb-2")
            ]))
            
        header_color_class = {
            "pessimista": "text-danger-custom",
            "esperado": "text-primary-custom",
            "otimista": "text-success-custom"
        }.get(s_name, "text-dark")
        
        card_cols.append(dbc.Col([
            dbc.Card([
                dbc.CardHeader(
                    html.H4(translate(s_name.capitalize(), lang), className=f"fw-bold mb-0 {header_color_class}"),
                    className="bg-transparent border-0 pt-3 pb-2"
                ),
                dbc.CardBody(kpi_rows, className="pt-0 pb-2")
            ], className=f"scenario-card-{s_name} shadow-sm h-100 p-4")
        ], width=12, lg=4))

    # 2. Grouped Cost Chart
    cost_cats = [
        translate("Frete", lang),
        translate("Armazenagem", lang),
        translate("Transbordo", lang),
        translate("Abertura", lang),
        translate("Expansão", lang),
        translate("Granelização", lang)
    ]
    
    fig_costs = go.Figure()
    cost_colors = {
        "pessimista": "#C8102E",
        "esperado": "#003366",
        "otimista": "#006633"
    }
    
    # Calculate max cost value across all scenarios to establish a 5% threshold
    all_y_vals = []
    scenario_y_vals = {}
    for s in ["pessimista", "esperado", "otimista"]:
        sk = scenario_kpis.get(s, {})
        opening = sk.get("total_opening_cost", 0.0)
        expand = sk.get("total_expand_cost", 0.0)
        bulk = sk.get("total_bulk_cost", 0.0)
        freight = sk.get("total_freight_cost", 0.0)
        storage = sk.get("total_storage_cost", 0.0)
        transshipment = sk.get("total_transshipment_cost", 0.0)
        vals = [freight, storage, transshipment, opening, expand, bulk]
        all_y_vals.extend(vals)
        scenario_y_vals[s] = vals
        
    max_val = max(all_y_vals) if all_y_vals else 0.0
    
    for s in ["pessimista", "esperado", "otimista"]:
        y_vals = scenario_y_vals[s]
        hover_texts = [fmt_curr(val) for val in y_vals]
        
        # Suppress text labels if value is >= 5% of max_val. Only show text for small non-zero values.
        text_labels = []
        text_positions = []
        for val in y_vals:
            if val > 0 and max_val > 0 and val < 0.05 * max_val:
                text_labels.append(fmt_curr(val))
                text_positions.append("outside")
            else:
                text_labels.append("")
                text_positions.append("none")
                
        fig_costs.add_trace(go.Bar(
            name=translate(s.capitalize(), lang),
            x=cost_cats,
            y=y_vals,
            marker_color=cost_colors[s],
            text=text_labels,
            textposition=text_positions,
            customdata=hover_texts,
            hovertemplate=f"<b>{translate(s.capitalize(), lang)}</b><br>%{{x}}: %{{customdata}}<extra></extra>"
        ))
        
    fig_costs.update_layout(
        barmode='group',
        height=350,
        margin=dict(l=40, r=40, t=80, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.08,
            xanchor="center",
            x=0.5,
            font=dict(size=12)
        ),
        font=dict(family="Roboto, sans-serif", size=12),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    fig_costs.update_xaxes(tickfont=dict(size=12))
    fig_costs.update_yaxes(gridcolor='#E5E7EB', zeroline=False, tickfont=dict(size=12))

    # Extract warehouse options for filters
    wh_metrics_scen = results_data.get("scenario_warehouse_metrics", {})
    esp_whs = wh_metrics_scen.get("esperado", [])
    
    # Sort wh_names alphabetically by display name
    wh_names = sorted(
        [(w["CDA"], w["Name"]) for w in esp_whs],
        key=lambda x: x[1]
    )
    
    # Unique names list for dropdown options
    wh_names_list = sorted(list(set(w["Name"] for w in esp_whs)))
    dropdown_options = [{"label": name, "value": name} for name in wh_names_list]

    # 5. Feasibility Warnings
    warnings = results_data.get("warnings", [])
    warnings_div = []
    if warnings:
        warnings_list = [html.Li(w) for w in warnings]
        warnings_div = [dbc.Alert([
            html.H5([html.I(className="bi bi-exclamation-triangle-fill me-2"), translate("Aviso de Capacidade / Demanda por Cenário", lang)], className="alert-heading"),
            html.P(translate("O modelo estocástico identificou desbalanços de oferta e demanda sob alguns cenários:", lang)),
            html.Hr(),
            html.Ul(warnings_list, className="mb-0")
        ], className="alert-warning-custom shadow-sm mb-3")]

    return (card_cols, fig_costs, dropdown_options, dropdown_options, None, None, warnings_div)


@app.callback(
    Output("graph-scenario-inventory", "figure"),
    [Input("store-model-results", "data"),
     Input("dropdown-scenario-inventory-warehouses", "value"),
     Input("stochastic-results-actual-card", "style"),
     Input("main-tabs", "active_tab")],
    [State("store-lang", "data")]
)
def update_scenario_inventory_chart(results_data, selected_warehouses, card_style, active_tab, lang="pt"):
    def make_default():
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        return fig
    
    if active_tab != 'tab-stochastic-results':
        return make_default()
        
    if not results_data or results_data.get("model_type") != "stochastic" or results_data.get("status") != "optimal":
        return make_default()

    try:
        scenario_inv = results_data.get("scenario_inventory", {})
        dfs = []
        for s in ["pessimista", "esperado", "otimista"]:
            inv_data = scenario_inv.get(s, [])
            if inv_data:
                df_s = pd.DataFrame(inv_data)
                if not df_s.empty:
                    df_s["Cenário"] = translate(s.capitalize(), lang)
                    dfs.append(df_s)
                    
        fig_inv = go.Figure()
        if dfs:
            df_all = pd.concat(dfs, ignore_index=True)
            df_grouped = df_all.groupby(["Período", "Cenário", "Name"])["Quantidade (ton)"].sum().reset_index()
            
            if selected_warehouses:
                df_grouped = df_grouped[df_grouped["Name"].isin(selected_warehouses)]
                
            warehouses = sorted(df_grouped["Name"].unique())
            scenarios_pt = [translate("Pessimista", lang), translate("Esperado", lang), translate("Otimista", lang)]
            
            # Setup warehouse fixed colors using px.colors.qualitative.Plotly
            import plotly.express as px
            color_cycle = px.colors.qualitative.Plotly
            wh_color_map = {wh: color_cycle[idx % len(color_cycle)] for idx, wh in enumerate(warehouses)}
            
            def hex_to_rgba(hex_str, alpha):
                hex_str = hex_str.lstrip('#')
                if len(hex_str) == 3:
                    hex_str = ''.join(c*2 for c in hex_str)
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                return f"rgba({r}, {g}, {b}, {alpha})"
            
            for wh in warehouses:
                df_wh = df_grouped[df_grouped["Name"] == wh]
                for s in scenarios_pt:
                    df_wh_s = df_wh[df_wh["Cenário"] == s]
                    
                    base_color = wh_color_map[wh]
                    # Apply color opacity based on scenario
                    if s == translate("Pessimista", lang):
                        bar_color = hex_to_rgba(base_color, 0.4)
                    elif s == translate("Otimista", lang):
                        bar_color = hex_to_rgba(base_color, 0.7)
                    else:  # Esperado (reference)
                        bar_color = base_color
                        
                    fig_inv.add_trace(go.Bar(
                        name=wh,
                        x=df_wh_s["Período"],
                        y=df_wh_s["Quantidade (ton)"],
                        offsetgroup=s,
                        legendgroup=wh,
                        showlegend=(s == translate("Esperado", lang)),
                        marker=dict(
                            color=bar_color
                        ),
                        hovertemplate=f"<b>{wh}</b><br>{translate('Cenário', lang)}: {s}<br>{translate('Período', lang)}: %{{x}}<br>{translate('Quantidade', lang)}: %{{y:,.2f}} t<extra></extra>"
                    ))
                    
        fig_inv.update_layout(
            barmode='stack',
            height=380,
            margin=dict(l=40, r=40, t=80, b=40),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.08,
                xanchor="center",
                x=0.5,
                font=dict(size=14)
            ),
            font=dict(family="Roboto, sans-serif", size=14),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        fig_inv.update_xaxes(tickfont=dict(size=14))
        fig_inv.update_yaxes(gridcolor='#E5E7EB', zeroline=False, tickfont=dict(size=14))
        return fig_inv
    except Exception as e:
        print(f"Error drawing scenario inventory chart: {e}")
        return make_default()


@app.callback(
    Output("graph-warehouse-utilization", "figure"),
    [Input("store-model-results", "data"),
     Input("dropdown-warehouse-utilization-warehouses", "value"),
     Input("stochastic-results-actual-card", "style"),
     Input("main-tabs", "active_tab")],
    [State("store-lang", "data")]
)
def update_warehouse_utilization_chart(results_data, selected_warehouses, card_style, active_tab, lang="pt"):
    def make_default():
        fig = go.Figure()
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        return fig
    
    if active_tab != 'tab-stochastic-results':
        return make_default()
        
    if not results_data or results_data.get("model_type") != "stochastic" or results_data.get("status") != "optimal":
        return make_default()

    try:
        fig_wh_util = go.Figure()
        wh_metrics_scen = results_data.get("scenario_warehouse_metrics", {})
        esp_whs = wh_metrics_scen.get("esperado", [])
        
        wh_names = sorted(
            [(w["CDA"], w["Name"]) for w in esp_whs],
            key=lambda x: x[1]
        )
        if selected_warehouses:
            wh_names = [x for x in wh_names if x[1] in selected_warehouses]
            
        cost_colors = {
            "pessimista": "#C8102E",
            "esperado": "#003366",
            "otimista": "#006633"
        }
        
        for s in ["pessimista", "esperado", "otimista"]:
            s_whs = wh_metrics_scen.get(s, [])
            s_dict = {w["CDA"]: w for w in s_whs}
            y_vals = []
            x_names = []
            for cda, name in wh_names:
                w = s_dict.get(cda, {})
                vol = w.get("TotalOutflow", 0.0) + w.get("FinalStock", 0.0)
                y_vals.append(vol)
                x_names.append(name)
                
            fig_wh_util.add_trace(go.Bar(
                name=translate(s.capitalize(), lang),
                x=x_names,
                y=y_vals,
                marker_color=cost_colors[s]
            ))
            
        cap_vals = []
        x_names = []
        for cda, name in wh_names:
            w = next((x for x in esp_whs if x["CDA"] == cda), {})
            cap_vals.append(w.get("EffectiveStaticCapacity", 0.0))
            x_names.append(name)
            
        fig_wh_util.add_trace(go.Scatter(
            name=translate("Capacidade Efetiva", lang),
            x=x_names,
            y=cap_vals,
            mode="markers",
            marker=dict(
                symbol="line-ew-open",
                size=24,
                line=dict(width=3, color="#7E7E65")
            )
        ))
        fig_wh_util.update_layout(
            barmode='group',
            height=430,
            margin=dict(l=40, r=40, t=80, b=40),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.08,
                xanchor="center",
                x=0.5,
                font=dict(size=14)
            ),
            font=dict(family="Roboto, sans-serif", size=14),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        fig_wh_util.update_xaxes(tickfont=dict(size=14))
        fig_wh_util.update_yaxes(gridcolor='#E5E7EB', zeroline=False, tickfont=dict(size=14))
        return fig_wh_util
    except Exception as e:
        print(f"Error drawing scenario utilization chart: {e}")
        return make_default()


# --- EVPI/VSS Background Computation Callback ---

@app.callback(
  output=(
    Output("res-evpi-value", "children"),
    Output("res-vss-value", "children"),
    Output("res-evpi-invest", "children"),
    Output("res-evpi-oper", "children"),
    Output("res-evpi-penalty", "children"),
    Output("res-vss-invest", "children"),
    Output("res-vss-oper", "children"),
    Output("res-vss-penalty", "children"),
    Output("res-evpi-decomp-container", "style"),
    Output("res-vss-decomp-container", "style"),
    Output("res-decomp-warning-container", "style"),
  ),
  inputs=[
    Input("store-model-results", "data")
  ],
  state=[
    State('stored-data', 'data'),
    State('store-warehouses', 'data'),
    State('store-prod-warehouses', 'data'),
    State('store-distance-matrix', 'data'),
    State('stored-demand-data', 'data'),
    State('toggle-detailed-log', 'value'),
    State('toggle-pareto-routes', 'value'),
    State('input-allocation-days', 'value'),
    State('input-interhub-factor', 'value'),
    State('input-solver-gap', 'value'),
    State('input-solver-time-limit', 'value'),
    State('dropdown-solver-name', 'value'),
    State('toggle-expansion-enabled', 'value'),
    State('toggle-bulk-enabled', 'value'),
    State('input-ratio-expand-rec', 'value'),
    State('input-ratio-expand-ship', 'value'),
    State('input-max-expand-capacity', 'value'),
    State('input-expand-fixed-cost', 'value'),
    State('input-expand-var-cost', 'value'),
    State('input-max-bulk-capacity', 'value'),
    State('input-bulk-fixed-cost', 'value'),
    State('input-bulk-var-cost', 'value'),
    State('input-bulk-eligible-types', 'value'),
    State('input-prob-pessimista', 'value'),
    State('input-prob-esperado', 'value'),
    State('input-prob-otimista', 'value'),
    State('radio-error-source', 'value'),
    State('input-supply-error-pct', 'value'),
    State('input-demand-error-pct', 'value'),
    State('store-prediction-results', 'data'),
    State('store-gurobi-lic', 'data'),
    State('store-lang', 'data')
  ],
  background=True,
  prevent_initial_call=True
)
def run_evpi_vss(results_data,
                 stored_data, stored_warehouses, stored_prod_warehouses, stored_matrix, stored_demand, detailed_log,
                 toggle_pareto, input_allocation_days, interhub_factor, solver_gap, solver_time_limit, solver_name,
                 expansion_enabled, bulk_enabled,
                 ratio_expand_rec, ratio_expand_ship, max_expand_capacity, expand_fixed_cost, expand_var_cost,
                 max_bulk_capacity, bulk_fixed_cost, bulk_var_cost, bulk_eligible_types,
                 prob_pessimista, prob_esperado, prob_otimista, error_source,
                 supply_error_pct, demand_error_pct, prediction_results_json, gurobi_lic_data, lang='pt'):

  if not results_data or results_data.get("model_type") != "stochastic" or results_data.get("status") != "optimal":
    return "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", {"display": "none"}, {"display": "none"}, {"display": "none"}

  stochastic_objective = results_data.get("objective", 0.0)

  try:
    # Load distance matrices
    import json
    stored_dict = json.loads(stored_matrix)
    df_dist_supply_wh = pd.read_json(io.StringIO(stored_dict['supply_to_warehouses']), orient='split')
    df_dist_wh_demand = pd.read_json(io.StringIO(stored_dict['warehouses_to_demand']), orient='split')
    df_dist_wh_wh = pd.read_json(io.StringIO(stored_dict['warehouses_to_warehouses']), orient='split')

    # Load input DataFrames
    df_supply = pd.read_json(io.StringIO(stored_data), orient='split')
    df_warehouses = pd.read_json(io.StringIO(stored_warehouses), orient='split')
    df_compat = pd.read_json(io.StringIO(stored_prod_warehouses), orient='split')
    df_demand = pd.read_json(io.StringIO(stored_demand), orient='split')

    # Load local CSVs for Freight and Storage
    import os
    data_dir = os.path.join(os.path.dirname(__file__), 'assets', 'data')
    try:
      df_freight = pd.read_csv(os.path.join(data_dir, 'Valor_Tonelada_km.csv'), sep=';', encoding='iso-8859-1')
    except Exception:
      df_freight = pd.DataFrame()

    try:
      df_storage = pd.read_csv(os.path.join(data_dir, 'Tarifa_de_Armazenagem.csv'), sep=';', encoding='iso-8859-1')
    except Exception:
      df_storage = pd.DataFrame()

    preds = json.loads(prediction_results_json) if prediction_results_json else {}

    p_pess = 0.33 if prob_pessimista is None else float(prob_pessimista)
    p_esp = 0.34 if prob_esperado is None else float(prob_esperado)
    p_otim = 0.33 if prob_otimista is None else float(prob_otimista)

    scenario_probabilities = {
      "pessimista": p_pess,
      "esperado": p_esp,
      "otimista": p_otim
    }

    temp_lic_path = None
    if solver_name == 'gurobi':
      if not gurobi_lic_data:
        return "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", {"display": "none"}, {"display": "none"}, {"display": "none"}
      try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.lic', encoding='utf-8') as temp_lic:
          temp_lic.write(gurobi_lic_data)
          temp_lic_path = temp_lic.name
        os.environ["GRB_LICENSE_FILE"] = temp_lic_path
      except Exception as e:
        print(f"Error preparing Gurobi license in run_evpi_vss: {e}")
        return "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", {"display": "none"}, {"display": "none"}, {"display": "none"}

    try:
      if results_data.get("evpi_vss"):
        evpi_vss_results = results_data["evpi_vss"]
      else:
        stochastic_kpis = results_data.get("kpis", {})
        stochastic_scenario_kpis = results_data.get("scenario_kpis", {})
        evpi_vss_results = compute_evpi_vss(
          df_supply=df_supply,
          df_warehouses=df_warehouses,
          df_compat=df_compat,
          df_dist_supply_wh=df_dist_supply_wh,
          df_dist_wh_demand=df_dist_wh_demand,
          df_dist_wh_wh=df_dist_wh_wh,
          df_demand=df_demand,
          df_freight=df_freight,
          df_storage=df_storage,
          scenario_probabilities=scenario_probabilities,
          error_source=error_source or "prediction",
          supply_error_pct=float(supply_error_pct) if supply_error_pct is not None else 15.0,
          demand_error_pct=float(demand_error_pct) if demand_error_pct is not None else 15.0,
          prediction_results=preds,
          stochastic_objective=stochastic_objective,
          detailed_log=detailed_log,
          toggle_pareto=toggle_pareto,
          input_allocation_days=input_allocation_days,
          interhub_factor=interhub_factor,
          solver_gap=solver_gap,
          solver_time_limit=solver_time_limit,
          ratio_expand_rec=ratio_expand_rec,
          ratio_expand_ship=ratio_expand_ship,
          max_expand_capacity=max_expand_capacity if expansion_enabled else None,
          expand_fixed_cost=expand_fixed_cost if expansion_enabled else None,
          expand_var_cost=expand_var_cost if expansion_enabled else None,
          max_bulk_capacity=max_bulk_capacity if bulk_enabled else None,
          bulk_fixed_cost=bulk_fixed_cost if bulk_enabled else None,
          bulk_var_cost=bulk_var_cost if bulk_enabled else None,
          bulk_eligible_types=bulk_eligible_types if bulk_enabled else None,
          lang=lang,
          solver_name=solver_name,
          stochastic_kpis=stochastic_kpis,
          stochastic_scenario_kpis=stochastic_scenario_kpis
        )
    finally:
      if temp_lic_path:
        try:
          if os.path.exists(temp_lic_path):
            os.remove(temp_lic_path)
        except Exception:
          pass
        os.environ.pop("GRB_LICENSE_FILE", None)

    def fmt_curr(val):
      if val is None:
        return "R$ 0,00"
      if abs(val) >= 1e9:
        s = f"{val:.2e}"
        if lang != 'en':
          s = s.replace(".", ",")
        return f"R$ {s}"
      return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    evpi_val = evpi_vss_results.get("evpi", 0.0)
    evpi_invest = evpi_vss_results.get("evpi_invest", 0.0)
    evpi_oper = evpi_vss_results.get("evpi_oper", 0.0)
    evpi_penalty = evpi_vss_results.get("evpi_penalty", 0.0)

    vss_val = evpi_vss_results.get("vss", 0.0)
    vss_invest = evpi_vss_results.get("vss_invest", 0.0)
    vss_oper = evpi_vss_results.get("vss_oper", 0.0)
    vss_penalty = evpi_vss_results.get("vss_penalty", 0.0)

    evpi_has_penalties = evpi_vss_results.get("evpi_has_penalties", False)
    vss_has_penalties = evpi_vss_results.get("vss_has_penalties", False) or evpi_vss_results.get("eev_has_penalties", False)
    has_penalties = evpi_vss_results.get("has_penalties", False) or evpi_has_penalties or vss_has_penalties

    #evpi_formatted = fmt_curr(max(0.0, evpi_val))
    evpi_formatted = fmt_curr(evpi_val)
    evpi_invest_fmt = fmt_curr(evpi_invest)
    evpi_oper_fmt = fmt_curr(evpi_oper)
    evpi_penalty_fmt = fmt_curr(evpi_penalty)

    #vss_formatted = fmt_curr(max(0.0, vss_val))
    vss_formatted = fmt_curr(vss_val)
    vss_invest_fmt = fmt_curr(vss_invest)
    vss_oper_fmt = fmt_curr(vss_oper)
    vss_penalty_fmt = fmt_curr(vss_penalty)

    evpi_decomp_style = {"display": "block"} if evpi_has_penalties else {"display": "none"}
    vss_decomp_style = {"display": "block"} if vss_has_penalties else {"display": "none"}
    warning_style = {"display": "block"} if has_penalties else {"display": "none"}

    return (
      evpi_formatted,
      vss_formatted,
      evpi_invest_fmt,
      evpi_oper_fmt,
      evpi_penalty_fmt,
      vss_invest_fmt,
      vss_oper_fmt,
      vss_penalty_fmt,
      evpi_decomp_style,
      vss_decomp_style,
      warning_style
    )

  except Exception as e:
    print(f"Error computing EVPI/VSS: {e}")
    return "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", "R$ -", {"display": "none"}, {"display": "none"}, {"display": "none"}


# Callback to toggle help modal for EVPI penalty decomposition
@app.callback(
    Output("modal-help-evpi-decomp", "is_open"),
    [Input("help-evpi-decomp-icon", "n_clicks"),
     Input("close-help-evpi-decomp", "n_clicks")],
    State("modal-help-evpi-decomp", "is_open")
)
def toggle_help_evpi_decomp(n_open, n_close, is_open):
    if n_open or n_close:
        return not is_open
    return is_open


# Callback to toggle help modal for VSS penalty decomposition
@app.callback(
    Output("modal-help-vss-decomp", "is_open"),
    [Input("help-vss-decomp-icon", "n_clicks"),
     Input("close-help-vss-decomp", "n_clicks")],
    State("modal-help-vss-decomp", "is_open")
)
def toggle_help_vss_decomp(n_open, n_close, is_open):
    if n_open or n_close:
        return not is_open
    return is_open


# Callback to toggle help modal for direct arcs
@app.callback(
    Output("modal-help-direct-arcs", "is_open"),
    [Input("help-direct-arcs-icon", "n_clicks"),
     Input("close-help-direct-arcs", "n_clicks")],
    State("modal-help-direct-arcs", "is_open")
)
def toggle_help_direct_arcs(n_open, n_close, is_open):
    if n_open or n_close:
        return not is_open
    return is_open


# Callback to dynamically update segment selector options
@app.callback(
    Output('distance-matrix-segment-selector', 'options'),
    Input('store-distance-matrix', 'data'),
    State('store-lang', 'data')
)
def update_segment_selector_options(stored_matrix_json, lang='pt'):
    options = [
        {"label": translate("De: Oferta | Para: Armazéns", lang), "value": "supply_to_warehouses"},
        {"label": translate("De: Armazéns | Para: Demanda", lang), "value": "warehouses_to_demand"},
        {"label": translate("De: Armazéns | Para: Armazéns", lang), "value": "warehouses_to_warehouses"},
    ]
    if stored_matrix_json:
        try:
            stored_dict = json.loads(stored_matrix_json)
            if 'supply_to_demand' in stored_dict:
                options.append({"label": translate("De: Oferta | Para: Demanda", lang), "value": "supply_to_demand"})
        except Exception:
            pass
    return options


def check_and_ensure_gitignore():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    gitignore_path = os.path.join(root_dir, ".gitignore")
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.splitlines()
        has_secrets = any(line.strip().startswith("secrets") for line in lines)
        if not has_secrets:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n# Gurobi Secrets\nsecrets/\nsecrets/*\n")


@app.callback(
    Output("gurobi-lic-upload-container", "style"),
    Input("dropdown-solver-name", "value")
)
def toggle_gurobi_lic_container(solver_name):
    if solver_name == "gurobi":
        return {"display": "block"}
    return {"display": "none"}


@app.callback(
    [
        Output("gurobi-lic-status", "children"),
        Output("store-gurobi-lic", "data")
    ],
    [
        Input("upload-gurobi-lic", "contents")
    ],
    [
        State("upload-gurobi-lic", "filename"),
        State("store-gurobi-lic", "data"),
        State("store-lang", "data")
    ]
)
def handle_gurobi_lic_upload(contents, filename, current_lic_data, lang="pt"):
    # Delete the persistent license file if it exists (stateless precaution)
    try:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        lic_path = os.path.join(root_dir, "secrets", "gurobi.lic")
        if os.path.exists(lic_path):
            os.remove(lic_path)
    except Exception:
        pass

    if contents is not None:
        try:
            content_type, content_string = contents.split(',')
            decoded = base64.b64decode(content_string)
            decoded_str = decoded.decode('utf-8', errors='ignore')
            
            return html.Span(translate("Licença carregada na sessão com sucesso!", lang), className="text-success fw-bold"), decoded_str
        except Exception as e:
            return html.Span(f"{translate('Erro ao processar licença.', lang)} {str(e)}", className="text-danger fw-bold"), None
            
    if current_lic_data:
        return html.Span(translate("Licença ativa na sessão!", lang), className="text-success fw-bold"), current_lic_data
    
    return html.Span(translate("Nenhuma licença enviada. Usando configurações padrão do sistema (se houver).", lang), className="text-muted"), None


# --- Initial Inventory Callbacks ---

@app.callback(
  Output('store-initial-inventory', 'data'),
  Output('error-modal', 'is_open', allow_duplicate=True),
  Output('modal-body-content', 'children', allow_duplicate=True),
  Output('upload-initial-inventory-data', 'contents'),
  [Input('main-tabs', 'active_tab'),
   Input('stored-data', 'data'),
   Input('store-warehouses', 'data'),
   Input('upload-initial-inventory-data', 'contents'),
   Input('btn-add-initial-inventory', 'n_clicks'),
   Input('table-initial-inventory', 'data_timestamp')],
  [State('store-initial-inventory', 'data'),
   State('table-initial-inventory', 'data'),
   State('input-init-inv-product', 'value'),
   State('input-init-inv-warehouse', 'value'),
   State('input-init-inv-amount', 'value'),
   State('upload-initial-inventory-data', 'filename'),
   State('store-lang', 'data')],
  prevent_initial_call=True
)
def manage_initial_inventory(active_tab, stored_data, stored_warehouses, upload_contents, n_add, timestamp,
                             stored_init_inv, table_data, form_product, form_warehouse, form_amount, upload_filename, lang='pt'):
  ctx = dash.callback_context
  if not ctx.triggered:
    return no_update, no_update, no_update, no_update

  trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

  def get_active_products():
    if not stored_data:
      return []
    try:
      df_prod = pd.read_json(io.StringIO(stored_data), orient='split')
      if not df_prod.empty and "Produto" in df_prod.columns:
        return sorted(df_prod["Produto"].dropna().unique().astype(str).tolist())
    except Exception:
      pass
    return []

  def get_registered_warehouses():
    if not stored_warehouses:
      return []
    try:
      df_arm = pd.read_json(io.StringIO(stored_warehouses), orient='split')
      if not df_arm.empty:
        if 'Status' in df_arm.columns:
          df_arm = df_arm[df_arm['Status'] == 'Existente']
        return df_arm
    except Exception:
      pass
    return None

  active_prods = get_active_products()
  df_arm = get_registered_warehouses()

  def check_capacity(df_to_check):
    if df_to_check.empty or 'Estoque Inicial (t)' not in df_to_check.columns:
      return None
    grouped = df_to_check.groupby('CDA')['Estoque Inicial (t)'].sum()
    for cda, tot in grouped.items():
      cap_est = 0.0
      if df_arm is not None and not df_arm.empty:
        w_row = df_arm[df_arm['CDA'] == cda]
        if not w_row.empty:
          cap_est = float(w_row.iloc[0]['Cap. Estática (t)'])
      if tot > cap_est + 1e-4:
        return cda, tot, cap_est
    return None

  if trigger_id in ['main-tabs', 'stored-data', 'store-warehouses']:
    if active_tab != 'tab-prod-warehouses':
      return no_update, no_update, no_update, no_update

    wh_list = []
    if df_arm is not None and not df_arm.empty:
      try:
        cda_idx = df_arm.columns.get_loc('CDA')
        arm_idx = df_arm.columns.get_loc('Armazenador')
        mun_idx = df_arm.columns.get_loc('Município')
        cap_idx = df_arm.columns.get_loc('Cap. Estática (t)')
        for row in df_arm.itertuples(index=False):
          wh_list.append({
            'CDA': str(row[cda_idx]).strip(),
            'Armazenador': str(row[arm_idx]).strip(),
            'Município': str(row[mun_idx]).strip(),
            'Cap. Estática (t)': float(row[cap_idx])
          })
      except Exception:
        for _, row in df_arm.iterrows():
          wh_list.append({
            'CDA': str(row['CDA']).strip(),
            'Armazenador': str(row['Armazenador']).strip(),
            'Município': str(row['Município']).strip(),
            'Cap. Estática (t)': float(row['Cap. Estática (t)'])
          })

    if not wh_list or not active_prods:
      empty_df = pd.DataFrame(columns=['CDA', 'Armazenador', 'Município', 'Cap. Estática (t)', 'Produto', 'Estoque Inicial (t)'])
      return empty_df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

    exist_map = {}
    if stored_init_inv:
      try:
        df_exist = pd.read_json(io.StringIO(stored_init_inv), orient='split')
        if not df_exist.empty:
          cda_idx = df_exist.columns.get_loc('CDA')
          prod_idx = df_exist.columns.get_loc('Produto')
          val_idx = df_exist.columns.get_loc('Estoque Inicial (t)')
          for row in df_exist.itertuples(index=False):
            exist_map[(str(row[cda_idx]).strip(), str(row[prod_idx]).strip())] = float(row[val_idx])
      except Exception:
        try:
          df_exist = pd.read_json(io.StringIO(stored_init_inv), orient='split')
          for _, row in df_exist.iterrows():
            exist_map[(str(row['CDA']).strip(), str(row['Produto']).strip())] = float(row['Estoque Inicial (t)'])
        except Exception:
          pass

    records = []
    for wh in wh_list:
      for prod in active_prods:
        val = exist_map.get((wh['CDA'], prod), 0.0)
        records.append({
          'CDA': wh['CDA'],
          'Armazenador': wh['Armazenador'],
          'Município': wh['Município'],
          'Cap. Estática (t)': wh['Cap. Estática (t)'],
          'Produto': prod,
          'Estoque Inicial (t)': val
        })
    df_new = pd.DataFrame(records)
    return df_new.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

  if trigger_id == 'btn-clear-initial-inventory':
    if not stored_init_inv:
      return no_update, no_update, no_update, no_update
    try:
      df = pd.read_json(io.StringIO(stored_init_inv), orient='split')
      if not df.empty:
        df['Estoque Inicial (t)'] = 0.0
        return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update
    except Exception:
      pass
    return no_update, no_update, no_update, no_update

  if trigger_id == 'btn-add-initial-inventory':
    if not form_product or not form_warehouse:
      return no_update, True, translate("Por favor, selecione um produto e um armazém.", lang), no_update

    amount = 0.0
    if form_amount is not None:
      try:
        amount = float(form_amount)
      except ValueError:
        return no_update, True, translate("O estoque inicial deve ser um número válido.", lang), no_update

    if not stored_init_inv:
      return no_update, no_update, no_update, no_update

    df = pd.read_json(io.StringIO(stored_init_inv), orient='split')
    df_temp = df.copy()
    mask = (df_temp['CDA'] == form_warehouse) & (df_temp['Produto'] == form_product)
    if mask.any():
      df_temp.loc[mask, 'Estoque Inicial (t)'] = amount
    else:
      arm_name = ""
      mun_name = ""
      cap_est = 0.0
      if df_arm is not None and not df_arm.empty:
        w_row = df_arm[df_arm['CDA'] == form_warehouse]
        if not w_row.empty:
          arm_name = str(w_row.iloc[0]['Armazenador'])
          mun_name = str(w_row.iloc[0]['Município'])
          cap_est = float(w_row.iloc[0]['Cap. Estática (t)'])
      new_row = pd.DataFrame([{
        'CDA': form_warehouse,
        'Armazenador': arm_name,
        'Município': mun_name,
        'Cap. Estática (t)': cap_est,
        'Produto': form_product,
        'Estoque Inicial (t)': amount
      }])
      df_temp = pd.concat([df_temp, new_row], ignore_index=True)

    violation = check_capacity(df_temp)
    if violation:
      cda, tot, cap_est = violation
      err_msg = translate("Erro: A soma do estoque inicial ({total_init_inv:.2f} t) do armazém {cda} excede a capacidade estática ({cap_est:.2f} t).", lang).format(total_init_inv=tot, cda=cda, cap_est=cap_est)
      return no_update, True, err_msg, no_update

    return df_temp.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

  if trigger_id == 'table-initial-inventory':
    if table_data is not None:
      df = pd.DataFrame(table_data)
      if not df.empty and 'Estoque Inicial (t)' in df.columns:
        df['Estoque Inicial (t)'] = df['Estoque Inicial (t)'].apply(lambda x: safe_parse_numeric(x) if pd.notna(x) else 0.0)
      
      violation = check_capacity(df)
      if violation:
        cda, tot, cap_est = violation
        err_msg = translate("Erro: A soma do estoque inicial ({total_init_inv:.2f} t) do armazém {cda} excede a capacidade estática ({cap_est:.2f} t).", lang).format(total_init_inv=tot, cda=cda, cap_est=cap_est)
        return no_update, True, err_msg, no_update

      return df.to_json(date_format='iso', orient='split'), no_update, no_update, no_update

  if trigger_id == 'upload-initial-inventory-data' and upload_contents:
    content_type, content_string = upload_contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
      if 'spreadsheetml' in content_type or (upload_filename and upload_filename.endswith('.xlsx')):
        df_upload = pd.read_excel(io.BytesIO(decoded))
      else:
        df_upload = pd.read_csv(io.StringIO(decoded.decode('utf-8')), sep=None, engine='python')

      df_upload.columns = [c.strip() for c in df_upload.columns]

      required_cols = ['CDA', 'Produto', 'Estoque Inicial (t)']
      missing_cols = [c for c in required_cols if c not in df_upload.columns]
      if missing_cols:
        return no_update, True, translate("Colunas obrigatórias ausentes na planilha de estoque inicial. Esperado: CDA, Produto, Estoque Inicial (t)", lang), ""

      upload_products = set(df_upload['Produto'].dropna().astype(str).str.strip().unique())
      upload_cdas = set(df_upload['CDA'].dropna().astype(str).str.strip().unique())

      active_products_set = set(active_prods)

      registered_cdas_set = set()
      if df_arm is not None and not df_arm.empty:
        registered_cdas_set = set(df_arm['CDA'].dropna().astype(str).str.strip().unique())

      invalid_products = upload_products - active_products_set
      invalid_cdas = upload_cdas - registered_cdas_set

      if invalid_products or invalid_cdas:
        err_msg = translate("Os produtos e armazéns informados na planilha não coincidem com os cadastrados no sistema.", lang)
        if invalid_products:
          err_msg += f"\n\n{translate('Os seguintes produtos da planilha não existem no sistema:', lang)} {', '.join(sorted(invalid_products))}"
        if invalid_cdas:
          err_msg += f"\n\n{translate('Os seguintes CDAs da planilha não existem no sistema:', lang)} {', '.join(sorted(invalid_cdas))}"
        return no_update, True, err_msg, ""

      upload_map = {}
      for row in df_upload.itertuples(index=False):
        cda = str(row[df_upload.columns.get_loc('CDA')]).strip()
        prod = str(row[df_upload.columns.get_loc('Produto')]).strip()
        val = safe_parse_numeric(row[df_upload.columns.get_loc('Estoque Inicial (t)')]) if pd.notna(row[df_upload.columns.get_loc('Estoque Inicial (t)')]) else 0.0
        upload_map[(cda, prod)] = val

      wh_list = []
      if df_arm is not None and not df_arm.empty:
        try:
          cda_idx = df_arm.columns.get_loc('CDA')
          arm_idx = df_arm.columns.get_loc('Armazenador')
          mun_idx = df_arm.columns.get_loc('Município')
          cap_idx = df_arm.columns.get_loc('Cap. Estática (t)')
          for row in df_arm.itertuples(index=False):
            wh_list.append({
              'CDA': str(row[cda_idx]).strip(),
              'Armazenador': str(row[arm_idx]).strip(),
              'Município': str(row[mun_idx]).strip(),
              'Cap. Estática (t)': float(row[cap_idx])
            })
        except Exception:
          for _, row in df_arm.iterrows():
            wh_list.append({
              'CDA': str(row['CDA']).strip(),
              'Armazenador': str(row['Armazenador']).strip(),
              'Município': str(row['Município']).strip(),
              'Cap. Estática (t)': float(row['Cap. Estática (t)'])
            })

      records = []
      for wh in wh_list:
        for prod in active_prods:
          val = upload_map.get((wh['CDA'], prod), 0.0)
          records.append({
            'CDA': wh['CDA'],
            'Armazenador': wh['Armazenador'],
            'Município': wh['Município'],
            'Cap. Estática (t)': wh['Cap. Estática (t)'],
            'Produto': prod,
            'Estoque Inicial (t)': val
          })
      df_new = pd.DataFrame(records)

      violation = check_capacity(df_new)
      if violation:
        cda, tot, cap_est = violation
        err_msg = translate("Erro: A soma do estoque inicial ({total_init_inv:.2f} t) do armazém {cda} excede a capacidade estática ({cap_est:.2f} t).", lang).format(total_init_inv=tot, cda=cda, cap_est=cap_est)
        return no_update, True, err_msg, ""

      return df_new.to_json(date_format='iso', orient='split'), no_update, no_update, ""
    except Exception as e:
      print(f"Error parsing uploaded initial inventory: {e}")
      return no_update, True, f"{translate('Erro ao processar arquivo.', lang)} Details: {str(e)}", ""

  return no_update, no_update, no_update, no_update


@app.callback(
  Output('table-initial-inventory', 'data'),
  Output('input-init-inv-product', 'options'),
  Output('input-init-inv-warehouse', 'options'),
  Input('main-tabs', 'active_tab'),
  Input('store-initial-inventory', 'data'),
  Input('stored-data', 'data'),
  Input('store-warehouses', 'data'),
  Input('store-lang', 'data')
)
def populate_initial_inventory_table(active_tab, stored_init_inv, stored_data, stored_warehouses, lang='pt'):
  if active_tab != 'tab-prod-warehouses':
    return no_update, no_update, no_update

  product_options = []
  if stored_data:
    try:
      df_prod = pd.read_json(io.StringIO(stored_data), orient='split')
      if not df_prod.empty and "Produto" in df_prod.columns:
        active_prods = sorted(df_prod["Produto"].dropna().unique().astype(str).tolist())
        product_options = [{'label': p, 'value': p} for p in active_prods]
    except Exception:
      pass

  warehouse_options = []
  if stored_warehouses:
    try:
      df_arm = pd.read_json(io.StringIO(stored_warehouses), orient='split')
      if not df_arm.empty:
        if 'Status' in df_arm.columns:
          df_arm = df_arm[df_arm['Status'] == 'Existente']
        cda_idx = df_arm.columns.get_loc('CDA')
        arm_idx = df_arm.columns.get_loc('Armazenador')
        mun_idx = df_arm.columns.get_loc('Município')
        for row in df_arm.itertuples(index=False):
          cda = str(row[cda_idx]).strip()
          arm = str(row[arm_idx]).strip()
          mun = str(row[mun_idx]).strip()
          label = f"{cda} - {arm} - {mun}"
          warehouse_options.append({'label': label, 'value': cda})
    except Exception:
      try:
        df_arm = pd.read_json(io.StringIO(stored_warehouses), orient='split')
        if 'Status' in df_arm.columns:
          df_arm = df_arm[df_arm['Status'] == 'Existente']
        for _, row in df_arm.iterrows():
          cda = str(row['CDA']).strip()
          arm = str(row['Armazenador']).strip()
          mun = str(row['Município']).strip()
          label = f"{cda} - {arm} - {mun}"
          warehouse_options.append({'label': label, 'value': cda})
      except Exception:
        pass

  if not stored_init_inv:
    return [], product_options, warehouse_options

  try:
    df = pd.read_json(io.StringIO(stored_init_inv), orient='split')
    return df.to_dict('records'), product_options, warehouse_options
  except Exception:
    return [], product_options, warehouse_options




@app.callback(
  Output("download-initial-inventory", "data"),
  Input("btn-export-initial-inventory-xlsx", "n_clicks"),
  State('store-initial-inventory', 'data'),
  State('store-lang', 'data'),
  prevent_initial_call=True
)
def export_initial_inventory(n_clicks, stored_init_inv, lang='pt'):
  if not n_clicks or not stored_init_inv:
    return no_update
  df = pd.read_json(io.StringIO(stored_init_inv), orient='split')
  df_export = df[['CDA', 'Cap. Estática (t)', 'Produto', 'Estoque Inicial (t)']]
  return dcc.send_data_frame(df_export.to_excel, translate("estoque_inicial.xlsx", lang), index=False)


def view():
    # Use environment variable to determine if we are in Docker or dev
    # '0.0.0.0' allows external access (from host to docker container)
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8050))
    app.run(debug=False, host=host, port=port)
