from enum import Enum, auto
from pacsltk import perfmodel

import conf
from co2_footprint import compute_local_energy, compute_cloud_energy, compute_local_variant_energy, compute_edge_energy
from faas import Dispatcher
from collections import defaultdict

COLD_START_PROB_INITIAL_GUESS = 0.0

class SchedulerDecision(Enum):
    EXEC = 1
    EXEC_VAR = 2
    OFFLOAD_EDGE = 3
    DROP = 4

def add_enum_members(enum_class, regions:list):
    """
    Dynamically adds new members to an existing Enum class by creating a new Enum.

    Args:
        enum_class: The existing Enum class.
        new_members: A dictionary of new members to add, where the key is the name, and the value is the value.

    Returns:
        A new Enum class with the added members.
    """
    new_members = {}
    start_index = max(member.value for member in enum_class)

    # Add dynamic cloud offloading options
    for region in regions:
        if region.is_cloud():
            start_index = start_index + 1
            decision_key = conf.OFFLOAD_CLOUD_DECISION + region.name.upper()
            new_members[decision_key] = start_index

    for name, value in new_members.items():
        # Ensure the member name doesn't already exist
        if name in enum_class.__members__:
            return
            #raise ValueError(f"Member '{name}' already exists in {enum_class.__name__}.")

        # Create a new member bypassing Enum's immutability restrictions
        member = object.__new__(enum_class)
        member._name_ = name
        member._value_ = value

        # Update Enum's internal mappings
        setattr(enum_class, name, member)
        enum_class._member_names_.append(name)
        enum_class._member_map_[name] = member


    print(enum_class)


class ColdStartEstimation(Enum):
    NO = auto()
    NAIVE = auto()
    NAIVE_PER_FUNCTION = auto()
    PACS = auto()
    FULL_KNOWLEDGE = auto()

    @classmethod
    def from_string(cls,s):

        #s = s.name.lower()
        s = s.lower()
        if s == "no":
            return ColdStartEstimation.NO
        elif s == "naive" or s == "":
            return ColdStartEstimation.NAIVE
        elif s == "naive-per-function":
            return ColdStartEstimation.NAIVE_PER_FUNCTION
        elif s == "pacs":
            return ColdStartEstimation.PACS
        elif s == "full-knowledge":
            return ColdStartEstimation.FULL_KNOWLEDGE
        return None


