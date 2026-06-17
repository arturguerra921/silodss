# Mathematical Formulation of the Multi-Period Granum Transshipment & Facility Location Model

> **Revision Notes — Changes from Previous Version**
>
> The following issues were identified in the previous formulation and corrected in this document:
>
> 1. **[ISSUE 1 — FIXED] Candidate Warehouse Initial Capacities:** Candidate warehouses have no pre-existing capacity data. When the solver opens a candidate ($h_d = 1$), its initial reception and shipping capacities are now derived from its decided static capacity using the same proportional scaling factors used for expansion ($\beta^{\text{rec}}$ and $\beta^{\text{ship}}$). A new parameter $\text{StaticCapDecided}_d$ replaces the empty $\text{StaticCap}_d$ for candidates, and the handling capacity constraints are reformulated to reflect this initialization. This also makes the flow-blocking guarantee for closed candidates ($h_d = 0$) structurally airtight, since all capacity terms reduce to zero when the facility is not opened.
>
> 2. **[ISSUE 2 — CONFIRMED, NO CHANGE]** Supply equality ($\sum x = S$) is retained. Export nodes are always configured to absorb the full network surplus, guaranteeing feasibility.
>
> 3. **[ISSUE 3 — REMOVED] Turnover Ratio:** The $\text{Turnover}_d$ variable, its auxiliary definition, and the associated `DynCap` constraint have been **removed from the model**. Both metrics will be computed outside the solver as post-optimization Python calculations, avoiding any risk of bilinear expressions entering the constraint matrix.
>
> 4. **[ISSUE 6 — FIXED] `WarehouseOpen` for Existing Warehouses:** For existing warehouses ($d \in D_{\text{exist}}$), $h_d$ is no longer declared as a binary decision variable. It is instead treated as a **fixed parameter** equal to $1$, reducing the MILP binary variable count and improving solver performance.
>
> 5. **[NEW] Optional Activation of Upgrade Modules (Physical Expansion & Bulkification):** Both expansion and bulkification are now optional, toggleable features in the configuration interface. If either is disabled by the user, its continuous and binary decision variables are fixed to zero:
>    * When Expansion is disabled: $y^{\text{exp}}_d = 0$ and $g_d = 0 \quad \forall d \in D$.
>    * When Bulkification is disabled: $y^{\text{bulk}}_d = 0$ and $q^{\text{bulk}}_d = 0 \quad \forall d \in D$.
>    This effectively zeros out the corresponding upgrade capital costs in the objective function, and reduces the capacity constraints to their base/candidate capacity equivalents without modifying the core constraint equations. The parameters $\beta^{\text{rec}}$ and $\beta^{\text{ship}}$ are now general parameters to always enable candidate warehouse capacity initialization regardless of whether expansion is active.

---

## 1. Problem Description and Assumptions

The strategic planning of agricultural supply chains requires institutional planners to manage seasonal harvest volumes, direct-to-warehouse allocations, inter-warehouse transshipments, and final customer demand fulfillment over a planning horizon. This macro-level logistical process must balance state-based freight rates and differentiated storage tariffs across both existing public/private warehouses and potential candidate hubs.

The system is modeled as a multi-period, multi-commodity network. Flows originate at supply cities, travel through storage and transshipment hubs, and terminate at regional customers. To eliminate mathematical singularities associated with infinite parameters, the customer destination layer is explicitly partitioned into:

* **Domestic Customers ($C_{\text{dom}}$):** Regional domestic markets with rigid, minimum demand fulfillment requirements.

* **Export Customers ($C_{\text{exp}}$):** International exit nodes (such as ports and borders) modeled as capacity-bounded or quota-controlled flow sinks. Export nodes are always configured to absorb the full network surplus, ensuring feasibility.

### Capacity Modification Upgrades

To support long-term infrastructural planning, the model incorporates options for strategic warehouse capacity upgrades. Planners can choose to invest in modifying existing warehouses or newly opened candidate facilities via two mutually exclusive structural pathways:

1. **Physical Expansion:** This process increases the static storage capacity of a warehouse by a continuous volume $g_d$. Because physical footprint expansions require corresponding increases in handling infrastructure, expanding static capacity automatically scales up the facility's daily receiving and shipping capacities by user-defined percentage relationships ($\beta^{\text{rec}}$ and $\beta^{\text{ship}}$). This upgrade features a fixed activation cost and a variable cost per ton of static capacity added.

