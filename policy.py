from enum import Enum, auto
from pacsltk import perfmodel

import co2_footprint
import conf
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

class CloudRegionDispatcherPolicy(Policy):

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
        node.avg_idle_power_consumption = (sum(cloud_node.idle_power_consumption for cloud_node in self.cloud_region_nodes))/(len(self.cloud_region_nodes))
        node.avg_tx_power_consumption = (sum(cloud_node.tx_power_consumption for cloud_node in self.cloud_region_nodes)) / (len(self.cloud_region_nodes))
        node.avg_rx_power_consumption = (sum(cloud_node.rx_power_consumption for cloud_node in self.cloud_region_nodes)) / (len(self.cloud_region_nodes))
        node.cloud_nodes_list = self.cloud_region_nodes
        self.current_index = 0

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


    def schedule(self, f, c, offloaded_from):
        n = len(self.cloud_region_nodes)
        if n == 0:
            return (SchedulerDecision.DROP, None)  # or raise

        start = self.current_index

        # 1) Prefer warm nodes, but iterate in RR order (avoid always picking the first)
        for i in range(n):
            idx = (start + i) % n
            node = self.cloud_region_nodes[idx]
            if f in node.warm_pool and node.can_execute_function(f):
                selected_node = node
                self.current_index = (idx + 1) % n  # advance RR from chosen node
                decision = conf.OFFLOAD_CLOUD_DECISION + self.region.name.upper()
                return (decision, selected_node)

        # 2) No warm node available -> cold start RR, but skip full nodes
        for i in range(n):
            idx = (start + i) % n
            node = self.cloud_region_nodes[idx]
            if node.can_execute_function(f):
                selected_node = node
                self.current_index = (idx + 1) % n
                decision = conf.OFFLOAD_CLOUD_DECISION + self.region.name.upper()
                return (decision, selected_node)

        # 3) All nodes full -> decide what you want (DROP / queue / force-evict / etc.)
        return (SchedulerDecision.DROP, None)

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
        self.rng_variant = self.simulation.rng_variant
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
        if f.has_variants:
            # returns the variant with the minimum speedup
            var = self.rng_variant.choice(f.variants)
            func = var.self_function
            latency_local_var, latency_cloud = self._estimate_latency(func, c)

            if self.can_execute_locally(func) and latency_local_var < latency_cloud:
                f.active_variant = func
                scheduler_decision, remote_node = SchedulerDecision.EXEC_VAR, None
            else:
                scheduler_decision, remote_node = self.offload_cloud_decision, self.dispatcher

        else:
            latency_local, latency_cloud = self._estimate_latency(f, c)
            if self.can_execute_locally(f) and latency_local < latency_cloud:
                scheduler_decision, remote_node = SchedulerDecision.EXEC, None
            else:
                scheduler_decision, remote_node = self.offload_cloud_decision, self.dispatcher

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
        self.rng_variant = self.simulation.rng_variant
        self.decision_dispatcher = {}
        self.decision_co2 = defaultdict(list)   #k: co2_intensity v: [decision] -> for main decision

        self.decision_co2[self.node.co2_footprint.co2_intensity].append(SchedulerDecision.EXEC)

        for dispatcher in self.simulation.infra.dispatchers:
            for decision in SchedulerDecision:
                if dispatcher.region.name.upper() in decision.name:
                    self.decision_co2[dispatcher.co2_footprint.co2_intensity].append(decision)
                    self.decision_dispatcher[decision] = dispatcher

        # cloud ranking of lowest co2 for offloading in case of impossible local execution
        self.cloud_co2_ranking = {
            co2: [d for d in decisions if d != SchedulerDecision.EXEC]
            for co2, decisions in sorted(self.decision_co2.items())
        }

    def schedule(self, f, c, offloaded_from):
        remote_node = None

        lowest_co2, decisions = min(self.decision_co2.items(), key=lambda item: item[0])
        decision = decisions[0]

        if decision == SchedulerDecision.EXEC:
            if f.has_variants:
                var = self.rng_variant.choice(f.variants)
                func = var.self_function
                if self.can_execute_locally(func):
                    f.active_variant = func
                    return SchedulerDecision.EXEC_VAR, None
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

        return decision, remote_node

