import numpy as np
from pacsltk import perfmodel

import conf
import lp_optimizer_carbon_aware
import lp_optimizer_carbon_aware_normalized
import optimizer_nonlinear
from co2_footprint import compute_local_emissions, compute_cloud_emissions
from optimization_carbon_aware import OptCarbonAwareProblemParams
from policy import Policy, ColdStartEstimation, COLD_START_PROB_INITIAL_GUESS, SchedulerDecision

ADAPTIVE_EDGE_MEMORY_COEFFICIENT = True


class ProbabilisticCarbonAwarePolicy(Policy):

    def __init__(self, simulation, node, strict_budget_enforce=False):
        super().__init__(simulation, node)

        self.rng = self.simulation.policy_rng1
        self.stats_snapshot = None
        self.last_update_time = None
        self.arrival_rate_alpha = self.simulation.config.getfloat(conf.SEC_POLICY, conf.POLICY_ARRIVAL_RATE_ALPHA,
                                                                  fallback=1.0)
        self.edge_enabled = simulation.config.getboolean(conf.SEC_POLICY, conf.EDGE_OFFLOADING_ENABLED, fallback="true")
        self.strict_budget_enforce = strict_budget_enforce

        self.rng_variant = self.simulation.rng_variant

        self.num_regions_cloud = int(simulation.infra.num_regions_cloud)
        assert (self.num_regions_cloud == len(simulation.infra.dispatchers))

        self.cloud_regions = self.simulation.infra.cloud_regions
        self.cloud_dispatchers = {}  # dispatchers
        for region in self.cloud_regions:
            for dispatcher_node in self.simulation.infra.dispatchers:
                if dispatcher_node.region == region:
                    self.cloud_dispatchers[region] = dispatcher_node

        self.local_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE.name))
        assert (self.local_cold_start_estimation != ColdStartEstimation.FULL_KNOWLEDGE)
        self.cloud_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE.name))
        assert (self.cloud_cold_start_estimation != ColdStartEstimation.FULL_KNOWLEDGE)
        self.edge_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE.name))
        assert (self.edge_cold_start_estimation != ColdStartEstimation.FULL_KNOWLEDGE)

        self.allow_multi_offloading = simulation.config.getboolean(conf.SEC_POLICY, conf.MULTIPLE_OFFLOADING_ALLOWED,
                                                                   fallback=False)
        self.local_rejection_fallback = simulation.config.get(conf.SEC_POLICY, conf.FALLBACK_ON_LOCAL_REJECTION,
                                                              fallback="reschedule")

        # Variables used for the adaptive local memory constraint
        self.adaptive_local_memory = simulation.config.getboolean(conf.SEC_POLICY, conf.ADAPTIVE_LOCAL_MEMORY,
                                                                  fallback=False)
        self.curr_local_blocked_reqs = 0
        self.curr_local_reqs = 0
        self.local_usable_memory_coeff = 1.0

        self.arrival_rates = {}
        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}
        self.cold_start_prob_local = {}

        self.cold_start_prob_cloud = {(region, f): {} for region in self.cloud_regions for f in simulation.functions}
        self.cloud_rtt = {region: 0.0 for region in self.cloud_regions}
        self.cloud_bw = {region: 0.0 for region in self.cloud_regions}

        self.init_time_local = {f: simulation.init_time[(f, self.node)] for f in simulation.functions}
        self.init_time_edge = {}  # updated periodically

        self.init_time_cloud = {}
        for region in self.cloud_regions:
            dispatcher_node = self.cloud_dispatchers[region]
            if region not in self.init_time_cloud:
                self.init_time_cloud[region] = {}
            for f in simulation.functions:
                self.init_time_cloud[region][f] = simulation.init_time[(f, dispatcher_node)]

        self.aggregated_edge_memory = 0.0
        self.estimated_service_time_edge = {}
        self.edge_rtt = 0.0
        self.edge_bw = float("inf")
        self.cold_start_prob_edge = {}

        self.aggregated_edge_power_consumption = 0.0
        self.aggregated_edge_idle_power_consumption = 0.0
        self.aggregated_edge_power_tx = 0.0
        self.aggregated_edge_power_rx = 0.0
        self.co2_green_threshold = 150.0
        self.aggregated_edge_cost = 0.0

        self.possible_decisions = list(SchedulerDecision)

        self.probs = {}
        self.variants_probs = {}
        self.build_probs()

        self.of_alpha = self.simulation.of_alpha
        self.of_beta = self.simulation.of_beta

        #initialize node g carbon emissions dict for probs > 0
        for prob_entry in self.probs.values():
            for decision, prob in prob_entry.items():
                if prob > 0.0:
                    for f in simulation.functions:
                        if decision.name == "EXEC" and f.is_default:
                            self.handle_exec_decision(f, node, decision)
                        elif conf.OFFLOAD_CLOUD_DECISION in decision.name and f.is_default:
                            self.handle_offload_cloud_decision(f, node, decision)

    def build_probs(self):
        # Iterate over all functions and classes
        self.default_functions = [f for f in self.simulation.functions if f.is_default]
        for f in self.default_functions:
            for c in self.simulation.classes:
                # Initialize the inner dictionary for (f, c)
                self.probs[(f, c)] = {}

                if not f.has_variants:
                    # Case: Function has no variants
                    initial_prob = float(1 / (1 + self.num_regions_cloud))

                    # Prepare the list of probabilities
                    probabilities = [initial_prob] + [0.0, 0.0, 0.0] + [initial_prob] * self.num_regions_cloud

                    # Assign probabilities to possible decisions
                    for decision, prob in zip(self.possible_decisions, probabilities):
                        self.probs[(f, c)][decision] = prob

                else:
                    # Case: Function has variants
                    initial_prob = float(1 / (2 + self.num_regions_cloud))
                    initial_var_prob = float(initial_prob / len(self.simulation.function_variants[f]))

                    # Initialize variant probabilities
                    if f not in self.variants_probs:
                        self.variants_probs[f] = {}

                    for fun_var in self.simulation.function_variants[f]:
                        if (fun_var, c) not in self.probs:
                            self.probs[(fun_var, c)] = {}

                        if fun_var not in self.variants_probs[f]:
                            self.variants_probs[f][fun_var] = {}

                        self.variants_probs[f][fun_var][c] = initial_var_prob

                        # Assign probabilities for variants
                        probabilities = [0.0] + [initial_var_prob] + [0.0] * (2 + self.num_regions_cloud)
                        for decision, prob in zip(self.possible_decisions, probabilities):
                            self.probs[(fun_var, c)][decision] = prob

                    # Assign probabilities for the default function
                    probabilities = [initial_prob] * 2 + [0.0, 0.0] + [initial_prob] * self.num_regions_cloud
                    for decision, prob in zip(self.possible_decisions, probabilities):
                        self.probs[(f, c)][decision] = prob

    def compute_initial_prob(self, f):
        base = 1 + self.num_regions_cloud if not f.has_variants else 2 + self.num_regions_cloud
        return float(1 / base)

    def handle_exec_decision(self, f, node, decision):
        local_eP = compute_local_emissions(f, node, 0.1)
        node.g_co2_emissions[f][decision] = local_eP

    def handle_offload_cloud_decision(self, f, node, decision):
        region_name = decision.name[len(conf.OFFLOAD_CLOUD_DECISION):].lower()
        dispatcher_node = self.simulation.infra.get_dispatcher_by_region_name(region_name)
        random_cloud_node = dispatcher_node.cloud_nodes_list[0]
        cloud_eP = compute_cloud_emissions(f, dispatcher_node, 0.1, random_cloud_node, node)
        node.g_co2_emissions[f][decision] = cloud_eP

    def pick_greener_cloud_region(self):
        dispatchers = self.simulation.infra.dispatchers
        remote_node = min(dispatchers, key=lambda d: d.co2_footprint.co2_intensity)
        sched_decision = f"{conf.OFFLOAD_CLOUD_DECISION}{remote_node.region.name.upper()}"
        return sched_decision, remote_node

    def schedule(self, f, c, offloaded_from):
        probabilities = self.probs[(f, c)].copy()
        if f.has_variants and len(self.variants_probs[f]) > 0:
            variants_probs = self.variants_probs[f].copy()

        # If the request has already been offloaded, cannot offload again
        if len(offloaded_from) > 0:
            if not self.allow_multi_offloading:
                probabilities[SchedulerDecision.OFFLOAD_EDGE] = 0.0
                for decision, prob in probabilities.items():
                    if conf.OFFLOAD_CLOUD_DECISION in decision.name:
                        probabilities[decision] = 0.0
            s = sum(probabilities.values())

            if s <= 0.0:
                return (SchedulerDecision.DROP, None)
            else:
                probabilities = self.renormalize_probs(probabilities, s)

        decision = self.rng.choice(list(probabilities.keys()), p=list(probabilities.values()))

        #print("[schedule - node ",self.node,"] decision: ", decision)

        if decision == SchedulerDecision.EXEC:
            self.curr_local_reqs += 1

        if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
            self.curr_local_blocked_reqs += 1

            if self.local_rejection_fallback == "fgcs24" or self.local_rejection_fallback == "reschedule":
                probabilities[SchedulerDecision.EXEC] = 0.0

                if self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
                    for cloud_decision, prob in probabilities.items():
                        if conf.OFFLOAD_CLOUD_DECISION in cloud_decision.name:
                            probabilities[decision] = 0.0
                    probabilities[SchedulerDecision.OFFLOAD_EDGE] = 0.0

                s = sum(probabilities.values())
                if s > 0.0:
                    probabilities = self.renormalize_probs(probabilities, s)
                    decision, node = self.rng.choice(list(probabilities.keys()), p=list(probabilities.values())), None
                else:
                    return (SchedulerDecision.DROP, None)

            elif self.local_rejection_fallback == "drop":
                return (SchedulerDecision.DROP, None)
            else:
                raise RuntimeError(f"Unknown local rejection fallback: {self.local_rejection_fallback}")

        if decision == SchedulerDecision.EXEC_VAR:
            self.curr_local_reqs += 1
            assert f.has_variants == True

            variant_choice = {}
            for function_variant, class_probability in variants_probs.items():
                variant_choice[function_variant] = class_probability[c]  #.varValue

            variants = list(variant_choice.keys())
            probs = np.array(list(variant_choice.values()), dtype=float)

            # normalize (in case they don't sum to 1)
            s = probs.sum()
            if s <= 0:
                return (SchedulerDecision.DROP, None)
            probs /= s

            selected_variant = self.rng_variant.choice(variants, p=probs)
            f.active_variant = selected_variant

        # Local rejection due to lack of resources
        if decision == SchedulerDecision.EXEC_VAR and not self.can_execute_locally(f):

            self.curr_local_blocked_reqs += 1

            if self.local_rejection_fallback == "fgcs24" or self.local_rejection_fallback == "reschedule":
                probabilities[SchedulerDecision.EXEC_VAR] = 0.0
                probabilities[SchedulerDecision.EXEC] = 0.0

                if self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
                    for cloud_decision, prob in probabilities.items():
                        if conf.OFFLOAD_CLOUD_DECISION in cloud_decision.name:
                            probabilities[decision] = 0.0
                    probabilities[SchedulerDecision.OFFLOAD_EDGE] = 0.0

                s = sum(probabilities.values())
                if s > 0.0:
                    probabilities = self.renormalize_probs(probabilities, s)
                    decision, node = self.rng.choice(list(probabilities.keys()), p=list(probabilities.values())), None
                else:
                    return (SchedulerDecision.DROP, None)

            elif self.local_rejection_fallback == "drop":
                return (SchedulerDecision.DROP, None)
            else:
                raise RuntimeError(f"Unknown local rejection fallback: {self.local_rejection_fallback}")


        if conf.OFFLOAD_CLOUD_DECISION in decision.name and self.strict_budget_enforce:
            if self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
                return (SchedulerDecision.DROP, None)

        if SchedulerDecision.OFFLOAD_EDGE == decision.name and self.strict_budget_enforce:
            if self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
                return (SchedulerDecision.DROP, None)

        return (decision, None)

    def renormalize_probs(self, probabilities, s):
        for decision, prob in probabilities.items():
            probabilities[decision] = prob / s
        return probabilities

    def update(self):
        self.update_metrics()

        arrivals = sum(
            [self.arrival_rates.get((f, c), 0.0) for f in self.simulation.functions for c in self.simulation.classes])
        if arrivals > 0.0:
            # trigger the optimizer
            self.update_probabilities()
            #pass

        self.stats_snapshot = self.simulation.stats.to_dict()
        self.last_update_time = self.simulation.t

        # reset counters
        self.curr_local_blocked_reqs = 0
        self.curr_local_reqs = 0

    def estimate_cold_start_prob(self, stats):
        #
        # LOCAL NODE
        #
        if self.local_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001,
                                         sum([self.arrival_rates.get((f, x), 0.0) for x in self.simulation.classes]))
                # XXX: we are ignoring initial warm pool....
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                              self.estimated_service_time[f],
                                                              self.estimated_service_time[f] +
                                                              self.simulation.init_time[(f, self.node)],
                                                              self.simulation.expiration_timeout)
                self.cold_start_prob_local[f] = props1["cold_prob"]
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f, self.node)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f, self.node)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 10:
                    self.cold_start_prob_local[f] = node_cs / node_compl
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f, self.node), 0) > 10:
                    self.cold_start_prob_local[f] = stats.cold_starts.get((f, self.node),
                                                                          0) / stats.node2completions.get(
                        (f, self.node), 0)
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        else:  # No
            for f in self.simulation.functions:
                self.cold_start_prob_local[f] = 0

        #for f in self.simulation.functions:
        #    if self.cold_start_prob_local[f] == 1.0:
        #        print("self.cold_start_prob_local[f] = 1 -> node: ",self.node," f: ",f)

        # CLOUD

        for region, dispatcher in self.cloud_dispatchers.items():
            node_compl = sum([dispatcher.avg_node2completions.get(_f, 0) for _f in self.simulation.functions])
            node_cs = sum([dispatcher.avg_cold_starts.get(_f, 0) for _f in self.simulation.functions])

            default_functions = list(f for f in self.simulation.functions if f.is_default)
            for f in default_functions:

                if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
                    sum_arrivals = 0
                    for x in self.simulation.classes:
                        for dec, prob in self.probs[(f, x)].items():
                            if dispatcher.region.name.upper() in dec.name:
                                sum_arrivals += self.arrival_rates.get((f, x), 0.0) + prob
                    total_arrival_rate = max(0.001, sum_arrivals)

                    props1, _ = perfmodel.get_sls_warm_count_dist(
                        total_arrival_rate,
                        self.estimated_service_time_cloud[region][f],
                        self.estimated_service_time_cloud[region][f] + self.simulation.init_time[
                            (f, dispatcher)],  #gia gestito in simulation
                        self.simulation.expiration_timeout
                    )
                    self.cold_start_prob_cloud[(region, f)] = props1["cold_prob"]

                elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
                    if node_compl > 10:
                        self.cold_start_prob_cloud[(region, f)] = node_cs / node_compl
                    else:
                        self.cold_start_prob_cloud[(region, f)] = COLD_START_PROB_INITIAL_GUESS

                elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
                    if dispatcher.avg_node2completions.get(f, 0) > 10:
                        self.cold_start_prob_cloud[(region, f)] = dispatcher.avg_cold_starts(f,
                                                                                             0) / dispatcher.node2completions.get(
                            f, 0)
                    else:
                        self.cold_start_prob_cloud[(region, f)] = COLD_START_PROB_INITIAL_GUESS

                else:  # No estimation
                    self.cold_start_prob_cloud[(region, f)] = 0.0

    def update_metrics(self):
        stats = self.simulation.stats

        if ADAPTIVE_EDGE_MEMORY_COEFFICIENT and self.stats_snapshot is not None:
            # Reduce exposed memory if offloaded have been dropped
            dropped_offl = sum([stats.dropped_offloaded[(f, c, self.node)] for f in self.simulation.functions for c in
                                self.simulation.classes])
            prev_dropped_offl = sum(
                [self.stats_snapshot["dropped_offloaded"][repr((f, c, self.node))] for f in self.simulation.functions
                 for c in self.simulation.classes])
            arrivals = sum(
                [stats.arrivals[(f, c, self.node)] - self.stats_snapshot["arrivals"][repr((f, c, self.node))] for f in
                 self.simulation.functions for c in self.simulation.classes])
            ext_arrivals = sum(
                [stats.ext_arrivals[(f, c, self.node)] - self.stats_snapshot["ext_arrivals"][repr((f, c, self.node))]
                 for f in self.simulation.functions for c in self.simulation.classes])

            loss = (dropped_offl - prev_dropped_offl) / (arrivals - ext_arrivals) if arrivals - ext_arrivals > 0 else 0
            if loss > 0.0:
                self.node.peer_exposed_memory_fraction = max(0.05, self.node.peer_exposed_memory_fraction * loss / 2.0)
            else:
                self.node.peer_exposed_memory_fraction = min(self.node.peer_exposed_memory_fraction * 1.1, 1.0)
            # print(f"{self.node}: Loss: {loss} ({dropped_offl-prev_dropped_offl}): {self.node.peer_exposed_memory_fraction:.3f}")

        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}

        for f in self.simulation.functions:

            if stats.node2completions[(f, self.node)] > 0:
                self.estimated_service_time[f] = stats.execution_time_sum[(f, self.node)] / \
                                                 stats.node2completions[(f, self.node)]
            else:
                self.estimated_service_time[f] = float(0.1)

            for region, dispatcher in self.cloud_dispatchers.items():
                if region not in self.estimated_service_time_cloud:
                    self.estimated_service_time_cloud[region] = {}

                if dispatcher.avg_node2completions[f] > 0:
                    self.estimated_service_time_cloud[region][f] = dispatcher.avg_execution_time_sum[f] / \
                                                                   dispatcher.avg_node2completions[f]
                else:
                    self.estimated_service_time_cloud[region][f] = 0.1

        if self.stats_snapshot is not None:
            arrival_rates = {}
            for f, c, n in stats.arrivals:
                if n != self.node:
                    continue
                new_arrivals = stats.arrivals[(f, c, self.node)] - self.stats_snapshot["arrivals"][repr((f, c, n))]
                new_rate = new_arrivals / (self.simulation.t - self.last_update_time)
                self.arrival_rates[(f, c)] = self.arrival_rate_alpha * new_rate + \
                                             (1.0 - self.arrival_rate_alpha) * self.arrival_rates[(f, c)]
        else:
            for f, c, n in stats.arrivals:
                if n != self.node:
                    continue
                self.arrival_rates[(f, c)] = stats.arrivals[(f, c, self.node)] / self.simulation.t

        self.estimate_cold_start_prob(stats)

        for region in self.cloud_regions:
            self.cloud_rtt[region] = 2 * self.simulation.infra.get_region_latency(self.node.region, region)
            self.cloud_bw[region] = self.simulation.infra.get_bandwidth(self.node.region, region)

        stats = self.simulation.stats

        if self.edge_enabled:
            neighbor_probs, neighbors = self._get_edge_peers_probabilities()

            if not neighbors:  #len(neighbors) == 0
                # Set default values when there are no neighbors
                self.aggregated_edge_memory = 0
                self.aggregated_edge_power_consumption = 0
                self.aggregated_edge_idle_power_consumption = 0
                self.aggregated_edge_power_tx = 0
                self.aggregated_edge_power_rx = 0
                self.edge_rtt = 0  # Default to 0 as no latency can be calculated
                self.edge_bw = 0  # Default to 0 as no bandwidth can be calculated
                self.aggregated_edge_cost = 0
            else:

                self.aggregated_edge_memory = max(1, sum([x.curr_memory * x.peer_exposed_memory_fraction for x in
                                                          neighbors]))

                p = sum(neighbor.processing_power_consumption for neighbor in neighbors)
                p_idle = sum(neighbor.idle_power_consumption for neighbor in neighbors)
                tx = sum(neighbor.tx_power_consumption for neighbor in neighbors)
                rx = sum(neighbor.rx_power_consumption for neighbor in neighbors)
                cost = sum(neighbor.cost for neighbor in neighbors)

                num = len(neighbors)
                self.aggregated_edge_power_consumption = p / num
                self.aggregated_edge_idle_power_consumption = p_idle / num
                self.aggregated_edge_power_tx = tx / num
                self.aggregated_edge_power_rx = rx / num
                self.aggregated_edge_cost = cost / num

                self.edge_rtt = sum(
                    self.simulation.infra.get_latency(self.node, x) * prob
                    for x, prob in zip(neighbors, neighbor_probs)
                )
                self.edge_bw = sum(
                    self.simulation.infra.get_bandwidth(self.node, x) * prob
                    for x, prob in zip(neighbors, neighbor_probs)
                )

            self.estimated_service_time_edge = {}
            for f in self.simulation.functions:
                inittime = 0.0
                servtime = 0.0
                for neighbor, prob in zip(neighbors, neighbor_probs):
                    if stats.node2completions[(f, neighbor)] > 0:
                        servtime += prob * stats.execution_time_sum[(f, neighbor)] / stats.node2completions[
                            (f, neighbor)]
                    inittime += prob * self.simulation.init_time[(f, neighbor)]
                if servtime == 0.0:
                    servtime = self.estimated_service_time[f]
                self.estimated_service_time_edge[f] = servtime
                self.init_time_edge[f] = inittime

            self.estimate_edge_cold_start_prob(stats, neighbors, neighbor_probs)

    def estimate_edge_cold_start_prob(self, stats, neighbors, neighbor_probs):
        peer_probs, peers = self._get_edge_peers_probabilities()
        default_functions = list(f for f in self.simulation.functions if f.is_default)

        if self.edge_cold_start_estimation == ColdStartEstimation.PACS:
            for f in default_functions:
                total_offloaded_rate = max(0.001, \
                                           sum([self.arrival_rates.get((f, x), 0.0) * self.probs[(f, x)][
                                               SchedulerDecision.OFFLOAD_EDGE] for x in
                                                self.simulation.classes]))
                props1, _ = perfmodel.get_sls_warm_count_dist(total_offloaded_rate,
                                                              self.estimated_service_time_edge[f],
                                                              self.estimated_service_time_edge[f] +
                                                              self.simulation.init_time[(f, self.node)],
                                                              self.simulation.expiration_timeout)
                self.cold_start_prob_edge[f] = props1["cold_prob"]
        elif self.edge_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            total_prob = 0
            for p, peer_prob in zip(peers, peer_probs):
                node_compl = sum([stats.node2completions[(_f, p)] for _f in self.simulation.functions])
                node_cs = sum([stats.cold_starts[(_f, p)] for _f in self.simulation.functions])
                if node_compl > 0:
                    _prob = node_cs / node_compl
                else:
                    _prob = COLD_START_PROB_INITIAL_GUESS
                total_prob += _prob * peer_prob
            for f in self.simulation.functions:
                self.cold_start_prob_edge[f] = total_prob
        elif self.edge_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                self.cold_start_prob_edge[f] = 0
                for p, peer_prob in zip(peers, peer_probs):
                    if stats.node2completions.get((f, p), 0) > 0:
                        _prob = stats.cold_starts.get((f, p), 0) / stats.node2completions.get((f, p), 0)
                    else:
                        _prob = COLD_START_PROB_INITIAL_GUESS
                    self.cold_start_prob_edge[f] += _prob * peer_prob

        else:  # No
            for f in self.simulation.functions:
                self.cold_start_prob_edge[f] = 0

    def update_probabilities(self):
        if self.adaptive_local_memory:
            loss = self.curr_local_blocked_reqs / self.curr_local_reqs if self.curr_local_reqs > 0 else 0
            if loss > 0.0:
                self.local_usable_memory_coeff -= self.local_usable_memory_coeff * loss / 2.0
            else:
                self.local_usable_memory_coeff = min(self.local_usable_memory_coeff * 1.1, 1.0)
            print(f"{self.node}: Usable memory: {self.local_usable_memory_coeff:.2f}")

        if not self.edge_enabled:
            # probably redundant, just to be sure
            self.aggregated_edge_memory = 0

        functions = [f for f in self.simulation.functions if f.is_default]

        params = OptCarbonAwareProblemParams(self.node,
                                             self.cloud_dispatchers,
                                             self.possible_decisions,
                                             functions,
                                             self.simulation.classes,
                                             self.simulation.function_variants,
                                             self.arrival_rates,
                                             self.estimated_service_time,  #local (include variants: [f][v]
                                             self.estimated_service_time_cloud,
                                             self.init_time_local,
                                             self.init_time_cloud,
                                             self.cold_start_prob_local,
                                             self.cold_start_prob_cloud,
                                             self.cloud_rtt,
                                             self.cloud_bw,
                                             self.local_usable_memory_coeff,
                                             self.local_budget,
                                             self.aggregated_edge_memory,
                                             self.estimated_service_time_edge,
                                             self.edge_rtt,
                                             self.cold_start_prob_edge,
                                             self.init_time_edge,
                                             self.edge_bw,
                                             self.aggregated_edge_power_consumption,
                                             self.aggregated_edge_power_tx,
                                             self.aggregated_edge_power_rx,
                                             self.co2_green_threshold,
                                             self.of_alpha,
                                             self.of_beta,
                                             self.simulation.t,
                                             self.simulation.lp_utilization_tmp_dict,
                                             self.simulation.lp_energy_tmp_dict,
                                             self.aggregated_edge_idle_power_consumption,
                                             self.aggregated_edge_cost
                                             )

        opt = self.get_optimizer()
        new_probs, variants_probs = opt.update_probabilities(params, self.simulation.verbosity)

        if new_probs is not None:
            self.probs = new_probs
        if variants_probs is not None:
            self.variants_probs = variants_probs

    def get_optimizer(self):
        optimizer_to_use = self.simulation.config.get(conf.SEC_POLICY, conf.QOS_OPTIMIZER, fallback="")
        if optimizer_to_use == "" or optimizer_to_use == "fgcs24" or optimizer_to_use == "lp":
            if self.of_alpha == 0.5 and self.of_beta == 0.5:
                opt = lp_optimizer_carbon_aware_normalized
            else:
                opt = lp_optimizer_carbon_aware
        elif optimizer_to_use == "nonlinear":
            opt = optimizer_nonlinear
        else:
            raise RuntimeError(f"Unknown optimizer: {optimizer_to_use}")
        return opt