class Policy:

    def __init__(self, simulation, node):
        self.simulation = simulation
        self.node = node
        self.__edge_peers = None
        self.budget = simulation.config.getfloat(conf.SEC_POLICY, conf.HOURLY_BUDGET, fallback=-1.0)
        self.local_budget = self.budget
        if simulation.config.getboolean(conf.SEC_POLICY, conf.SPLIT_BUDGET_AMONG_EDGE_NODES, fallback=False):
            nodes = len(simulation.infra.get_edge_nodes())
            self.local_budget = self.budget / nodes

        self.__region_peers = None


    def schedule(self, function, qos_class, offloaded_from):
        pass

    def update(self):
        pass

    def can_execute_locally(self, f, reclaim_memory=True):
        if f in self.node.warm_pool or self.node.curr_memory >= f.memory:
            return True
        if reclaim_memory:
            reclaimed = self.node.warm_pool.reclaim_memory(f.memory - self.node.curr_memory)
            self.node.curr_memory += reclaimed
        return self.node.curr_memory >= f.memory

    def _get_edge_peers (self):
        if self.__edge_peers is None:
            # TODO: need to refresh over time?
            self.__edge_peers = self.simulation.infra.get_neighbors_node(self.node, self.simulation.node_choice_rng, self.simulation.max_neighbors)
        return self.__edge_peers

    def _get_edge_peers_probabilities(self):
        # Filter peers to include only those with memory left
        peers = [peer for peer in self._get_edge_peers() if peer.curr_memory > 0.0]
        if not peers:  # If no peers have memory left, handle gracefully
            return [], []  # Return empty probabilities and peers

        valid_peers = []
        for peer in peers:
            if peer.curr_memory < 0.0:
                print(f"Invalid peer detected (negative memory): {peer}, memory: {peer.curr_memory}")
                continue
            if peer.peer_exposed_memory_fraction < 0.0:
                print(
                    f"Invalid peer detected (negative exposed memory fraction): {peer}, exposed fraction: {peer.peer_exposed_memory_fraction}")
                continue

            valid_peers.append(peer)
        if not valid_peers:  # Handle case where all peers are invalid
            return [], []

        total_memory = sum(x.curr_memory * x.peer_exposed_memory_fraction for x in valid_peers)
        if total_memory > 0.0:
            probs = [x.curr_memory * x.peer_exposed_memory_fraction / total_memory for x in valid_peers]
        else:
            n = len(valid_peers)
            probs = [1.0 / n for _ in valid_peers]
        return probs, valid_peers

    # Picks a node for Edge offloading
    def pick_edge_node (self, fun, qos):
        # Pick peers based on resource availability
        probs, peers = self._get_edge_peers_probabilities()
        if len(peers) < 1:
            return None
        return self.simulation.node_choice_rng.choice(peers, p=probs)

    def compute_g_co2_decision(self, current_node, f, c, scheduler_decision):
        if scheduler_decision == SchedulerDecision.EXEC:
            current_node.g_co2_emissions[f][SchedulerDecision.EXEC] = compute_local_energy(
                f, current_node, f.serviceMean)
        elif scheduler_decision == SchedulerDecision.EXEC_VAR:
            v = f.active_variant
            current_node.g_co2_emissions[v][SchedulerDecision.EXEC_VAR] = compute_local_variant_energy(
                v, current_node, v.serviceMean)
        elif scheduler_decision == SchedulerDecision.OFFLOAD_EDGE:
            remote_node = self.pick_edge_node(f, c)
            current_node.g_co2_emissions[f][scheduler_decision] = compute_edge_energy(
                f, remote_node.curr_memory * remote_node.peer_exposed_memory_fraction, remote_node.processing_power_consumption,
                f.serviceMean, current_node.tx_energy_consumption, remote_node.rx_energy_consumption,
                current_node.rx_energy_consumption, remote_node.tx_energy_consumption,
                remote_node.co2_footprint.co2_intensity)
        elif conf.OFFLOAD_CLOUD_DECISION in scheduler_decision.name:
            region_name = self.simulation.get_region_name_by_scheduler_decision(scheduler_decision)
            remote_node = self.simulation.pick_cloud_remote_node_by_region(region_name)
            #current_node.g_co2_emissions[f][scheduler_decision] = compute_cloud_energy(f, remote_node, f.serviceMean,
            #                                                                           current_node.tx_energy_consumption,
            #                                                                           current_node.rx_energy_consumption)


class BasicPolicy(Policy):

    def schedule(self, f, c, offloaded_from):
        if self.can_execute_locally(f):
            return (SchedulerDecision.EXEC, None)
        else:
            return (SchedulerDecision.OFFLOAD_CLOUD, None)


class BasicPolicyMultiRegion(Policy):

    def schedule(self, f, c, offloaded_from):
        scheduler_decision_cloud, remote_node_cloud = self.simulation.pick_closest_cloud_region(self.node)

        if not self.simulation.is_approximate_computing_enabled:
            if self.can_execute_locally(f):
                scheduler_decision, remote_node = SchedulerDecision.EXEC, None
            else:
                scheduler_decision, remote_node = scheduler_decision_cloud, remote_node_cloud
        else:
            if f.has_variants:
                # returns the variant with the minimum speedup
                lightest_variant = min(f.variants, key=lambda variant: variant.speedup)
                lightest_variant_func = lightest_variant.self_function
                if self.can_execute_locally(lightest_variant_func):
                    f.active_variant = lightest_variant_func
                    scheduler_decision, remote_node = SchedulerDecision.EXEC_VAR, None
                else:
                    scheduler_decision, remote_node = scheduler_decision_cloud, remote_node_cloud

            else:
                if self.can_execute_locally(f):
                    scheduler_decision, remote_node = SchedulerDecision.EXEC, None
                else:
                    scheduler_decision, remote_node = scheduler_decision_cloud, remote_node_cloud

        #self.compute_g_co2_decision(self.node, f, c, scheduler_decision)
        return scheduler_decision, remote_node

