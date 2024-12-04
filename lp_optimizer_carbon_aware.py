import os
from asyncore import dispatcher

import conf
import math
import sys
import pulp as pl

from infrastructure import Infrastructure
from optimization import OptProblemParams
from optimization_carbon_aware import OptCarbonAwareProblemParams

warm_start = False


def compute_deadline_satisfaction_probs(params: OptCarbonAwareProblemParams):
    deadline_satisfaction_prob_local = {}
    deadline_satisfaction_prob_edge = {}
    deadline_satisfaction_prob_cloud = {} #key:(region,f,c) - value:resp_time
    dispatchers = params.cloud_regions_dipatchers

    # TODO: we are assuming exponential distribution
    # Probability of satisfying the deadline
    for f, c in params.fun_classes():
        p = 0.0
        if c.max_rt - params.init_time_local[f] > 0.0:
            p += params.cold_start_p_local[f] * (
                        1.0 - math.exp(-1.0 / params.serv_time_local[f] * (c.max_rt - params.init_time_local[f])))
        if c.max_rt > 0.0:
            p += (1.0 - params.cold_start_p_local[f]) * (1.0 - math.exp(-1.0 / params.serv_time_local[f] * c.max_rt))
        deadline_satisfaction_prob_local[(f, c)] = p

        for region, dispatcher in dispatchers.items():
            if dispatcher.aggregated_region_memory > 0.0:
                p = 0.0
                try:
                    tx_time = f.inputSizeMean * 8 / 1000 / 1000 / params.bandwidth_cloud[region]
                    if c.max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[region] - tx_time > 0.0:
                        p += params.cold_start_p_cloud[region][f] * (1.0 - math.exp(-1.0 / params.serv_time_cloud[(region, f)] * (
                                    c.max_rt - params.init_time_cloud[region][f] - params.offload_time_cloud[region] - tx_time)))
                    if c.max_rt - params.offload_time_cloud[region] - tx_time > 0.0:
                        p += (1.0 - params.cold_start_p_cloud[region][f]) * (1.0 - math.exp(
                            -1.0 / params.serv_time_cloud[(region, f)] * (c.max_rt - params.offload_time_cloud[region] - tx_time)))
                except:
                    pass
                deadline_satisfaction_prob_cloud[(region.name,f, c)] = p
            else:
                deadline_satisfaction_prob_cloud = {rfc: 0 for rfc in params.reg_fun_classes()}

        if params.aggregated_edge_memory > 0.0:
            p = 0.0
            try:
                tx_time = f.inputSizeMean * 8 / 1000 / 1000 / params.bandwidth_edge
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

    return deadline_satisfaction_prob_local, deadline_satisfaction_prob_cloud, deadline_satisfaction_prob_edge


