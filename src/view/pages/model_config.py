from src.logic.i18n import translate
from dash import html, dcc
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME

def get_tab_model_config_layout(lang='pt'):
    # Card Config
    config_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Execução do Modelo Matemático", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-model-config", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Otimiza a alocação de produtos para os armazéns disponíveis baseando-se na distância, capacidades, expansão e granelização.", lang),
                        target="help-model-config",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    html.P(translate("Certifique-se de que preencheu os dados em todas as abas anteriores (Oferta, Armazéns, Relação Produto x Armazém, Demanda, Matriz de Distâncias) antes de executar.", lang), className="text-muted small mb-4"),

                    # Principal toggles
                    html.Div([
                        dbc.Switch(
                            id="toggle-pareto-routes",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Utilizar Princípio de Pareto (20% melhores rotas)", lang),
                            htmlFor="toggle-pareto-routes",
                            className="mb-0 mx-2 text-muted cursor-pointer small"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-pareto", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Aplica o Princípio de Pareto (Regra 80/20) filtrando apenas as 20% melhores rotas (mais curtas) de cada origem. Isso acelera significativamente o tempo de resolução do modelo matemático.", lang),
                            target="help-pareto",
                            placement="top"
                        )
                    ], className="mb-4 d-flex align-items-center justify-content-center"),

                    html.Hr(className="my-4"),

                    # Group 1: General Parameters
                    html.H6(translate("Parâmetros Gerais", lang), className="fw-bold small text-primary-custom mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Dias operacionais por período", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-days", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Quantidade de dias que multiplica as recepções (mínima e máxima) do armazém, simulando mais de um dia de operação por período.", lang), target="help-days")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-allocation-days", type="number", min=1, placeholder=translate("Ex: 22", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Desconto de transbordo (α)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-transshipment-discount", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator de desconto aplicado aos custos de frete no transporte entre armazéns (transbordo).", lang), target="help-transshipment-discount")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-transshipment-discount", type="number", min=0, max=1, step=0.01, placeholder=translate("Ex: 0.85", lang), className="mb-4")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Gap do solver (%)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-solver-gap", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Tolerância de gap de otimalidade para o solver de programação inteira mista.", lang), target="help-solver-gap")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-solver-gap", type="number", min=0, max=100, step=0.1, placeholder=translate("Ex: 1.0", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Tempo limite do solver (s)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-solver-time-limit", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Tempo máximo de execução permitido para o solver (em segundos).", lang), target="help-solver-time-limit")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-solver-time-limit", type="number", min=1, placeholder=translate("Ex: 1200", lang), className="mb-4")
                        ], width=6)
                    ]),

                    html.Hr(className="my-4"),

                    # Group 2: Physical Expansion Parameters
                    html.H6(translate("Parâmetros de Expansão Física", lang), className="fw-bold small text-primary-custom mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Fator β^rec (recepção)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-ratio-expand-rec", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator percentual que converte a capacidade estática expandida em capacidade de recepção diária.", lang), target="help-ratio-expand-rec")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-ratio-expand-rec", type="number", min=0, max=1, step=0.01, placeholder=translate("Ex: 0.10", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Fator β^ship (expedição)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-ratio-expand-ship", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator percentual que converte a capacidade estática expandida em capacidade de expedição diária.", lang), target="help-ratio-expand-ship")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-ratio-expand-ship", type="number", min=0, max=1, step=0.01, placeholder=translate("Ex: 0.10", lang), className="mb-4")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Expansão máxima (t)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-max-expand-capacity", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Limite máximo de capacidade estática expandida permitida por armazém.", lang), target="help-max-expand-capacity")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-max-expand-capacity", type="number", min=0, placeholder=translate("Ex: 5000", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Custo fixo de expansão ($)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-expand-fixed-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Custo de capital fixo para iniciar o projeto de expansão física do armazém.", lang), target="help-expand-fixed-cost")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-expand-fixed-cost", type="number", min=0, placeholder=translate("Ex: 50000", lang), className="mb-4")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Custo variável de expansão ($/t)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-expand-var-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Custo de investimento por tonelada de capacidade estática expandida.", lang), target="help-expand-var-cost")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-expand-var-cost", type="number", min=0, placeholder=translate("Ex: 100", lang), className="mb-4")
                        ], width=6)
                    ]),

                    html.Hr(className="my-4"),

                    # Group 3: Bulkification Parameters
                    html.H6(translate("Parâmetros de Granelização", lang), className="fw-bold small text-primary-custom mb-3"),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Granelização máxima (t/dia)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-max-bulk-capacity", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Limite máximo de capacidade de recebimento/expedição adicionada por meio de granelização.", lang), target="help-max-bulk-capacity")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-max-bulk-capacity", type="number", min=0, placeholder=translate("Ex: 500", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Custo fixo de granelização ($)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-bulk-fixed-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Custo de capital fixo para iniciar o projeto de granelização no armazém.", lang), target="help-bulk-fixed-cost")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-bulk-fixed-cost", type="number", min=0, placeholder=translate("Ex: 30000", lang), className="mb-4")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Custo var. de granelização ($/(t/dia))", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-bulk-var-cost", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Custo de investimento por unidade de capacidade de movimentação diária adicionada.", lang), target="help-bulk-var-cost")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-bulk-var-cost", type="number", min=0, placeholder=translate("Ex: 200", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Tipos elegíveis para granelização", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-bulk-eligible-types", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Selecione quais tipos de armazém podem sofrer o processo de granelização.", lang), target="help-bulk-eligible-types")
                            ], className="d-flex align-items-center mb-1"),
                            dcc.Dropdown(id="input-bulk-eligible-types", multi=True, placeholder=translate("Selecione os tipos...", lang), className="mb-4")
                        ], width=6)
                    ]),

                    html.Hr(className="my-4"),

                    # Detailed log toggle and execution buttons
                    html.Div([
                        dbc.Switch(
                            id="toggle-detailed-log",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Detalhar log do modelo", lang),
                            htmlFor="toggle-detailed-log",
                            className="mb-0 mx-2 text-muted cursor-pointer small"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-detailed-log", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Ativar esta opção incluirá a construção detalhada do modelo matemático (em Python) no log. No entanto, isso pode aumentar significativamente o tempo de resolução.", lang),
                            target="help-detailed-log",
                            placement="top"
                        )
                    ], className="mb-4 d-flex align-items-center justify-content-center"),
                    dbc.Button(translate("Rodar Modelo", lang), id="btn-run-model", className="btn-primary-custom w-100 mb-3"),
                    dbc.Button(translate("Baixar Log de Execução (.txt)", lang), id="btn-download-log", n_clicks=0, className="btn-outline-secondary-custom w-100 mb-3", disabled=True),
                    html.Div(id="model-output-text", className="mt-3 text-center")
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-3"
    )

    # Loading Modal
    loading_modal = dbc.Modal(
        [
            dbc.ModalBody(
                [
                    html.Div(
                        [
                            dbc.Spinner(spinner_class_name="text-primary-custom", spinner_style={"width": "3rem", "height": "3rem"}),
                            html.H5(translate("Otimizando alocação...", lang), className="mt-4"),
                            html.P(translate("Isso pode levar alguns minutos. Por favor, aguarde.", lang), className="text-muted text-center mt-2"),
                            dbc.Button(translate("Interromper Modelo", lang), id="btn-cancel-model", color="none", className="btn-danger-custom mt-4 w-50", disabled=True)
                        ],
                        className="d-flex flex-column align-items-center justify-content-center p-5"
                    )
                ]
            )
        ],
        id="modal-model-running",
        is_open=False,
        backdrop="static", # Prevent closing by clicking outside
        keyboard=False, # Prevent closing with ESC key
        centered=True,
    )

    return html.Div([
        dbc.Row(
            [
                dbc.Col([
                    config_card
                ], width=12, md=10, lg=8, className="mb-24 mx-auto"),
            ],
            className="justify-content-center"
        ),
        loading_modal
    ])