class BasicBudgetAwarePolicy(Policy):

    def schedule(self, f, c, offloaded_from):
        budget_ok = self.simulation.stats.cost / self.simulation.t * 3600 < self.budget

        if self.can_execute_locally(f):
            return (SchedulerDecision.EXEC, None)
        elif self.simulation.stats.cost / self.simulation.t * 3600 < self.budget:
            return (SchedulerDecision.OFFLOAD_CLOUD, None)
        else:
            return (SchedulerDecision.DROP, None)

class BasicEdgePolicy(Policy):

    def schedule(self, f, c, offloaded_from):
        if self.can_execute_locally(f):
            return (SchedulerDecision.EXEC, None)
        elif len(offloaded_from) == 0:
            return (SchedulerDecision.OFFLOAD_EDGE, self.pick_edge_node(f,c))
        else:
            return (SchedulerDecision.DROP, None)

class CloudPolicy(Policy):

    def schedule(self, f, c, offloaded_from):
        if self.can_execute_locally(f):
            return (SchedulerDecision.EXEC, None)
        else:
            return (SchedulerDecision.DROP, None)

class CloudRegionDispatcherRandomPolicy(Policy):

    def __init__(self, simulation, node: Dispatcher):
        super().__init__(simulation, node)
        self.region = node.region
        self.cloud_region_nodes = simulation.infra.get_cloud_nodes_by_region(self.region)
        self.rng = simulation.cloud_node_random_choice
        node.aggregated_region_memory = sum(cloud_node.curr_memory for cloud_node in self.cloud_region_nodes)
        node.avg_speedup = (sum(cloud_node.speedup for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.aggregated_region_cost = (sum(cloud_node.cost for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.cost = (sum(cloud_node.cost for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.avg_processing_power_consumption = (sum(cloud_node.processing_power_consumption for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.avg_tx_energy_consumption = (sum(cloud_node.tx_energy_consumption for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.avg_rx_energy_consumption = (sum(cloud_node.rx_energy_consumption for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.cloud_nodes_list = self.cloud_region_nodes

    def update(self):
        self.node.aggregated_region_memory = sum(cloud_node.curr_memory for cloud_node in self.cloud_region_nodes)
        stats = self.simulation.stats
        num_nodes = len(self.cloud_region_nodes)

        for f in self.simulation.functions:
            #accumulate stats across all cloud region nodes for f
            exec_time_sum = sum(
                stats.execution_time_sum_cloud_nodes[(self.region, f, n)] for n in self.cloud_region_nodes)
            completions_sum = sum(stats.completions_cloud_nodes[(self.region, f, n)] for n in self.cloud_region_nodes)
            cold_starts_sum = sum(stats.cold_starts_cloud_nodes[(self.region, f, n)] for n in self.cloud_region_nodes)

            avg_completions = completions_sum / num_nodes
            avg_exec_time = exec_time_sum / num_nodes
            avg_cold_starts = cold_starts_sum / num_nodes

            self.node.avg_node2completions[f] = avg_completions
            self.node.avg_execution_time_sum[f] = avg_exec_time
            self.node.avg_cold_starts[f] = avg_cold_starts

            #print("update policy dispatcher -> self.node.avg_node2completions[f] = ",self.node.avg_node2completions)
            #print("update policy dispatcher ->self.node.avg_exec_time[f] = ",self.node.avg_execution_time_sum)
            #print("update policy dispatcher ->self.node.avg_cold_starts[f] = ",self.node.avg_cold_starts)



    def schedule(self, f, c, offloaded_from):
        selected_node = self.rng.choice(self.cloud_region_nodes)
        decision = conf.OFFLOAD_CLOUD_DECISION+self.region.name.upper()
        return (decision, selected_node)


class GreedyPolicy(Policy):

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        self.cold_start_prob = {}
        self.cold_start_prob_cloud = {}
        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}

        self.local_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, fallback=""))
        self.cloud_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, fallback=""))

        # OLD: cloud_region = node.region.default_cloud
        #self.cloud = self.simulation.node_choice_rng.choice(self.simulation.infra.get_region_nodes(cloud_region), 1)[0]

        # Pick the closest cloud node
        nodes_w_lat = [(_n,simulation.infra.get_latency(node,_n)) for _n in simulation.infra.get_cloud_nodes()]
        self.cloud = sorted(nodes_w_lat, key=lambda x: x[1])[0][0]

    def _estimate_latency (self, f, c):
        if self.local_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.node.warm_pool:
                self.cold_start_prob[(f, self.node)] = 0
            else:
                self.cold_start_prob[(f, self.node)] = 1
        if self.cloud_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.cloud.warm_pool:
                self.cold_start_prob[(f, self.cloud)] = 0
            else:
                self.cold_start_prob[(f, self.cloud)] = 1

        latency_local = self.estimated_service_time.get(f, 0) + \
                        self.cold_start_prob.get((f, self.node), 1) * \
                        self.simulation.init_time[(f,self.node)]

        latency_cloud = self.estimated_service_time_cloud.get(f, 0) +\
                2 * self.simulation.infra.get_latency(self.node, self.cloud) + \
                        self.cold_start_prob.get((f, self.cloud), 1) * self.simulation.init_time[(f,self.cloud)] +\
                        f.inputSizeMean*8/1000/1000/self.simulation.infra.get_bandwidth(self.node, self.cloud)
        return (latency_local, latency_cloud)

    def schedule(self, f, c, offloaded_from):
        latency_local, latency_cloud = self._estimate_latency(f,c)

        if self.can_execute_locally(f) and latency_local < latency_cloud:
            return (SchedulerDecision.EXEC, None)
        else:
            return (SchedulerDecision.OFFLOAD_CLOUD, self.cloud)

    def update_cold_start (self, stats):
        #
        # LOCAL NODE
        #
        if self.local_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,self.node), 0.0) for x in self.simulation.classes])/self.simulation.t)
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time[f],
                                                            self.estimated_service_time[f] + self.simulation.init_time[(f,self.node)],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob[(f, self.node)] = props1["cold_prob"]
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.node)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.node)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob[(f, self.node)] = node_cs / node_compl
                else:
                    self.cold_start_prob[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.node), 0) > 0:
                    self.cold_start_prob[(f, self.node)] = stats.cold_starts.get((f,self.node),0) / stats.node2completions.get((f,self.node),0)
                else:
                    self.cold_start_prob[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NO: 
            for f in self.simulation.functions:
                self.cold_start_prob[(f, self.node)] = 0

        # CLOUD
        #
        if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,self.cloud), 0.0) for x in self.simulation.classes])/self.simulation.t)
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time[f],
                                                            self.estimated_service_time[f] + self.simulation.init_time[(f,self.cloud)],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob[(f, self.cloud)] = props1["cold_prob"]
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.cloud)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.cloud)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob[(f, self.cloud)] = node_cs / node_compl
                else:
                    self.cold_start_prob[(f, self.cloud)] = COLD_START_PROB_INITIAL_GUESS
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.cloud), 0) > 0:
                    self.cold_start_prob[(f, self.cloud)] = stats.cold_starts.get((f,self.cloud),0) / stats.node2completions.get((f,self.cloud),0)
                else:
                    self.cold_start_prob[(f, self.cloud)] = COLD_START_PROB_INITIAL_GUESS
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NO: 
            for f in self.simulation.functions:
                self.cold_start_prob[(f, self.cloud)] = 0

    def update(self):
        stats = self.simulation.stats

        for f in self.simulation.functions:
            if stats.node2completions[(f, self.node)] > 0:
                self.estimated_service_time[f] = stats.execution_time_sum[(f, self.node)] / \
                                                 stats.node2completions[(f, self.node)]
            else:
                self.estimated_service_time[f] = 0.1
            if stats.node2completions[(f, self.cloud)] > 0:
                self.estimated_service_time_cloud[f] = stats.execution_time_sum[(f, self.cloud)] / \
                                                       stats.node2completions[(f, self.cloud)]
            else:
                self.estimated_service_time_cloud[f] = 0.1

        self.update_cold_start(stats)

