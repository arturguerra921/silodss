import os
import io
import base64
import pandas as pd
from src.logic.i18n import translate
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from src.view.theme import UNB_THEME

def get_tab_costs_layout(lang='pt'):
    # Card 1: Manage Storage Tariff
    storage_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Tarifa de Armazenagem", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-storage-costs", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Valores para armazenamento de cada produto. O sistema buscará o nome exato do produto (ignorando acentos e maiúsculas/minúsculas). Caso não encontre, utilizará a tarifa da linha 'Outros'. A linha 'Outros' é obrigatória e será criada automaticamente com valor 50 caso não exista em um novo arquivo. Atualizações na tabela serão salvas automaticamente.", lang),
                        target="help-storage-costs",
                        placement="right",
                        style={"maxWidth": "400px"}
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Button(translate("Adicionar Linha", lang), id="btn-add-storage-row", color="none", className="btn-primary-custom w-100 mb-2"),
                                    dcc.Upload(
                                        id='upload-storage-csv',
                                        children=html.Div([
                                            html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                                            html.Span(translate('Arraste e solte ou ', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                                            html.A(translate('Selecione', lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                            html.Div(translate("Formatos: .csv, .xlsx", lang), className="text-muted small mt-2")
                                        ]),
                                        className="upload-box mb-3",
                                        multiple=False,
                                        accept='.csv, .xlsx'
                                    ),
                                    dbc.Button(translate("Baixar Planilha (.xlsx)", lang), id="btn-download-storage", n_clicks=0, color="none", className="btn-success-custom w-100 mb-2")
                                ],
                                width=12, lg=3, className="mb-3 mb-lg-0"
                            ),
                            dbc.Col(
                                [
                                    dbc.Spinner(
                                        html.Div(id='table-storage-container', children=[
                                            dash_table.DataTable(
                                                id='table-costs-storage',
                                                data=[],
                                                columns=[
                                                    {'name': translate('Produto', lang), 'id': 'Produto'},
                                                    {'name': translate('Armazenar Público', lang), 'id': 'Armazenar_Publico'},
                                                    {'name': translate('Armazenar Privado', lang), 'id': 'Armazenar_Privado'}
                                                ],
                                                editable=True,
                                                row_deletable=True,
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
                                ],
                                width=12, lg=9
                            )
                        ]
                    )
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom mb-4"
    )

    # Card 2: Manage Freight Cost
    freight_card = dbc.Card(
        [
            dbc.CardHeader(
                html.Div([
                    html.Span(translate("Valor do Frete", lang), className="me-2"),
                    html.I(className="bi bi-question-circle-fill text-muted", id="help-freight-costs", style={"cursor": "help", "fontSize": "var(--font-size-small)"}),
                    dbc.Tooltip(translate("Valores de frete por tonelada e km para cada estado. Atualizações na tabela serão salvas automaticamente.", lang),
                        target="help-freight-costs",
                        placement="right"
                    ),
                ], className="d-flex align-items-center"),
                className="card-header-custom"
            ),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Button(translate("Adicionar Linha", lang), id="btn-add-freight-row", color="none", className="btn-primary-custom w-100 mb-2"),
                                    dcc.Upload(
                                        id='upload-freight-csv',
                                        children=html.Div([
                                            html.Div("📂", style={"fontSize": "2rem", "marginBottom": "8px"}),
                                            html.Span(translate('Arraste e solte ou ', lang), style={"color": UNB_THEME['UNB_GRAY_DARK']}),
                                            html.A(translate('Selecione', lang), className="fw-bold text-decoration-underline", style={"color": UNB_THEME['UNB_BLUE']}),
                                            html.Div(translate("Formatos: .csv, .xlsx", lang), className="text-muted small mt-2")
                                        ]),
                                        className="upload-box mb-3",
                                        multiple=False,
                                        accept='.csv, .xlsx'
                                    ),
                                    dbc.Button(translate("Baixar Planilha (.xlsx)", lang), id="btn-download-freight", n_clicks=0, color="none", className="btn-success-custom w-100 mb-2")
                                ],
                                width=12, lg=3, className="mb-3 mb-lg-0"
                            ),
                            dbc.Col(
                                [
                                    dbc.Spinner(
                                        html.Div(id='table-freight-container', children=[
                                            dash_table.DataTable(
                                                id='table-costs-freight',
                                                data=[],
                                                columns=[
                                                    {'name': translate('Estado', lang), 'id': 'Estado'},
                                                    {'name': translate('Frete (R$/ton.km)', lang), 'id': 'Frete Tonelada Km'}
                                                ],
                                                editable=True,
                                                row_deletable=True,
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
                                ],
                                width=12, lg=9
                            )
                        ]
                    )
                ],
                className="card-body-custom"
            ),
        ],
        className="card-custom h-100"
    )

    return html.Div([
        storage_card,
        freight_card
    ])
