from src.logic.i18n import translate
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME

def get_tab_prediction_layout(lang='pt'):
  # Configuration Card
  config_card = dbc.Card(
    [
      dbc.CardHeader(
        html.Div([
          html.Span(translate("Modelagem Preditiva", lang), className="me-2"),
          html.I(className="bi bi-question-circle-fill text-muted", id="help-prediction-config", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
          dbc.Tooltip(translate("Configure os parâmetros do modelo e execute a previsão.", lang),
            target="help-prediction-config",
            placement="right"
          ),
        ], className="d-flex align-items-center"),
        className="card-header-custom"
      ),
      dbc.CardBody(
        [
          # Model Selector
          html.Div([
            dbc.Label(translate("Modelo", lang), className="fw-bold small mb-1"),
            dcc.Dropdown(
              id="prediction-model-select",
              options=[
                {"label": "SARIMA (Estatístico)", "value": "sarima"},
                {"label": "Prophet (Estatístico)", "value": "prophet"},
                {"label": "XGBoost (Machine Learning)", "value": "xgboost"},
                {"label": "LSTM (Neural Network)", "value": "lstm"}
              ],
              value="sarima",
              clearable=False,
              className="mb-16"
            )
          ]),

          # Test Split Size and Horizon
          dbc.Row([
            dbc.Col([
              dbc.Label(translate("Tamanho do Teste (Meses)", lang), className="fw-bold small mb-1"),
              dbc.Input(id="prediction-test-size", type="number", min=0, value=12, className="mb-16")
            ], width=6),
            dbc.Col([
              dbc.Label(translate("Horizonte (Meses)", lang), className="fw-bold small mb-1"),
              dbc.Input(id="prediction-horizon", type="number", min=1, value=12, className="mb-16")
            ], width=6)
          ], className="g-2"),

          # Action Buttons
          html.Div(className="d-grid gap-2 mt-2 mb-24", children=[
            dbc.Button(translate("Executar Previsão", lang),
              id="btn-run-forecast",
              color="none", className="btn-primary-custom w-100"
            ),
            dbc.Button(translate("Cancelar Previsão", lang),
              id="btn-cancel-forecast",
              color="none", className="btn-danger-custom w-100",
              disabled=True
            ),
            dbc.Button(translate("Exportar Resultados", lang),
              id="btn-download-forecast",
              color="none", className="btn-outline-secondary-custom w-100",
              disabled=True
            )
          ]),

          html.Hr(className="my-3"),
          
          # Visualization Filters
          html.Div(translate("Visualização", lang), className="fw-bold small mb-12 text-uppercase text-muted"),

          # Series Type Selector
          html.Div([
            dbc.Label(translate("Série", lang), className="fw-bold small mb-1"),
            dcc.Dropdown(
              id="prediction-series-type",
              options=[
                {"label": translate("Oferta", lang), "value": "supply"},
                {"label": translate("Demanda", lang), "value": "demand"}
              ],
              placeholder=translate("Aguardando previsão", lang),
              clearable=False,
              disabled=True,
              className="mb-16"
            )
          ]),

          # Product Dropdown
          html.Div([
            dbc.Label(translate("Produto", lang), className="fw-bold small mb-1"),
            dcc.Dropdown(
              id="prediction-product-dropdown",
              placeholder=translate("Aguardando previsão", lang),
              clearable=False,
              disabled=True,
              className="mb-16"
            )
          ]),

          # City Dropdown
          html.Div([
            dbc.Label(translate("Cidade", lang), className="fw-bold small mb-1"),
            dcc.Dropdown(
              id="prediction-city-dropdown",
              placeholder=translate("Aguardando previsão", lang),
              clearable=False,
              disabled=True,
              className="mb-16"
            )
          ])
        ],
        className="card-body-custom"
      ),
    ],
    className="card-custom h-100"
  )

  # KPI section
  kpis_section = dbc.Row(
    [
      dbc.Col(
        dbc.Card(
          dbc.CardBody([
            html.Div([
              html.I(className="bi bi-graph-up fs-2 me-3", style={"color": UNB_THEME['UNB_BLUE']}),
              html.Div([
                html.H6(translate("MAPE (%)", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                html.H3(id="prediction-kpi-mape", children="-", className="mb-0", style={"color": UNB_THEME['UNB_BLUE']})
              ])
            ], className="d-flex align-items-center py-1")
          ], className="p-3"),
          className="shadow-sm border-0 h-100",
          style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
        ),
        width=12, sm=3
      ),
      dbc.Col(
        dbc.Card(
          dbc.CardBody([
            html.Div([
              html.I(className="bi bi-calculator fs-2 me-3", style={"color": UNB_THEME['UNB_GREEN']}),
              html.Div([
                html.H6(translate("RMSE", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                html.H3(id="prediction-kpi-rmse", children="-", className="mb-0", style={"color": UNB_THEME['UNB_GREEN']})
              ])
            ], className="d-flex align-items-center py-1")
          ], className="p-3"),
          className="shadow-sm border-0 h-100",
          style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
        ),
        width=12, sm=3
      ),
      dbc.Col(
        dbc.Card(
          dbc.CardBody([
            html.Div([
              html.I(className="bi bi-activity fs-2 me-3", style={"color": UNB_THEME['UNB_BLUE_MED']}),
              html.Div([
                html.H6(translate("MAE", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                html.H3(id="prediction-kpi-mae", children="-", className="mb-0", style={"color": UNB_THEME['UNB_BLUE_MED']})
              ])
            ], className="d-flex align-items-center py-1")
          ], className="p-3"),
          className="shadow-sm border-0 h-100",
          style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
        ),
        width=12, sm=3
      ),
      dbc.Col(
        dbc.Card(
          dbc.CardBody([
            html.Div([
              html.I(className="bi bi-award fs-2 me-3", id="prediction-kpi-badge-icon", style={"color": UNB_THEME['UNB_GRAY_DARK']}),
              html.Div([
                html.H6(translate("Indicador de Qualidade", lang), className="text-muted small text-uppercase fw-bold mb-1"),
                html.Div(id="prediction-kpi-quality-container", children="-", className="h4 mb-0 fw-bold")
              ])
            ], className="d-flex align-items-center py-1")
          ], className="p-3"),
          className="shadow-sm border-0 h-100",
          style={"backgroundColor": "#f8f9fa", "borderRadius": "12px"}
        ),
        width=12, sm=3
      )
    ],
    className="g-3 mb-24"
  )

  # Graph and tabs card
  results_card = dbc.Card(
    [
      dbc.CardHeader(
        html.Div([
          html.Span(translate("Série Histórica e Previsão Futura", lang), className="me-2"),
          html.I(className="bi bi-question-circle-fill text-muted", id="help-prediction-results", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
          dbc.Tooltip(translate("Visualize os resultados e resíduos nos gráficos abaixo.", lang),
            target="help-prediction-results",
            placement="right"
          ),
        ], className="d-flex align-items-center"),
        className="card-header-custom"
      ),
      dbc.CardBody(
        [
          kpis_section,
          
          dbc.Tabs([
            dbc.Tab(
              label=translate("Previsão", lang),
              tab_id="pred-tab-plot",
              children=[
                html.Div(id="prediction-chart-container", children=[
                  dcc.Graph(
                    id="prediction-graph-forecast",
                    style={"borderRadius": "8px", "border": f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                    className="mt-24 mb-16"
                  )
                ])
              ]
            ),
            dbc.Tab(
              label=translate("Análise de Resíduos", lang),
              tab_id="pred-tab-residuals",
              children=[
                dbc.Row([
                  dbc.Col([
                    dcc.Graph(
                      id="prediction-graph-residuals-time",
                      style={"borderRadius": "8px", "border": f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                      className="mt-24 mb-16"
                    )
                  ], width=12, lg=6),
                  dbc.Col([
                    dcc.Graph(
                      id="prediction-graph-residuals-hist",
                      style={"borderRadius": "8px", "border": f"1px solid {UNB_THEME['BORDER_LIGHT']}"},
                      className="mt-24 mb-16"
                    )
                  ], width=12, lg=6)
                ])
              ]
            ),
            dbc.Tab(
              label=translate("Parâmetros do Modelo", lang),
              tab_id="pred-tab-params",
              children=[
                html.Div([
                  html.H6(translate("Parâmetros do Modelo", lang), className="fw-bold small mt-24 mb-12"),
                  html.Pre(
                    id="prediction-model-parameters",
                    className="p-3 bg-light border rounded",
                    style={"whiteSpace": "pre-wrap", "fontSize": "var(--font-size-small)"}
                  )
                ])
              ]
            )
          ], id="prediction-results-tabs", active_tab="pred-tab-plot")
        ],
        className="card-body-custom d-flex flex-column"
      )
    ],
    className="card-custom h-100",
    style={"minHeight": "600px"}
  )

  # Status display div
  status_output = html.Div(id="prediction-output-text", className="mt-3 text-center")

  # Main layout row
  return html.Div([
    dbc.Row(
      [
        dbc.Col([
          config_card
        ], width=12, lg=3, className="mb-24"),

        dbc.Col([
          results_card,
          status_output
        ], width=12, lg=9, className="mb-24")
      ]
    )
  ])