class GreedyPolicyMultiRegion(Policy):

    def __init__(self, simulation, node):
        super().__init__(simulation, node)
        self.cold_start_prob = {}
        self.cold_start_prob_cloud = {}
        self.estimated_service_time = {}
        self.estimated_service_time_cloud = {}

        self.local_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, fallback=""))
        self.cloud_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, fallback=""))

        # Pick the closest cloud node
        scheduler_decision_cloud, closest_dispatcher = self.simulation.pick_closest_cloud_region(self.node)
        self.offload_cloud_decision = scheduler_decision_cloud
        self.dispatcher = closest_dispatcher
        self.cloud = simulation.infra.get_cloud_nodes_by_region(closest_dispatcher.region)[0]


    def _estimate_latency (self, f, c):
        if self.local_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.node.warm_pool:
                self.cold_start_prob[(f, self.node)] = 0
            else:
                self.cold_start_prob[(f, self.node)] = 1
        if self.cloud_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.cloud.warm_pool:
                self.cold_start_prob[(f, self.cloud)] = 0
            else:
                self.cold_start_prob[(f, self.cloud)] = 1

        latency_local = self.estimated_service_time.get(f, 0) + \
                        self.cold_start_prob.get((f, self.node), 1) * \
                        self.simulation.init_time[(f,self.node)]

        latency_cloud = self.estimated_service_time_cloud.get(f, 0) +\
                2 * self.simulation.infra.get_latency(self.node, self.cloud) + \
                        self.cold_start_prob.get((f, self.cloud), 1) * self.simulation.init_time[(f,self.cloud)] +\
                        f.inputSizeMean*8/1000/1000/self.simulation.infra.get_bandwidth(self.node, self.cloud)
        return (latency_local, latency_cloud)

    def schedule(self, f, c, offloaded_from):

        remote_node = None
        if not self.simulation.is_approximate_computing_enabled:
            latency_local, latency_cloud = self._estimate_latency(f, c)
            if self.can_execute_locally(f) and latency_local < latency_cloud:
                scheduler_decision = SchedulerDecision.EXEC

            else:
                scheduler_decision = self.offload_cloud_decision
                remote_node = self.dispatcher
        else:
            if f.has_variants:
                # returns the variant with the minimum speedup
                lightest_variant = min(f.variants, key=lambda variant: variant.speedup)
                lightest_variant_func = lightest_variant.self_function
                latency_local_var, latency_cloud = self._estimate_latency(lightest_variant_func, c)
                #latency_local_var, latency_cloud = self._estimate_latency(f, c)
                if self.can_execute_locally(lightest_variant_func) and latency_local_var < latency_cloud:
                    f.active_variant = lightest_variant_func
                    scheduler_decision, remote_node = SchedulerDecision.EXEC_VAR, None
                else:
                    scheduler_decision, remote_node = self.offload_cloud_decision, self.dispatcher


            else:
                latency_local, latency_cloud = self._estimate_latency(f, c)
                if self.can_execute_locally(f) and latency_local < latency_cloud:
                    scheduler_decision, remote_node = SchedulerDecision.EXEC, None
                else:
                    scheduler_decision, remote_node = self.offload_cloud_decision, self.dispatcher


        #self.compute_g_co2_decision(self.node, f, c, scheduler_decision)
        return scheduler_decision, remote_node

    def update_cold_start (self, stats):
        #
        # LOCAL NODE
        #
        if self.local_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,self.node), 0.0) for x in self.simulation.classes])/self.simulation.t)
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time[f],
                                                            self.estimated_service_time[f] + self.simulation.init_time[(f,self.node)],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob[(f, self.node)] = props1["cold_prob"]
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.node)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.node)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob[(f, self.node)] = node_cs / node_compl
                else:
                    self.cold_start_prob[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.node), 0) > 0:
                    self.cold_start_prob[(f, self.node)] = stats.cold_starts.get((f,self.node),0) / stats.node2completions.get((f,self.node),0)
                else:
                    self.cold_start_prob[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NO:
            for f in self.simulation.functions:
                self.cold_start_prob[(f, self.node)] = 0

        # CLOUD
        #
        if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,self.cloud), 0.0) for x in self.simulation.classes])/self.simulation.t)
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time[f],
                                                            self.estimated_service_time[f] + self.simulation.init_time[(f,self.cloud)],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob[(f, self.cloud)] = props1["cold_prob"]
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.cloud)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.cloud)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob[(f, self.cloud)] = node_cs / node_compl
                else:
                    self.cold_start_prob[(f, self.cloud)] = COLD_START_PROB_INITIAL_GUESS
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.cloud), 0) > 0:
                    self.cold_start_prob[(f, self.cloud)] = stats.cold_starts.get((f,self.cloud),0) / stats.node2completions.get((f,self.cloud),0)
                else:
                    self.cold_start_prob[(f, self.cloud)] = COLD_START_PROB_INITIAL_GUESS
        elif self.cloud_cold_start_estimation == ColdStartEstimation.NO:
            for f in self.simulation.functions:
                self.cold_start_prob[(f, self.cloud)] = 0

    def update(self):
        stats = self.simulation.stats

        for f in self.simulation.functions:
            if stats.node2completions[(f, self.node)] > 0:
                self.estimated_service_time[f] = stats.execution_time_sum[(f, self.node)] / \
                                                 stats.node2completions[(f, self.node)]
            else:
                self.estimated_service_time[f] = 0.1
            if stats.node2completions[(f, self.cloud)] > 0:
                self.estimated_service_time_cloud[f] = stats.execution_time_sum[(f, self.cloud)] / \
                                                       stats.node2completions[(f, self.cloud)]
            else:
                self.estimated_service_time_cloud[f] = 0.1

        self.update_cold_start(stats)

