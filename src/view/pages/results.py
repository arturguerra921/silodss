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
                    html.Span(translate("Métricas da Operação (Total)", lang), className="me-2"),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
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
                            width=12, lg=2
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
                            width=12, lg=2
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
                            width=12, lg=3
                        ),
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
                            width=12, lg=3
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

    # 2. Tabela de Rotas Realizadas
    table_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Rotas Realizadas", lang), className="me-2"),
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
                    ),
                    html.Div(className="d-flex justify-content-end mt-3", children=[
                        dbc.Button(
                            [html.I(className="bi bi-download me-2"), translate("Baixar Relatório Completo (.xlsx)", lang)],
                            id='btn-download-results',
                            n_clicks=0,
                            color="none", className="btn-success-custom"
                        )
                    ])
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
                    html.Span(translate("Visualização da Rota", lang), className="me-2"),
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
                                html.Div(id="route-details-container", children=[
                                    html.P(translate("Selecione uma rota na tabela ao lado para ver os detalhes e indicadores aqui.", lang), className="text-muted small mt-2")
                                ])
                            ],
                            width=12, lg=4
                        )
                    ])
                ],
                className="card-body-custom"
            )
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

    # Layout Principal
    return html.Div([
        dbc.Row(dbc.Col(kpi_card, width=12)),
        warnings_container,
        dbc.Row([
            dbc.Col(table_card, width=12, className="mb-24")
        ]),
        dbc.Row(dbc.Col(map_card, width=12, className="mb-24")),
        confirm_all_routes_modal
    ])