class RandomPolicy(Policy):

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        self.rng = self.simulation.policy_rng1
        self.rng_variant = self.simulation.rng_variant
        self.decisions = list(SchedulerDecision)
        #self.decisions.remove(SchedulerDecision.OFFLOAD_EDGE)
        self.decisions_no_var = list(SchedulerDecision)
        self.decisions_no_var.remove(SchedulerDecision.EXEC_VAR)
        self.allow_multi_offloading = simulation.config.getboolean(conf.SEC_POLICY, conf.MULTIPLE_OFFLOADING_ALLOWED,
                                                                   fallback=False)

    def schedule(self, f, c, offloaded_from):
        decisions = self.decisions
        decisions_no_var = self.decisions_no_var

        if len(offloaded_from) > 0:
            if not self.allow_multi_offloading:
                if f.has_variants:
                    var = self.rng_variant.choice(f.variants)
                    func = var.self_function
                    if self.can_execute_locally(func):
                        f.active_variant = func
                        return SchedulerDecision.EXEC_VAR, None
                    else:
                        return SchedulerDecision.DROP, None
                else:
                    if self.can_execute_locally(f):
                        return SchedulerDecision.EXEC, None
                    else:
                        return SchedulerDecision.DROP, None

        if not f.has_variants:
            decision = self.rng.choice(decisions_no_var)

            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                decision = self.rng.choice(decisions_no_var[2:])
            return (decision, None)
        else:
            decision = self.rng.choice(decisions)

            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                decision = self.rng.choice(decisions[1:])
            if decision == SchedulerDecision.EXEC_VAR:
                var = self.rng_variant.choice(f.variants)
                func = var.self_function
                if self.can_execute_locally(func):
                    f.active_variant = func
                else:
                    decisions = decisions[2:]
                    decision = self.rng.choice(decisions)

            return (decision, None)


    def update(self):
        pass