def compute_energy_consumption(params, pL, pE, pC):
    F = params.functions
    C = params.classes
    dispatchers = params.cloud_regions_dipatchers

    eP_local = {}
    eP_offloading_edge = {}
    eP_offlading_cloud = {}

    for f, c in params.fun_classes():
        #eP_local

        eP_local[(f, c)] = 0.0

        if params.usable_local_memory_coeff > 0.0:
            power_cons = params.local_node.processing_power_consumption
            m_f = f.memory / 1024
            m_u = params.usable_local_memory_coeff
            co2 = params.local_node.co2_footprint.co2_intensity
            serv_time_local = params.serv_time_local[f]
            arrival_rates = params.arrival_rates[(f,c)]

            param_local_energy_consumption = (  pL[f][c]        *
                                                arrival_rates   *
                                                power_cons      *
                                                float(m_f/m_u)  *
                                                serv_time_local *
                                                float(co2/3600)
                                                )
            eP_local[(f, c)] = param_local_energy_consumption

            # eP_Edge

            eP_offloading_edge[(f, c)] = 0.0

            if params.aggregated_edge_memory > 0.0:
                power_cons_e = params.aggregated_edge_power_consumption
                m_f = f.memory / 1024
                m_e = params.aggregated_edge_memory
                co2 = params.local_node.co2_footprint.co2_intensity
                serv_time_edge = params.serv_time_edge[f]
                arrival_rates = params.arrival_rates[(f, c)]
                data_size_input = f.inputSizeMean * 8 / 1000 / 1000
                data_size_output = f.outputSizeMean * 8 / 1000 / 1000
                energy_tx_local = params.local_node.tx_energy_consumption
                energy_rx_e = params.aggregated_edge_energy_rx
                energy_rx_local = params.local_node.rx_energy_consumption
                energy_tx_e = params.aggregated_edge_energy_tx

                param_edge_energy_consumption = (pE[f][c]      *
                                                  arrival_rates *
                                                   ((power_cons_e * float(m_f / m_e) * serv_time_edge)  +
                                                    data_size_input * (energy_tx_local + energy_rx_e)   +
                                                    data_size_output * (energy_tx_e + energy_rx_local)) *
                                                    float(co2 / 3600)
                                                  )
                eP_local[(f, c)] = param_edge_energy_consumption

        # eP_offloading_cloud
        for region, dispatcher in dispatchers.items():

            eP_offlading_cloud[(region, f, c)] = 0.0

            if dispatcher.aggregated_region_memory > 0.0:
                power_cons_Ci = dispatcher.avg_processing_power_consumption
                m_f = f.memory / 1024
                m_Ci = dispatcher.aggregated_region_memory
                co2 = dispatcher.co2_footprint.co2_intensity
                serv_time_Ci = params.serv_time_cloud[(region, f)]
                arrival_rates = params.arrival_rates[(f, c)]
                data_size_input = f.inputSizeMean * 8 / 1000 / 1000
                data_size_output = f.outputSizeMean * 8 / 1000 / 1000
                energy_tx_local = params.local_node.tx_energy_consumption
                energy_rx_Ci = dispatcher.avg_rx_energy_consumption
                energy_rx_local = params.local_node.rx_energy_consumption
                energy_tx_Ci = dispatcher.avg_tx_energy_consumption

                param_cloud_energy_consumption = (  pC[region.name][f][c]   *
                                                    arrival_rates           *
                                                    ((power_cons_Ci * float(m_f/m_Ci) * serv_time_Ci)       +
                                                     data_size_input * (energy_tx_local + energy_rx_Ci)     +
                                                     data_size_output * (energy_tx_Ci + energy_rx_local))   *
                                                    float(co2/3600)
                                                    )

                eP_offlading_cloud[(region, f, c)] = param_cloud_energy_consumption

    return eP_local, eP_offlading_cloud

