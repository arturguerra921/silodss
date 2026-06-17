# Mathematical Formulation of the Two-Stage Stochastic Multi-Period Granum Transshipment & Facility Location Model

## 1. Problem Description and Assumptions

In agricultural supply chains, strategic decisions like facility location (opening new warehouses), physical expansions, and bulkification represent long-term capital investments that must be made before operational uncertainties (such as crop yields and market demands) resolve. A deterministic model optimizes against a single forecasted scenario, which can lead to sub-optimal or infeasible solutions under real-world fluctuations.

To address this, we formulate a **Two-Stage Stochastic Mixed-Integer Linear Programming (MILP) model** in extensive form. The model structures decisions into two distinct stages:

1. **First-Stage Decisions (Strategic/Capital):** Deciding which candidate warehouses to open, their static capacities, and whether to physically expand or bulkify warehouses. These decisions are made under uncertainty, must be uniform across all scenarios, and cannot be adjusted once the uncertainty is revealed.
2. **Second-Stage Decisions (Operational):** Deciding commodity flow routing (origins to warehouses, transshipments between warehouses, warehouses to customers) and inventory carry-overs. These decisions are recourse actions taken after uncertainty is resolved, and are optimized separately for each scenario.

### Scenario Representation
Uncertainty is modeled via a finite set of discrete scenarios $S = \{\text{Pessimista}, \text{Esperado}, \text{Otimista}\}$ with corresponding scenario probabilities $\pi_s$ such that $\sum_{s \in S} \pi_s = 1.0$.

* **Expected (Esperado):** Represents the base forecast scenario.
* **Pessimistic (Pessimista):** Represents the worst-case supply chain conditions: low crop supply and high domestic demand.
* **Optimistic (Otimista):** Represents the best-case supply chain conditions: high crop supply and low domestic demand.

Uncertainty affects both origin supply volumes and domestic customer demands. To model the risk-oriented behavior, supply and domestic demand are anti-correlated between the pessimistic and optimistic scenarios using Weighted Mean Absolute Percentage Error (WMAPE):

* **Supply in Scenario $s$:**
  * $S_{opt}^{\text{Esperado}} = \text{PredictedSupply}_{opt}$
  * $S_{opt}^{\text{Pessimista}} = \text{PredictedSupply}_{opt} \times (1 - \text{WMAPE}^{\text{supply}})$
  * $S_{opt}^{\text{Otimista}} = \text{PredictedSupply}_{opt} \times (1 + \text{WMAPE}^{\text{supply}})$
* **Domestic Demand in Scenario $s$:**
  * $\text{Dem}^{\text{dom}, \text{Esperado}}_{cpt} = \text{PredictedDemand}^{\text{dom}}_{cpt}$
  * $\text{Dem}^{\text{dom}, \text{Pessimista}}_{cpt} = \text{PredictedDemand}^{\text{dom}}_{cpt} \times (1 + \text{WMAPE}^{\text{demand}})$
  * $\text{Dem}^{\text{dom}, \text{Otimista}}_{cpt} = \text{PredictedDemand}^{\text{dom}}_{cpt} \times (1 - \text{WMAPE}^{\text{demand}})$

Export customer demand bounds represent maximum limits and remain unchanged across all scenarios.

---

## 2. Extended Sets, Parameters, and Variables

The stochastic model extends the deterministic sets, parameters, and variables by indexing all second-stage (operational) elements by scenario $s \in S$.

### Sets and Indices
* $S = \{\text{Pessimista}, \text{Esperado}, \text{Otimista}\}$: Set of scenarios.
* $s \in S$: Scenario index.

### Parameters
* $\pi_s$: Probability of scenario $s \in S$ (where $\pi_s \ge 0, \sum_{s \in S} \pi_s = 1.0$).
* $S^s_{opt}$: Available supply of product $p$ at origin $o$ in period $t$ under scenario $s$ (in t).
* $\text{Dem}^{\text{dom},s}_{cpt}$: Hard demand of product $p$ required exactly at domestic customer $c \in C_{\text{dom}}$ in period $t$ under scenario $s$ (in t).