class RandomPolicyNoDrop(Policy):

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        self.rng = self.simulation.policy_rng1
        self.rng_variant = self.simulation.rng_variant
        self.decisions = list(SchedulerDecision)
        #self.decisions.remove(SchedulerDecision.OFFLOAD_EDGE)
        self.decisions.remove(SchedulerDecision.DROP)
        self.decisions_no_var = list(SchedulerDecision)
        self.decisions_no_var.remove(SchedulerDecision.EXEC_VAR)
        self.decisions_no_var.remove(SchedulerDecision.DROP)

    def schedule(self, f, c, offloaded_from):
        decisions = self.decisions
        decisions_no_var = self.decisions_no_var

        if len(offloaded_from) > 0:
            if not self.allow_multi_offloading:
                if f.has_variants:
                    var = self.rng_variant.choice(f.variants)
                    func = var.self_function
                    if self.can_execute_locally(func):
                        f.active_variant = func
                        return SchedulerDecision.EXEC_VAR, None
                    else:
                        return SchedulerDecision.DROP, None
                else:
                    if self.can_execute_locally(f):
                        return SchedulerDecision.EXEC, None
                    else:
                        return SchedulerDecision.DROP, None

        if not f.has_variants:
            decision = self.rng.choice(decisions_no_var)
            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                decision = self.rng.choice(decisions_no_var[2:])
            return (decision, None)
        else:
            decision = self.rng.choice(decisions)

            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                decision = self.rng.choice(decisions[1:])
            if decision == SchedulerDecision.EXEC_VAR:
                var = self.rng_variant.choice(f.variants)
                func = var.self_function
                if self.can_execute_locally(func):
                    f.active_variant = func
                else:
                    decisions = decisions[2:]
                    decision = self.rng.choice(decisions)

            return (decision, None)

    def update(self):
        pass