2. **Bulkification:** This process converts a portion of a warehouse's existing storage volume from packaged/bagged storage to high-efficiency internal cylindrical bulk silos. Bulkification **does not increase** the total static capacity of the facility, but it substantially boosts both daily reception and shipping capacities by a continuous upgraded rate $q^{\text{bulk}}_d$. Similar to expansion, bulkification features a fixed cost to initiate and a variable cost per unit of capacity rate upgraded. This modification is restricted to a compatible subset of eligible warehouse types.

A strict coordination rule ensures that during the entire planning horizon, any single warehouse can be submitted to at most **one** of these modification options.

**[NEW] Optional Module Activation:** Planners can toggle the availability of both Physical Expansion and Bulkification independently. The mathematical behavior is governed as follows:
* **Both Enabled:** The model operates as described above, enforcing mutual exclusion (Constraint 5a) at each warehouse.
* **Expansion Only:** Bulkification decision variables are fixed to zero ($y^{\text{bulk}}_d = 0$, $q^{\text{bulk}}_d = 0$). Only physical expansion decisions are optimized.
* **Bulkification Only:** Physical expansion decision variables are fixed to zero ($y^{\text{exp}}_d = 0$, $g_d = 0$). Only bulkification decisions are optimized.
* **Neither Enabled:** Both sets of decision variables are fixed to zero ($y^{\text{exp}}_d = 0$, $g_d = 0$, $y^{\text{bulk}}_d = 0$, $q^{\text{bulk}}_d = 0$). The network operates under base and candidate opening capacities only, and no upgrade investment costs are incurred.

### Core Assumptions

1. The amount of available supply at each origin location for each commodity type is known and deterministic for every monthly time step.

2. The initial inventory of commodities present in **existing** warehouses is known and deterministic. Candidate warehouses start with zero inventory.

3. Monthly storage tariffs, state-based freight rates, and candidate warehouse opening costs are known and fixed.

4. Storage compatibility between commodities and destination warehouse types is binary and fixed.

5. Transportation flows are continuous, bypassing discrete vehicle trip parameters to maintain high computational performance.

6. Inventory balances across consecutive periods must be strictly conserved.

7. Hub-to-hub transshipments are permitted between valid warehouses, incurring freight rates scaled by a dedicated discount factor $\alpha$.

8. Domestic demands represent targets that must be met exactly, while export demands represent maximum capacity caps or contract quotas. Export nodes always have sufficient ceiling capacity to absorb total system surplus.

9. Operations are bound strictly by physical constraints; no slack variables or penalty-based violations are permitted.

10. **[NEW]** Candidate warehouses carry no pre-existing capacity data. If opened, their initial daily reception and shipping capacities are determined by applying the scaling factors $\beta^{\text{rec}}$ and $\beta^{\text{ship}}$ to the chosen static capacity decision $\kappa_d$ (see Section 2).

---

## 2. Model Sets, Parameters, and Variables

### Table 1: Model Indices and Sets

| **Index/Set** | **Pyomo Variable** | **Description** |
| --- | --- | --- |
| $o \in O$ | `model.Origins` | Set of supply origins (harvest cities). |
| $d, d_1, d_2 \in D$ | `model.Destinations` | Set of warehouses (hubs), partitioned into existing ($D_{\text{exist}}$) and candidate ($D_{\text{cand}}$) facilities. |
| $D_{\text{bulk\_eligible}} \subseteq D$ | `model.BulkEligible` | Subset of warehouses structurally eligible to undergo bulkification based on type compatibility. |
| $c \in C$ | `model.Customers` | Set of demand customers, partitioned into domestic markets $C_{\text{dom}}$ and export markets $C_{\text{exp}}$ ($C = C_{\text{dom}} \cup C_{\text{exp}}$, $C_{\text{dom}} \cap C_{\text{exp}} = \emptyset$). |
| $p \in P$ | `model.Products` | Set of product types (grain commodities). |
| $t \in T$ | `model.TimePeriods` | Chronological sequence of time periods (months), where $t_{\text{end}} \in T$ represents the last index of the set. |
| $(o,d,p) \in R_{ODP} \subseteq O \times D \times P$ | `model.ValidRoutesOD` | Sparse subset of allowed origin-to-warehouse routes, restricted by compatibility and the Pareto distance filter. |
| $(d,c,p) \in R_{DCP} \subseteq D \times C \times P$ | `model.ValidRoutesDC` | Sparse subset of allowed warehouse-to-customer routes, restricted by compatibility and the Pareto distance filter. |
| $(d_1,d_2,p) \in R_{DDP} \subseteq D \times D \times P$ | `model.ValidRoutesDD` | Sparse subset of allowed hub-to-hub transshipment routes ($d_1 \neq d_2$). |

### Table 2: Model Parameters

