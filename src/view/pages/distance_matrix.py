from src.logic.i18n import translate
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME

def get_tab_distance_matrix_layout(lang='pt'):
    # Calculation Card
    calc_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Cálculo da Matriz de Distâncias", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-calc-matrix", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Calcula a distância rodoviária real entre cada cidade de origem (Oferta) e cada armazém (Armazéns).", lang),
                        target="help-calc-matrix",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    html.P(translate("Clique no botão abaixo para iniciar o cálculo. Isso pode levar alguns segundos dependendo da quantidade de dados.", lang), className="text-muted small mb-3"),
                    dbc.Button(translate("Calcular Matriz", lang), id="btn-calc-matrix", color="none", className="btn-primary-custom w-100 mb-2"),
                    html.Div(id="calc-status-message", className="text-center small mt-2")
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-3"
    )

    # Export Card
    export_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Exportar Matriz", lang), className="me-2"),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                     dbc.Button(translate("Baixar Planilha (.xlsx)", lang), id="btn-download-matrix", n_clicks=0, color="none", className="btn-success-custom w-100", disabled=True)
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom"
    )

    # Matrix Table Card
    table_card = dbc.Card(
        [
            dbc.CardHeader(translate("Matriz de Distâncias (km)", lang),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Spinner(
                        html.Div(id='table-matrix-container', children=[
                            dash_table.DataTable(
                                id='table-distance-matrix',
                                data=[],
                                columns=[],
                                page_size=5, # Reduced page size to bring map closer
                                style_table={'overflowX': 'auto', 'borderRadius': '8px', 'border': f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                                style_cell={
                                    'textAlign': 'center',
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
                                    'borderBottom': f"2px solid {UNB_THEME['BORDER_LIGHT']}",
                                    'textAlign': 'center'
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
                    html.Div(translate("Clique em uma célula da tabela para visualizar a rota no mapa abaixo.", lang), className="text-muted small mt-2")
                ],
                className="card-body-custom d-flex flex-column"
            ),
        ],
        className="card-custom mb-3", # Removed h-100 and minHeight to shrink to fit content
    )

    # Map Card
    map_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Visualização da Rota", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-route-map", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Clique na tabela acima para visualizar a rota desejada. Apenas é possível visualizar uma rota de cada vez. Nos casos em que a rota for exibida como uma linha reta vermelha, isso indica que a rota real não pôde ser calculada, possivelmente devido ao ponto estar fora do Brasil ou em área isolada sem estradas em um raio de 50 km. Nesses casos, a distância exibida na tabela é a distância geodésica (linha reta) entre os pontos, e não a distância rodoviária real.", lang),
                        target="help-route-map",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dcc.Graph(
                        id="graph-route-map",
                        style={"height": "600px"}, # Increased height for better view
                        config={
                            "displayModeBar": True,
                            "scrollZoom": True,
                            "showAxisDragHandles": True,
                            "modeBarButtonsToAdd": ['drawline', 'drawopenpath', 'drawclosedpath', 'drawcircle', 'drawrect', 'eraseshape'],
                            "toImageButtonOptions": {
                                "format": "png",
                                "filename": "mapa_matriz_distancia",
                                "height": None,
                                "width": None,
                                "scale": 1
                            }
                        }
                    )
                ],
                className="card-body-custom"
            )
        ],
        className="card-custom mb-3"
    )

    return html.Div([
        dbc.Row(
            [
                dbc.Col([
                    calc_card,
                    export_card
                ], width=12, lg=3, className="mb-24"),
                dbc.Col([
                    table_card,
                    map_card
                ], width=12, lg=9, className="mb-24"),
            ]
        ),
    ])