class GreedyCarbonAware(GreedyPolicy):

    def __init__ (self, simulation, node):
        super().__init__(simulation, node)
        self.decision_dispatcher = {}
        self.decision_co2 = defaultdict(list)   #k: co2_intensity v: [decision] -> for general decision

        for dispatcher in self.simulation.infra.dispatchers:
            for decision in SchedulerDecision:
                if dispatcher.region.name.upper() in decision.name:
                    self.decision_co2[dispatcher.co2_footprint.co2_intensity].append(decision)
                    self.decision_dispatcher[decision] = dispatcher

        # cloud ranking of lowest co2 for offloading in case of impossible local execution
        self.cloud_co2_ranking = dict(sorted(self.decision_co2.items())) #k: co2_intensity v: [decision]
        self.decision_co2[self.node.co2_footprint.co2_intensity].append(SchedulerDecision.EXEC)

    def schedule(self, f, c, offloaded_from):
        remote_node = None

        lowest_co2, decisions = min(self.decision_co2.items(), key=lambda item: item[0])
        decision = decisions[0]

        if not self.simulation.is_approximate_computing_enabled:
            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                #offloading verso cloud a region con tasso co2 minore
                first_co2_intensity, first_decisions = next(iter(self.cloud_co2_ranking.items()))
                decision = first_decisions[0]

        else:

            if decision == SchedulerDecision.EXEC:
                if f.has_variants:
                    lightest_variant = min(f.variants, key=lambda variant: variant.speedup)
                    lightest_variant_func = lightest_variant.self_function
                    if self.can_execute_locally(lightest_variant_func):
                        f.active_variant = lightest_variant_func
                        decision = SchedulerDecision.EXEC_VAR
                    else: #offload to cloud
                        first_co2_intensity, first_decisions = next(iter(self.cloud_co2_ranking.items()))
                        decision = first_decisions[0]
                else:
                    if not self.can_execute_locally(f):
                        # offloading verso cloud a region con tasso co2 minore
                        first_co2_intensity, first_decisions = next(iter(self.cloud_co2_ranking.items()))
                        decision = first_decisions[0]

        if conf.OFFLOAD_CLOUD_DECISION in decision.name:
            remote_node = self.decision_dispatcher[decision]

        #self.compute_g_co2_decision(self.node, f, c, decision)
        return decision, remote_node