| **Symbol** | **Pyomo Variable** | **Description** |
| --- | --- | --- |
| $S_{opt}$ | `model.Supply[o,p,t]` | Available supply of product $p$ at origin $o$ in period $t$ (in t). |
| $\text{Dem}^{\text{dom}}_{cpt}$ | `model.DemandMin[c,p,t]` | Hard demand of product $p$ required exactly at domestic customer $c \in C_{\text{dom}}$ in period $t$ (in t). |
| $\text{Dem}^{\text{exp}}_{cpt}$ | `model.DemandMax[c,p,t]` | Maximum export ceiling capacity of product $p$ allowed at export customer $c \in C_{\text{exp}}$ in period $t$ (in t). Defaults to total aggregate supply $\sum_{o \in O} S_{opt}$ to act as a non-binding sink. |
| $\text{StaticCap}_d$ | `model.StaticCapacity[d]` | Initial static storage capacity of warehouse $d \in D_{\text{exist}}$ (in t). **Not defined for $d \in D_{\text{cand}}$; see $\kappa_d$ below.** |
| $\text{ReceptionCap}_d$ | `model.ReceptionCapacity[d]` | Initial maximum daily receiving rate of warehouse $d \in D_{\text{exist}}$ (in t/day). **Not defined for $d \in D_{\text{cand}}$.** |
| $\text{ShippingCap}_d$ | `model.ShippingCapacity[d]` | Initial maximum daily shipping rate of warehouse $d \in D_{\text{exist}}$ (in t/day). **Not defined for $d \in D_{\text{cand}}$.** |
| $I_{dp}$ | `model.InitialInventory[d,p]` | Initial inventory of product $p$ present at existing warehouse $d \in D_{\text{exist}}$ before the first period (in t). Set to $0$ for all $d \in D_{\text{cand}}$. |
| $\text{OpenCost}_d$ | `model.OpeningCost[d]` | Fixed setup/capital cost to open candidate warehouse $d \in D_{\text{cand}}$ (in \$). |
| $\text{MaxCandStatic}_d$ | `model.MaxCandStaticCapacity[d]` | **[NEW]** Maximum allowable static storage capacity for candidate warehouse $d \in D_{\text{cand}}$ (in t). Bounds the $\kappa_d$ decision variable. |
| $\text{StorageCost}_{d,p}$ | `model.StorageTariff[d,p]` | Storage tariff at destination $d$ for product $p$ (in \$/t per month). |
| $F^O_o$ | `model.FreightOrigin[o]` | Unit freight cost factor from origin $o$, based on its state (in \$/t·km). |
| $F^D_d$ | `model.FreightDest[d]` | Unit freight cost factor from warehouse $d$, based on its state (in \$/t·km). |
| $\text{Dist}_{od}$ | `model.DistanceOD[o,d]` | Road distance between origin $o$ and warehouse $d$ (in km). |
| $\text{Dist}_{dc}$ | `model.DistanceDC[d,c]` | Road distance between warehouse $d$ and customer $c$ (in km). |
| $\text{Dist}_{d_1d_2}$ | `model.DistanceDD[d1,d2]` | Road distance between warehouse $d_1$ and warehouse $d_2$ (in km). |
| $\alpha$ | `model.TransshipmentDiscount` | Discount multiplier applied to hub-to-hub transshipment routes ($\alpha \in (0, 1]$). |
| $\text{Days}$ | `model.Days` | Active operational days within each period $t \in T$ (in days). |
| $\text{MaxExpand}_d$ | `model.MaxExpandCapacity[d]` | Maximum physical capacity expansion allowed for warehouse $d$ (in t). |
| $\text{ExpandCost}^{\text{fixed}}_d$ | `model.ExpandFixedCost[d]` | Fixed capital investment to initiate expansion at warehouse $d$ (in \$). |
| $\text{ExpandCost}^{\text{var}}_d$ | `model.ExpandVarCost[d]` | Variable cost per unit of expanded static capacity at warehouse $d$ (in \$/t). |
| $\text{MaxBulk}_d$ | `model.MaxBulkCapacity[d]` | Maximum daily handling rate increase allowed via bulkification at warehouse $d$ (in t/day). |
| $\text{BulkCost}^{\text{fixed}}_d$ | `model.BulkFixedCost[d]` | Fixed capital investment to initiate bulkification at warehouse $d$ (in \$). |
| $\text{BulkCost}^{\text{var}}_d$ | `model.BulkVarCost[d]` | Variable cost per unit of bulkified reception/shipping handling capacity at warehouse $d$ (in \$/(t/day)). |
| $\beta^{\text{rec}}$ | `model.RatioExpandRec` | Percentage factor translating static capacity (t) to reception capacity (t/day) (e.g., $0.10$). Used both for expansion scaling and for initializing candidate warehouse reception capacity. |
| $\beta^{\text{ship}}$ | `model.RatioExpandShip` | Percentage factor translating static capacity (t) to shipping capacity (t/day) (e.g., $0.10$). Used both for expansion scaling and for initializing candidate warehouse shipping capacity. |

