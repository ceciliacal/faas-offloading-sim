import os
from asyncore import dispatcher

import conf
import math
import pulp as pl

from co2_footprint import compute_cloud_energy, compute_edge_energy, compute_local_variant_energy, compute_local_energy
from infrastructure import Infrastructure
from optimization_carbon_aware import OptCarbonAwareProblemParams

warm_start = False


def compute_deadline_satisfaction_probs(params: OptCarbonAwareProblemParams):
    deadline_satisfaction_prob_local = {}
    deadline_satisfaction_prob_local_variants = {}  #key:(f,v,c) - value:resp_time
    deadline_satisfaction_prob_edge = {}
    deadline_satisfaction_prob_cloud = {} #key:(region,f,c) - value:resp_time
    dispatchers = params.cloud_regions_dispatchers

    # TODO: we are assuming exponential distribution
    # Probability of satisfying the deadline
    for f,c in params.fun_classes():

        # Default variant local execution
        p = 0.0
        if c.max_rt - params.init_time_local[f] > 0.0:
            p += params.cold_start_p_local[f] * (1.0 - math.exp(-1.0 / params.serv_time_local[f] * (c.max_rt - params.init_time_local[f])))
        if c.max_rt > 0.0:
            p += (1.0 - params.cold_start_p_local[f]) * (1.0 - math.exp(-1.0 / params.serv_time_local[f] * c.max_rt))
        deadline_satisfaction_prob_local[(f, c)] = p
        #print("==== node: ", params.local_node.name, "mem = ",params.local_node.curr_memory)
        #print("init_time_local: " + str(params.init_time_local[f]))
        #print("serv_time_local: " + str(params.serv_time_local[f]))
        #print("cold_start_p_local: " + str( params.cold_start_p_local[f]))

        # Lighter variant local execution
        if f.has_variants:
            for v in params.variants[f]:
                p = 0.0
                if c.max_rt - params.init_time_local[v] > 0.0:
                    p += params.cold_start_p_local[v]*(1.0 - math.exp(-1.0/params.serv_time_local[v]*(c.max_rt - params.init_time_local[v])))
                if c.max_rt > 0.0:
                    p += (1.0-params.cold_start_p_local[v])*(1.0 - math.exp(-1.0/params.serv_time_local[v]*c.max_rt))
                deadline_satisfaction_prob_local_variants[(f,v,c)] = p

        for region, dispatcher in dispatchers.items():
            if dispatcher.aggregated_region_memory > 0.0:
                p = 0.0
                tx_time = f.inputSizeMean * 8 / 1000 / 1000 / params.bandwidth_cloud[region]
                #print("["+region.name+"]: "+"tx_time: "+str(tx_time))
                #print("["+region.name+"]: "+"init_time_cloud: "+ str(params.init_time_cloud[region][f]))
                #print("[" + region.name + "]: " + "serv_time_cloud: " + str(params.serv_time_cloud[region][f]))
                #print("[" + region.name + "]: " + "offload_time_cloud: " + str(params.offload_time_cloud[region]))
                #print("[" + region.name + "]: " + "cold_start_p_cloud: " + str(params.cold_start_p_cloud[(region,f)]))
                if c.max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[region] - tx_time > 0.0:
                    p += params.cold_start_p_cloud[(region,f)] * (1.0 - math.exp(-1.0 / params.serv_time_cloud[region][f] * (
                                c.max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[region] - tx_time)))
                if c.max_rt - params.offload_time_cloud[region] - tx_time > 0.0:
                    p += (1.0 - params.cold_start_p_cloud[(region,f)]) * (1.0 - math.exp(
                        -1.0 / params.serv_time_cloud[region][f] * (c.max_rt - params.offload_time_cloud[region] - tx_time)))
                deadline_satisfaction_prob_cloud[(region.name, f, c)] = p
                #print("[" + region.name + "]: " + "p: " + str(p))

        if params.aggregated_edge_memory > 0.0:
            p = 0.0
            try:
                tx_time = f.inputSizeMean * 8 / 1000 / 1000 / params.bandwidth_edge
                #print("tx_time edge " + str(tx_time))
                #print("serv_time_edge " + str(params.serv_time_edge[f]))

                if c.max_rt - params.init_time_edge[f] - params.offload_time_edge - tx_time > 0.0:
                    p += params.cold_start_p_edge[f] * (1.0 - math.exp(-1.0 / params.serv_time_edge[f] * (
                                c.max_rt - params.init_time_edge[f] - params.offload_time_edge - tx_time)))
                if c.max_rt - params.offload_time_edge - tx_time > 0.0:
                    p += (1.0 - params.cold_start_p_edge[f]) * (1.0 - math.exp(
                        -1.0 / params.serv_time_edge[f] * (c.max_rt - params.offload_time_edge - tx_time)))
            except:
                pass
            deadline_satisfaction_prob_edge[(f, c)] = p
        else:
            deadline_satisfaction_prob_edge = {fc: 0 for fc in params.fun_classes()}

    #print("node: ",params.local_node.name)
    #print("deadline_satisfaction_prob_local_variants :", deadline_satisfaction_prob_local_variants)
    #print("deadline_satisfaction_prob_local: ", deadline_satisfaction_prob_local)
    #print("deadline_satisfaction_prob_cloud: ", deadline_satisfaction_prob_cloud)
    #print("deadline_satisfaction_prob_edge :", deadline_satisfaction_prob_edge)

    return deadline_satisfaction_prob_local, deadline_satisfaction_prob_local_variants, deadline_satisfaction_prob_cloud, deadline_satisfaction_prob_edge