### First-Stage Decision Variables (Scenario-Independent)
* $h_d \in \{0, 1\}$: Binary decision to open candidate warehouse $d \in D_{\text{cand}}$ ($h_d$ is fixed to $1$ for $d \in D_{\text{exist}}$).
* $\kappa_d \ge 0$: Decided initial static storage capacity of candidate warehouse $d \in D_{\text{cand}}$ (in t).
* $y^{\text{exp}}_d \in \{0, 1\}$: Binary decision to physically expand warehouse $d \in D$.
* $g_d \ge 0$: Static capacity added to warehouse $d \in D$ (in t).
* $y^{\text{bulk}}_d \in \{0, 1\}$: Binary decision to bulkify warehouse $d \in D$.
* $q^{\text{bulk}}_d \ge 0$: Bulk handling capacity rate added to warehouse $d \in D$ (in t/day).

### Second-Stage Decision Variables (Scenario-Dependent)
* $x_{odpts} \ge 0$: Flow of product $p$ from origin $o$ to warehouse $d$ in period $t$ under scenario $s$ (in t).
* $z_{dcpts} \ge 0$: Flow of product $p$ from warehouse $d$ to customer $c$ in period $t$ under scenario $s$ (in t).
* $y_{d_1d_2pts} \ge 0$: Transshipment flow of product $p$ from warehouse $d_1$ to $d_2$ in period $t$ under scenario $s$ (in t).
* $e_{dpts} \ge 0$: Inventory of product $p$ stored at warehouse $d$ at the end of period $t$ under scenario $s$ (in t).

---

## 3. Mathematical Formulation

### Objective Function

The objective is to minimize the total expected cost $Z$, which comprises the deterministic first-stage capital investment costs and the expected second-stage operational (freight and storage) costs across all scenarios:

$$
\min Z = \text{FirstStageCapitalCost} + \sum_{s \in S} \pi_s \cdot \text{SecondStageOperationalCost}_s
$$

#### First-Stage Capital Cost:
$$
\begin{aligned}
\text{FirstStageCapitalCost} = & \sum_{d \in D_{\text{cand}}} \text{OpenCost}_d \cdot h_d \\
& + \sum_{d \in D} \left( \text{FixExpandCost}_d \cdot y^{\text{exp}}_d + \text{VarExpandCost}_d \cdot g_d \right) \\
& + \sum_{d \in D} \left( \text{FixBulkCost}_d \cdot y^{\text{bulk}}_d + \text{VarBulkCost}_d \cdot q^{\text{bulk}}_d \right)
\end{aligned}
$$

#### Second-Stage Operational Cost (per scenario $s$):
$$
\begin{aligned}
\text{SecondStageOperationalCost}_s = & \sum_{t \in T} \sum_{(o,d,p) \in R_{ODP}} \text{FreightOD}_{od} \cdot x_{odpts} \\
& + \sum_{t \in T} \sum_{(d,c,p) \in R_{DCP}} \text{FreightDC}_{dc} \cdot z_{dcpts} \\
& + \sum_{t \in T} \sum_{(d_1,d_2,p) \in R_{DDP}} \alpha \cdot \text{FreightDD}_{d_1d_2} \cdot y_{d_1d_2pts} \\
& + \sum_{t \in T} \sum_{d \in D} \sum_{p \in P} \text{StorageTariff}_{dp} \cdot e_{dpts}
\end{aligned}
$$

### Constraints (Replicated for each Scenario $s \in S$)

#### 1. Supply Dispatch Equality:
All available supply in scenario $s$ must be fully dispatched from origins:
$$
\sum_{\{d \mid (o,d,p) \in R_{ODP}\}} x_{odpts} = S^s_{opt} \quad \forall o \in O,\ p \in P,\ t \in T,\ s \in S
$$

