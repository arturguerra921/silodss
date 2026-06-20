import json
import os
import sys

locales_dir = r"c:\Users\artur\Documents\GitHub\silodss\src\locales"
en_path = os.path.join(locales_dir, "en.json")
pt_path = os.path.join(locales_dir, "pt.json")

with open(en_path, "r", encoding="utf-8") as f:
    en = json.load(f)

with open(pt_path, "r", encoding="utf-8") as f:
    pt = json.load(f)

keys = [
    "Comparação de Cenários (Estocástico)",
    "Esta aba exibe a comparação de cenários e o valor da solução estocástica (EVPI/VSS) após a execução do modelo estocástico. Para visualizar estes resultados, ative o Modelo Estocástico na aba de Configuração do Modelo.",
    "Análise de Valor Estocástico",
    "O cálculo do EVPI/VSS pode demorar alguns minutos. Ele ajuda a avaliar o benefício de adotar o modelo estocástico considerando os diferentes cenários e suas incertezas.",
    "EVPI",
    "VSS",
    "Valor Esperado da Informação Perfeita (EVPI)",
    "O ganho máximo que seria possível obter caso o resultado de cada cenário fosse conhecido antes de qualquer decisão.",
    "A incerteza tem grande impacto nos resultados. Melhorar previsões ou reduzir a incerteza pode gerar ganhos significativos.",
    "A incerteza tem pouco impacto. Os resultados são semelhantes independentemente do cenário que ocorrer.",
    "Valor da Solução Estocástica (VSS)",
    "O ganho de usar um modelo que considera múltiplos cenários em vez de um modelo que usa apenas o cenário médio.",
    "Considerar múltiplos cenários leva a decisões visivelmente melhores. O modelo estocástico agrega valor claro.",
    "O cenário médio é uma aproximação suficiente. Um modelo mais simples chegaria a resultados similares.",
    "Relação entre os dois (VSS \u2264 EVPI)",
    "O EVPI é o melhor resultado possível sob qualquer circunstância. O VSS mostra o quão próximo o modelo estocástico chega desse teto. Se o VSS exceder o EVPI, há um erro no modelo.",
    "Métricas Comparativas por Cenário",
    "Compara os KPIs de custo e volume entre os três cenários (Pessimista, Esperado, Otimista). Os badges \u0394% indicam a variação percentual em relação ao cenário Esperado (referência).",
    "Custos Operacionais por Cenário",
    "Compara cada categoria de custo (Frete, Armazenagem, Abertura, Expansão, Granelização) lado a lado entre os três cenários. Identifique rapidamente qual categoria mais varia entre cenários.",
    "Estoque em Armazéns por Período",
    "Compara o estoque acumulado em armazéns ao longo dos períodos para todos os cenários simultaneamente. Identifique períodos onde os cenários divergem significativamente em necessidade de armazenagem.",
    "Filtrar Armazéns",
    "Todos os armazéns",
    "Utilização de Armazéns por Cenário",
    "Mostra a utilização de cada armazém (Saída Total + Estoque Final) comparada à sua Capacidade Efetiva, para cada cenário. A linha de referência indica a capacidade máxima. Barras que se aproximam ou ultrapassam a linha indicam estresse operacional.",
    "Diferenças nas Decisões de Armazéns",
    "Exibe apenas os armazéns onde as decisões diferem entre cenários (ex: um candidato que abre no Pessimista mas permanece fechado no Otimista, ou expansões que ocorrem apenas em alguns cenários). Armazéns com decisões idênticas em todos os cenários não aparecem aqui.",
    "Armazém",
    "Tipo",
    "Pessimista",
    "Esperado",
    "Otimista",
    "Comparação Geográfica dos Armazéns",
    "Exibe a localização geográfica dos armazéns em cada um dos três cenários. Marcadores verdes indicam armazéns abertos/ativos no cenário correspondente, enquanto marcadores vermelhos representam armazéns fechados ou candidatos não selecionados.",
    "Cenário Pessimista",
    "Cenário Esperado",
    "Cenário Otimista",
    "Aviso de Capacidade / Demanda por Cenário",
    "O modelo estocástico identificou desbalanços de oferta e demanda sob alguns cenários:",
    "Referência",
    "Custo Total",
    "Total Movimentado",
    "Distância Total",
    "Custo Frete",
    "Custo Armazenagem",
    "Custo Abertura",
    "Custo Expansão",
    "Custo Granelização",
    "Frete",
    "Armazenagem",
    "Abertura",
    "Expansão",
    "Granelização",
    "Candidato",
    "Existente",
    "Aberto",
    "Fechado",
    "Exp.",
    "Granel",
    "Capacidade Efetiva",
    "Cenário",
    "Período",
    "Quantidade"
]

missing_en = []
missing_pt = []

print("Checking translations...")
for k in keys:
    if k not in en:
        missing_en.append(k)
    if k not in pt:
        missing_pt.append(k)

print(f"Missing in en.json ({len(missing_en)}):")
for k in missing_en:
    print(f"  - {k.encode('ascii', errors='backslashreplace').decode('ascii')}")

print(f"\nMissing in pt.json ({len(missing_pt)}):")
for k in missing_pt:
    print(f"  - {k.encode('ascii', errors='backslashreplace').decode('ascii')}")