class GreedyCarbonAwareStrict(GreedyPolicy):

    def __init__ (self, simulation, node):
        super().__init__(simulation, node)
        self.decision_dispatcher = {}
        self.decision_co2 = defaultdict(list)   #k: co2_intensity v: [decision] -> for general decision

        for dispatcher in self.simulation.infra.dispatchers:
            for decision in SchedulerDecision:
                if dispatcher.region.name.upper() in decision.name:
                    self.decision_co2[dispatcher.co2_footprint.co2_intensity].append(decision)
                    self.decision_dispatcher[decision] = dispatcher

        self.decision_co2[self.node.co2_footprint.co2_intensity].append(SchedulerDecision.EXEC)

    def schedule(self, f, c, offloaded_from):
        remote_node = None

        lowest_co2, decisions = min(self.decision_co2.items(), key=lambda item: item[0])
        decision = decisions[0]

        if not self.simulation.is_approximate_computing_enabled:
            if decision == SchedulerDecision.EXEC and not self.can_execute_locally(f):
                decision = SchedulerDecision.DROP

        else:

            if decision == SchedulerDecision.EXEC:
                if f.has_variants:
                    lightest_variant = min(f.variants, key=lambda variant: variant.speedup)
                    lightest_variant_func = lightest_variant.self_function
                    if self.can_execute_locally(lightest_variant_func):
                        f.active_variant = lightest_variant_func
                        decision = SchedulerDecision.EXEC_VAR
                    else: #offload to cloud
                        decision = SchedulerDecision.DROP
                else:
                    if not self.can_execute_locally(f):
                        decision = SchedulerDecision.DROP

        if conf.OFFLOAD_CLOUD_DECISION in decision.name:
            remote_node = self.decision_dispatcher[decision]

        #self.compute_g_co2_decision(self.node, f, c, decision)
        return decision, remote_node

