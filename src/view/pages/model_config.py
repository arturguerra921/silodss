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
                    dbc.Tooltip(translate("Otimiza a alocação de produtos para os armazéns disponíveis baseando-se na distância e capacidade.", lang),
                        target="help-model-config",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    html.P(translate("Certifique-se de que preencheu os dados em todas as abas anteriores antes de executar.", lang), className="text-muted small mb-3"),

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
                        dbc.Tooltip(translate("Aplica o Princípio de Pareto (Regra 80/20) filtrando apenas as 20% melhores rotas (mais curtas) de cada origem. Isso acelera significativamente o tempo de resolução do modelo matemático. Atenção: se a oferta e a demanda estiverem muito justas, essa restrição pode impedir o modelo de encontrar uma solução ótima, pois rotas alternativas fora das 20% melhores foram descartadas.", lang),
                            target="help-pareto",
                            placement="top"
                        )
                    ], className="mb-4 d-flex align-items-center justify-content-center"),

                    html.Div([
                        dbc.Switch(
                            id="toggle-min-max-capacity",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Adicionar limites de recepção e rota", lang),
                            htmlFor="toggle-min-max-capacity",
                            className="mb-0 mx-2 text-muted cursor-pointer small"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-min-max", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Ative para configurar limites de recepção e limites de rota. Utilizar estes limites pode ajudar a criar soluções mais realistas, mas também pode aumentar consideravelmente o tempo de resolução do modelo.", lang),
                            target="help-min-max",
                            placement="top"
                        )
                    ], className="mb-4 d-flex align-items-center justify-content-center"),

                    # Container for extra options (initially hidden)
                    html.Div(
                        id="container-min-max-options",
                        style={"display": "none"},
                        children=[
                            html.Hr(className="mt-2 mb-3"),

                            html.P([
                                html.I(className="bi bi-info-circle me-1"),
                                translate("Campos deixados em branco (sem valor numérico) não serão considerados no limite. Você não precisa preencher todos.", lang)
                            ], className="text-muted small mb-3 fst-italic", style={"fontSize": "0.8rem"}),

                            html.H6(translate("Limites de Recepção do Armazém", lang), className="fw-bold small text-primary-custom mb-3"),

                            # Linha 1: Recepção Mínima
                            dbc.Row([
                                dbc.Col([
                                    html.Div([
                                        dbc.Label(translate("Recepção mínima diária (ton)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-min-load", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("A soma de todas as rotas chegando em um armazém deve ser pelo menos este valor diariamente. Essa regra só se aplica se o armazém for utilizado.", lang), target="help-min-load")
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-min-load", type="number", min=0, placeholder=translate("Ex: 10", lang), className="mb-4")
                                ], width=6)
                            ]),

                            # Linha 2: Recepção Máxima e Switch
                            dbc.Row([
                                dbc.Col([
                                    html.Div([
                                        dbc.Label(translate("Recepção máxima diária (ton)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-max-load", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("A soma de todas as rotas chegando em um armazém não pode ultrapassar este valor diariamente.", lang), target="help-max-load")
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-max-load", type="number", min=0, placeholder=translate("Ex: 100", lang), className="mb-4")
                                ], width=6),
                                dbc.Col([
                                    # Para o alinhamento perfeito
                                    html.Div([
                                        dbc.Label(translate("Spacer", lang), className="fw-bold small me-2 mb-0", style={"visibility": "hidden"}),
                                        html.I(className="bi bi-question-circle-fill", style={"visibility": "hidden", "fontSize": "var(--font-size-small)"})
                                    ], className="d-flex align-items-center mb-1"),
                                    html.Div([
                                        dbc.Switch(
                                            id="toggle-use-reception",
                                            value=False,
                                            className="custom-switch mb-0 small"
                                        ),
                                        html.Label(translate("Utilizar Cap. de Recepção", lang),
                                            htmlFor="toggle-use-reception",
                                            className="mb-0 mx-2 text-muted cursor-pointer small",
                                            style={"whiteSpace": "nowrap"}
                                        ),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-use-reception", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Se ativado, utiliza a capacidade de recepção (t) dos armazéns cadastrados no banco de dados como recepção máxima diária.", lang),
                                            target="help-use-reception",
                                            placement="top"
                                        )
                                    ], className="d-flex align-items-center mb-4", style={"height": "38px"})
                                ], width=6),
                            ]),

                            # Linha 3: Dias para alocação
                            dbc.Row([
                                dbc.Col([
                                    html.Div([
                                        dbc.Label(translate("Dias para alocação", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-days", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Quantidade de dias que multiplica as recepções (mínima e máxima) do armazém, simulando mais de um dia de operação.", lang), target="help-days")
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-allocation-days", type="number", min=1, placeholder=translate("Ex: 5", lang), className="mb-4")
                                ], width=6)
                            ]),

                            html.Hr(className="mt-2 mb-4"),

                            html.H6(translate("Limites de Rota Individual (Frete)", lang), className="fw-bold small text-primary-custom mb-3"),

                            # Linha 3: Carga mínima e máxima de frete
                            dbc.Row([
                                dbc.Col([
                                    html.Div([
                                        dbc.Label(translate("Carga mínima de frete (ton)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-min-freight", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Valor mínimo que uma rota individual deve transportar. Nenhuma rota terá carga menor que esta. Essa regra se aplica apenas caso a rota seja utilizada. Rotas não escolhidas continuam com carga zero.", lang), target="help-min-freight")
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-min-freight", type="number", min=0, placeholder=translate("Ex: 15", lang), className="mb-4")
                                ], width=6),
                                dbc.Col([
                                    html.Div([
                                        dbc.Label(translate("Carga máxima de frete (ton)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                        html.I(className="bi bi-question-circle-fill text-muted", id="help-max-freight", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                        dbc.Tooltip(translate("Valor máximo que uma rota individual pode transportar. Nenhuma rota terá carga maior que esta.", lang), target="help-max-freight")
                                    ], className="d-flex align-items-center mb-1"),
                                    dbc.Input(id="input-max-freight", type="number", min=0, placeholder=translate("Ex: 50", lang), className="mb-4")
                                ], width=6)
                            ]),

                            html.Hr(className="mt-0 mb-4")
                        ]
                    ),
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
                        dbc.Tooltip(translate("Ativar esta opção incluirá a construção detalhada do modelo matemático (em Python) no log. No entanto, isso pode aumentar significativamente o tempo de resolução. Use esta opção apenas para depuração ou se você quiser entender como o modelo é construído.", lang),
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
                ], width=12, md=8, lg=6, className="mb-24 mx-auto"),
            ],
            className="justify-content-center"
        ),
        loading_modal
    ])
