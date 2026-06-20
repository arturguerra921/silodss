import json
import os

locales_dir = r"c:\Users\artur\Documents\GitHub\silodss\src\locales"
en_path = os.path.join(locales_dir, "en.json")
pt_path = os.path.join(locales_dir, "pt.json")

# Load existing
with open(en_path, "r", encoding="utf-8") as f:
    en = json.load(f)

with open(pt_path, "r", encoding="utf-8") as f:
    pt = json.load(f)

# Define translations
new_translations = {
    "Abertura": "Opening",
    "Armazenagem": "Storage",
    "Armazém": "Warehouse",
    "Armazém Selecionado": "Selected Warehouse",
    "Armazém de Transbordo": "Transshipment Warehouse",
    "Aviso de Capacidade / Demanda por Cenário": "Capacity / Demand Warning by Scenario",
    "Candidato - Aberto": "Candidate - Open",
    "Candidato - Fechado": "Candidate - Closed",
    "Candidato": "Candidate",
    "Existente": "Existing",
    "Capacidade Efetiva": "Effective Capacity",
    "Capacidade Estática Eficiente": "Effective Static Capacity",
    "Cenário Esperado": "Expected Scenario",
    "Cenário Otimista": "Optimistic Scenario",
    "Cenário Pessimista": "Pessimistic Scenario",
    "Cliente / Demanda": "Customer / Demand",
    "Compara cada categoria de custo (Frete, Armazenagem, Abertura, Expansão, Granelização) lado a lado entre os três cenários. Identifique rapidamente qual categoria mais varia entre cenários.": "Compares each cost category (Freight, Storage, Opening, Expansion, Bulkification) side-by-side across the three scenarios. Quickly identify which category varies the most between scenarios.",
    "Compara o estoque acumulado em armazéns ao longo dos períodos para todos os cenários simultaneamente. Identifique períodos onde os cenários divergem significativamente em necessidade de armazenagem.": "Compares cumulative inventory in warehouses over time for all scenarios simultaneously. Identify periods where scenarios diverge significantly in storage requirements.",
    "Compara os KPIs de custo e volume entre os três cenários (Pessimista, Esperado, Otimista). Os badges Δ% indicam a variação percentual em relação ao cenário Esperado (referência).": "Compares cost and volume KPIs across the three scenarios (Pessimistic, Expected, Optimistic). The Δ% badges show the percentage variation relative to the Expected scenario (reference).",
    "Comparação Geográfica dos Armazéns": "Geographic Warehouse Comparison",
    "Considere utilizar o modelo com prazos mais flexíveis ou revisar as rotas de menor custo.": "Consider using the model with more flexible deadlines or reviewing lower cost routes.",
    "Coordenadas do armazém não encontradas.": "Warehouse coordinates not found.",
    "Custo Total de Abertura (R$)": "Total Opening Cost (R$)",
    "Custo Total de Armazenagem (R$)": "Total Storage Cost (R$)",
    "Custo Total de Expansão (R$)": "Total Expansion Cost (R$)",
    "Custo Total de Frete (R$)": "Total Freight Cost (R$)",
    "Custo Total de Granelização (R$)": "Total Bulkification Cost (R$)",
    "Detalhes do armazém não encontrados.": "Warehouse details not found.",
    "Diferenças nas Decisões de Armazéns": "Differences in Warehouse Decisions",
    "Distancia (km)": "Distance (km)",
    "Distância Total Percorrida (km)": "Total Distance Traveled (km)",
    "Erro: A soma das probabilidades dos cenários deve ser igual a 1.0 (atual: {val:.2f})": "Error: The sum of scenario probabilities must be equal to 1.0 (current: {val:.2f})",
    "Erro: Linha selecionada inválida.": "Error: Invalid selected row.",
    "Estoque": "Inventory",
    "Estoque (ton)": "Inventory (tons)",
    "Estoque Final": "Final Stock",
    "Exibe a localização geográfica dos armazéns em cada um dos três cenários. Marcadores verdes indicam armazéns abertos/ativos no cenário correspondente, enquanto marcadores vermelhos representam armazéns fechados ou candidatos não selecionados.": "Displays the geographic location of warehouses in each of the three scenarios. Green markers indicate open/active warehouses in the corresponding scenario, while red markers represent closed warehouses or candidate warehouses that were not selected.",
    "Exibe apenas os armazéns onde as decisões diferem entre cenários (ex: um candidato que abre no Pessimista mas permanece fechado no Otimista, ou expansões que ocorrem apenas em alguns cenários). Armazéns com decisões idênticas em todos os cenários não aparecem aqui.": "Displays only the warehouses where decisions differ between scenarios (e.g., a candidate that opens in the Pessimistic but remains closed in the Optimistic, or expansions that occur only in some scenarios). Warehouses with identical decisions in all scenarios do not appear here.",
    "Existente - Aberto": "Existing - Open",
    "Exp.": "Exp.",
    "Expansão": "Expansion",
    "Filtrar Armazéns": "Filter Warehouses",
    "Frete": "Freight",
    "Granel": "Bulk",
    "Granelização": "Bulkification",
    "Mostra a utilização de cada armazém (Saída Total + Estoque Final) comparada à sua Capacidade Efetiva, para cada cenário. A linha de referência indica a capacidade máxima. Barras que se aproximam ou ultrapassam a linha indicam estresse operacional.": "Shows the utilization of each warehouse (Total Outflow + Final Stock) compared to its Effective Capacity, for each scenario. The reference line indicates the maximum capacity. Bars close to or exceeding the line indicate operational stress.",
    "Movimentação Total": "Total Throughput",
    "O modelo estocástico identificou desbalanços de oferta e demanda sob alguns cenários:": "The stochastic model identified supply and demand imbalances under some scenarios:",
    "Origem / Produtor": "Origin / Producer",
    "Quantidade": "Quantity",
    "Quantidade (ton)": "Quantity (tons)",
    "Referência": "Reference",
    "Resumo por Cenário": "Summary by Scenario",
    "Saída Total": "Total Outflow",
    "Status da Solução": "Solution Status",
    "Tempo de Execução (segundos)": "Execution Time (seconds)",
    "Todos os armazéns": "All warehouses",
    "Total de Restrições": "Total Constraints",
    "Total de Variáveis": "Total Variables",
    "Utilização de Armazéns por Cenário": "Warehouse Utilization by Scenario",
    "Variáveis Binárias": "Binary Variables",
    "Variáveis Contínuas": "Continuous Variables",
    "Variáveis Inteiras": "Integer Variables",
    "Volume Total Movimentado (ton)": "Total Volume Moved (tons)"
}

# Update en
for k, v in new_translations.items():
    en[k] = v

# Update pt
for k in new_translations.keys():
    pt[k] = k

# Save back with same formatting
with open(en_path, "w", encoding="utf-8") as f:
    json.dump(en, f, indent=4, ensure_ascii=False)

with open(pt_path, "w", encoding="utf-8") as f:
    json.dump(pt, f, indent=4, ensure_ascii=False)

print("Translations updated successfully.")