### Table 3: Model Decision and Evaluation Variables

| **Symbol** | **Domain** | **Pyomo Variable** | **Description** |
| --- | --- | --- | --- |
| $x_{odpt}$ | $\mathbb{R}_+$ | `model.FlowOD[o,d,p,t]` | Continuous flow from origin $o$ to warehouse $d$ of product $p$ in period $t$ (in t). |
| $z_{dcpt}$ | $\mathbb{R}_+$ | `model.FlowDC[d,c,p,t]` | Continuous flow from warehouse $d$ to customer $c$ of product $p$ in period $t$ (in t). |
| $y_{d_1d_2pt}$ | $\mathbb{R}_+$ | `model.FlowDD[d1,d2,p,t]` | Continuous transshipment flow from hub $d_1$ to hub $d_2$ of product $p$ in period $t$ (in t). |
| $e_{dpt}$ | $\mathbb{R}_+$ | `model.Inventory[d,p,t]` | Inventory level of product $p$ held in warehouse $d$ at the end of period $t$ (in t). |
| $\kappa_d$ | $\mathbb{R}_+$ | `model.CandStaticCapacity[d]` | **[NEW]** Continuous decision variable representing the static storage capacity chosen for candidate warehouse $d \in D_{\text{cand}}$ if opened (in t). Fixed to $0$ if $h_d = 0$. |
| $g_d$ | $\mathbb{R}_+$ | `model.ExpandedCapacity[d]` | Continuous quantity of static storage capacity added to warehouse $d$ via physical expansion (in t). |
| $q^{\text{bulk}}_d$ | $\mathbb{R}_+$ | `model.BulkCapacity[d]` | Continuous quantity of handling rate capacity added to both reception and shipping limits at warehouse $d$ via bulkification (in t/day). |
| $h_d$ | $\{0,1\}$ | `model.WarehouseOpen[d]` | **[CHANGED: defined only for $d \in D_{\text{cand}}$]** Binary variable indicating whether candidate warehouse $d$ is opened ($1$) or not ($0$). For $d \in D_{\text{exist}}$, this is a fixed parameter equal to $1$. |
| $y^{\text{exp}}_d$ | $\{0,1\}$ | `model.IsExpanded[d]` | Binary variable indicating if warehouse $d$ undergoes physical capacity expansion ($1$) or not ($0$). |
| $y^{\text{bulk}}_d$ | $\{0,1\}$ | `model.IsBulkified[d]` | Binary variable indicating if warehouse $d$ undergoes bulkification conversion ($1$) or not ($0$). |
| $\text{DynCap}_d$ | $\mathbb{R}_+$ | *(post-solve only)* | **[CHANGED]** Dynamic capacity of warehouse $d$: total outflow across all periods plus final inventory. Computed outside the solver. |

> **Implementation Note — `WarehouseOpen` for Existing Facilities:**
> In Pyomo, for $d \in D_{\text{exist}}$, define `h_d` as a `Param` with value `1` rather than a `Var`. This eliminates unnecessary binary variables from the branch-and-bound tree. The unified notation $h_d$ is retained throughout the formulation for compactness, with the understanding that it is a fixed constant for existing facilities.

---

## 3. Mixed-Integer Linear Programming (MILP) Model Formulation

The multi-period MILP model optimizes tactical routing, multi-commodity warehouse storage, transshipment flows, facility configurations, and structural capacity modifications over the entire time horizon $T$.

### Objective Function

The objective function seeks to minimize the total operational and capital costs of the agricultural supply chain network:

$$
\begin{aligned}
\min Z_{\text{MILP}} = & \sum_{(o,d,p) \in R_{ODP}} \sum_{t \in T} x_{odpt} \cdot \left(\text{Dist}_{od} \cdot F^O_o\right) \\
& + \sum_{(d,c,p) \in R_{DCP}} \sum_{t \in T} z_{dcpt} \cdot \left(\text{Dist}_{dc} \cdot F^D_d\right) \\
& + \sum_{(d_1,d_2,p) \in R_{DDP}} \sum_{t \in T} y_{d_1d_2pt} \cdot \left(\alpha \cdot \text{Dist}_{d_1d_2} \cdot F^D_{d_1}\right) \\
& + \sum_{d \in D} \sum_{p \in P} \sum_{t \in T} e_{dpt} \cdot \text{StorageCost}_{d,p} \\
& + \sum_{d \in D_{\text{cand}}} h_d \cdot \text{OpenCost}_d \\
& + \sum_{d \in D} \left( y^{\text{exp}}_d \cdot \text{ExpandCost}^{\text{fixed}}_d + g_d \cdot \text{ExpandCost}^{\text{var}}_d \right) \\
& + \sum_{d \in D_{\text{bulk\_eligible}}} \left( y^{\text{bulk}}_d \cdot \text{BulkCost}^{\text{fixed}}_d + q^{\text{bulk}}_d \cdot \text{BulkCost}^{\text{var}}_d \right)
\end{aligned}
$$

### Operational Constraints

#### 1. Supply Allocation Bound

Every origin location $o \in O$ must fully dispatch its available deterministic supply of product $p \in P$ in each period $t \in T$:

$$
\sum_{\{d \mid (o,d,p) \in R_{ODP}\}} x_{odpt} = S_{opt} \quad \forall o \in O,\ p \in P,\ t \in T
$$

#### 2. Inventory Balance and Conservation (Carry-over Loop)

The inventory of commodity $p \in P$ held at warehouse $d \in D$ at the end of period $t \in T$ must equal its incoming flows and previous inventory minus outgoing shipments.

Let the total inflow to warehouse $d$ for product $p$ in period $t$ be:

$$
\text{Inflow}_{dpt} = \sum_{\{o \mid (o,d,p) \in R_{ODP}\}} x_{odpt} + \sum_{\{d_1 \mid (d_1,d,p) \in R_{DDP}\}} y_{d_1dpt}
$$

Let the total outflow from warehouse $d$ for product $p$ in period $t$ be:

$$
\text{Outflow}_{dpt} = \sum_{\{c \mid (d,c,p) \in R_{DCP}\}} z_{dcpt} + \sum_{\{d_2 \mid (d,d_2,p) \in R_{DDP}\}} y_{dd_2pt}
$$

The conservation balance is governed by:

$$
e_{dpt} = e_{dp,t-1} + \text{Inflow}_{dpt} - \text{Outflow}_{dpt} \quad \forall d \in D,\ p \in P,\ t \in T
$$

Where, for the boundary condition at the first period ($t = 1$), the lagged state is defined as:

$$
e_{dp,0} = I_{dp} \quad \forall d \in D,\ p \in P
$$

With $I_{dp} = 0$ for all $d \in D_{\text{cand}}$.

#### 3. Warehouse Static Capacity Bound

**[CHANGED]** The total volume stored across all commodities at warehouse $d$ at the end of period $t$ cannot exceed the effective static capacity of the facility. The effective static capacity is defined differently for existing and candidate warehouses:

**For existing warehouses ($d \in D_{\text{exist}}$), where $h_d = 1$ (fixed):**

$$
\sum_{p \in P} e_{dpt} \le \text{StaticCap}_d + g_d \quad \forall d \in D_{\text{exist}},\ t \in T
$$

**For candidate warehouses ($d \in D_{\text{cand}}$):**

$$
\sum_{p \in P} e_{dpt} \le \kappa_d + g_d \quad \forall d \in D_{\text{cand}},\ t \in T
$$

Where $\kappa_d$ is the decided static capacity of the candidate warehouse if opened (see Constraint 5c below).

#### 4. Warehouse Physical Handling Bounds (Reception & Shipping Limits)

**[CHANGED]** The volumes handled during each period are restricted by the daily receiving and shipping capabilities, scaled across the simulation window ($\text{Days}$). The effective base capacity differs between existing and candidate facilities.

**For existing warehouses ($d \in D_{\text{exist}}$):**

* **Reception:**
$$
\sum_{p \in P} \text{Inflow}_{dpt} \le \left(\text{ReceptionCap}_d + \beta^{\text{rec}} \cdot g_d + q^{\text{bulk}}_d \right) \cdot \text{Days} \quad \forall d \in D_{\text{exist}},\ t \in T
$$

* **Shipping:**
$$
\sum_{p \in P} \text{Outflow}_{dpt} \le \left(\text{ShippingCap}_d + \beta^{\text{ship}} \cdot g_d + q^{\text{bulk}}_d \right) \cdot \text{Days} \quad \forall d \in D_{\text{exist}},\ t \in T
$$

**For candidate warehouses ($d \in D_{\text{cand}}$):**