def update_probabilities(params: OptCarbonAwareProblemParams, VERBOSE=False):
    F = params.functions
    C = params.classes
    F_C = [(f, c) for f in F for c in C]
    dispatchers = params.cloud_regions_dipatchers

    EDGE_ENABLED = True if params.aggregated_edge_memory > 0.0 else False

    if VERBOSE > 1:
        print("------------------------------")
        print(f"Edge memory: {aggregated_edge_memory}")
        print(f"Arrival rates: {arrival_rates}")
        print("------------------------------")

    prob = pl.LpProblem("MyProblem", pl.LpMaximize)
    x = pl.LpVariable.dicts("X", (F, C), 0, None, pl.LpContinuous)
    y = pl.LpVariable.dicts("Y", (F, C), 0, None, pl.LpContinuous)
    pL = pl.LpVariable.dicts("PExec", (F, C), 0, 1, pl.LpContinuous)
    pC = {}
    pD = pl.LpVariable.dicts("PDrop", (F, C), 0, 1, pl.LpContinuous)
    if EDGE_ENABLED:
        pE = pl.LpVariable.dicts("PEdge", (F, C), 0, 1, pl.LpContinuous)
    for region in dispatchers.keys():
        region_name = region.name
        pC[region_name] = pl.LpVariable.dicts(f"PCloud_{region_name}", (F, C), 0, 1, pl.LpContinuous)

    deadline_satisfaction_prob_local, deadline_satisfaction_prob_cloud, deadline_satisfaction_prob_edge = compute_deadline_satisfaction_probs(
        params)
    #todo: E(P) * ro_CO2 (fai calcolo E(P))
    eP_local, eP_offlading_cloud = compute_energy_consumption(params, pL, pE, pC)

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
    if EDGE_ENABLED:
        prob += (
            pl.lpSum([
                c.utility * params.arrival_rates[(f, c)] * (
                        pL[f][c] * deadline_satisfaction_prob_local[(f, c)] +
                        pE[f][c] * deadline_satisfaction_prob_edge[(f, c)] +
                        pl.lpSum([
                            pC[region.name][f][c] * deadline_satisfaction_prob_cloud[(region.name, f, c)]
                            for region in dispatchers.keys()
                        ])
                )
                for f, c in F_C
            ])
            -
            pl.lpSum([
                c.deadline_penalty * params.arrival_rates[(f, c)] * (
                        pL[f][c] * (1.0 - deadline_satisfaction_prob_local[(f, c)]) +
                        pE[f][c] * (1.0 - deadline_satisfaction_prob_edge[(f, c)]) +
                        pl.lpSum([
                            pC[region.name][f][c] * (1.0 - deadline_satisfaction_prob_cloud[(region.name, f, c)])
                            for region in dispatchers.keys()
                        ])
                )
                for f, c in F_C
            ])
            -
            pl.lpSum([
                c.drop_penalty * params.arrival_rates[(f, c)] * pD[f][c]
                for f, c in F_C
            ]),
            "objUtilCost"
        )

    else:
        prob += (pl.lpSum([c.utility * params.arrival_rates[(f, c)] * \
                           (pL[f][c] * deadline_satisfaction_prob_local[(f, c)] + \
                            pC[f][c] * deadline_satisfaction_prob_cloud[(f, c)]) for f, c in F_C]) - \
                 pl.lpSum([c.deadline_penalty * params.arrival_rates[(f, c)] * \
                           (pL[f][c] * (1.0 - deadline_satisfaction_prob_local[(f, c)]) + \
                            pC[f][c] * (1.0 - deadline_satisfaction_prob_cloud[(f, c)])) for f, c in F_C]) - \
                 pl.lpSum([c.drop_penalty * params.arrival_rates[(f, c)] * pD[f][c] for f, c in F_C]),
                 "objUtilCost")

    # Probability
    if EDGE_ENABLED:
        for f, c in F_C:
            prob += (
                    pL[f][c] +
                    pE[f][c] +
                    pl.lpSum([pC[region.name][f][c] for region in dispatchers.keys()]) +
                    pD[f][c]
                    == 1.0
            )
    else:
        for f, c in F_C:
            prob += (
                    pL[f][c] +
                    pl.lpSum([pC[region.name][f][c] for region in dispatchers.keys()]) +
                    pD[f][c]
                    == 1.0
            )

    # Memory
    prob += (pl.lpSum(
        [f.memory * x[f][c] for f, c in F_C]) <= params.usable_local_memory_coeff * params.local_node.total_memory)
    if EDGE_ENABLED:
        prob += (pl.lpSum([f.memory * y[f][c] for f, c in F_C]) <= params.aggregated_edge_memory)

    # Share
    for f, c in F_C:
        prob += (pL[f][c] * params.arrival_rates[(f, c)] * params.serv_time_local[f] <= x[f][c])
        if EDGE_ENABLED:
            prob += (pE[f][c] * params.arrival_rates[(f, c)] * params.serv_time_edge[f] <= y[f][c])

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
        prob += (pl.lpSum([dispatcher.cost * params.arrival_rates[(f, c)] *
                           pC[region.name][f][c] * params.serv_time_cloud[(region, f)] * f.memory / 1024
                           for region, dispatcher in dispatchers.items()
                           for f, c in params.fun_classes()]) <= params.budget / 3600)


    #Proximity matrix
    region = params.local_node.region
    for other_region_name, is_neighbor in region.neighbors.items():
        if not is_neighbor and conf.CLOUD in other_region_name:
            for f, c in F_C:
                prob += pC[other_region_name][f][c] == 0.0

    #print("in update_probabilities: node = ", params.local_node.name,
    #      ", CO2_datetime = ", params.local_node.co2_footprint.co2_datetime,
    #      ", CO2_intensity = ", params.local_node.co2_footprint.co2_intensity)



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

    decision_fc_probability = {}
    for scheduler_decision in params.possible_decisions:
        if "EXEC" in scheduler_decision.name:
            decision_fc_probability[scheduler_decision] = pL
        elif "EDGE" in scheduler_decision.name:
            decision_fc_probability[scheduler_decision] = pE if EDGE_ENABLED else 0.0
        elif "DROP" in scheduler_decision.name:
            decision_fc_probability[scheduler_decision] = pD
        elif "CLOUD" in scheduler_decision.name:
            cloud_key = scheduler_decision.name[len(conf.OFFLOAD_CLOUD_DECISION):].lower()
            decision_fc_probability[scheduler_decision] = pC[cloud_key]


    probs = {}

    for decision, f_c_probabilities in decision_fc_probability.items():
        for function, classes in f_c_probabilities.items():
            for service_class, probability in classes.items():
                # Create the key based on function and service class
                key = (function, service_class)

                # If the key does not exist, initialize it with an empty dictionary
                if key not in probs:
                    probs[key] = {}

                # Add the decision and its corresponding probability to the value dictionary
                probs[key][decision] = probability.varValue
    #print(probs)


    '''
        for f, c in F_C:
        bho[sched_dec for sched_dec in params.possible_decisions if "EXEC" in sched_dec.name]:(pl.value(pL[f][c]))
        bho.append(pl.value(pE[f][c]))
        bho.append(pl.value(pD[f][c]))
        for region in dispatchers.keys():
            bho.append(pl.value(pC[region][f][c]))



    if EDGE_ENABLED:    #todo modifica come restituisci vettore probs
        probs = {(f, c): [pl.value(pL[f][c]),
                          pl.value(pC[f][c]),
                          pl.value(pE[f][c]),
                          pl.value(pD[f][c])] for f, c in F_C}

        probs = {
            (f, c): {
                decision: prob
                for decision, prob in zip(
                    params.possible_decisions,
                    pl.value(pC[f][c])
                )
            } for f, c in F_C}


    else:
        probs = {(f, c): [pl.value(pL[f][c]),
                          pl.value(pC[f][c]),
                          0.0,
                          pl.value(pD[f][c])] for f, c in F_C}
    '''
    # Expected cost
    # ec = 0
    # ctput = 0
    # for f,c in F_C:
    #    ec += cloud.cost*arrival_rates[(f,c)]*pl.value(pC[f][c])*serv_time_cloud[f]*f.memory/1024
    #    ctput += arrival_rates[(f,c)]*pl.value(pC[f][c])
    # print(f"Expected cost: {ec:.5f} ({budget/3600:.5f})")
    # print(f"Expected cloud throughput: {ctput:.1f}")

    # Workaround to avoid numerical issues
    for f, c in F_C:

        s = 0
        for decision, probability in probs[(f, c)].items():
            s = s + probability

        if s > 0:
        # Scale each probability variable or expression by dividing through normalization
            probs[(f, c)] = {decision: prob / s for decision, prob in probs[(f, c)].items()}

        # Optional verbose logging
        if VERBOSE > 0:
            print(f"{f}-{c}: {probs[(f, c)]}")

    return probs

'''
    for f, c in F_C:
        s = sum(probs[(f, c)])
        probs[(f, c)] = [x / s for x in probs[(f, c)]]
        if VERBOSE > 0:
            print(f"{f}-{c}: {probs[(f, c)]}")
    return probs
'''



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