#### 2. Inventory Conservation:
Inventory carry-over at each warehouse must balance across periods in scenario $s$:
$$
e_{dpts} = e_{dp,\,t-1,\,s} + \text{Inflow}_{dpts} - \text{Outflow}_{dpts} \quad \forall d \in D,\ p \in P,\ t \in T,\ s \in S
$$
Where:
* For $t = 1$: $e_{dp,\,t-1,\,s} = I_{dp}$ (Initial inventory parameter).
* $\text{Inflow}_{dpts} = \sum_{\{o \mid (o,d,p) \in R_{ODP}\}} x_{odpts} + \sum_{\{d_1 \mid (d_1,d,p) \in R_{DDP}\}} y_{d_1dpts}$
* $\text{Outflow}_{dpts} = \sum_{\{c \mid (d,c,p) \in R_{DCP}\}} z_{dcpts} + \sum_{\{d_2 \mid (d,d_2,p) \in R_{DDP}\}} y_{dd_2pts}$

#### 3. Storage Static Capacity Constraints:
The total inventory of all products at warehouse $d$ at the end of period $t$ cannot exceed its static storage capacity:
* For existing warehouses ($d \in D_{\text{exist}}$):
$$
\sum_{p \in P} e_{dpts} \le \text{StaticCap}_d + g_d \quad \forall t \in T,\ s \in S
$$
* For candidate warehouses ($d \in D_{\text{cand}}$):
$$
\sum_{p \in P} e_{dpts} \le \kappa_d + g_d \quad \forall t \in T,\ s \in S
$$

#### 4. Warehouse Throughput Handling Constraints:
Total inflow and outflow at warehouse $d$ during period $t$ are bounded by its receiving and shipping capacities (converted to monthly capacity based on 30 operational days):
* **Receiving/Inflow Bound:**
  * For existing warehouses ($d \in D_{\text{exist}}$):
$$
\text{Inflow}_{dpts} \le 30 \times \left( \text{ReceptionCap}_d + \beta^{\text{rec}} \cdot g_d + q^{\text{bulk}}_d \right) \quad \forall p \in P,\ t \in T,\ s \in S
$$
  * For candidate warehouses ($d \in D_{\text{cand}}$):
$$
\text{Inflow}_{dpts} \le 30 \times \left( \beta^{\text{rec}} \cdot \kappa_d + \beta^{\text{rec}} \cdot g_d + q^{\text{bulk}}_d \right) \quad \forall p \in P,\ t \in T,\ s \in S
$$

* **Shipping/Outflow Bound:**
  * For existing warehouses ($d \in D_{\text{exist}}$):
$$
\text{Outflow}_{dpts} \le 30 \times \left( \text{ShippingCap}_d + \beta^{\text{ship}} \cdot g_d + q^{\text{bulk}}_d \right) \quad \forall p \in P,\ t \in T,\ s \in S
$$
  * For candidate warehouses ($d \in D_{\text{cand}}$):
$$
\text{Outflow}_{dpts} \le 30 \times \left( \beta^{\text{ship}} \cdot \kappa_d + \beta^{\text{ship}} \cdot g_d + q^{\text{bulk}}_d \right) \quad \forall p \in P,\ t \in T,\ s \in S
$$

#### 5. Customer Demand Fulfillment:
* **Domestic Demand (Hard Equality):**
$$
\sum_{\{d \mid (d,c,p) \in R_{DCP}\}} z_{dcpts} = \text{Dem}^{\text{dom},s}_{cpt} \quad \forall c \in C_{\text{dom}},\ p \in P,\ t \in T,\ s \in S
$$
* **Export Demand (Upper Bound):**
$$
\sum_{\{d \mid (d,c,p) \in R_{DCP}\}} z_{dcpts} \le \text{Dem}^{\text{exp}}_{cpt} \quad \forall c \in C_{\text{exp}},\ p \in P,\ t \in T,\ s \in S
$$

