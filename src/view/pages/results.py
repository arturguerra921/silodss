import dash
from src.logic.i18n import translate
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME

def get_tab_results_layout(lang='pt'):
    # 1. KPIs Globais
    kpi_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Métricas da Operação (Total)", lang), className="me-2 fw-bold"),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    # Row 1 of KPIs (3 columns)
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo Total Ótimo (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-objective", children="R$ 0,00", className="mb-0 text-success-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=4
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Total Movimentado (ton)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-tons", children="0.00", className="mb-0 text-primary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=4
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Distância Total (km)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-km", children="0.00", className="mb-0 text-secondary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=4
                        ),
                    ], className="g-3 mb-3"),
                    # Row 2 of KPIs (6 columns)
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo com Frete (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-freight", children="R$ 0,00", className="mb-0 text-danger-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo Armazenagem (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-storage", children="R$ 0,00", className="mb-0 text-warning-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo de Transbordo (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-transshipment", children="R$ 0,00", className="mb-0 text-info-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo de Abertura (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-opening", children="R$ 0,00", className="mb-0 text-primary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo de Expansão (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-expand", children="R$ 0,00", className="mb-0 text-secondary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Custo de Granelização (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-kpi-bulk", children="R$ 0,00", className="mb-0 text-success-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=2
                        ),
                    ], className="g-3")
                ],
                className="card-body-custom"
            )
        ],
        className="card-custom mb-3"
    )

    # 1.5 Avisos e Alertas (Dummies)
    warnings_container = html.Div(id="results-warnings-container", className="mb-4")

    # 1.8 Decisões de Armazéns
    warehouse_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Decisões sobre Armazéns", lang), className="me-2 fw-bold"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-results-warehouses", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Métricas detalhadas sobre abertura de candidatos, expansões, granelizações e fluxo nos armazéns.", lang),
                        target="help-results-warehouses",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row([
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Candidatos Abertos", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-wh-opened-count", children="0", className="mb-0 text-success-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=3
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Armazéns Expandidos", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-wh-expanded-count", children="0", className="mb-0 text-secondary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=3
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Armazéns Granelizados", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-wh-bulkified-count", children="0", className="mb-0 text-primary-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=3
                        ),
                        dbc.Col(
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Investimento em Infraestrutura (R$)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                                    html.H4(id="res-wh-investment", children="R$ 0,00", className="mb-0 text-danger-custom")
                                ]),
                                className="shadow-sm border-0 h-100 text-center",
                                style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
                            ),
                            width=12, lg=3
                        ),
                    ], className="g-3 mb-4"),
                    html.Div([
                        dbc.Label(translate("Mostrar armazéns não utilizados", lang), html_for="switch-show-all-warehouses", className="me-2 fw-bold mb-0"),
                        dbc.Switch(
                            id="switch-show-all-warehouses",
                            value=False,
                            className="custom-switch",
                            style={"display": "inline-block", "verticalAlign": "middle"}
                        ),
                        html.I(
                            className="bi bi-question-circle-fill text-muted ms-2",
                            id="help-unused-warehouses",
                            style={"cursor": "help", "fontSize": "var(--font-size-small)"}
                        ),
                        dbc.Tooltip(
                            translate("Exibe todos os armazéns cadastrados, incluindo aqueles que não tiveram fluxo ou novos candidatos que permaneceram fechados na solução ótima.", lang),
                            target="help-unused-warehouses",
                            placement="right"
                        ),
                    ], className="d-flex align-items-center mb-3"),
                    dbc.Spinner(
                        html.Div(id='results-warehouses-table-container', children=[
                            dash_table.DataTable(
                                id='table-results-warehouses',
                                data=[],
                                columns=[
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
                                ],
                                filter_action='native',
                                page_size=10,
                                style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                style_cell={
                                    'textAlign': 'left',
                                    'fontFamily': "'Roboto', sans-serif",
                                    'padding': '12px',
                                    'fontSize': 'var(--font-size-small)',
                                    'color': UNB_THEME['SECONDARY']
                                },
                                style_header={
                                    'backgroundColor': '#F8F9FA',
                                    'color': UNB_THEME['PRIMARY'],
                                    'fontWeight': 'bold',
                                    'border': 'none',
                                    'padding': '12px',
                                    'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}"
                                },
                                style_data={
                                    'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}",
                                    'cursor': 'pointer'
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
                ],
                className="card-body-custom"
            )
        ],
        className="card-custom mb-3"
    )

    # 2. Tabela de Rotas Realizadas
    table_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Rotas Realizadas", lang), className="me-2 fw-bold"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-results-table", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Selecione uma rota para visualizá-la no mapa abaixo e ver suas métricas específicas.", lang),
                        target="help-results-table",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Spinner(
                        html.Div(id='results-table-container', children=[
                            dash_table.DataTable(
                                id='table-results-routes',
                                data=[],
                                columns=[
                                    {'name': translate('Origem', lang), 'id': 'Origem'},
                                    {'name': translate('Destino', lang), 'id': 'Destino'},
                                    {'name': translate('Produto', lang), 'id': 'Produto'},
                                    {'name': translate('Qtd (ton)', lang), 'id': 'Quantidade (ton)'}
                                ],
                                filter_action='native',
                                page_size=10,
                                style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                style_cell={
                                    'textAlign': 'left',
                                    'fontFamily': "'Roboto', sans-serif",
                                    'padding': '12px',
                                    'fontSize': 'var(--font-size-small)',
                                    'color': UNB_THEME['SECONDARY']
                                },
                                style_header={
                                    'backgroundColor': '#F8F9FA',
                                    'color': UNB_THEME['PRIMARY'],
                                    'fontWeight': 'bold',
                                    'border': 'none',
                                    'padding': '12px',
                                    'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}"
                                },
                                style_data={
                                    'borderBottom': f"1px solid {UNB_THEME['BORDER_LIGHT']}",
                                    'cursor': 'pointer'
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
                className="card-body-custom"
            )
        ],
        className="card-custom h-100"
    )

    # 3. Mapa e Detalhes da Rota
    map_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Visualização da Rota", lang), className="me-2 fw-bold"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-results-map", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Mapa exibindo a rota selecionada ou todas as rotas (malha).", lang),
                        target="help-results-map",
                        placement="right"
                    ),
                    html.Div(
                        dbc.Button(translate("Ver Todas as Rotas", lang), id="btn-show-all-routes", size="sm", color="none", className="btn-outline-secondary-custom ms-3"),
                        className="ms-auto"
                    )
                ], className="d-flex align-items-center w-100"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row([
                        # Coluna do Mapa
                        dbc.Col(
                            dbc.Spinner(
                                dcc.Graph(
                                    id='graph-results-map',
                                    config={
                                        "displayModeBar": True,
                                        "scrollZoom": True,
                                        "showAxisDragHandles": True,
                                        "modeBarButtonsToAdd": ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape'],
                                        "toImageButtonOptions": {
                                            "format": "png",
                                            "filename": "mapa_de_rotas",
                                            "height": None,
                                            "width": None,
                                            "scale": 1
                                        }
                                    },
                                    style={"height": "600px", "borderRadius": "8px", "overflow": "hidden"}
                                ),
                                spinner_class_name="text-primary-custom"
                            ),
                            width=12, lg=8, className="mb-3"
                        ),
                        # Coluna de Detalhes Específicos
                        dbc.Col(
                            [
                                html.Div(
                                    id="route-details-container",
                                    className="flex-grow-1 d-flex flex-column",
                                    children=[
                                        html.P(translate("Selecione uma rota na tabela ao lado para ver os detalhes e indicadores aqui.", lang), className="text-muted small mt-2")
                                    ]
                                )
                            ],
                            width=12, lg=4, className="mb-3 d-flex flex-column"
                        )
                    ])
                ],
                className="card-body-custom"
            )
        ],
        className="card-custom mb-3 mt-4"
    )

    # 1.9 Mapa e Detalhes dos Armazéns
    warehouse_map_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Visualização de Armazéns e Fluxos", lang), className="me-2 fw-bold"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-results-wh-map", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Selecione um armazém na tabela de decisões acima para ver sua localização, conexões de entrada/saída e custos associados.", lang),
                        target="help-results-wh-map",
                        placement="right"
                    ),
                ], className="d-flex align-items-center w-100"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row([
                        # Coluna de Detalhes Específicos (Metrics card) on the left
                        dbc.Col(
                            [
                                html.Div(
                                    id="warehouse-details-container",
                                    className="flex-grow-1 d-flex flex-column",
                                    children=[
                                        html.P(translate("Selecione um armazém na tabela acima para ver os detalhes, indicadores e custos aqui.", lang), className="text-muted small mt-2")
                                    ]
                                )
                            ],
                            width=12, lg=4, className="mb-3 d-flex flex-column"
                        ),
                        # Coluna do Mapa
                        dbc.Col(
                            [
                                html.Div([
                                    dbc.RadioItems(
                                        id="wh-route-type-filter",
                                        className="btn-group btn-group-sm wh-filter-group",
                                        input_class_name="btn-check",
                                        label_class_name="btn btn-outline-primary-custom d-flex align-items-center gap-2",
                                        label_checked_class_name="active btn-primary-custom text-white",
                                        options=[
                                            {"label": translate("Ver Todos", lang), "value": "all"},
                                            {"label": translate("Origem -> Armazém", lang), "value": "inflow"},
                                            {"label": translate("Interhub", lang), "value": "interhub"},
                                            {"label": translate("Armazém -> Cliente Doméstico", lang), "value": "outflow_domestic"},
                                            {"label": translate("Armazém -> Cliente Exportação", lang), "value": "outflow_export"},
                                            {"label": translate("Origem -> Cliente Doméstico", lang), "value": "direct_domestic"},
                                            {"label": translate("Origem -> Cliente Exportação", lang), "value": "direct_export"},
                                        ],
                                        value="all",
                                    )
                                ], className="d-flex justify-content-start mb-3"),
                                dbc.Spinner(
                                    dcc.Graph(
                                        id='graph-results-wh-map',
                                        config={
                                            "displayModeBar": True,
                                            "scrollZoom": True,
                                            "showAxisDragHandles": True,
                                            "modeBarButtonsToAdd": ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape'],
                                            "toImageButtonOptions": {
                                                "format": "png",
                                                "filename": "mapa_de_armazens",
                                                "height": None,
                                                "width": None,
                                                "scale": 1
                                            }
                                        },
                                        style={"height": "600px", "borderRadius": "8px", "overflow": "hidden"}
                                    ),
                                    spinner_class_name="text-primary-custom"
                                )
                            ],
                            width=12, lg=8, className="mb-3"
                        )
                    ])
                ],
                className="card-body-custom"
            ),
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(translate("Estoque por Período", lang), className="me-2 fw-bold"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-results-wh-inventory", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Exibe o estoque do armazém selecionado ao longo dos períodos.", lang),
                                    target="help-results-wh-inventory",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody([
                            dbc.Spinner(
                                dcc.Graph(
                                    id="graph-results-wh-inventory",
                                    style={"height": "350px"}
                                ),
                                spinner_class_name="text-primary-custom"
                            )
                        ], className="card-body-custom")
                    ], className="card-custom mb-3")
                ], width=12)
            ], id="warehouse-inventory-chart-row", className="mt-3 mx-0", style={"display": "none"})
        ],
        className="card-custom mb-3 mt-4"
    )

    # Modal Confirmação Malha (Muitas rotas)
    confirm_all_routes_modal = dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle(translate("Atenção: Processamento Pesado", lang)), close_button=True),
            dbc.ModalBody(
                [
                    html.P(translate("O modelo gerou um número elevado de rotas realizadas (> 150).", lang)),
                    html.P(translate("Desenhar todas essas rotas no mapa simultaneamente pode demorar consideravelmente ou até causar travamentos no seu navegador.", lang), className="text-danger fw-bold"),
                    html.P(translate("É recomendável que você exporte o Relatório Completo (Excel) para salvar os resultados. Você também pode visualizar as rotas individuais no mapa ao selecionar as células correspondentes na tabela.", lang)),
                    html.P(translate("Tem certeza que deseja tentar visualizar todas as rotas de uma só vez?", lang))
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(translate("Cancelar", lang), id="btn-cancel-all-routes", color="none", className="btn-secondary-custom me-2", n_clicks=0),
                    dbc.Button(translate("Sim, carregar todas as rotas", lang), id="btn-confirm-all-routes", color="none", className="btn-danger-custom", n_clicks=0),
                ]
            ),
        ],
        id="modal-confirm-all-routes",
        is_open=False,
    )

    download_report_card = dbc.Card(
        dbc.CardBody(
            dbc.Button(
                [html.I(className="bi bi-download me-2"), translate("Baixar Relatório Completo (.xlsx)", lang)],
                id='btn-download-results',
                n_clicks=0,
                color="none",
                className="btn-success-custom w-100 d-flex align-items-center justify-content-center fw-bold h-100",
                style={"borderRadius": "8px", "fontSize": "17px", "padding": "12px"}
            ),
            className="d-flex align-items-center justify-content-center p-3 h-100"
        ),
        className="shadow-sm border-0 h-100",
        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px", "minHeight": "90px"}
    )

    scenario_selector_card = dbc.Card(
        dbc.CardBody(
            dbc.Row([
                dbc.Col(
                    html.Span(translate("Cenário para Visualização:", lang), className="fw-bold text-primary-custom", style={"fontSize": "17px"}),
                    width=12, md=5, className="d-flex align-items-center justify-content-md-end justify-content-center mb-2 mb-md-0"
                ),
                dbc.Col(
                    dbc.RadioItems(
                        id="radio-results-scenario-select",
                        options=[
                            {"label": translate("Pessimista", lang), "value": "pessimista"},
                            {"label": translate("Esperado", lang), "value": "esperado"},
                            {"label": translate("Otimista", lang), "value": "otimista"}
                        ],
                        value="esperado",
                        inline=True,
                        className="btn-group scenario-selector",
                        inputClassName="btn-check",
                        labelClassName="btn btn-outline-primary-custom d-flex align-items-center justify-content-center",
                        labelCheckedClassName="active btn-primary-custom",
                        style={"display": "flex", "width": "100%", "maxWidth": "500px", "height": "46px", "fontSize": "17px"}
                    ),
                    width=12, md=7, className="d-flex align-items-center justify-content-md-start justify-content-center"
                )
            ], className="align-items-center h-100")
        ),
        className="shadow-sm border-0 h-100",
        style={"backgroundColor": "#f8f9fa", "borderRadius": "12px", "minHeight": "90px"}
    )

    stochastic_scenario_selector = dbc.Col(
        scenario_selector_card,
        id="results-scenario-selector-container",
        width=12, lg=9,
        style={"display": "none"}
    )

    # Layout Principal
    return html.Div([
        dbc.Row([
            dbc.Col(download_report_card, width=12, lg=3),
            stochastic_scenario_selector
        ], className="g-3 mb-24 align-items-stretch"),
        dbc.Row(dbc.Col(kpi_card, width=12)),
        warnings_container,
        dbc.Row(dbc.Col(warehouse_card, width=12, className="mb-24")),
        dbc.Row(dbc.Col(warehouse_map_card, width=12, className="mb-24")),
        dbc.Row([
            dbc.Col(table_card, width=12, className="mb-24")
        ]),
        dbc.Row(dbc.Col(map_card, width=12, className="mb-24")),
        confirm_all_routes_modal
    ])