**[NEW]** Candidate warehouses have no pre-existing capacity data. If opened ($h_d = 1$), their initial reception and shipping capacities are derived from their decided static capacity $\kappa_d$ using the same proportional scaling factors applied to physical expansions. Upgrades ($g_d$, $q^{\text{bulk}}_d$) may additionally be applied on top of this base:

* **Reception:**
$$
\sum_{p \in P} \text{Inflow}_{dpt} \le \left(\beta^{\text{rec}} \cdot \kappa_d + \beta^{\text{rec}} \cdot g_d + q^{\text{bulk}}_d \right) \cdot \text{Days} \quad \forall d \in D_{\text{cand}},\ t \in T
$$

* **Shipping:**
$$
\sum_{p \in P} \text{Outflow}_{dpt} \le \left(\beta^{\text{ship}} \cdot \kappa_d + \beta^{\text{ship}} \cdot g_d + q^{\text{bulk}}_d \right) \cdot \text{Days} \quad \forall d \in D_{\text{cand}},\ t \in T
$$

*Note: When $h_d = 0$ (candidate not opened), Constraint 5c forces $\kappa_d = 0$, Constraint 5 forces $g_d = 0$ and $q^{\text{bulk}}_d = 0$, reducing all capacity terms to zero. Combined with the inventory balance (Constraint 2) and non-negativity of all flow variables, this structurally prevents any flow from entering or leaving a closed candidate facility.*

*(Note: For warehouses not eligible for bulkification, $y^{\text{bulk}}_d$ and $q^{\text{bulk}}_d$ are set statically to $0$.)*

#### 5. Warehouse Upgrade Coordination Constraints

These coordination constraints govern physical expansions, bulkifications, and their structural mutual exclusion.

* **5a. Mutual Exclusion of Modifications:** A warehouse can undergo at most one modification type across the planning horizon, and only if the facility itself is opened/active ($h_d = 1$):

$$
y^{\text{exp}}_d + y^{\text{bulk}}_d \le h_d \quad \forall d \in D
$$

*(For $d \in D_{\text{exist}}$, $h_d = 1$ is a fixed parameter, so this reduces to $y^{\text{exp}}_d + y^{\text{bulk}}_d \le 1$.)*

* **5b. Bulkification Eligibility Enforcement:** If a warehouse is not in the compatible set, its bulkification binary variable is locked to zero:

$$
y^{\text{bulk}}_d = 0 \quad \forall d \in D \setminus D_{\text{bulk\_eligible}}
$$

* **5c. Candidate Static Capacity Bounding:** **[NEW]** The decided static capacity of a candidate warehouse is continuous and bounded by the maximum allowed parameter. It can only take a positive value if the candidate facility is opened:

$$
\kappa_d \le h_d \cdot \text{MaxCandStatic}_d \quad \forall d \in D_{\text{cand}}
$$

This single constraint guarantees that a closed candidate ($h_d = 0$) has $\kappa_d = 0$, which through Constraints 3 and 4 forces all inventory and flow to zero at that facility.

* **5d. Bulkification Continuous Quantity Bounding:** The quantity of handling capacity added to warehouse $d$ is continuous and bounded by the maximum allowed bulkification capacity parameter. It can only take a positive value if bulkification is activated ($y^{\text{bulk}}_d = 1$):

$$
q^{\text{bulk}}_d \le y^{\text{bulk}}_d \cdot \text{MaxBulk}_d \quad \forall d \in D
$$

* **5e. Continuous Expansion Bounding:** The quantity of static capacity added to warehouse $d$ is continuous and bounded by the maximum allowed expansion parameter. It can only take a positive value if the expansion decision is activated ($y^{\text{exp}}_d = 1$):

$$
g_d \le y^{\text{exp}}_d \cdot \text{MaxExpand}_d \quad \forall d \in D
$$

#### 6. Customer Demand Satisfaction Constraints

The flow reaching customers is split into two separate constraints, separating domestic fulfillment from export demands.

* **6a. Domestic Demand Satisfaction (Hard Equality):**
For all domestic consumption regions, incoming warehouse shipments must meet the domestic consumption requirements exactly:

$$
\sum_{\{d \mid (d,c,p) \in R_{DCP}\}} z_{dcpt} = \text{Dem}^{\text{dom}}_{cpt} \quad \forall c \in C_{\text{dom}},\ p \in P,\ t \in T
$$

* **6b. Export Demand Bounds (Hard Upper Bound):**
For all export destinations, total incoming shipments are restricted by the export ceiling:

$$
\sum_{\{d \mid (d,c,p) \in R_{DCP}\}} z_{dcpt} \le \text{Dem}^{\text{exp}}_{cpt} \quad \forall c \in C_{\text{exp}},\ p \in P,\ t \in T
$$