---

## 4. First-Stage Structuring and Coordination Constraints

First-stage variables are scenario-independent, linking the structural decisions across all operational scenarios.

* **Mutual Exclusion of Modifications:**
$$
y^{\text{exp}}_d + y^{\text{bulk}}_d \le h_d \quad \forall d \in D
$$
* **Bulkification Eligibility:**
$$
y^{\text{bulk}}_d = 0 \quad \forall d \in D \setminus D_{\text{bulk\_eligible}}
$$
* **Candidate Static Capacity Sizing Limit:**
$$
\kappa_d \le h_d \cdot \text{MaxCandStatic}_d \quad \forall d \in D_{\text{cand}}
$$
* **Bulkification Quantity Limit:**
$$
q^{\text{bulk}}_d \le y^{\text{bulk}}_d \cdot \text{MaxBulk}_d \quad \forall d \in D
$$
* **Continuous Expansion Sizing Limit:**
$$
g_d \le y^{\text{exp}}_d \cdot \text{MaxExpand}_d \quad \forall d \in D
$$

---

## 5. Pre-Solve Feasibility Check

Because domestic demand is a hard equality constraint and supply dispatch is also a hard equality constraint, a scenario is infeasible if total supply is less than total domestic demand in any period. Before initiating Pyomo, we verify:

$$
\sum_{o \in O} \sum_{p \in P} S^s_{opt} \ge \sum_{c \in C_{\text{dom}}} \sum_{p \in P} \text{Dem}^{\text{dom},s}_{cpt} \quad \forall t \in T,\ \forall s \in S
$$

If this fails for any scenario $s$ and period $t$, a warning is shown to the user indicating a supply shortage under that scenario, but the solver run is not blocked.

---

## 6. EVPI and VSS Evaluation

To evaluate the benefits of the stochastic programming approach, we define two metrics:

### Expected Value of Perfect Information (EVPI)
EVPI measures the expected savings if the decision-maker had perfect information about the future scenario before making the first-stage decisions.
1. Solve 3 separate deterministic models (one for each scenario $s \in S$). Let $Z^*_s$ be the optimal objective value of scenario $s$'s deterministic model.
2. Compute the **Wait-and-See (WS)** value:
$$
\text{WS} = \sum_{s \in S} \pi_s \cdot Z^*_s
$$
3. Let $Z^*_{\text{RP}}$ be the optimal objective of the Recourse Problem (the stochastic model solved above).
4. Compute EVPI:
$$
\text{EVPI} = Z^*_{\text{RP}} - \text{WS}
$$
*(Note: Since RP is a single plan hedging against all scenarios while WS optimizes for each scenario individually, $Z^*_{\text{RP}} \ge \text{WS}$ and $\text{EVPI} \ge 0$.)*

### Value of Stochastic Solution (VSS)
VSS measures the expected savings from using the stochastic model rather than solving a deterministic model using the expected values and fixing those first-stage decisions.
1. Solve the deterministic model using the expected values (Scenario Expected). Let the optimal first-stage decisions be $\bar{h}_d$, $\bar{\kappa}_d$, $\bar{y}^{\text{exp}}_d$, $\bar{g}_d$, $\bar{y}^{\text{bulk}}_d$, $\bar{q}^{\text{bulk}}_d$.
2. Solve the stochastic model with the first-stage variables fixed to these values. Let $Z^*_{\text{EEV}}$ (Expected result of the Expected Value solution) be the resulting optimal objective.
3. Let $Z^*_{\text{RP}}$ be the optimal objective of the stochastic model.
4. Compute VSS:
$$
\text{VSS} = Z^*_{\text{EEV}} - Z^*_{\text{RP}}
$$
*(Note: Since RP is the unconstrained optimal recourse solution, $Z^*_{\text{EEV}} \ge Z^*_{\text{RP}}$ and $\text{VSS} \ge 0$.)*