def get_tab_stochastic_results_layout(lang='pt'):
    # Placeholder card displayed when results are not stochastic or missing
    placeholder_card = dbc.Card(
        dbc.CardBody([
            html.Div([
                html.I(className="bi bi-info-circle-fill text-primary-custom me-2", style={"fontSize": "20px"}),
                html.Span(translate("Comparação de Cenários (Estocástico)", lang), className="fw-bold fs-5")
            ], className="d-flex align-items-center mb-3"),
            html.P(translate("Esta aba exibe a comparação de cenários e o valor da solução estocástica (EVPI/VSS) após a execução do modelo estocástico. Para visualizar estes resultados, ative o Modelo Estocástico na aba de Configuração do Modelo.", lang), className="text-muted mb-0")
        ]),
        id="stochastic-results-placeholder",
        className="card-custom mb-3",
        style={"display": "block"}
    )

    # EVPI/VSS card helper
    evpi_vss_card = dbc.Card([
        dbc.CardHeader(
            html.Div([
                html.Span(translate("Análise de Valor Estocástico", lang), className="me-2 fw-bold"),
                html.I(
                    className="bi bi-question-circle-fill text-muted",
                    id="help-comp-evpi-vss",
                    style={"cursor": "help", "fontSize": "var(--font-size-small)"}
                ),
                dbc.Tooltip(
                    translate("O cálculo do EVPI/VSS pode demorar alguns minutos. Ele ajuda a avaliar o benefício de adotar o modelo estocástico considerando os diferentes cenários e suas incertezas.", lang),
                    target="help-comp-evpi-vss",
                    placement="right"
                ),
            ], className="d-flex align-items-center"),
            className="card-header-custom"
        ),
        dbc.CardBody([
            html.Div([
                dbc.Spinner(
                    html.Div([
                        html.Div([
                          html.H6(translate("EVPI", lang), className="text-muted small text-uppercase mb-1 fw-bold", style={"fontSize": "12px"}),
                          html.H5(id="res-evpi-value", children="R$ -", className="text-info-custom fw-bold mb-0", style={"fontSize": "22px"})
                        ], className="text-center p-3 bg-light rounded border mb-3"),
                        html.Div([
                          html.H6(translate("VSS", lang), className="text-muted small text-uppercase mb-1 fw-bold", style={"fontSize": "12px"}),
                          html.H5(id="res-vss-value", children="R$ -", className="text-success-custom fw-bold mb-0", style={"fontSize": "22px"})
                        ], className="text-center p-3 bg-light rounded border")
                    ]),
                    spinner_class_name="text-primary-custom"
                ),
                
                # Static Explanations and Interpretation Guide
                html.Div([
                    # EVPI section
                    html.Div([
                        html.Div(translate("Valor Esperado da Informação Perfeita (EVPI)", lang), className="fw-bold mb-2 text-primary-custom", style={"fontSize": "18px"}),
                        html.P(translate("O ganho máximo que seria possível obter caso o resultado de cada cenário fosse conhecido antes de qualquer decisão.", lang), className="text-muted mb-2", style={"fontSize": "17px", "lineHeight": "1.4"}),
                        html.Div([
                            html.Div([
                                html.Span(html.I(className="bi bi-arrow-up text-success-custom fs-6 fw-bold"), className="delta-badge-positive me-2 d-inline-flex align-items-center justify-content-center", style={"width": "24px", "height": "24px", "minWidth": "24px", "borderRadius": "50%", "padding": "0"}),
                                html.Span(translate("A incerteza tem grande impacto nos resultados. Melhorar previsões ou reduzir a incerteza pode gerar ganhos significativos.", lang), className="text-muted", style={"fontSize": "16px", "lineHeight": "1.4"})
                            ], className="d-flex align-items-start mb-2"),
                            html.Div([
                                html.Span(html.I(className="bi bi-arrow-down text-danger-custom fs-6 fw-bold"), className="delta-badge-negative me-2 d-inline-flex align-items-center justify-content-center", style={"width": "24px", "height": "24px", "minWidth": "24px", "borderRadius": "50%", "padding": "0"}),
                                html.Span(translate("A incerteza tem pouco impacto. Os resultados são semelhantes independentemente do cenário que ocorrer.", lang), className="text-muted", style={"fontSize": "16px", "lineHeight": "1.4"})
                            ], className="d-flex align-items-start")
                        ], className="mt-2")
                    ], className="p-3 mb-3 rounded border bg-light", style={"borderLeft": "4px solid #003366"}),
                    
                    # VSS section
                    html.Div([
                        html.Div(translate("Valor da Solução Estocástica (VSS)", lang), className="fw-bold mb-2 text-success-custom", style={"fontSize": "18px"}),
                        html.P(translate("O ganho de usar um modelo que considera múltiplos cenários em vez de um modelo que usa apenas o cenário médio.", lang), className="text-muted mb-2", style={"fontSize": "17px", "lineHeight": "1.4"}),
                        html.Div([
                            html.Div([
                                html.Span(html.I(className="bi bi-arrow-up text-success-custom fs-6 fw-bold"), className="delta-badge-positive me-2 d-inline-flex align-items-center justify-content-center", style={"width": "24px", "height": "24px", "minWidth": "24px", "borderRadius": "50%", "padding": "0"}),
                                html.Span(translate("Considerar múltiplos cenários leva a decisões visivelmente melhores. O modelo estocástico agrega valor claro.", lang), className="text-muted", style={"fontSize": "16px", "lineHeight": "1.4"})
                            ], className="d-flex align-items-start mb-2"),
                            html.Div([
                                html.Span(html.I(className="bi bi-arrow-down text-danger-custom fs-6 fw-bold"), className="delta-badge-negative me-2 d-inline-flex align-items-center justify-content-center", style={"width": "24px", "height": "24px", "minWidth": "24px", "borderRadius": "50%", "padding": "0"}),
                                html.Span(translate("O cenário médio é uma aproximação suficiente. Um modelo mais simples chegaria a resultados similares.", lang), className="text-muted", style={"fontSize": "16px", "lineHeight": "1.4"})
                            ], className="d-flex align-items-start")
                        ], className="mt-2")
                    ], className="p-3 mb-3 rounded border bg-light", style={"borderLeft": "4px solid #006633"}),
                    
                    # Relationship section
                    html.Div([
                        html.Div(translate("Relação entre os dois", lang), className="fw-bold mb-2 text-dark", style={"fontSize": "18px"}),
                        html.P(translate("O EVPI é o melhor resultado possível sob qualquer circunstância. O VSS mostra o quão próximo o modelo estocástico chega desse teto.", lang), className="text-muted mb-0", style={"fontSize": "17px", "lineHeight": "1.4"})
                    ], className="p-3 mb-3 rounded border bg-light", style={"borderLeft": "4px solid #7E7E65"}),
                ], className="mt-3 border-top pt-3")
            ], className="d-flex flex-column justify-content-center h-100 gap-3")
        ], className="card-body-custom")
    ], className="card-custom h-100")

    stochastic_results_card = html.Div(
        id="stochastic-results-actual-card",
        style={"display": "none"},
        children=[
            # Section 1: Stochastic Warnings
            html.Div(id="stochastic-warnings-container", className="mb-4"),

            # Section 2: KPI Side-by-Side Cards (9/12 split, next to EVPI/VSS)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(translate("Métricas Comparativas por Cenário", lang), className="me-2 fw-bold"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-comp-kpi-cards", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Compara os KPIs de custo e volume entre os três cenários (Pessimista, Esperado, Otimista). Os badges Δ% indicam a variação percentual em relação ao cenário Esperado (referência).", lang),
                                    target="help-comp-kpi-cards",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody(
                            dbc.Row(id="scenario-kpi-cards-container", className="g-3"),
                            className="card-body-custom"
                        )
                    ], className="card-custom h-100")
                ], width=12, lg=8),
                dbc.Col(evpi_vss_card, width=12, lg=4)
            ], className="g-3 mb-24 align-items-stretch"),

            # Section 3: Grouped Cost Chart (full width)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(translate("Custos Operacionais por Cenário", lang), className="me-2 fw-bold"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-comp-costs-grouped", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Compara cada categoria de custo (Frete, Armazenagem, Abertura, Expansão, Granelização) lado a lado entre os três cenários. Identifique rapidamente qual categoria mais varia entre cenários.", lang),
                                    target="help-comp-costs-grouped",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody(
                            dbc.Spinner(
                                dcc.Graph(id="graph-scenario-costs", style={"height": "350px"}),
                                spinner_class_name="text-primary-custom"
                            ),
                            className="card-body-custom"
                        )
                    ], className="card-custom h-100")
                ], width=12, className="mb-24")
            ], className="align-items-stretch", style={"display": "none"}),

            # Section 4: Inventory Comparison Chart (full width)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(translate("Estoque em Armazéns por Período", lang), className="me-2 fw-bold"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-comp-inventory", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Compara o estoque acumulado em armazéns ao longo dos períodos para todos os cenários simultaneamente. Identifique períodos onde os cenários divergem significativamente em necessidade de armazenagem.", lang),
                                    target="help-comp-inventory",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody([
                            html.Div([
                                dbc.Label(translate("Filtrar Armazéns", lang), className="fw-bold small mb-1 me-2"),
                                dcc.Dropdown(
                                    id="dropdown-scenario-inventory-warehouses",
                                    multi=True,
                                    placeholder=translate("Todos os armazéns", lang),
                                    className="mb-3"
                                )
                            ], style={"maxWidth": "400px"}),
                            dbc.Spinner(
                                dcc.Graph(id="graph-scenario-inventory", style={"height": "380px"}),
                                spinner_class_name="text-primary-custom"
                            )
                        ], className="card-body-custom")
                    ], className="card-custom mb-24")
                ], width=12)
            ]),

            # Section 5: Warehouse Utilization + Decision Differences
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Span(translate("Utilização de Armazéns por Cenário", lang), className="me-2 fw-bold"),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-comp-wh-util", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Mostra a utilização de cada armazém (Saída Total + Estoque Final) comparada à sua Capacidade Efetiva, para cada cenário. A linha de referência indica a capacidade máxima. Barras que se aproximam ou ultrapassam a linha indicam estresse operacional.", lang),
                                    target="help-comp-wh-util",
                                    placement="right"
                                ),
                            ], className="d-flex align-items-center"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody([
                            html.Div([
                                dbc.Label(translate("Filtrar Armazéns", lang), className="fw-bold small mb-1 me-2"),
                                dcc.Dropdown(
                                    id="dropdown-warehouse-utilization-warehouses",
                                    multi=True,
                                    placeholder=translate("Todos os armazéns", lang),
                                    className="mb-3"
                                )
                            ], style={"maxWidth": "400px"}),
                            dbc.Spinner(
                                dcc.Graph(id="graph-warehouse-utilization", style={"height": "430px"}),
                                spinner_class_name="text-primary-custom"
                            )
                        ], className="card-body-custom")
                    ], className="card-custom mb-24")
                ], width=12)
            ]),


            # Section 6: Geographic Warehouse Comparison Map
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(
                            html.Div([
                                html.Div([
                                    html.Span(translate("Comparação Geográfica dos Armazéns", lang), className="me-2 fw-bold"),
                                    html.I(className="bi bi-question-circle-fill text-muted", id="help-comp-network-map", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                    dbc.Tooltip(translate("Exibe a localização geográfica dos armazéns em cada um dos três cenários. O tamanho e a cor dos marcadores variam conforme a métrica selecionada.", lang),
                                        target="help-comp-network-map",
                                        placement="right"
                                    ),
                                ], className="d-flex align-items-center"),
                                html.Div([
                                    dbc.RadioItems(
                                        id="radio-scenario-comparison-variable",
                                        className="btn-group btn-group-sm",
                                        input_class_name="btn-check",
                                        label_class_name="btn btn-outline-primary-custom d-flex align-items-center gap-2",
                                        label_checked_class_name="active btn-primary-custom text-white",
                                        options=[
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Utilização de Capacidade", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-utilization", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Utilização de Capacidade", lang), target="help-radio-utilization", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "utilization"
                                            },
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Saída Total", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-outflow", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Saída Total", lang), target="help-radio-outflow", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "outflow"
                                            },
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Estoque Final", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-final-stock", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Estoque Final", lang), target="help-radio-final-stock", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "final_stock"
                                            },
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Custo de Armazenagem", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-storage-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Custo de Armazenagem", lang), target="help-radio-storage-cost", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "storage_cost"
                                            },
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Capacidade Dinâmica Anual", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-dynamic-capacity", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Capacidade Dinâmica Anual", lang), target="help-radio-dynamic-capacity", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "dynamic_capacity"
                                            },
                                            {
                                                "label": html.Div([
                                                    html.Span(translate("Giro Anual (Turnover)", lang)),
                                                    html.I(className="bi bi-question-circle-fill text-muted ms-1", id="help-radio-turnover", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(translate("Explicação Giro Anual (Turnover)", lang), target="help-radio-turnover", placement="top")
                                                ], className="d-flex align-items-center"),
                                                "value": "turnover"
                                            }
                                        ],
                                        value="utilization",
                                    )
                                ], className="d-flex justify-content-start")
                            ], className="d-flex align-items-center justify-content-start flex-wrap gap-4 w-100"),
                            className="card-header-custom"
                        ),
                        dbc.CardBody([
                            dbc.Row([
                                dbc.Col([
                                    html.Div(translate("Cenário Pessimista", lang), className="fw-bold fs-5 text-center mb-2 text-danger-custom"),
                                    html.Div(
                                        dbc.Spinner(
                                            dcc.Graph(
                                                id="graph-scenario-minimap-pessimista",
                                                style={"height": "400px"},
                                                config={"displayModeBar": True, "scrollZoom": True}
                                            ),
                                            spinner_class_name="text-primary-custom"
                                        ),
                                        className="mini-map-container"
                                    )
                                ], width=12, lg=4),
                                dbc.Col([
                                    html.Div(translate("Cenário Esperado", lang), className="fw-bold fs-5 text-center mb-2 text-primary-custom"),
                                    html.Div(
                                        dbc.Spinner(
                                            dcc.Graph(
                                                id="graph-scenario-minimap-esperado",
                                                style={"height": "400px"},
                                                config={"displayModeBar": True, "scrollZoom": True}
                                            ),
                                            spinner_class_name="text-primary-custom"
                                        ),
                                        className="mini-map-container"
                                    )
                                ], width=12, lg=4),
                                dbc.Col([
                                    html.Div(translate("Cenário Otimista", lang), className="fw-bold fs-5 text-center mb-2 text-success-custom"),
                                    html.Div(
                                        dbc.Spinner(
                                            dcc.Graph(
                                                id="graph-scenario-minimap-otimista",
                                                style={"height": "400px"},
                                                config={"displayModeBar": True, "scrollZoom": True}
                                            ),
                                            spinner_class_name="text-primary-custom"
                                        ),
                                        className="mini-map-container"
                                    )
                                ], width=12, lg=4)
                            ], className="g-3")
                        ], className="card-body-custom")
                    ], className="card-custom mb-24")
                ], width=12)
            ])
        ]
    )

    return html.Div([
        placeholder_card,
        stochastic_results_card
    ])