class GreedyCarbonAwareStrict(GreedyCarbonAware):

    def __init__ (self, simulation, node):
        super().__init__(simulation, node)
        self.rng_variant = self.simulation.rng_variant


    def schedule(self, f, c, offloaded_from):
        remote_node = None

        lowest_co2, decisions = min(self.decision_co2.items(), key=lambda item: item[0])
        decision = decisions[0]

        if decision == SchedulerDecision.EXEC:
            if f.has_variants:
                var = self.rng_variant.choice(f.variants)
                func = var.self_function
                if self.can_execute_locally(func):
                    f.active_variant = func
                    decision = SchedulerDecision.EXEC_VAR
                else:  # offload to cloud
                    decision = SchedulerDecision.DROP
            else:
                if not self.can_execute_locally(f):
                    decision = SchedulerDecision.DROP

        if conf.OFFLOAD_CLOUD_DECISION in decision.name:
            remote_node = self.decision_dispatcher[decision]

        # self.compute_g_co2_decision(self.node, f, c, decision)
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



class EnergylessPolicy(Policy):

    def __init__(self, simulation, node):

        super().__init__(simulation, node)
        self.aggregated_edge_power_consumption = 0.0
        self.aggregated_edge_idle_power_consumption = 0.0
        self.aggregated_edge_power_tx = 0.0
        self.aggregated_edge_power_rx = 0.0
        self.instances = []
        self.obj_f = {f: float("inf") for f in self.simulation.functions}
        self.ins_f = {f: None for f in self.simulation.functions}
        self.edge_nodes = []
        self.cloud_nodes = []
        self.aggregated_edge_memory = 0.0
        self.rng_variant = self.simulation.rng_variant

        for edge_node in simulation.infra.get_edge_nodes():
            #self.instances.append(self.Instance(name=edge_node.name, kind="edge", node_ref=edge_node))
            if edge_node.name != self.node.name:
                self.edge_nodes.append(edge_node)
            self.instances.append(edge_node)

        for cloud_node in simulation.infra.get_cloud_nodes():
            if not isinstance(cloud_node, Dispatcher):
                self.cloud_nodes.append(cloud_node)
                self.instances.append(cloud_node)


        self.cold_start_prob_instance = {(f,i): 1.0 for f in self.simulation.functions for i in self.instances}
        self.estimated_service_time_instance = {(f,i): 0.1 for f in self.simulation.functions for i in self.instances}

        self.local_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.LOCAL_COLD_START_EST_STRATEGY, fallback=""))
        self.cloud_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.CLOUD_COLD_START_EST_STRATEGY, fallback=""))
        self.edge_cold_start_estimation = ColdStartEstimation.from_string(self.simulation.config.get(conf.SEC_POLICY, conf.EDGE_COLD_START_EST_STRATEGY, fallback=""))

        self.gamma1 = float(self.simulation.config.get(conf.SEC_POLICY, conf.GAMMA_TT, fallback=0.25))
        self.gamma2 = float(self.simulation.config.get(conf.SEC_POLICY, conf.GAMMA_E, fallback=0.25))
        self.gamma3 = float(self.simulation.config.get(conf.SEC_POLICY, conf.GAMMA_CO, fallback=0.25))
        self.gamma4 = float(self.simulation.config.get(conf.SEC_POLICY, conf.GAMMA_Z, fallback=0.25))

        self.allow_multi_offloading = simulation.config.getboolean(conf.SEC_POLICY, conf.MULTIPLE_OFFLOADING_ALLOWED,
                                                                   fallback=False)

        self.norm_factor = {
            (f, c): (1.0, 1.0, 1.0, 1.0)
            for f in self.simulation.functions
            for c in self.simulation.classes
        }

    def estimate_latency_TT(self, f, instance):
        if instance.name == self.node.name:
            latency = self.estimated_service_time_instance.get((f,instance),0.0) + \
                      self.cold_start_prob_instance.get((f, instance), 1) * \
                            self.simulation.init_time[(f, instance)]
        else:
            latency = self.estimated_service_time_instance.get((f,instance),0.0) +\
                2 * self.simulation.infra.get_latency(self.node, instance) + \
                        self.cold_start_prob_instance.get((f, instance), 1) * self.simulation.init_time[(f,instance)] +\
                        f.inputSizeMean*8/1000/1000/self.simulation.infra.get_bandwidth(self.node, instance)
        return latency

    def estimate_CO2(self, f, instance):
        if instance.name == self.node.name:
            co = co2_footprint.compute_local_emissions(f, instance, self.estimated_service_time_instance.get((f, instance), 0.0))
        else:
            if instance.has_dispatcher: #is a cloud node
                co = co2_footprint.compute_cloud_emissions(f, instance.has_dispatcher, self.estimated_service_time_instance.get((f, instance), 0.0),
                                                           instance, self.node)
            else: #edge node
                co = co2_footprint.compute_edge_emissions(f, self.aggregated_edge_memory, self.aggregated_edge_power_consumption,
                                                          self.aggregated_edge_idle_power_consumption, self.estimated_service_time_instance.get((f, instance), 0.0),
                                                          self.node.tx_power_consumption, self.aggregated_edge_power_rx, self.node.rx_power_consumption, self.aggregated_edge_power_tx,
                                                          self.node.co2_footprint.co2_intensity)
        return co

    def estimate_energy(self, f, instance):
        service_time = self.estimated_service_time_instance.get((f, instance), 0.0)
        energy = co2_footprint.function_processing_energy_consumption(instance, f, service_time)

        if instance.name != self.node.name:
            if instance.has_dispatcher:  # cloud node
                energy += co2_footprint.compute_transmission_energy_cloud(
                    f, instance.has_dispatcher, self.node, instance
                )
            else:  # edge node
                energy += co2_footprint.compute_transmission_energy_edge(
                    f,
                    self.node.tx_power_consumption,
                    self.node.rx_power_consumption,
                    self.aggregated_edge_power_tx,
                    self.aggregated_edge_power_rx,
                )
        return energy

    def estimate_cost_Z(self, f, instance):
        #cost = $/GB-s -> cost = c * m_f * T_f + c * (input_size + output_size) * bandwidth
        cost_node = instance.cost * f.memory / 1000 * self.estimated_service_time_instance.get((f,instance),0.1)
        #cost_transmission = instance.cost * (f.inputSizeMean + f.outputSizeMean) / (1000*1000*1000) * self.simulation.infra.get_bandwidth(self.node,instance)/8000
        cost = cost_node
        return cost

    def compute_normalized_factors(self):
        min = 1e-9
        self.norm_factor.clear()

        for f in self.simulation.functions:
            for c in self.simulation.classes:
                T_star = E_star = CO_star = Z_star = 0.0

                for instance in self.instances:
                    if not instance.can_execute_function(f):
                        continue

                    TT = self.estimate_latency_TT(f, instance)

                    if TT > c.max_rt:
                        continue

                    E = self.estimate_energy(f, instance)
                    CO = self.estimate_CO2(f, instance)
                    Z = self.estimate_cost_Z(f, instance)

                    T_star = max(T_star, TT)
                    E_star = max(E_star, E)
                    CO_star = max(CO_star, CO)
                    Z_star = max(Z_star, Z)

                self.norm_factor[(f, c)] = (max(T_star, min), max(E_star, min),max(CO_star, min), max(Z_star, min))
                #print("(",f,",",c,"): ",self.norm_factor[(f, c)])


    def schedule(self, f, c, offloaded_from):
        self.obj_f[f] = float("inf")
        self.ins_f[f] = None

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


        T_norm, E_norm, CO_norm, Z_norm = self.norm_factor[(f, c)]

        for instance in self.instances:
            if instance.can_execute_function(f):    #todo: è qui problema
                #estimate latency , energy consumption, co2, cost
                TT = self.estimate_latency_TT(f,instance)
                CO = self.estimate_CO2(f, instance)
                Z = self.estimate_cost_Z(f,instance)
                E = self.estimate_energy(f, instance)

                if TT < c.max_rt:
                    x = (self.gamma1 * TT / (T_norm if not None else 1.0) +
                         self.gamma2 * E / (E_norm if not None else 1.0) +
                         self.gamma3 * CO / (CO_norm if not None else 1.0) +
                         self.gamma4 * Z / (Z_norm if not None else 1.0))

                    if x <= self.obj_f.get(f,0.0):
                        self.obj_f[f] = x
                        self.ins_f[f] = instance
            else:
                print("instance "+instance.name+" cannot execute function")

        target_node = self.ins_f[f]
        if target_node is None:
            return SchedulerDecision.DROP, None
        if target_node.name == self.node.name:
            if f.has_variants:
                var = self.simulation.rng_variant.choice(f.variants)
                func = var.self_function
                if self.can_execute_locally(func):
                    f.active_variant = func
                    return SchedulerDecision.EXEC_VAR, None
            else:
                if self.can_execute_locally(f):
                    return SchedulerDecision.EXEC, None
            return SchedulerDecision.DROP, None
        elif target_node in self.edge_nodes:
            return SchedulerDecision.OFFLOAD_EDGE, target_node
        elif target_node in self.cloud_nodes:
            return conf.OFFLOAD_CLOUD_DECISION+target_node.region.name.upper(), target_node
        else:
            return SchedulerDecision.DROP, None

    def update(self):
        stats = self.simulation.stats

        for f in self.simulation.functions:
            for i in self.instances:
                if stats.node2completions[(f, i)] > 0:
                    self.estimated_service_time_instance[(f, i)] = stats.execution_time_sum[(f, i)] / \
                                                                   stats.node2completions[(f, i)]
                else:
                    self.estimated_service_time_instance[(f, i)] = 0.1

        self.update_cold_start(stats)
        self.compute_normalized_factors()

        #aggregated edge values
        neighbors = self.edge_nodes
        if not neighbors:  # len(neighbors) == 0
            # Set default values when there are no neighbors
            self.aggregated_edge_memory = 0
            self.aggregated_edge_power_consumption = 0
            self.aggregated_edge_idle_power_consumption = 0
            self.aggregated_edge_power_tx = 0
            self.aggregated_edge_power_rx = 0

        else:

            self.aggregated_edge_memory = max(1, sum([x.curr_memory * x.peer_exposed_memory_fraction for x in
                                                      neighbors]))

            p = sum(neighbor.processing_power_consumption for neighbor in neighbors)
            p_idle = sum(neighbor.idle_power_consumption for neighbor in neighbors)
            tx = sum(neighbor.tx_power_consumption for neighbor in neighbors)
            rx = sum(neighbor.rx_power_consumption for neighbor in neighbors)

            num = len(neighbors)
            self.aggregated_edge_power_consumption = p / num
            self.aggregated_edge_idle_power_consumption = p_idle / num
            self.aggregated_edge_power_tx = tx / num
            self.aggregated_edge_power_rx = rx / num



    def update_cold_start (self, stats):
        #
        # LOCAL NODE
        #
        if self.local_cold_start_estimation == ColdStartEstimation.PACS:
            for f in self.simulation.functions:
                total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,self.node), 0.0) for x in self.simulation.classes])/self.simulation.t)
                props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                            self.estimated_service_time_instance[(f, self.node)],
                                                            self.estimated_service_time_instance[(f, self.node)] + self.simulation.init_time[(f,self.node)],
                                                            self.simulation.expiration_timeout)
                self.cold_start_prob_instance[(f, self.node)] = props1["cold_prob"]
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE:
            # Same prob for every function
            node_compl = sum([stats.node2completions[(_f,self.node)] for _f in self.simulation.functions])
            node_cs = sum([stats.cold_starts[(_f,self.node)] for _f in self.simulation.functions])
            for f in self.simulation.functions:
                if node_compl > 0:
                    self.cold_start_prob_instance[(f, self.node)] = node_cs / node_compl
                else:
                    self.cold_start_prob_instance[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
            for f in self.simulation.functions:
                if stats.node2completions.get((f,self.node), 0) > 0:
                    self.cold_start_prob_instance[(f, self.node)] = stats.cold_starts.get((f,self.node),0) / stats.node2completions.get((f,self.node),0)
                else:
                    self.cold_start_prob_instance[(f, self.node)] = COLD_START_PROB_INITIAL_GUESS
        elif self.local_cold_start_estimation == ColdStartEstimation.NO:
            for f in self.simulation.functions:
                self.cold_start_prob_instance[(f, self.node)] = 0

        # CLOUD
        #
        for cloud_instance in self.cloud_nodes:
            if self.cloud_cold_start_estimation == ColdStartEstimation.PACS:
                for f in self.simulation.functions:
                    total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,cloud_instance), 0.0) for x in self.simulation.classes])/self.simulation.t)
                    props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                                self.estimated_service_time_instance[(f, cloud_instance)],
                                                                self.estimated_service_time_instance[(f,cloud_instance)] + self.simulation.init_time[(f,cloud_instance)],
                                                                self.simulation.expiration_timeout)
                    self.cold_start_prob_instance[(f, cloud_instance)] = props1["cold_prob"]
            elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE:
                # Same prob for every function
                node_compl = sum([stats.node2completions[(_f,cloud_instance)] for _f in self.simulation.functions])
                node_cs = sum([stats.cold_starts[(_f,cloud_instance)] for _f in self.simulation.functions])
                for f in self.simulation.functions:
                    if node_compl > 0:
                        self.cold_start_prob_instance[(f, cloud_instance)] = node_cs / node_compl
                    else:
                        self.cold_start_prob_instance[(f, cloud_instance)] = COLD_START_PROB_INITIAL_GUESS
            elif self.cloud_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
                for f in self.simulation.functions:
                    if stats.node2completions.get((f,cloud_instance), 0) > 0:
                        self.cold_start_prob_instance[(f, cloud_instance)] = stats.cold_starts.get((f,cloud_instance),0) / stats.node2completions.get((f,cloud_instance),0)
                    else:
                        self.cold_start_prob_instance[(f, cloud_instance)] = COLD_START_PROB_INITIAL_GUESS
            elif self.cloud_cold_start_estimation == ColdStartEstimation.NO:
                for f in self.simulation.functions:
                    self.cold_start_prob_instance[(f, cloud_instance)] = 0

        # EDGE
        #
        for edge_instance in self.edge_nodes:
            if self.edge_cold_start_estimation == ColdStartEstimation.PACS:
                for f in self.simulation.functions:
                    total_arrival_rate = max(0.001, sum([stats.arrivals.get((f,x,edge_instance), 0.0) for x in self.simulation.classes])/self.simulation.t)
                    props1, _ = perfmodel.get_sls_warm_count_dist(total_arrival_rate,
                                                                self.estimated_service_time_instance[(f, edge_instance)],
                                                                self.estimated_service_time_instance[(f,edge_instance)] + self.simulation.init_time[(f,edge_instance)],
                                                                self.simulation.expiration_timeout)
                    self.cold_start_prob_instance[(f, edge_instance)] = props1["cold_prob"]
            elif self.edge_cold_start_estimation == ColdStartEstimation.NAIVE:
                # Same prob for every function
                node_compl = sum([stats.node2completions[(_f,edge_instance)] for _f in self.simulation.functions])
                node_cs = sum([stats.cold_starts[(_f,edge_instance)] for _f in self.simulation.functions])
                for f in self.simulation.functions:
                    if node_compl > 0:
                        self.cold_start_prob_instance[(f, edge_instance)] = node_cs / node_compl
                    else:
                        self.cold_start_prob_instance[(f, edge_instance)] = COLD_START_PROB_INITIAL_GUESS
            elif self.edge_cold_start_estimation == ColdStartEstimation.NAIVE_PER_FUNCTION:
                for f in self.simulation.functions:
                    if stats.node2completions.get((f,edge_instance), 0) > 0:
                        self.cold_start_prob_instance[(f, edge_instance)] = stats.cold_starts.get((f,edge_instance),0) / stats.node2completions.get((f,edge_instance),0)
                    else:
                        self.cold_start_prob_instance[(f, edge_instance)] = COLD_START_PROB_INITIAL_GUESS
            elif self.edge_cold_start_estimation == ColdStartEstimation.NO:
                for f in self.simulation.functions:
                    self.cold_start_prob_instance[(f, edge_instance)] = 0


