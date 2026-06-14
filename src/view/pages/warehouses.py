from src.logic.i18n import translate
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
from src.view.theme import UNB_THEME

def get_tab_warehouses_layout(lang='pt', city_options=None):
    if city_options is None:
        city_options = []

    # 1. Clear Card
    clear_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Limpar Base", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-clear", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Remove todos os armazéns cadastrados nesta sessão para iniciar uma nova configuração.", lang),
                        target="help-wh-clear",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Button(
                        translate("Limpar Base / Iniciar Nova", lang),
                        id="btn-clear-warehouses",
                        color="none",
                        className="btn-danger-custom w-100"
                    )
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-24"
    )

    # 2. Upload Card
    upload_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Carregar Arquivo", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-upload", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Carregue uma planilha com sua base de armazéns (Excel .xlsx ou CSV). Ela deve seguir o modelo esperado.", lang),
                        target="help-wh-upload",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dcc.Upload(
                        id="upload-warehouses-data",
                        children=html.Div([
                            html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                            html.Span(translate("Arraste e solte ou ", lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                            html.A(translate("Selecione", lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                            html.Div(translate("Formatos: .xlsx, .csv", lang), className="text-muted small mt-2")
                        ]),
                        className="upload-box",
                        multiple=False,
                        accept=".xlsx, .csv"
                    ),
                    dbc.Button(
                        translate("Baixar Planilha Exemplo (.xlsx)", lang),
                        id="btn-wh-download-template",
                        color="none",
                        className="btn-secondary-custom w-100 mt-16"
                    )
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-24"
    )

    # 3. Add Warehouse Card
    add_warehouse_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Adicionar Armazém", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-add", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Insira um novo armazém manualmente à base desta sessão.", lang),
                        target="help-wh-add",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row([
                        # Status toggle (Existente / Candidato)
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Status", lang), className="fw-bold small mb-0 me-2"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-status", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Selecione 'Existente' se o armazém já estiver em operação ou 'Candidato' para avaliar a viabilidade de sua abertura.", lang),
                                    target="help-wh-status",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center mb-1"),
                            dbc.RadioItems(
                                id="wh-status-radio",
                                options=[
                                    {"label": translate("Existente", lang), "value": "Existente"},
                                    {"label": translate("Candidato", lang), "value": "Candidato"},
                                ],
                                value="Existente",
                                inline=True,
                                className="mb-16"
                            )
                        ], width=12),
                        
                        # City selection
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Cidade", lang), className="fw-bold small mb-0 me-2"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-city", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Selecione o município onde o armazém está (ou será) localizado. O sistema preenche a latitude e longitude automaticamente.", lang),
                                    target="help-wh-city",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center mb-1"),
                            dcc.Dropdown(
                                id="wh-input-city",
                                options=[],
                                placeholder=translate("Selecione a cidade...", lang),
                                className="mb-16",
                                searchable=True
                            )
                        ], width=12),

                        # Lat / Lon and Manual Edit
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Latitude", lang), className="fw-bold small mb-0 me-2"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-lat", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Latitude geográfica do armazém, em graus decimais.", lang),
                                    target="help-wh-lat",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="wh-input-lat", type="number", placeholder=translate("Lat", lang), className="mb-16", disabled=True)
                        ], width=5),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Longitude", lang), className="fw-bold small mb-0 me-2"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-lon", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Longitude geográfica do armazém, em graus decimais.", lang),
                                    target="help-wh-lon",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="wh-input-lon", type="number", placeholder=translate("Lon", lang), className="mb-16", disabled=True)
                        ], width=5),
                        dbc.Col([
                            dbc.Button("🔒", id="btn-wh-manual-edit", color="none", className="btn-secondary-custom d-flex align-items-center justify-content-center w-100 mb-16", style={"height": "38px"}, n_clicks=0, title=translate("Editar Lat/Long manualmente", lang))
                        ], width=2, className="d-flex align-items-end"),

                        # Capacidade Estática Máxima (Shared field)
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Capacidade Estática Máxima (t)", lang), className="fw-bold small mb-0 me-2"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-max-static-cap", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Limite máximo permitido de capacidade estática (t). Para existentes, define o teto para uma eventual expansão. Para candidatos, define o limite superior da capacidade a ser construída.", lang),
                                    target="help-wh-max-static-cap",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="wh-input-max-static-cap", type="number", placeholder=translate("Ex: 15000", lang), className="mb-16")
                        ], width=12),

                        # Existing-only Fields Container
                        dbc.Col([
                            html.Div(
                                id="wh-existing-fields-container",
                                children=[
                                    dbc.Row([
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Armazenador", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-provider", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Nome do proprietário ou operador responsável pelo armazém (ex: CONAB, privado).", lang),
                                                    target="help-wh-provider",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-provider", type="text", placeholder=translate("Ex: CONAB", lang), className="mb-16")
                                        ], width=12),
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Tipo", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-type", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Tipo de estrutura de armazenagem (ex: Silo, Graneleiro, Convencional).", lang),
                                                    target="help-wh-type",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-type", type="text", placeholder=translate("Ex: Convencional", lang), className="mb-16")
                                        ], width=12),
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Capacidade Estática (t)", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-static-cap", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Capacidade física atual de armazenagem em toneladas.", lang),
                                                    target="help-wh-static-cap",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-static-cap", type="number", placeholder=translate("Ex: 10000", lang), className="mb-16")
                                        ], width=12),
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Capacidade de Recepção", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-reception-cap", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Capacidade máxima diária de recebimento de produtos no armazém (t/dia).", lang),
                                                    target="help-wh-reception-cap",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-reception-cap", type="number", placeholder=translate("Ex: 1000", lang), className="mb-16")
                                        ], width=12),
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Cap. Expedição (t)", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-expedition-cap", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Capacidade máxima diária de expedição/saída de produtos do armazém (t/dia).", lang),
                                                    target="help-wh-expedition-cap",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-expedition-cap", type="number", placeholder=translate("Ex: 800", lang), className="mb-16")
                                        ], width=12)
                                    ])
                                ],
                                style={"display": "block"}
                            )
                        ], width=12),

                        # Candidate-only Fields Container
                        dbc.Col([
                            html.Div(
                                id="wh-candidate-fields-container",
                                children=[
                                    dbc.Row([
                                        dbc.Col([
                                            html.Div([
                                                dbc.Label(translate("Custo de Abertura ($)", lang), className="fw-bold small mb-0 me-2"),
                                                html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-opening-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                dbc.Tooltip(translate("Custo fixo de investimento para a abertura do armazém candidato ($).", lang),
                                                    target="help-wh-opening-cost",
                                                    placement="right"
                                                ),
                                            ], className="d-flex align-items-center mb-1"),
                                            dbc.Input(id="wh-input-opening-cost", type="number", placeholder=translate("Ex: 50000", lang), className="mb-16")
                                        ], width=12)
                                    ])
                                ],
                                style={"display": "none"}
                            )
                        ], width=12),

                        # Add button
                        dbc.Col([
                            dbc.Button(
                                translate("Adicionar Armazém", lang),
                                id="btn-wh-add-row",
                                color="none",
                                className="btn-primary-custom w-100 mt-8"
                            )
                        ], width=12)
                    ])
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-24"
    )

    # 4. Export Card
    export_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Exportar", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-export", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Exporta a planilha atualizada com os armazéns cadastrados.", lang),
                        target="help-wh-export",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Button(
                        translate("Baixar Planilha (.xlsx)", lang),
                        id="btn-wh-export-xlsx",
                        color="none",
                        className="btn-success-custom w-100"
                    )
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-24"
    )

    # Right Panel — 1. DataTable Card
    # Initial empty dataframe matching expected columns
    initial_cols = [
        "Status", "Município", "UF", "Latitude", "Longitude", 
        "Armazenador", "Tipo", "Cap. Estática (t)", "Cap. Estática Máxima (t)", "Cap. Recepção (t)", "Cap. Expedição (t)", "Custo de Abertura ($)"
    ]
    initial_df = pd.DataFrame(columns=initial_cols)

    metrics_section = dbc.Row(
        [
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-building-fill fs-3 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
                                    html.Div(
                                        [
                                            html.H6(translate("Total de Armazéns", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                            html.H4(id="wh-metric-total-count", children="0", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']})
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
                width=6, lg=3
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-check-circle-fill fs-3 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
                                    html.Div(
                                        [
                                            html.H6(translate("Armazéns Existentes", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                            html.H4(id="wh-metric-existing-count", children="0", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']})
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
                width=6, lg=3
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-plus-circle-fill fs-3 me-3", style={"color": UNB_THEME['UNB_YELLOW_DARK']}),
                                    html.Div(
                                        [
                                            html.H6(translate("Armazéns Candidatos", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                            html.H4(id="wh-metric-candidate-count", children="0", className="mb-0", style={"color": UNB_THEME['UNB_YELLOW_DARK']})
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
                width=6, lg=3
            ),
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Div(
                                [
                                    html.I(className="bi bi-box-seam-fill fs-3 me-3", style={"color": UNB_THEME['UNB_GREEN']}),
                                    html.Div(
                                        [
                                            html.H6(translate("Capacidade Estática Total (t)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                            html.H4(id="wh-metric-total-capacity", children="0.00", className="mb-0", style={"color": UNB_THEME['UNB_GREEN']})
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
                width=6, lg=3
            ),
        ],
        className="mt-16 g-3"
    )

    table_card = dbc.Card(
        [
            dbc.CardHeader(
                translate("Tabela de Armazéns", lang),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Spinner(
                        html.Div(id="table-warehouses-container", children=[
                            dash_table.DataTable(
                                id="table-warehouses",
                                data=initial_df.to_dict('records'),
                                columns=[
                                    {
                                        'name': translate(col, lang), 
                                        'id': col, 
                                        'deletable': False, 
                                        'renamable': False,
                                        'presentation': 'dropdown' if col == 'Status' else 'input'
                                    } for col in initial_df.columns
                                ],
                                dropdown={
                                    'Status': {
                                        'options': [
                                            {'label': translate('Existente', lang), 'value': translate('Existente', lang)},
                                            {'label': translate('Candidato', lang), 'value': translate('Candidato', lang)}
                                        ]
                                    }
                                },
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
                    )
                ],
                className="card-body-custom d-flex flex-column"
            ),
        ],
        className="card-custom mb-24",
        style={"minHeight": "600px"}
    )

    # Right Panel — 2. Map Card
    map_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Localização dos Armazéns", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-wh-map", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Visualização geográfica dos armazéns na base. Armazéns existentes aparecem em azul, e candidatos em laranja.", lang),
                        target="help-wh-map",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dcc.Graph(
                        id="graph-warehouses-map",
                        style={"height": "500px"},
                        config={
                            "displayModeBar": True,
                            "scrollZoom": True,
                            "showAxisDragHandles": True,
                            "toImageButtonOptions": {
                                "format": "png",
                                "filename": "mapa_armazens",
                                "height": None,
                                "width": None,
                                "scale": 1
                            }
                        }
                    ),
                    metrics_section
                ],
                className="card-body-custom"
            )
        ],
        className="card-custom mb-24"
    )

    # 5. Confirm Clear Dataset Modal
    confirm_clear_modal = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(translate("Confirmar Limpeza", lang)), id="confirm-clear-wh-header-title"),
            dbc.ModalBody(translate("Aviso: Se o progresso não for salvo ele será perdido. Recomendamos baixar os dados antes de limpar a base.", lang)),
            dbc.ModalFooter([
                dbc.Button(translate("Cancelar", lang), id="btn-cancel-clear-warehouses", className="me-2 btn-secondary-custom", color="secondary", n_clicks=0),
                dbc.Button(translate("Limpar Base", lang), id="btn-confirm-clear-warehouses", className="btn-danger-custom", color="danger", n_clicks=0)
            ]),
        ],
        id="confirm-clear-warehouses-modal",
        is_open=False,
    )

    return html.Div([
        dbc.Row(
            [
                dbc.Col([
                    clear_card,
                    upload_card,
                    add_warehouse_card,
                    export_card
                ], width=12, lg=3, className="mb-24"),
                dbc.Col([
                    map_card,
                    table_card
                ], width=12, lg=9, className="mb-24"),
            ]
        ),
        confirm_clear_modal
    ])
