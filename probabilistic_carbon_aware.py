from pacsltk import perfmodel

import conf
import lp_optimizer_carbon_aware
import optimizer_nonlinear
from optimization import OptProblemParams
from optimization_carbon_aware import OptCarbonAwareProblemParams
from policy import Policy, ColdStartEstimation, COLD_START_PROB_INITIAL_GUESS, \
    SchedulerDecisionMultiRegionManager, SchedulerDecisionMultiRegion

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

        self.rng_cloud_region = self.simulation.cloud_region_choice

        self.num_regions_cloud = int(simulation.infra.num_regions_cloud)
        assert (self.num_regions_cloud == len(simulation.infra.dispatchers))

        self.cloud_regions = self.simulation.infra.cloud_regions
        self.cloud_dispatchers = {} # dispatchers
        for region in self.cloud_regions:
            for dispatcher_node in self.simulation.infra.dispatchers:
                if dispatcher_node.region == region:
                    self.cloud_dispatchers[region] = dispatcher_node

        self.cloud_nodes = {}  # cloud nodes without dispatcher_node
        for region in self.cloud_regions:
                    self.cloud_nodes[region] = [n for n in self.simulation.infra.get_nodes_by_region(region) if conf.DISPATCHER not in n.name]

        print("cloud_dispatchers: ", self.cloud_dispatchers)

        self.local_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE))
        assert (self.local_cold_start_estimation != ColdStartEstimation.FULL_KNOWLEDGE)
        self.cloud_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE))
        assert (self.cloud_cold_start_estimation != ColdStartEstimation.FULL_KNOWLEDGE)
        self.edge_cold_start_estimation = ColdStartEstimation.from_string(
            self.simulation.config.get(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY,
                                       fallback=ColdStartEstimation.NAIVE))
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
        self.estimated_service_time_cloud = {region: {} for region in self.cloud_regions}
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

        self.probability_tag = (["local", "edge", "drop"]
                                + [f"{region.name}" for region in self.cloud_regions])

        print("probability_tag: ", self.probability_tag)
        self.possible_decisions = list(decision.name if isinstance(decision, SchedulerDecisionMultiRegion) else str(decision)
        for decision in SchedulerDecisionMultiRegionManager.get_decisions().values())

        self.probs = {
            (f, c): {
                decision: prob
                for decision, prob in zip(
                    self.possible_decisions,
                    [0.5, 0.5, 0.0] + [0.0] * self.num_regions_cloud
                )
            }
            for f in simulation.functions
            for c in simulation.classes
        }

        '''
             self.probs = {
            (f, c):#[
                {"decision": decision, "probability": prob}
                for decision, prob in zip(
                    self.possible_decisions,
                    [0.5, 0.5, 0.0] + [0.0] * self.num_regions_cloud
                )
            #]
            for f in simulation.functions
            for c in simulation.classes

        }
        '''



        # Build a decision-to-index mapping for cloud region probabilities
        '''
        self.decision_to_index = {}
        for key, value in self.probs.items():
            for i, decision_entry in enumerate(value):
                if conf.CLOUD in decision_entry["decision"]:
                    region_index = int(decision_entry["decision"].split("_")[-1])
                    self.decision_to_index[region_index] = i
        '''


        '''
        self.probs = {
            (f, c): [0.5, 0.5, 0.0] + [0.0] * self.num_regions_cloud
            for f in simulation.functions
            for c in simulation.classes
        }
        '''

        print("probs: ", self.probs)


    def schedule(self, f, c, offloaded_from):
        probabilities = self.probs[(f, c)].copy()
        #probabilities = {item['decision']: item['probability'] for item in self.probs[(f, c)].copy()}
        # If the request has already been offloaded, cannot offload again
        if len(offloaded_from) > 0 and not self.allow_multi_offloading:
            for decision, prob in probabilities:
                if conf.EDGE or conf.CLOUD in decision:
                    prob = 0

            # Renormalize probabilities if any have been zeroed out
            s = sum(probabilities.values())
            if s <= 0.0:
                return (SchedulerDecisionMultiRegion.DROP, None)
            else:
                #new_probs = [x / s for x in probabilities.values()]
                probabilities = self.renormalize_probs(probabilities, s)

        #decision = self.rng.choice(self.possible_decisions, p=probabilities)
        # Convert dictionary to list in the correct order for rng.choice
        decision = self.rng.choice(list(probabilities.keys()), p=list(probabilities.values()))
        if decision == SchedulerDecisionMultiRegion.EXEC:
            self.curr_local_reqs += 1

        # Local rejection due to lack of resources
        if decision == SchedulerDecisionMultiRegion.EXEC and not self.can_execute_locally(f):
            self.curr_local_blocked_reqs += 1

            if self.local_rejection_fallback == "fgcs24" or self.local_rejection_fallback == "reschedule":
                probabilities[conf.EXEC] = 0

                if self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
                    for decision, prob in probabilities:
                        if conf.CLOUD in decision:
                            prob = 0

                s = sum(probabilities.values())
                if not s > 0.0:
                    # NOTE: we may add new Cloud offloadings even if p_cloud=0
                    # Attempt Cloud offloading if utility allows
                    if c.utility > 0.0 and \
                            self.simulation.stats.cost / self.simulation.t * 3600 < self.budget \
                            and (self.allow_multi_offloading or len(offloaded_from) == 0):

                        cloud_decisions = []
                        cloud_probs = []
                        for decision, prob in probabilities:
                            if conf.CLOUD in decision:
                                cloud_decisions.append(decision)
                                cloud_probs.append(prob)

                        decision = self.rng_cloud_region(cloud_decisions, p=cloud_probs)

                        return (decision, None)
                    else:
                        return (SchedulerDecisionMultiRegion.DROP, None)

                probabilities = self.renormalize_probs(probabilities, s)
                #decision_probs = [probabilities[tag] for tag in self.probability_tag]
                return (self.rng.choice(list(probabilities.keys), p=list(probabilities.values)), None)

            elif self.local_rejection_fallback == "drop":
                return (SchedulerDecisionMultiRegion.DROP, None)
            else:
                raise RuntimeError(f"Unknown local rejection fallback: {self.local_rejection_fallback}")


        if conf.CLOUD in decision and self.strict_budget_enforce and \
                self.simulation.stats.cost / self.simulation.t * 3600 > self.budget:
            return (SchedulerDecisionMultiRegion.DROP, None)

        return (decision, None)

    def renormalize_probs(self, probabilities, s):
        for decision, prob in probabilities:
            probabilities[decision] = prob / s
        return probabilities

    def update(self):
        self.update_metrics()

        arrivals = sum(
            [self.arrival_rates.get((f, c), 0.0) for f in self.simulation.functions for c in self.simulation.classes])
        if arrivals > 0.0:
            # trigger the optimizer
            self.update_probabilities()

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
                if node_compl > 0:
                    self.cold_start_prob_local[f] = node_cs / node_compl
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f, self.node), 0) > 0:
                    self.cold_start_prob_local[f] = stats.cold_starts.get((f, self.node),
                                                                          0) / stats.node2completions.get(
                        (f, self.node), 0)
                else:
                    self.cold_start_prob_local[f] = COLD_START_PROB_INITIAL_GUESS
        else:  # No
            for f in self.simulation.functions:
                self.cold_start_prob_local[f] = 0

        # CLOUD

        for region, dispatcher in self.cloud_dispatchers.items():
            node_compl = sum([dispatcher.avg_node2completions.get(_f, 0) for _f in self.simulation.functions])
            node_cs = sum([dispatcher.avg_cold_starts.get(_f, 0) for _f in self.simulation.functions])

            for f in self.simulation.functions:

                if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
                    total_arrival_rate = max(
                        0.001,
                        sum([
                            self.arrival_rates.get((f, x), 0.0) *
                            self.probs[(f, x)][dispatcher.decision]
                            for x in self.simulation.classes
                        ]))
                    props1, _ = perfmodel.get_sls_warm_count_dist(
                        total_arrival_rate,
                        self.estimated_service_time_cloud[region][f],
                        self.estimated_service_time_cloud[region][f] + self.simulation.init_time[
                            (f, dispatcher)],   #gia gestito in simulation
                        self.simulation.expiration_timeout
                    )
                    self.cold_start_prob_cloud[(region, f)] = props1["cold_prob"]

                elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
                    if node_compl > 0:
                        self.cold_start_prob_cloud[(region, f)] = node_cs / node_compl
                    else:
                        self.cold_start_prob_cloud[(region, f)] = COLD_START_PROB_INITIAL_GUESS

                elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
                    if dispatcher.avg_node2completions.get(f, 0) > 0:
                        self.cold_start_prob_cloud[(region, f)] = dispatcher.avg_cold_starts(f, 0) / dispatcher.node2completions.get(f, 0)
                    else:
                        self.cold_start_prob_cloud[(region, f)] = COLD_START_PROB_INITIAL_GUESS

                else:  # No estimation
                    self.cold_start_prob_cloud[(region, f)] = 0

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
            if stats.node2completions[(f, self.node)] > 0: #todo qui ci vanno exec time esposti dal dispatcher
                self.estimated_service_time[f] = stats.execution_time_sum[(f, self.node)] / \
                                                 stats.node2completions[(f, self.node)]
            else:
                self.estimated_service_time[f] = 0.1

            for region, dispatcher in self.cloud_dispatchers.items(): #######
                if dispatcher.avg_node2completions[f] > 0:
                    self.estimated_service_time_cloud[region, f] = dispatcher.avg_execution_time_sum[f] / \
                                                           dispatcher.avg_node2completions[f]
                else:
                    self.estimated_service_time_cloud[region, f] = 0.1

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
            if len(neighbors) == 0:
                self.aggregated_edge_memory = 0
            else:
                self.aggregated_edge_memory = max(1, sum([x.curr_memory * x.peer_exposed_memory_fraction for x in
                                                          neighbors]))

            self.edge_rtt = sum(
                [self.simulation.infra.get_latency(self.node, x) * prob for x, prob in zip(neighbors, neighbor_probs)])
            self.edge_bw = sum([self.simulation.infra.get_bandwidth(self.node, x) * prob for x, prob in
                                zip(neighbors, neighbor_probs)])

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

        if self.edge_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_offloaded_rate = max(0.001, \
                                           sum([self.arrival_rates.get((f, x), 0.0) * self.probs[(f, x)][3] for x in
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

        params = OptCarbonAwareProblemParams(self.node,
                                  self.cloud_dispatchers,   #todo: modifica
                                  self.simulation.functions,
                                  self.simulation.classes,
                                  self.arrival_rates,
                                  self.estimated_service_time,
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
                                  self.edge_bw)

        opt = self.get_optimizer()
        new_probs = opt.update_probabilities(params, self.simulation.verbosity)

        if new_probs is not None:
            self.probs = new_probs
            # print(f"[{self.node}] Probs: {self.probs}")

    def get_optimizer(self):
        optimizer_to_use = self.simulation.config.get(conf.SEC_POLICY, conf.QOS_OPTIMIZER, fallback="")
        if optimizer_to_use == "" or optimizer_to_use == "fgcs24" or optimizer_to_use == "lp":
            opt = lp_optimizer_carbon_aware
        elif optimizer_to_use == "nonlinear":
            opt = optimizer_nonlinear
        else:
            raise RuntimeError(f"Unknown optimizer: {optimizer_to_use}")
        return opt


class OfflineProbabilisticCarbonAwarePolicy(ProbabilisticCarbonAwarePolicy):
    """
    Probabilistic, with probabilities computed offline with *known* parameters.
    An ideal approach.
    """

    def __init__(self, simulation, node, strict_budget_enforce=False):
        super().__init__(simulation, node, strict_budget_enforce)

        if not self.edge_enabled:
            # probably redundant, just to be sure
            self.aggregated_edge_memory = 0

        if not self.node in self.simulation.node2arrivals:
            # No arrivals here... just skip
            self.probs = {(f, c): [0.5, 0.5, 0., 0.] for f in simulation.functions for c in simulation.classes}
            return

        self.update_metrics()

        params = OptProblemParams(self.node,
                                  self.cloud,
                                  self.simulation.functions,
                                  self.simulation.classes,
                                  self.arrival_rates,
                                  self.estimated_service_time,
                                  self.estimated_service_time_cloud,
                                  self.init_time_local,
                                  self.init_time_cloud,
                                  self.cold_start_prob_local,
                                  self.cold_start_prob_cloud,
                                  self.cloud_rtt,
                                  self.cloud_bw,
                                  1.0,
                                  self.local_budget,
                                  self.aggregated_edge_memory,
                                  self.estimated_service_time_edge,
                                  self.edge_rtt,
                                  self.cold_start_prob_edge,
                                  self.init_time_edge,
                                  self.edge_bw)

        self.probs = self.get_optimizer().update_probabilities(params, self.simulation.verbosity)

    def update(self):
        pass

    def update_metrics(self):

        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}

        for f in self.simulation.functions:
            self.estimated_service_time[f] = f.serviceMean / self.node.speedup
            self.estimated_service_time_cloud[f] = f.serviceMean / self.cloud.speedup

        for arv_proc in self.simulation.node2arrivals[self.node]:
            f = arv_proc.function
            # NOTE: this only works for some arrival processes (e.g., not for
            # trace-driven)
            rate_per_class = arv_proc.get_per_class_mean_rate()
            for c, r in rate_per_class.items():
                self.arrival_rates[(f, c)] = r

        self.estimate_cold_start_prob(self.simulation.stats)  # stats are empty at this point...

        self.cloud_rtt = 2 * self.simulation.infra.get_latency(self.node, self.cloud)
        self.cloud_bw = self.simulation.infra.get_bandwidth(self.node, self.cloud)

        if self.edge_enabled:
            neighbor_probs, neighbors = self._get_edge_peers_probabilities()
            if len(neighbors) == 0:
                self.aggregated_edge_memory = 0
            else:
                self.aggregated_edge_memory = max(1, sum([x.curr_memory * x.peer_exposed_memory_fraction for x in
                                                          neighbors]))

            self.edge_rtt = sum(
                [self.simulation.infra.get_latency(self.node, x) * prob for x, prob in zip(neighbors, neighbor_probs)])
            self.edge_bw = sum([self.simulation.infra.get_bandwidth(self.node, x) * prob for x, prob in
                                zip(neighbors, neighbor_probs)])

            self.estimated_service_time_edge = {}
            for f in self.simulation.functions:
                inittime = 0.0
                servtime = 0.0
                for neighbor, prob in zip(neighbors, neighbor_probs):
                    servtime += prob * f.serviceMean / neighbor.speedup
                    inittime += prob * self.simulation.init_time[(f, neighbor)]
                if servtime == 0.0:
                    servtime = self.estimated_service_time[f]
                self.estimated_service_time_edge[f] = servtime
                self.init_time_edge[f] = inittime

            self.estimate_edge_cold_start_prob(self.simulation.stats, neighbors, neighbor_probs)