*Mathematical Note on Export Ceiling:*
To model an unconstrained (infinite) export customer $c \in C_{\text{exp}}$ in period $t$, institutional planners define the parameter as the total available supply across the network:

$$
\text{Dem}^{\text{exp}}_{cpt} = \sum_{o \in O} S_{opt} \quad \forall c \in C_{\text{exp}},\ p \in P,\ t \in T
$$

This behaves as a non-binding upper limit and guarantees feasibility: because domestic demand is a hard equality and supply must be fully dispatched, any surplus is absorbed by export nodes. No grain is stranded in the network.

#### 7. Auxiliary Evaluation Metric (For Academic and Post-Optimization Analysis)

**[CHANGED]** The Dynamic Capacity ($\text{DynCap}_d$) is **computed outside the solver** as a post-optimization calculation to avoid introducing non-linear or bilinear terms into the constraint matrix.

* **7a. Dynamic Capacity (Post-Solve Calculation):**

$$
\text{DynCap}_d = \sum_{p \in P} \sum_{t \in T} \text{Outflow}_{dpt} + \sum_{p \in P} e_{dp,\, t_{\text{end}}} \quad \forall d \in D
$$

* **7b. Turnover Ratio (Post-Solve Calculation):**

**[REMOVED from model]** The Turnover Ratio is defined conceptually as:

$$
\text{Turnover}_d = \frac{\text{DynCap}_d}{\text{EffectiveStaticCap}_d} \quad \text{where } \text{EffectiveStaticCap}_d > 0
$$

With effective static capacity equal to $\text{StaticCap}_d + g_d$ for existing warehouses and $\kappa_d + g_d$ for candidates. Both metrics are computed in Python after the solver terminates:

```python
# Post-Solve Computation — Dynamic Capacity and Turnover
for d in model.Destinations:
    total_outflow = sum(
        value(model.FlowDC[d, c, p, t])
        for (d2, c, p) in model.ValidRoutesDC if d2 == d
        for t in model.TimePeriods
    ) + sum(
        value(model.FlowDD[d, d2, p, t])
        for (d1, d2, p) in model.ValidRoutesDD if d1 == d
        for t in model.TimePeriods
    )
    final_stock = sum(
        value(model.Inventory[d, p, model.TimePeriods.last()])
        for p in model.Products
    )
    dyn_cap = total_outflow + final_stock

    if d in model.Destinations_exist:
        effective_static = value(model.StaticCapacity[d]) + value(model.ExpandedCapacity[d])
    else:  # candidate
        effective_static = value(model.CandStaticCapacity[d]) + value(model.ExpandedCapacity[d])

    turnover = dyn_cap / effective_static if effective_static > 0 else None
```

#### 8. Variable Domains

$$
x_{odpt} \ge 0 \quad \forall (o,d,p) \in R_{ODP},\ t \in T
$$

$$
z_{dcpt} \ge 0 \quad \forall (d,c,p) \in R_{DCP},\ t \in T
$$

$$
y_{d_1d_2pt} \ge 0 \quad \forall (d_1,d_2,p) \in R_{DDP},\ t \in T
$$

$$
e_{dpt} \ge 0 \quad \forall d \in D,\ p \in P,\ t \in T
$$

$$
\kappa_d \ge 0 \quad \forall d \in D_{\text{cand}}
$$

$$
g_d \ge 0 \quad \forall d \in D
$$

$$
q^{\text{bulk}}_d \ge 0 \quad \forall d \in D
$$

$$
h_d \in \{0, 1\} \quad \forall d \in D_{\text{cand}} \quad \text{(fixed parameter } h_d = 1 \text{ for } d \in D_{\text{exist}}\text{)}
$$

$$
y^{\text{exp}}_d \in \{0, 1\} \quad \forall d \in D
$$

$$
y^{\text{bulk}}_d \in \{0, 1\} \quad \forall d \in D
$$

---

## 4. Architectural Analysis: Formulating the Advanced Multi-Period Engine

By transitioning from a static allocation formulation to this multi-period, multi-commodity transshipment MILP, the model matches the architectural requirements of strategic national network planning.

```
 [ Harvest Origins (o) ]
       | (Continuous flow, full dispatch equality)
       v
 [ Storage & Transshipment (d) ] <==> [ Hub-to-Hub (d1 -> d2) ]
   * Existing: fixed StaticCap, ReceptionCap, ShippingCap
   * Candidate: decided kappa_d, beta-scaled reception/shipping
   * Physical Expansion (g_d, y^exp)
   * Bulkification Silos (q^bulk, y^bulk)
       | (Inventory Carry-Over, Facility Selection)
       +-------------------------+
       |                         |
       v                         v
 [ Domestic Customers (c_dom) ] [ Export Customers (c_exp) ]
  (Strict Equal Demand Target)   (Hard Max / System Clearing Sink)
```