class GreedyBudgetAware(GreedyPolicy):

    def __init__ (self, simulation, node):
        super().__init__(simulation, node)

    def schedule(self, f, c, offloaded_from):
        latency_local, latency_cloud = self._estimate_latency(f,c)
        local_ok = self.can_execute_locally(f)
        budget_ok = self.simulation.stats.cost / self.simulation.t * 3600 < self.budget

        if not budget_ok and not local_ok:
            return (SchedulerDecision.DROP, None)
        if local_ok and latency_local < latency_cloud:
            return (SchedulerDecision.EXEC, None)
        if budget_ok:
            return (SchedulerDecision.OFFLOAD_CLOUD, self.cloud)
        else:
            return (SchedulerDecision.EXEC, None)


class GreedyPolicyWithCostMinimization(GreedyPolicy):

    def __init__ (self, simulation, node):
        super().__init__(simulation, node)
        # Pick the closest cloud node
        nodes_w_lat = [(_n,simulation.infra.get_latency(node,_n)) for _n in simulation.infra.get_cloud_nodes()]
        self.cloud = sorted(nodes_w_lat, key=lambda x: x[1])[0][0]

    def schedule(self, f, c, offloaded_from):
        if self.local_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.node.warm_pool:
                self.cold_start_prob[(f, self.node)] = 0
            else:
                self.cold_start_prob[(f, self.node)] = 1
        if self.cloud_cold_start_estimation == ColdStartEstimation.FULL_KNOWLEDGE:
            if f in self.cloud.warm_pool:
                self.cold_start_prob[(f, self.cloud)] = 0
            else:
                self.cold_start_prob[(f, self.cloud)] = 1

        latency_local = self.estimated_service_time.get(f, 0) + \
                        self.cold_start_prob.get((f, self.node), 1) * \
                        self.simulation.init_time[(f,self.node)]

        latency_cloud = self.estimated_service_time_cloud.get(f, 0) + 2 * self.simulation.infra.get_latency(self.node, self.cloud) + \
                        self.cold_start_prob.get((f, self.cloud), 1) * self.simulation.init_time[(f,self.cloud)] +\
                        f.inputSizeMean*8/1000/1000/self.simulation.infra.get_bandwidth(self.node, self.cloud)

        if latency_local < c.max_rt and self.can_execute_locally(f):
            # Choose the configuration with minimum cost (edge execution) if both configuration can execute within
            # the deadline
            sched_decision = SchedulerDecision.EXEC, None
        elif latency_cloud < c.max_rt:
            sched_decision = SchedulerDecision.OFFLOAD_CLOUD, self.cloud
        elif self.can_execute_locally(f):
            sched_decision = SchedulerDecision.EXEC, None
        else:
            sched_decision = SchedulerDecision.OFFLOAD_CLOUD, self.cloud

        return sched_decision