def compute_energy_consumption(params):
    dispatchers = params.cloud_regions_dispatchers

    # CO2 drop value
    min_co2_intensity = min(dispatcher.co2_footprint.co2_intensity for dispatcher in dispatchers.values())
    co2_drop = min_co2_intensity / max(
        float(params.local_node.co2_footprint.co2_intensity),
        *(float(dispatcher.co2_footprint.co2_intensity) for dispatcher in dispatchers.values())
    )
    large_penalty = 1e6

    eP_local = {}
    eP_local_variants = {}
    eP_offloading_edge = {}
    eP_offloading_cloud = {}

    for f in params.functions:
        # Local energy
        local_consumption = compute_local_energy(
            function=f,
            node=params.local_node,
            serv_time_local=params.serv_time_local[f]
        )
        if local_consumption == 0.0:
            local_consumption = large_penalty
        eP_local[f] = local_consumption

        # Local variant energy
        if f.has_variants:
            for v in params.variants[f]:
                local_variant_consumption = compute_local_variant_energy(
                    function_variant=v,
                    node=params.local_node,
                    serv_time_local_variant=params.serv_time_local[v]
                )
                if local_variant_consumption == 0.0:
                    local_variant_consumption = large_penalty
                eP_local_variants[(f, v)] = local_variant_consumption

        # Edge energy
        edge_consumption = compute_edge_energy(
            function=f,
            aggregated_edge_memory=params.aggregated_edge_memory,
            aggregated_edge_power_consumption=params.aggregated_edge_power_consumption,
            serv_time_edge=params.serv_time_edge[f],
            local_tx_energy=params.local_node.tx_energy_consumption,
            edge_rx_energy=params.aggregated_edge_energy_rx,
            local_rx_energy=params.local_node.rx_energy_consumption,
            edge_tx_energy=params.aggregated_edge_energy_tx,
            co2_edge=params.local_node.co2_footprint.co2_intensity
        )
        if edge_consumption == 0.0:
            edge_consumption = large_penalty
        eP_offloading_edge[f] = edge_consumption

        # Cloud energy
        for region, dispatcher in dispatchers.items():
            if region.name not in eP_offloading_cloud:
                eP_offloading_cloud[region.name] = {}

            random_cloud_node = dispatcher.cloud_nodes_list[0]
            cloud_consumption = compute_cloud_energy(
                function=f,
                dispatcher=dispatcher,
                serv_time_cloud=params.serv_time_cloud[region][f],
                cloud_node=random_cloud_node,
                initial_node=params.local_node
            )
            if cloud_consumption == 0.0:
                cloud_consumption = large_penalty
            eP_offloading_cloud[region.name][f] = cloud_consumption

    #print("node: ", params.local_node.name)
    #print("eP_local :", eP_local)
    #print("eP_offloading_edge: ", eP_offloading_edge)
    #print("eP_offlading_cloud: ", eP_offloading_cloud)
    #print("eP_local_variants :", eP_local_variants)

    return eP_local, eP_local_variants, eP_offloading_cloud, eP_offloading_edge, co2_drop


