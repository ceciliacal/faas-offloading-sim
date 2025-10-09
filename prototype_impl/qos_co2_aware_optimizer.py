import os
import json
import math
import sys
import pulp as pl

import conf

warm_start = False

m_u = 2048.0

class OptCarbonAwareProblemParams:
    #todo: su FGCS guarda in solver.go & metricGrabber.go
    #todo: su offloading guarda remotePolicyParams in remote_offloading_policy.go
    #info di attributi in classi Node, Function, Class vanno passate separatamente (es memory, speedup nodo ecc)
    def __init__(self):
        #self.local_node = None
        self.cloud_regions = {} #<region_name, list> : [aggregated_memory, co2_intensity, avg_processing_power_consumption,avg_tx_energy_consumption, avg_rx_energy_consumption]
        self.possible_decisions = set() #["EXEC","OFFLOAD_EDGE","OFFLOAD_CLOUD_{r}","DROP"]
        self.functions = set()  #[f.name]
        self.classes = set()    #[c.name]
        #self.variants = {}
        self.arrival_rates = {} #{(f,c):lambda}
        self.serv_time_local = {} #{f.name:float}
        self.serv_time_cloud = {} #{[region.name, f.name]:float}
        self.init_time_local = {} #{f.name:float}
        self.init_time_cloud = {} #{[region.name, f.name]:float}
        self.cold_start_p_local = {} #{f.name:float}
        self.cold_start_p_cloud = {} #{[region.name, f.name]:float}
        self.offload_time_cloud = {} #cloud rtt: nodo-nodo
        self.bandwidth_cloud = {} #cloud bw: nodo-nodo
        self.usable_local_memory_coeff = 1.0
        self.budget = -1.0
        self.aggregated_edge_memory = 0.0
        self.serv_time_edge = {} #{f.name:float}
        self.offload_time_edge = 0.0
        self.cold_start_p_edge = {} #{f.name:float}
        self.init_time_edge = {} #{f.name:float}
        self.bandwidth_edge = float("inf")
        self.aggregated_edge_power_consumption = float("inf")
        self.aggregated_edge_energy_tx = float("inf")
        self.aggregated_edge_energy_rx = float("inf")
        self.co2_green_threshold = float("inf")
        self.alpha = 0.0
        self.beta = 0.0

        # Flattened "local node"
        self.node_memory = float("inf")
        self.node_co2_footprint = float("inf")
        self.node_processing_power_consumption = float("inf")
        self.node_tx_energy_consumption = float("inf")  # J/byte after conversion
        self.node_rx_energy_consumption = float("inf")

        # Per-function & per-class scalar dictionaries
        self.function_memory = {}  # f.name -> MB (or consistent unit)
        self.function_input_size_mean = {}  # f.name -> bytes
        self.function_output_size_mean = {}  # f.name -> bytes
        self.class_maxRt = {}  # c.name -> sec
        self.class_utility = {}  # c.name -> scalar
        self.class_deadline_penalty = {}  # c.name -> scalar
        self.class_drop_penalty = {}  # c.name -> scalar

    def fun_classes(self):
        for f in self.functions:
            for c in self.classes:
                yield (f, c)

    # --------- READERS ----------
    @classmethod
    def from_json(cls, json_str: str) -> "OptCarbonAwareProblemParams":
        """Create params from a JSON string matching the sample structure."""
        data = json.loads(json_str)
        return cls._from_mapping(data)

    @classmethod
    def from_file(cls, path: str) -> "OptCarbonAwareProblemParams":
        """Create params from a JSON file on disk."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls._from_mapping(data)

    # --------- INTERNAL HELPER ----------
    @classmethod
    def _from_mapping(cls, data: dict) -> "OptCarbonAwareProblemParams":
        p = cls()

        # sets / simple collections
        if "cloud_regions" in data:              p.cloud_regions = dict(data["cloud_regions"])
        if "possible_decisions" in data:         p.possible_decisions = set(data["possible_decisions"])
        if "functions" in data:                  p.functions = set(data["functions"])
        if "classes" in data:                    p.classes = set(data["classes"])

        # dicts (copy as-is, structure already JSON-friendly)
        for k in [
            "arrival_rates", "serv_time_local", "serv_time_cloud",
            "init_time_local", "init_time_cloud", "cold_start_p_local",
            "cold_start_p_cloud", "offload_time_cloud", "bandwidth_cloud",
            "serv_time_edge", "cold_start_p_edge", "init_time_edge",
            "function_memory", "function_input_size_mean", "function_output_size_mean",
            "class_maxRt", "class_utility", "class_deadline_penalty",
            "class_drop_penalty"
        ]:
            if k in data:
                setattr(p, k, data[k])

        # scalars with safe defaults
        p.usable_local_memory_coeff = float(data.get("usable_local_memory_coeff", p.usable_local_memory_coeff))
        p.budget = float(data.get("budget", p.budget))
        p.aggregated_edge_memory = float(data.get("aggregated_edge_memory", p.aggregated_edge_memory))
        p.offload_time_edge = float(data.get("offload_time_edge", p.offload_time_edge))
        p.bandwidth_edge = float(data.get("bandwidth_edge", p.bandwidth_edge))
        p.aggregated_edge_power_consumption = float(
            data.get("aggregated_edge_power_consumption", p.aggregated_edge_power_consumption))
        p.aggregated_edge_energy_tx = float(data.get("aggregated_edge_energy_tx", p.aggregated_edge_energy_tx))
        p.aggregated_edge_energy_rx = float(data.get("aggregated_edge_energy_rx", p.aggregated_edge_energy_rx))
        p.co2_green_threshold = float(data.get("co2_green_threshold", p.co2_green_threshold))
        p.alpha = float(data.get("alpha", p.alpha))
        p.beta = float(data.get("beta", p.beta))

        p.node_memory = float(data.get("node_memory", p.node_memory))
        p.node_co2_footprint = float(data.get("node_co2_footprint", p.node_co2_footprint))
        p.node_processing_power_consumption = float(
            data.get("node_processing_power_consumption", p.node_processing_power_consumption))
        p.node_tx_energy_consumption = float(data.get("node_tx_energy_consumption", p.node_tx_energy_consumption))
        p.node_rx_energy_consumption = float(data.get("node_rx_energy_consumption", p.node_rx_energy_consumption))

        return p




#todo: per optimizer, devo solo togliere strutture e tenere dictionaries (piu o meno come ho gia fatto)
#todo: per arrival rates, li calcolo x finestra temporale di update in nodo edge e passo già arrival rate!


class MyLPOptimizer:

    def extract_region_metrics(self, region_list):
        """
        Converts a list of region dicts into a dictionary with region_name as key and
        a list of 5 floats as value:
        [aggregated_memory, co2_intensity, avg_processing_power_consumption,
         avg_tx_energy_consumption, avg_rx_energy_consumption]

        Parameters:
            region_list (list): List of dictionaries, each representing a region.

        Returns:
            dict: Dictionary mapping region_name to a list of 5 float values.
                {
                'cloud1': [1000.0, 10.5, 20.3, 5.0, 4.8],
                ('region_name':[aggregated_memory, co2_intensity, avg_processing_power_consumption,avg_tx_energy_consumption, avg_rx_energy_consumption])
                'cloud2': [1000.0, 15.2, 25.1, 6.2, 3.9]
                }
        """
        result = {}
        for region in region_list:
            name = region.get("region_name")
            values = [
                region.get("aggregated_memory", 0.0),
                region.get("co2_intensity", 0.0),
                region.get("avg_processing_power_consumption", 0.0),#todo: xke edge?!
                region.get("avg_tx_energy_consumption", 0.0),
                region.get("avg_rx_energy_consumption", 0.0)
            ]
            result[name] = values
        return result


    def _as_nested_arrival(self, arrival_rates):
        # accept {(f,c): lam} or {f:{c:lam}}
        nested = {}
        for k, v in arrival_rates.items():
            if isinstance(k, tuple) and len(k) == 2:
                f, c = k
                nested.setdefault(f, {})[c] = v
            else:
                # assume nested already
                return arrival_rates
        return nested

    def solve(self, p: OptCarbonAwareProblemParams):
        F = list(p.functions)
        C = list(p.classes)
        R = p.cloud_regions

        F_C = [(f, c) for f in F for c in C]

        EDGE_ENABLED = p.aggregated_edge_memory > 0.0

        ar_nested = self._as_nested_arrival(p.arrival_rates)
        lam = {(f, c): ar_nested.get(f, {}).get(c, 0.0) for f in F for c in C}

        prob = pl.LpProblem("MyProblem", pl.LpMaximize)

        x = pl.LpVariable.dicts("X", (F, C), 0, None, pl.LpContinuous)
        y = pl.LpVariable.dicts("Y", (F, C), 0, None, pl.LpContinuous)
        pC = {}
        pL = pl.LpVariable.dicts("PExec", (F, C), 0, 1, pl.LpContinuous)
        pD = pl.LpVariable.dicts("PDrop", (F, C), 0, 1, pl.LpContinuous)
        pE = pl.LpVariable.dicts("PEdge", (F, C), 0, 1, pl.LpContinuous) if EDGE_ENABLED else None
        for region in R:
            pC[region] = pl.LpVariable.dicts(f"PCloud_{region}", (F, C), 0, 1, pl.LpContinuous)

        '''
               (deadline_satisfaction_prob_local,
         deadline_satisfaction_prob_cloud,
         deadline_satisfaction_prob_edge)\ 
        '''

        deadline_satisfaction_prob_local, deadline_satisfaction_prob_edge, deadline_satisfaction_prob_cloud= self.compute_deadline_satisfaction_probs(p, region_metrics=R)

        #eP_local, eP_local_variants, eP_offlading_cloud, eP_offloading_edge, co2_drop = compute_energy_consumption(p)
        eP_local, eP_offlading_cloud, eP_offloading_edge, co2_drop = self.compute_energy_consumption(p, region_metrics=R)

        alpha, beta = p.alpha, p.beta

        # TODO: Continua qui!

        # objective
        util = pl.lpSum([
            p.class_utility[c] * lam[(f,c)] * (
                pL[f][c] * deadline_satisfaction_prob_local[(f,c)]
                + (pE[f][c] * deadline_satisfaction_prob_edge[(f,c)] if EDGE_ENABLED else 0.0)
                + pl.lpSum([pC[r][f][c] * deadline_satisfaction_prob_cloud[(r,f,c)] for r in R])
            )
            for f in F for c in C
        ])

        deadline_pen = pl.lpSum([
            p.class_deadline_penalty[c] * lam[(f, c)] * (
                    pL[f][c] * (1.0 - deadline_satisfaction_prob_local[(f, c)])
                    + (pE[f][c] * (1.0 - deadline_satisfaction_prob_edge[(f, c)]) if EDGE_ENABLED else 0.0)
                    + pl.lpSum([pC[r][f][c] * (1.0 - deadline_satisfaction_prob_cloud[(r, f, c)]) for r in R])
            )
            for f in F for c in C
        ])

        drop_pen = pl.lpSum([
            p.class_drop_penalty[c] * lam[(f, c)] * pD[f][c]
            for f in F for c in C
        ])

        energy = pl.lpSum([
            lam[(f, c)] * (
                    pL[f][c] * eP_local[f]
                    + (pE[f][c] * eP_offloading_edge.get(f, 0.0) if EDGE_ENABLED else 0.0)
                    + pD[f][c] * co2_drop
                    + pl.lpSum([pC[r][f][c] * eP_offlading_cloud[r][f] for r in R])
            )
            for f in F for c in C
        ])

        prob += alpha * (util - deadline_pen - drop_pen) - beta * energy

        for f in F:
            for c in C:
                prob += (
                        pL[f][c]
                        + (pE[f][c] if EDGE_ENABLED else 0.0)
                        + pl.lpSum([pC[r][f][c] for r in R])
                        + pD[f][c] == 1.0
                )

        # memory constraints (local/edge)
        prob += pl.lpSum([p.function_memory[f] * x[f][c] for f in F for c in C]) \
                <= p.usable_local_memory_coeff * p.node_memory
        if EDGE_ENABLED:
            prob += pl.lpSum([p.function_memory[f] * y[f][c] for f in F for c in C]) \
                    <= p.aggregated_edge_memory

        # share constraints
        for f in F:
            stL = p.serv_time_local.get(f, 0.0)
            for c in C:
                prob += pL[f][c] * lam[(f, c)] * stL <= x[f][c]
                if EDGE_ENABLED:
                    stE = p.serv_time_edge.get(f, 0.0)
                    prob += pE[f][c] * lam[(f, c)] * stE <= y[f][c]

        # (Optional) budget or class min completion, add if you use them.

        # solve
        prob.writeLP("problem.lp")
        status = self.__solve(prob)
        if status != "Optimal":
            return status, None

        obj = pl.value(prob.objective)
        if obj is None:
            print(f"WARNING: objective is None")
            return None

        # === populating prob vector ===
        decision_fc_probability = {}
        decision_fc_probability_var = {}
        decision_eP = {}

        for scheduler_decision in p.possible_decisions:
            if "EXEC" == scheduler_decision:
                decision_fc_probability[scheduler_decision] = pL
                #decision_eP[scheduler_decision] = eP_local

            elif "EDGE_ENABLED" in scheduler_decision:
                if not EDGE_ENABLED:
                    for f, c in F_C:
                        pE[f][c] = 0.0
                        eP_offloading_edge[f] = 0.0
                decision_fc_probability[scheduler_decision] = pE
                #decision_eP[scheduler_decision] = eP_offloading_edge
            elif "DROP" in scheduler_decision:
                decision_fc_probability[scheduler_decision] = pD
            elif "CLOUD" in scheduler_decision:
                cloud_key = scheduler_decision[len(conf.OFFLOAD_CLOUD_DECISION):].lower()
                decision_fc_probability[scheduler_decision] = pC[cloud_key]
                #decision_eP[scheduler_decision] = eP_offlading_cloud[cloud_key]

        probs = {}

        # populating probs with updated values
        for decision, f_c_probabilities in decision_fc_probability.items():
            for function, classes in f_c_probabilities.items():
                for service_class, probability in classes.items():
                    # Create the key based on function and service class
                    key = (function, service_class)
                    if key not in probs:
                        probs[key] = {}
                    # Add the decision and its corresponding probability to each (f,c) pair
                    probs[key][decision] = pl.value(probability)

        # workaround to avoid numerical issues
        for f, c in F_C:
            s = 0
            for decision, probability in probs[(f, c)].items():
                s = s + probability
            if s > 0:
                probs[(f, c)] = {decision: prob / s for decision, prob in probs[(f, c)].items()}


        #TODO: METRICHE X NODO CHE FA REQ - populating local node's updated emissions calculation
        '''
        for f in F:
            #exec_var_key = next((decision for decision in decision_eP if "VAR" in decision.name), None)
            for decision, eP in decision_eP.items():
                if "VAR" not in decision.name:
                    p.node_co2_footprint[f][decision] = eP[f]
         
            if f.has_variants and exec_var_key:
                for v in V[f]:
                    params.local_node.g_co2_emissions[v][exec_var_key] = decision_eP.get(exec_var_key, {}).get((f, v),

        '''

        # print("[optimizer] -  probs: ",probs)
        return probs #, decision_fc_probability_var

    def compute_deadline_satisfaction_probs(self, params: OptCarbonAwareProblemParams, region_metrics: dict):
        deadline_satisfaction_prob_local = {}
        deadline_satisfaction_prob_edge = {}
        deadline_satisfaction_prob_cloud = {}  # key:(region,f,c) - value:resp_time

        # Probability of satisfying the deadline
        for f, c in params.fun_classes():
            max_rt = params.class_maxRt[c]

            # Default variant local execution
            p = 0.0
            if max_rt - params.init_time_local[f] > 0.0:
                p += params.cold_start_p_local[f] * (
                            1.0 - math.exp(-1.0 / params.serv_time_local[f] * (max_rt - params.init_time_local[f])))
            if max_rt > 0.0:
                p += (1.0 - params.cold_start_p_local[f]) * (
                            1.0 - math.exp(-1.0 / params.serv_time_local[f] * max_rt))
            deadline_satisfaction_prob_local[(f, c)] = p


            for region, dispatcher_attributes in region_metrics.items():
                aggregated_region_memory = dispatcher_attributes[0] #todo continua
                if aggregated_region_memory > 0.0:
                    p = 0.0
                    tx_time = params.function_input_size_mean[f] * 8 / 1000 / 1000 / params.bandwidth_cloud[region]

                    if max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[region] - tx_time > 0.0:
                        p += params.cold_start_p_cloud[region][f] * (
                                    1.0 - math.exp(-1.0 / params.serv_time_cloud[region][f] * (
                                    max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[
                                region] - tx_time)))
                    if max_rt - params.offload_time_cloud[region] - tx_time > 0.0:
                        p += (1.0 - params.cold_start_p_cloud[region][f]) * (1.0 - math.exp(
                            -1.0 / params.serv_time_cloud[region][f] * (
                                        max_rt - params.offload_time_cloud[region] - tx_time)))
                    deadline_satisfaction_prob_cloud[(region, f, c)] = p

            if params.aggregated_edge_memory > 0.0:
                p = 0.0
                try:
                    tx_time = params.function_input_size_mean[f] * 8 / 1000 / 1000 / params.bandwidth_edge

                    if max_rt - params.init_time_edge[f] - params.offload_time_edge - tx_time > 0.0:
                        p += params.cold_start_p_edge[f] * (1.0 - math.exp(-1.0 / params.serv_time_edge[f] * (
                                max_rt - params.init_time_edge[f] - params.offload_time_edge - tx_time)))
                    if max_rt - params.offload_time_edge - tx_time > 0.0:
                        p += (1.0 - params.cold_start_p_edge[f]) * (1.0 - math.exp(
                            -1.0 / params.serv_time_edge[f] * (max_rt - params.offload_time_edge - tx_time)))
                except:
                    pass
                deadline_satisfaction_prob_edge[(f, c)] = p
            else:
                deadline_satisfaction_prob_edge = {fc: 0 for fc in params.fun_classes()}

        return deadline_satisfaction_prob_local, deadline_satisfaction_prob_edge, deadline_satisfaction_prob_cloud

    def compute_energy_consumption(self, params: OptCarbonAwareProblemParams, region_metrics: dict):
        """
          region_metrics: dict[str, list[float]]
              {
                "<region_name>": [
                    aggregated_memory,
                    co2_intensity,
                    aggregated_power_consumption,
                    aggregated_energy_tx,
                    aggregated_energy_rx
                ],
                ...
              }
          """
        # ---- indices for readability ----
        IDX_MEM = 0
        IDX_CO2 = 1
        IDX_PWR = 2
        IDX_TX = 3
        IDX_RX = 4

        # CO2 drop value
        co2_values = [metrics[IDX_CO2] for metrics in region_metrics.values()]
        min_co2_intensity = min(co2_values) if co2_values else 0.0
        co2_drop = min_co2_intensity / max(
            float(params.node_co2_footprint),
            *co2_values
        )
        large_penalty = 1e6

        eP_local = {}
        eP_local_variants = {}
        eP_offloading_edge = {}
        eP_offloading_cloud = {}

        for f in params.functions:
            # Local energy
            local_consumption = compute_local_energy(
                m_f=params.function_memory[f],
                current_memory=params.node_memory,
                processing_power_consumption=params.node_processing_power_consumption,
                serv_time_local=params.serv_time_local[f],
                co2_local=params.node_co2_footprint
            )
            if local_consumption == 0.0:
                local_consumption = large_penalty
            eP_local[f] = local_consumption

            #todo: add variants

            # Edge energy
            edge_consumption = compute_edge_energy(
                m_f=params.function_memory[f],
                input_size_mean=params.function_input_size_mean[f],
                output_size_mean=params.function_output_size_mean[f],
                aggregated_edge_memory=params.aggregated_edge_memory,
                aggregated_edge_power_consumption=params.aggregated_edge_power_consumption,
                serv_time_edge=params.serv_time_edge[f],
                local_tx_energy=params.node_tx_energy_consumption,
                edge_rx_energy=params.aggregated_edge_energy_rx,
                local_rx_energy=params.node_rx_energy_consumption,
                edge_tx_energy=params.aggregated_edge_energy_tx,
                co2_edge=params.node_co2_footprint
            )
            if edge_consumption == 0.0:
                edge_consumption = large_penalty
            eP_offloading_edge[f] = edge_consumption

            # Cloud energy
            for region, dispatcher_attributes in region_metrics.items():
                if region not in eP_offloading_cloud:
                    eP_offloading_cloud[region] = {}

                memory_region = dispatcher_attributes[IDX_MEM]
                co2_region = dispatcher_attributes[IDX_CO2]
                processing_power_consumption = dispatcher_attributes[IDX_PWR]
                tx_energy = dispatcher_attributes[IDX_TX]
                rx_energy = dispatcher_attributes[IDX_RX]

                #todo: tolto il random cloud node x trasferimento dispatcher - nodo cloud
                cloud_consumption = compute_cloud_energy(
                    m_f=params.function_memory[f],
                    input_size_mean=params.function_input_size_mean[f],
                    output_size_mean=params.function_output_size_mean[f],
                    aggregated_region_memory=memory_region,
                    avg_processing_power_consumption=processing_power_consumption,
                    serv_time_cloud=params.serv_time_cloud[region][f],
                    local_tx_energy=params.node_tx_energy_consumption,
                    dispatcher_rx_energy=rx_energy,
                    local_rx_energy=params.node_rx_energy_consumption,
                    dispatcher_tx_energy=tx_energy,
                    co2_cloud=co2_region
                )
                if cloud_consumption == 0.0:
                    cloud_consumption = large_penalty
                eP_offloading_cloud[region][f] = cloud_consumption

        return eP_local, eP_offloading_cloud, eP_offloading_edge, co2_drop


    def __solve(self, problem):
        global warm_start
        solver_name = os.environ.get("PULP_SOLVER", "GLPK_CMD")

        if not solver_name in ["CPLEX_CMD", "GUROBI_CMD", "PULP_CBC_CMD", "CBC_CMD", "CPLEX_PY",
                               "GUROBI"] and warm_start:
            print("WARNING: warmStart not supported by solver {}".format(solver_name))
            warm_start = False

        if not warm_start:
            if solver_name == "GUROBI_CMD":
                solver = pl.getSolver(solver_name, gapRel=0.02, timeLimit=900)
            else:
                solver = pl.getSolver(solver_name, msg=False)
        else:
            solver = pl.getSolver(solver_name, warmStart=warm_start)

        problem.solve(solver)
        return pl.LpStatus[problem.status]



def compute_edge_energy(m_f, input_size_mean, output_size_mean, aggregated_edge_memory, aggregated_edge_power_consumption,
                        serv_time_edge, local_tx_energy, edge_rx_energy, local_rx_energy, edge_tx_energy, co2_edge):
    #Compute the emitted co2 grams for a function offloaded to the edge.
    #m_f = function.memory
    #input_size_mean = function_input_size_mean
    #output_size_mean = function_output_size_mean

    if aggregated_edge_memory <= 0.0:
        return 0.0


    return (
        ((aggregated_edge_power_consumption * float(m_f / m_u) * serv_time_edge) +
         input_size_mean * (local_tx_energy + edge_rx_energy) +
         output_size_mean * (edge_tx_energy + local_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_edge)
    )

def compute_local_energy(m_f, current_memory, processing_power_consumption,
                         serv_time_local, co2_local):
    #m_f = function_memory

    if current_memory <= 0.0:
        return 0.0

    return (
        (processing_power_consumption * float(m_f / m_u) * serv_time_local) *
        (1 / (3600 * 1000)) *
        float(co2_local)
    )

def compute_cloud_energy(m_f, input_size_mean, output_size_mean,
                         aggregated_region_memory,
                         avg_processing_power_consumption,
                         serv_time_cloud,
                         local_tx_energy,
                         dispatcher_rx_energy,
                         local_rx_energy,
                         dispatcher_tx_energy,
                         co2_cloud):
    #m_f = function.memory
    #input_size_mean = function_input_size_mean
    #output_size_mean = function_output_size_mean

    if aggregated_region_memory <= 0.0:
        return 0.0

    return (
        ((avg_processing_power_consumption * float(m_f / m_u) * serv_time_cloud) +
         input_size_mean * (local_tx_energy + dispatcher_rx_energy) +
         output_size_mean * (dispatcher_tx_energy + local_rx_energy)) *
        (1 / (3600 * 1000)) *
        float(co2_cloud)
    )


def main():
    try:
        params_file_name = "sample_params.json"
        params = OptCarbonAwareProblemParams.from_file(params_file_name)
    except FileNotFoundError:
        print(f"Error: file not found: {params_file_name}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error while reading/parsing JSON: {e}", file=sys.stderr)
        sys.exit(2)

    # Quick sanity print
    print("✓ Parameters loaded")
    print(f"- Regions: {list(params.cloud_regions)}")
    print(f"- Functions: {sorted(list(params.functions))}")
    print(f"- Classes: {sorted(list(params.classes))}")
    print(f"- Possible decisions: {sorted(list(params.possible_decisions))}")
    print(f"- Budget: {params.budget}")
    print(f"- Usable local memory coeff: {params.usable_local_memory_coeff}")

    # Show an example nested lookup (if present)
    if params.serv_time_cloud:
        region = next(iter(params.serv_time_cloud))
        f = next(iter(params.serv_time_cloud[region])) if params.serv_time_cloud[region] else None
        if f:
            print(f"- Example serv_time_cloud[{region}][{f}] = {params.serv_time_cloud[region][f]}")
    #todo: confronta con chat x p_cloud_regions ecc
    optimizer = MyLPOptimizer()
    probs = optimizer.solve(params)
    print("probs: ",probs)
if __name__ == "__main__":
    main()


    '''
    elif "VAR" in scheduler_decision.name:
        decision_fc_probability_var = pL_variants
        decision_fc_probability[scheduler_decision] = {}
        for f in F:
            decision_fc_probability[scheduler_decision][f] = {}
            decision_eP[scheduler_decision] = eP_local_variants
            for c in C:
                sum_prob_variants = 0.0
                if f.has_variants:
                    # Summing probabilities of all variants for function f and class c
                    sum_prob_variants = sum((pL_variants[f][v][c]).varValue for v in V[f])
    
                decision_fc_probability[scheduler_decision][f][c] = sum_prob_variants
    '''