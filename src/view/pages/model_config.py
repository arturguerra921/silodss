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
                    html.P(translate("Certifique-se de que preencheu os dados em todas as abas anteriores antes de executar.", lang), className="text-muted small mb-4"),

                    # Seleção de tipo de modelo
                    html.Div([
                        html.Div([
                            dbc.Label(translate("Tipo de Modelo", lang), className="fw-bold small mb-0 me-2", style={"color": "#9ca3af"}),
                            html.I(className="bi bi-question-circle-fill text-muted", id="help-model-type", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                            dbc.Tooltip(
                                translate("O modelo Determinístico otimiza a rede utilizando apenas o cenário esperado (valores nominais da previsão/dados). O modelo Estocástico otimiza as decisões considerando simultaneamente os cenários Pessimista, Esperado e Otimista ponderados por suas probabilidades, gerando uma solução robusta contra incertezas.", lang),
                                target="help-model-type",
                                placement="top"
                            )
                        ], className="d-flex align-items-center mb-2"),
                        dbc.RadioItems(
                            id="radio-model-type",
                            options=[
                                {"label": translate("Determinístico", lang), "value": "deterministic"},
                                {"label": translate("Estocástico", lang), "value": "stochastic"}
                            ],
                            value="deterministic",
                            inline=True,
                            className="mb-4"
                        )
                    ]),

                    # Configurações Estocásticas
                    dbc.Collapse(
                        id="collapse-stochastic-fields",
                        is_open=False,
                        children=[
                            dbc.Card(
                                dbc.CardBody([
                                    html.H6(translate("Configuração Estocástica", lang), className="fw-bold small text-primary-custom mb-3"),
                                    
                                    # Probabilidades
                                    html.Div([
                                        dbc.Label(translate("Probabilidades dos Cenários (Soma deve ser 1.0)", lang), className="fw-bold small mb-2", style={"color": "#9ca3af"}),
                                        dbc.Row([
                                            dbc.Col([
                                                html.Div([
                                                    dbc.Label(translate("Pessimista", lang), className="small text-muted mb-1 me-1"),
                                                    html.I(className="bi bi-question-circle-fill text-muted", id="help-prob-pessimista", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(
                                                        translate("Cenário desfavorável: reduz a oferta (por 1 - WMAPE) e aumenta a demanda (por 1 + WMAPE) para simular escassez de produto e alto estresse na rede.", lang),
                                                        target="help-prob-pessimista",
                                                        placement="top"
                                                    )
                                                ], className="d-flex align-items-center mb-1"),
                                                dbc.Input(id="input-prob-pessimista", type="number", min=0, max=1, step=0.01, placeholder="Ex: 0.33", value=0.33)
                                            ], width=4),
                                            dbc.Col([
                                                html.Div([
                                                    dbc.Label(translate("Esperado", lang), className="small text-muted mb-1 me-1"),
                                                    html.I(className="bi bi-question-circle-fill text-muted", id="help-prob-esperado", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(
                                                        translate("Cenário nominal: utiliza os valores originais da oferta e da demanda conforme a previsão ou dados informados, sem alterações.", lang),
                                                        target="help-prob-esperado",
                                                        placement="top"
                                                    )
                                                ], className="d-flex align-items-center mb-1"),
                                                dbc.Input(id="input-prob-esperado", type="number", min=0, max=1, step=0.01, placeholder="Ex: 0.34", value=0.34)
                                            ], width=4),
                                            dbc.Col([
                                                html.Div([
                                                    dbc.Label(translate("Otimista", lang), className="small text-muted mb-1 me-1"),
                                                    html.I(className="bi bi-question-circle-fill text-muted", id="help-prob-otimista", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                                    dbc.Tooltip(
                                                        translate("Cenário favorável: aumenta a oferta (por 1 + WMAPE) e reduz a demanda (por 1 - WMAPE) para simular abundância de produto e baixa pressão na rede.", lang),
                                                        target="help-prob-otimista",
                                                        placement="top"
                                                    )
                                                ], className="d-flex align-items-center mb-1"),
                                                dbc.Input(id="input-prob-otimista", type="number", min=0, max=1, step=0.01, placeholder="Ex: 0.33", value=0.33)
                                            ], width=4)
                                        ]),
                                        html.Div(id="prob-validation-text", className="small mt-2 fw-bold")
                                    ], className="mb-4"),
                                    
                                    # Fonte de Erro
                                    html.Div([
                                        html.Div([
                                            dbc.Label(translate("Fonte de Erro (WMAPE)", lang), className="fw-bold small mb-0 me-2", style={"color": "#9ca3af"}),
                                            html.I(className="bi bi-question-circle-fill text-muted", id="help-error-source", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                            dbc.Tooltip(
                                                translate("Define a origem da margem de erro (WMAPE) usada para calcular os cenários. 'Usar Métricas da Previsão' obtém o erro calculado no modelo de previsão para cada localidade/produto. 'Inserir Manualmente' aplica um percentual fixo global.", lang),
                                                target="help-error-source",
                                                placement="top"
                                            )
                                        ], className="d-flex align-items-center mb-2"),
                                        dbc.RadioItems(
                                            id="radio-error-source",
                                            options=[
                                                {"label": translate("Usar Métricas da Previsão (WMAPE)", lang), "value": "prediction"},
                                                {"label": translate("Inserir Manualmente", lang), "value": "manual"}
                                            ],
                                            value="prediction",
                                            inline=True,
                                            className="mb-3"
                                        )
                                    ]),
                                    
                                    # Erros Manuais
                                    dbc.Collapse(
                                        id="collapse-manual-error",
                                        is_open=False,
                                        children=[
                                            dbc.Row([
                                                dbc.Col([
                                                    dbc.Label(translate("Erro da oferta (%)", lang), className="small text-muted mb-1"),
                                                    dbc.Input(id="input-supply-error-pct", type="number", min=0, max=100, step=0.1, placeholder="Ex: 15.0", value=15.0)
                                                ], width=6),
                                                dbc.Col([
                                                    dbc.Label(translate("Erro da demanda (%)", lang), className="small text-muted mb-1"),
                                                    dbc.Input(id="input-demand-error-pct", type="number", min=0, max=100, step=0.1, placeholder="Ex: 15.0", value=15.0)
                                                ], width=6)
                                            ], className="mb-3")
                                        ]
                                    ),
                                    
                                    # Status da previsão
                                    html.Div(id="prediction-status-container", className="mt-3")
                                ]),
                                className="mb-4 bg-transparent border-secondary"
                            )
                        ]
                    ),

                    # Principal toggles
                    html.Div([
                        dbc.Switch(
                            id="toggle-pareto-routes",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Utilizar Princípio de Pareto (20% melhores rotas)", lang),
                            htmlFor="toggle-pareto-routes",
                            className="mb-0 mx-2 fw-bold small text-primary-custom cursor-pointer"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-pareto", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Aplica o Princípio de Pareto (Regra 80/20) filtrando apenas as 20% melhores rotas (mais curtas) de cada origem. Isso acelera significativamente o tempo de resolução do modelo matemático. Atenção: Não recomendado para instâncias pequenas (com poucos nós), pois a redução de rotas pode causar inviabilidade na rede e ativar variáveis de penalidade (big-M).", lang),
                            target="help-pareto",
                            placement="top"
                        )
                    ], className="mb-4 d-flex align-items-center"),

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
                                dbc.Label(translate("Fator interhub (α)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-interhub-factor", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator aplicado aos custos de frete no transporte entre armazéns (interhub). Se menor que 1, representa um desconto; se maior que 1, uma penalidade.", lang), target="help-interhub-factor")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-interhub-factor", type="number", min=0, step=0.01, placeholder=translate("Ex: 1.00", lang), className="mb-4")
                        ], width=6)
                    ]),
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Solver", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-solver-name", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Selecione o solver de otimização a ser utilizado.", lang), target="help-solver-name")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Select(
                                id="dropdown-solver-name",
                                options=[
                                    {"label": "CBC (Default)", "value": "cbc"},
                                    {"label": "Gurobi", "value": "gurobi"}
                                ],
                                value="cbc",
                                className="mb-4"
                            )
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                html.Div([
                                    dbc.Label(translate("Licença Gurobi (.lic)", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                    html.I(className="bi bi-question-circle-fill text-muted", id="help-gurobi-lic", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                    dbc.Tooltip(translate("Faça o upload do arquivo de licença gurobi.lic para executar o Gurobi localmente.", lang), target="help-gurobi-lic")
                                ], className="d-flex align-items-center mb-1"),
                                dcc.Upload(
                                    id="upload-gurobi-lic",
                                    children=html.Button(
                                        translate("Fazer upload da licença", lang),
                                        id="btn-upload-gurobi-lic",
                                        className="btn-none btn-outline-secondary btn-sm small w-100",
                                        style={"border": "1px dashed #ced4da", "height": "38px", "borderRadius": "0.375rem"}
                                    ),
                                    multiple=False,
                                    className="mb-1"
                                ),
                                html.Div(id="gurobi-lic-status", className="small")
                            ], id="gurobi-lic-upload-container", style={"display": "none"})
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
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Razão de Capacidade de Recepção", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-ratio-expand-rec", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator percentual que converte a capacidade estática inicial (para candidatos) ou a capacidade expandida em capacidade de recepção diária.", lang), target="help-ratio-expand-rec")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-ratio-expand-rec", type="number", min=0, max=1, step=0.01, placeholder=translate("Ex: 0.10", lang), className="mb-4")
                        ], width=6),
                        dbc.Col([
                            html.Div([
                                dbc.Label(translate("Razão de Capacidade de Expedição", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
                                html.I(className="bi bi-question-circle-fill text-muted", id="help-ratio-expand-ship", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                                dbc.Tooltip(translate("Fator percentual que converte a capacidade estática inicial (para candidatos) ou a capacidade expandida em capacidade de expedição diária.", lang), target="help-ratio-expand-ship")
                            ], className="d-flex align-items-center mb-1"),
                            dbc.Input(id="input-ratio-expand-ship", type="number", min=0, max=1, step=0.01, placeholder=translate("Ex: 0.10", lang), className="mb-4")
                        ], width=6)
                    ]),

                    html.Hr(className="my-4"),

                    # Group 2: Physical Expansion Parameters
                    html.Div([
                        dbc.Switch(
                            id="toggle-expansion-enabled",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Habilitar Expansão Física", lang),
                            htmlFor="toggle-expansion-enabled",
                            className="mb-0 mx-2 fw-bold small text-primary-custom cursor-pointer"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-expansion-enabled", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Permite ao modelo matemático optar pela expansão da capacidade estática de armazenamento nos armazéns, com acréscimo proporcional das capacidades de recepção e expedição.", lang),
                            target="help-expansion-enabled",
                            placement="top"
                        )
                    ], className="mb-3 d-flex align-items-center"),
                    
                    dbc.Collapse(
                        id="collapse-expansion-fields",
                        is_open=False,
                        children=[
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
                            ])
                        ]
                    ),

                    html.Hr(className="my-4"),

                    # Group 3: Bulkification Parameters
                    html.Div([
                        dbc.Switch(
                            id="toggle-bulk-enabled",
                            value=False,
                            className="custom-switch mb-0 small"
                        ),
                        html.Label(translate("Habilitar Granelização", lang),
                            htmlFor="toggle-bulk-enabled",
                            className="mb-0 mx-2 fw-bold small text-primary-custom cursor-pointer"
                        ),
                        html.I(className="bi bi-question-circle-fill text-muted", id="help-bulk-enabled", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                        dbc.Tooltip(translate("Permite ao modelo matemático modernizar armazéns para granelização, aumentando as capacidades diárias de recepção e expedição.", lang),
                            target="help-bulk-enabled",
                            placement="top"
                        )
                    ], className="mb-3 d-flex align-items-center"),

                    dbc.Collapse(
                        id="collapse-bulk-fields",
                        is_open=False,
                        children=[
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
                                        dbc.Label(translate("Custo var. de granelização ($/(t · dia))", lang), className="fw-bold small me-2 mb-0", style={"color": "#9ca3af"}),
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
                            ])
                        ]
                    ),

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
                    ], className="mb-4 d-flex align-items-center"),
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
                            
                            # Real-time log viewer container
                            html.Div(
                                [
                                    html.Pre(
                                        id="model-running-log-text",
                                        style={
                                            "maxHeight": "240px",
                                            "overflowY": "auto",
                                            "backgroundColor": "#1e1e1e",
                                            "color": "#d4d4d4",
                                            "padding": "16px",
                                            "borderRadius": "8px",
                                            "fontSize": "12px",
                                            "fontFamily": "Courier New, monospace",
                                            "textAlign": "left",
                                            "width": "100%",
                                            "margin": "16px 0 0 0",
                                            "whiteSpace": "pre-wrap",
                                            "wordBreak": "break-all"
                                        }
                                    )
                                ],
                                className="w-100",
                                id="model-running-log-container",
                                style={"display": "none"}
                            ),
                            
                            # Interval for polling log updates (polls every 3 seconds)
                            dcc.Interval(
                                id="interval-model-log",
                                interval=3000,
                                n_intervals=0,
                                disabled=True
                            ),
                            
                            dbc.Button(translate("Interromper Modelo", lang), id="btn-cancel-model", color="none", className="btn-danger-custom mt-4 w-50", disabled=True)
                        ],
                        className="d-flex flex-column align-items-center justify-content-center p-4"
                    )
                ]
            )
        ],
        id="modal-model-running",
        is_open=False,
        backdrop="static", # Prevent closing by clicking outside
        keyboard=False, # Prevent closing with ESC key
        centered=True,
        size="lg"
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