def update_probabilities(params: OptCarbonAwareProblemParams, VERBOSE=False):
    F = params.functions
    C = params.classes
    F_C = [(f, c) for f in F for c in C]
    dispatchers = params.cloud_regions_dispatchers
    regions = dispatchers.keys()
    V = params.variants

    EDGE_ENABLED = True if params.aggregated_edge_memory > 0.0 else False
    #EDGE_ENABLED = False
    if not EDGE_ENABLED:
        print("EDGE_ENABLED = False")

    if VERBOSE > 1:
        print("------------------------------")
        print(f"Edge memory: {aggregated_edge_memory}")
        print(f"Arrival rates: {arrival_rates}")
        print("------------------------------")

    prob = pl.LpProblem("MyProblem", pl.LpMaximize)
    x = pl.LpVariable.dicts("X", (F, C), 0, None, pl.LpContinuous)
    y = pl.LpVariable.dicts("Y", (F, C), 0, None, pl.LpContinuous)
    pC = {}
    pD = pl.LpVariable.dicts("PDrop", (F, C), 0, 1, pl.LpContinuous)
    pL = pl.LpVariable.dicts("PExec", (F, C), 0, 1, pl.LpContinuous)

    # Variables for variants
    pL_variants = {}
    x_variants = {}

    for f in F:
        if f.has_variants:
            pL_variants[f] = pl.LpVariable.dicts(
                f"PExec",
                (V[f], C),  # Variants have their own dimensions
                0,
                1,
                pl.LpContinuous,
            )
            x_variants[f] = pl.LpVariable.dicts(
                f"X",
                (V[f], C),
                0,
                None,
                pl.LpContinuous)

    #if EDGE_ENABLED:
    pE = pl.LpVariable.dicts("PEdge", (F, C), 0, 1, pl.LpContinuous)

    for region in regions:
        region_name = region.name
        pC[region_name] = pl.LpVariable.dicts(f"PCloud_{region_name}", (F, C), 0, 1, pl.LpContinuous)

    (deadline_satisfaction_prob_local,
     deadline_satisfaction_prob_local_variants,
     deadline_satisfaction_prob_cloud,
     deadline_satisfaction_prob_edge,
     ) = compute_deadline_satisfaction_probs(params)

    eP_local, eP_local_variants, eP_offlading_cloud, eP_offloading_edge, co2_drop = compute_energy_consumption(params)

    if VERBOSE > 1:
        print("------------------------------")
        print(f"ColdStart ProbL: {cold_start_p_local}")
        print(f"ColdStart ProbC: {cold_start_p_cloud}")
        print(f"ColdStart ProbE: {cold_start_p_edge}")
        print(f"Deadline Sat ProbL: {deadline_satisfaction_prob_local}")
        print(f"Deadline Sat ProbC: {deadline_satisfaction_prob_cloud}")
        print(f"Deadline Sat ProbE: {deadline_satisfaction_prob_edge}")
        print("------------------------------")

        # Build the objective function
    alfa = params.alpha
    beta = params.beta
    if EDGE_ENABLED:
        prob += (
            alfa * (
            pl.lpSum([
                c.utility * params.arrival_rates[(f, c)] * (
                        pL[f][c] * deadline_satisfaction_prob_local[(f, c)] +
                        pl.lpSum([pL_variants[f][v.self_function][c] * deadline_satisfaction_prob_local_variants[(f, v.self_function, c)] * v.utility
                                  for v in f.variants] if f.has_variants else 0.0) +
                        pE[f][c] * deadline_satisfaction_prob_edge[(f, c)] +
                        pl.lpSum([pC[region.name][f][c] * deadline_satisfaction_prob_cloud[(region.name, f, c)]
                            for region in regions])
                )
                for f, c in F_C
            ])
            -
            pl.lpSum([
                c.deadline_penalty * params.arrival_rates[(f, c)] * (
                        pL[f][c] * (1.0 - deadline_satisfaction_prob_local[(f, c)]) +
                        pl.lpSum([pL_variants[f][v][c] * (1.0 - deadline_satisfaction_prob_local_variants[(f, v, c)])
                            for v in V[f]] if f.has_variants else 0.0)+
                        pE[f][c] * (1.0 - deadline_satisfaction_prob_edge[(f, c)]) +
                        pl.lpSum([pC[region.name][f][c] * (1.0 - deadline_satisfaction_prob_cloud[(region.name, f, c)])
                            for region in regions])
                )
                for f, c in F_C
            ])
            -
            pl.lpSum([c.drop_penalty * params.arrival_rates[(f, c)] * pD[f][c] for f, c in F_C])
            )
            -
            beta * (
            pl.lpSum([
                params.arrival_rates[(f, c)] * (
                        pL[f][c] * (eP_local[f]) +
                        pl.lpSum([pL_variants[f][v][c] * (eP_local_variants[(f, v)]) for v in V[f]]
                                 if f.has_variants else 0.0) +
                        pE[f][c] * (eP_offloading_edge[f]) +
                        pD[f][c] * (co2_drop) +
                        pl.lpSum([pC[region.name][f][c] * (eP_offlading_cloud[region.name][f]) for region in regions])
                )
                for f, c in F_C
            ])),
            "objUtilCost"
        )

    else:
        prob += (
            alfa * (
                    pl.lpSum([
                        c.utility * params.arrival_rates[(f, c)] * (
                        pL[f][c] * deadline_satisfaction_prob_local[(f, c)] +
                        pl.lpSum([pL_variants[f][v.self_function][c] * deadline_satisfaction_prob_local_variants[(f, v.self_function, c)] * v.utility
                                  for v in f.variants] if f.has_variants else 0.0) +
                        pl.lpSum([pC[region.name][f][c] * deadline_satisfaction_prob_cloud[(region.name, f, c)]
                            for region in regions])
                        )
                        for f, c in F_C
                    ])
                    -
                    pl.lpSum([
                c.deadline_penalty * params.arrival_rates[(f, c)] * (
                        pL[f][c] * (1.0 - deadline_satisfaction_prob_local[(f, c)]) +
                        pl.lpSum([pL_variants[f][v][c] * (1.0 - deadline_satisfaction_prob_local_variants[(f, v, c)])
                            for v in V[f]] if f.has_variants else 0.0)+
                        pl.lpSum([pC[region.name][f][c] * (1.0 - deadline_satisfaction_prob_cloud[(region.name, f, c)])
                            for region in regions])
                        )
                        for f, c in F_C
                    ])
                    -
                    pl.lpSum([c.drop_penalty * params.arrival_rates[(f, c)] * pD[f][c] for f, c in F_C]))
            -
            beta * (
                pl.lpSum([
                    params.arrival_rates[(f, c)] * (
                            pL[f][c] * (eP_local[f]) +
                            pl.lpSum([pL_variants[f][v][c] * (eP_local_variants[(f, v)]) for v in V[f]]
                                     if f.has_variants else 0.0) +
                            pD[f][c] * (co2_drop) +
                            pl.lpSum(
                                [pC[region.name][f][c] * (eP_offlading_cloud[region.name][f]) for region in regions])
                    )
                    for f, c in F_C
                ])),
            "objUtilCost"
        )

    # Probability
    for f, c in F_C:
        prob += (pL[f][c] +
                (pl.lpSum(pL_variants[f][v][c] for v in V[f]) if f.has_variants else 0.0) +
                (pE[f][c] if EDGE_ENABLED else 0.0) +
                pl.lpSum(pC[region.name][f][c] for region in regions) +
                pD[f][c] == 1.0
        )


    for f in F:
        if f.has_variants:
            for c in C:
                prob += (
                        pL[f][c] + pl.lpSum(pL_variants[f][v][c] for v in V[f]) <= 1.0
                )

    # Memory
    prob += (pl.lpSum(
        [f.memory * (x[f][c] + pl.lpSum([x_variants[f][v][c] for v in V[f]])) for f, c in F_C]) <= params.usable_local_memory_coeff * params.local_node.total_memory)
    if EDGE_ENABLED:
        prob += (pl.lpSum([f.memory * y[f][c] for f, c in F_C]) <= params.aggregated_edge_memory)

    # Share
    for f, c in F_C:
        prob += (pL[f][c] * params.arrival_rates[(f, c)] * params.serv_time_local[f] <= x[f][c])
        if EDGE_ENABLED:
            prob += (pE[f][c] * params.arrival_rates[(f, c)] * params.serv_time_edge[f] <= y[f][c])

    for f in F:
        if f.has_variants:
            for v in V[f]:
                for c in C:
                    prob += (
                        (pL_variants[f][v][c] * params.arrival_rates[(f,c)]) * params.serv_time_local[v] <= x_variants[f][v][c]
                )

    class_arrival_rates = {}
    for c in C:
        class_arrival_rates[c] = sum([params.arrival_rates[(f, c)] for f in F if c in C])

    # Min completion
    for c in C:
        if c.min_completion_percentage > 0.0 and class_arrival_rates[c] > 0.0:
            prob += (pl.lpSum([pD[f][c] * params.arrival_rates[(f, c)] for f in F]) / class_arrival_rates[
                c] <= 1 - c.min_completion_percentage)

    # Max hourly budget
    if params.budget is not None and params.budget > 0.0:
        prob += (pl.lpSum([dispatcher.aggregated_region_cost * params.arrival_rates[(f, c)] *
                           pC[region.name][f][c] * params.serv_time_cloud[region][f] * f.memory / 1024
                           for region, dispatcher in dispatchers.items()
                           for f, c in params.fun_classes()]) <= params.budget / 3600)


    prob.writeLP("problem.lp")
    status = solve(prob)
    if status != "Optimal":
        print(f"WARNING: solution status: {status}")
        return None

    obj = pl.value(prob.objective)
    if obj is None:
        print(f"WARNING: objective is None")
        return None

    if VERBOSE > 0:
        print("Obj = ", obj)
        shares = {(f, c): pl.value(x[f][c]) for f, c in F_C}
        print(f"Shares: {shares}")

    #for f, c in F_C:
        #print("[lp_optimizer] pL: ",f,"-",c,"  ", pl.value(pL[f][c][v]))
        #print("[lp_optimizer] pE: ",f,"-",c,"  ", pl.value(pE[f][c]))
        #for region, dispatcher in dispatchers.items():
        #    print("[lp_optimizer] pC: ",f,"-",c,"  ", pl.value(pC[region.name][f][c]))
        #print("[lp_optimizer] pD: ", f, "-", c, "  ", pl.value(pD[f][c]))
    decision_fc_probability = {}
    decision_fc_probability_var = {}
    decision_eP = {}

    for scheduler_decision in params.possible_decisions:
        if "EXEC" == scheduler_decision.name:
            decision_fc_probability[scheduler_decision] = pL
            decision_eP[scheduler_decision] = eP_local
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
        elif "EDGE" in scheduler_decision.name:
            if not EDGE_ENABLED:
                for f, c in F_C:
                    pE[f][c] = 0.0
                    eP_offloading_edge[f] = 0.0
            decision_fc_probability[scheduler_decision] = pE
            decision_eP[scheduler_decision] = eP_offloading_edge
        elif "DROP" in scheduler_decision.name:
            decision_fc_probability[scheduler_decision] = pD
        elif "CLOUD" in scheduler_decision.name:
            cloud_key = scheduler_decision.name[len(conf.OFFLOAD_CLOUD_DECISION):].lower()
            decision_fc_probability[scheduler_decision] = pC[cloud_key]
            decision_eP[scheduler_decision] = eP_offlading_cloud[cloud_key]

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
        if VERBOSE > 0:
            print(f"{f}-{c}: {probs[(f, c)]}")

    # populating local node's updated emissions calculation
    for f in F:
        exec_var_key = next((decision for decision in decision_eP if "VAR" in decision.name), None)
        for decision, eP in decision_eP.items():
            if "VAR" not in decision.name:
                params.local_node.g_co2_emissions[f][decision] = eP[f]
        if f.has_variants and exec_var_key:
            for v in V[f]:
                params.local_node.g_co2_emissions[v][exec_var_key] = decision_eP.get(exec_var_key, {}).get((f, v), 0.0)

    #print("[optimizer] -  probs: ",probs)
    return probs, decision_fc_probability_var



def solve(problem):
    global warm_start
    solver_name = os.environ.get("PULP_SOLVER", "GLPK_CMD")

    if not solver_name in ["CPLEX_CMD", "GUROBI_CMD", "PULP_CBC_CMD", "CBC_CMD", "CPLEX_PY", "GUROBI"] and warm_start:
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