### 1. Inventory Conservation Over Time (Carry-over Loop)

Unlike static allocation models where all shipped materials must be immediately consumed, this model incorporates the temporal coupling of storage. The dynamic inventory state equation:

$$
e_{dpt} = e_{dp,t-1} + \text{Inflow}_{dpt} - \text{Outflow}_{dpt}
$$

allows the solver to store commodities during low-tariff periods or high-supply harvest months and hold them inside the static capacity envelope until peak customer demand periods. This enables simulation of strategic stocks over multi-month planning horizons.

### 2. Candidate Facility Location and Sizing

Rather than treating the warehouse network as a static set, the binary variable $h_d \in \{0,1\}$ paired with the continuous sizing variable $\kappa_d$ and the parameter $\text{OpenCost}_d$ jointly constitute a **capacitated facility location and sizing problem**. The solver simultaneously decides:
- **Whether** to open each candidate ($h_d$),
- **How large** to build it ($\kappa_d \le h_d \cdot \text{MaxCandStatic}_d$), and
- **Whether** to further upgrade it via expansion or bulkification.

This reflects realistic infrastructure planning, where the physical footprint of a new terminal is itself a strategic decision rather than a given.

### 3. Sparse Transshipment Routing

The model splits routing into three distinct sparse sets ($R_{ODP}$, $R_{DCP}$, $R_{DDP}$). This achieves two design goals:

* **Compatibility Enforcement:** Any variables for incompatible pairs are pruned automatically. If a warehouse $d$ cannot store soy ($\text{Compatible}_{\text{Soy}, \text{Tipo}_d} = 0$), no elements containing $(\cdot, d, \text{Soy})$ exist in the sparse sets.

* **Pareto Filter Scaling:** By pre-filtering only the top 20% shortest paths into these sets, the solver bypasses millions of unnecessary long-distance variables, enabling the model to scale to continent-sized national grain distribution networks.

### 4. Cohesive Customer Layer Design (Surplus-to-Export Clearing Logic)

Supply from origins is a hard equality constraint: all harvested grain enters the network. Domestic demand is also a strict equality: domestic consumption absorbs its exact required volume. Any remaining flow — including harvest surplus exceeding domestic demand — has only one mathematically open pathway: export channels.

Export nodes are configured with $\text{Dem}^{\text{exp}}_{cpt} = \sum_{o} S_{opt}$, making the ceiling non-binding and turning export destinations into perfect **system clearing sinks**. This eliminates the need for artificial slack variables or penalty-based infeasibility handling.

### 5. Upgrade Economics: Physical Expansion vs. Bulkification

Both upgrade pathways share a symmetrical economic structure — a fixed activation cost plus a variable cost per unit added — but differ in what they expand:

* **Physical Expansion (storage-heavy):** $g_d$ directly grows the static storage envelope and proportionally scales both handling rates via $\beta^{\text{rec}}$ and $\beta^{\text{ship}}$.

* **Bulkification (throughput-heavy):** $q^{\text{bulk}}_d$ adds directly to both daily reception and shipping rates without touching the static storage envelope. Strategically targets fast transshipment terminals where velocity is preferred over grain banking.

The mutual exclusion constraint ($y^{\text{exp}}_d + y^{\text{bulk}}_d \le h_d$) forces the MILP solver to select the single most economically viable modernization path per terminal.

### 6. Research Dimension: Dynamic Capacity and Asset Turnover

Post-solve, the Dynamic Capacity ($\text{DynCap}_d$) and Turnover Ratio ($\text{Turnover}_d$) provide deeper analytical insight beyond static capacity limits:

* **Static vs. Dynamic Footprints:** A terminal with low static storage but high-speed bulkified handling can achieve vastly higher dynamic throughput than a massive but slow regional grain bank. $\text{DynCap}_d$ captures the total material that successfully crossed the facility plus what remained at period end.

* **Capital Efficiency and Node Classification:**
  * **High Storage, Low Turnover ($\text{Turnover}_d \le 1.0$):** Strategic safety reserves — seasonal hubs that hold inventory over long durations to absorb harvest shocks.
  * **Low Storage, High Turnover ($\text{Turnover}_d \gg 1.0$):** Rapid transshipment gateways — fast mechanized systems moving massive flows through a minimal physical footprint.

These metrics are computed entirely in post-solve Python (see Constraint 7), preserving the LP/MILP linearity of the solver model.
